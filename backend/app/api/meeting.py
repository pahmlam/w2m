from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models.requests import MeetingRequest, RerankRequest
from app.models.responses import ErrorResponse, MapConfig, MeetingResponse

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
             responses={503: {"model": ErrorResponse}})
def meeting_points(body: MeetingRequest, request: Request):
    # M1–M4 will connect the graph and optimizer; no synthetic success response.
    return unavailable(request)


@router.post("/meeting-points/{request_id}/rerank", response_model=MeetingResponse,
             responses={503: {"model": ErrorResponse}})
def rerank(request_id: str, body: RerankRequest, request: Request):
    return unavailable(request)


@router.get("/map/config", response_model=MapConfig, responses={503: {"model": ErrorResponse}})
def map_config(request: Request):
    return unavailable(request)
