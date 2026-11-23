from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.requests import Location, MeetingRequest, RerankRequest
from app.models.responses import ErrorResponse, MapConfig, MeetingResponse, Objective, SnappedOrigin
from app.services.coordinate_snapper import SnapError
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

    origins = [SnappedOrigin(
        id=snap.origin_id,
        snap_distance_m=snap.snap_distance_m,
        access_seconds=quantize_seconds(snap.access_seconds),
        snapped=Location(lon=snap.snapped_lonlat[0], lat=snap.snapped_lonlat[1]),
    ) for snap in computation.snaps]
    empty = not computation.results
    return MeetingResponse(
        request_id=uuid4().hex,
        graph_version=graph.graph_version,
        weight_profile_version=graph.weight_profile_version,
        status="empty" if empty else "success",
        objective=Objective(phi=body.optimization.phi, weights=list(computation.objective_weights)),
        origins=origins,
        results=computation.results,
        timings_ms=computation.timings_ms,
        error_code="NO_COMMON_REACHABLE_NODE" if empty else None,
        message="Không có điểm gặp trong giới hạn thời gian." if empty else None,
        min_required_seconds=f"> {body.optimization.max_travel_seconds}" if empty else None,
    )


@router.post("/meeting-points/{request_id}/rerank", response_model=MeetingResponse,
             responses={503: {"model": ErrorResponse}})
def rerank(request_id: str, body: RerankRequest, request: Request):
    return unavailable(request)


@router.get("/map/config", response_model=MapConfig, responses={503: {"model": ErrorResponse}})
def map_config(request: Request):
    return unavailable(request)
