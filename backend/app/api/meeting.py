from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from shapely.geometry import mapping

from app.config.settings import (
    MAX_TRAVEL_SECONDS_BOUNDS,
    MIN_SPACING_METERS_BOUNDS,
    PHI_BOUNDS,
    TOP_K_BOUNDS,
)
from app.models.requests import Location, MeetingRequest, Optimization, RerankRequest
from app.models.responses import (
    ErrorResponse,
    MapConfig,
    MapDefaults,
    MeetingResponse,
    Objective,
    ParameterLimits,
    ParameterRange,
    Polygon,
    SnappedOrigin,
)
from app.services.coordinate_snapper import SnapError
from app.services.csr_meeting_service import CSRMeetingComputation
from app.services.objective import quantize_seconds

router = APIRouter(prefix="/api/v1", responses={
    400: {"model": ErrorResponse},
    "4XX": {"model": ErrorResponse},
    500: {"model": ErrorResponse},
})


def unavailable(request: Request) -> JSONResponse:
    error = ErrorResponse(
        error_code="GRAPH_UNAVAILABLE",
        message="Dữ liệu định tuyến chưa sẵn sàng.",
        request_id=request.state.request_id,
    )
    return JSONResponse(status_code=503, content=error.model_dump())


def _meeting_response(
    request_id: str, computation: CSRMeetingComputation, optimization: Optimization,
) -> MeetingResponse:
    graph = computation.routing.graph
    origins = [SnappedOrigin(
        id=snap.origin_id,
        snap_distance_m=snap.snap_distance_m,
        access_seconds=quantize_seconds(snap.access_seconds),
        snapped=Location(lon=snap.snapped_lonlat[0], lat=snap.snapped_lonlat[1]),
    ) for snap in computation.snaps]
    empty = not computation.results
    return MeetingResponse(
        request_id=request_id,
        graph_version=graph.graph_version,
        weight_profile_version=graph.weight_profile_version,
        status="empty" if empty else "success",
        objective=Objective(phi=optimization.phi, weights=list(computation.objective_weights)),
        origins=origins,
        results=computation.results,
        timings_ms=computation.timings_ms,
        error_code="NO_COMMON_REACHABLE_NODE" if empty else None,
        message="Không có điểm gặp trong giới hạn thời gian." if empty else None,
        min_required_seconds=f"> {optimization.max_travel_seconds}" if empty else None,
    )


@router.post("/meeting-points", response_model=MeetingResponse,
             responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def meeting_points(body: MeetingRequest, request: Request) -> MeetingResponse | JSONResponse:
    """Compute fresh meeting points using the graph loaded at startup."""
    graph = request.app.state.csr_graph
    service = request.app.state.csr_meeting_service
    if graph is None or service is None:
        return unavailable(request)

    try:
        computation = await service.compute_request(body)
    except SnapError as exc:
        error = ErrorResponse(error_code=exc.error_code, message=str(exc),
                              request_id=request.state.request_id)
        return JSONResponse(status_code=422, content=error.model_dump())

    response = _meeting_response(uuid4().hex, computation, body.optimization)
    request.app.state.meeting_routing_cache.put(response.request_id, computation.routing)
    return response


@router.post("/meeting-points/{request_id}/rerank", response_model=MeetingResponse,
             responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def rerank(
    request_id: str, body: RerankRequest, request: Request,
) -> MeetingResponse | JSONResponse:
    """Rebuild meeting results from the original request's routing tables."""
    graph = request.app.state.csr_graph
    service = request.app.state.csr_meeting_service
    if graph is None or service is None:
        return unavailable(request)

    routing = request.app.state.meeting_routing_cache.get(request_id)
    if (routing is None or routing.graph is not graph
            or body.optimization.max_travel_seconds > routing.max_travel_seconds):
        error = ErrorResponse(
            error_code="RECOMPUTE_REQUIRED",
            message="Cần tính lại điểm gặp với các tham số hiện tại.",
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=409, content=error.model_dump())

    computation = await service.rerank(routing, body.optimization)
    return _meeting_response(request_id, computation, body.optimization)


@router.get("/map/config", response_model=MapConfig, responses={503: {"model": ErrorResponse}})
def map_config(request: Request) -> MapConfig | JSONResponse:
    """Publish the active graph's coverage and the API's optimization settings."""
    graph = getattr(request.app.state, "csr_graph", None)
    if graph is None:
        return unavailable(request)

    settings = request.app.state.settings
    return MapConfig(
        aoi=Polygon.model_validate(mapping(graph.aoi)),
        travel_modes=["car"],
        limits=ParameterLimits(
            phi=ParameterRange(min=PHI_BOUNDS[0], max=PHI_BOUNDS[1]),
            max_travel_seconds=ParameterRange(
                min=MAX_TRAVEL_SECONDS_BOUNDS[0], max=MAX_TRAVEL_SECONDS_BOUNDS[1],
            ),
            top_k=ParameterRange(min=TOP_K_BOUNDS[0], max=TOP_K_BOUNDS[1]),
            min_spacing_meters=ParameterRange(
                min=MIN_SPACING_METERS_BOUNDS[0], max=MIN_SPACING_METERS_BOUNDS[1],
            ),
        ),
        defaults=MapDefaults(
            phi=settings.default_phi,
            max_travel_seconds=settings.default_max_travel_seconds,
            top_k=settings.default_top_k,
            min_spacing_meters=settings.default_min_spacing_meters,
            v_access=settings.access_speed_mps,
        ),
        graph_version=graph.graph_version,
        weight_profile_version=graph.weight_profile_version,
        source_date=date.fromisoformat(graph.source_date),
    )
