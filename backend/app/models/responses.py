from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from app.models.requests import ContractModel, Location, Optimization

Seconds = Annotated[float, Field(ge=0)]
ErrorCode = Literal[
    "INVALID_COORDINATES", "INVALID_PARAMETERS", "OUT_OF_COVERAGE", "SNAP_FAILED",
    "NO_COMMON_REACHABLE_NODE", "RECOMPUTE_REQUIRED", "GRAPH_UNAVAILABLE", "INTERNAL_ERROR",
]


class ErrorResponse(ContractModel):
    error_code: ErrorCode
    message: str
    request_id: str


class LineString(ContractModel):
    type: Literal["LineString"] = "LineString"
    coordinates: Annotated[list[tuple[float, float]], Field(min_length=2)]


class SnappedOrigin(ContractModel):
    id: str
    snap_distance_m: Seconds
    access_seconds: Seconds
    snapped: Location


class Route(ContractModel):
    network_seconds: Seconds
    access_seconds: Seconds
    duration_seconds: Seconds
    distance_meters: Annotated[float, Field(ge=0)]
    geometry: LineString


class MeetingResult(ContractModel):
    rank: Annotated[int, Field(ge=1, le=5)]
    node_id: int
    location: Location
    travel_times: dict[str, Seconds]
    max_time: Seconds
    min_time: Seconds
    difference: Seconds
    avg_time: Seconds
    score: Seconds
    routes: dict[str, Route]


class Objective(ContractModel):
    type: Literal["owa_geometric"] = "owa_geometric"
    phi: Annotated[float, Field(ge=0, le=1)]
    weights: list[float]


class Timings(ContractModel):
    snap: Seconds
    dijkstra: Seconds
    scan: Seconds
    rank: Seconds
    routes: Seconds
    total: Seconds


class MeetingResponse(ContractModel):
    request_id: str
    graph_version: str
    weight_profile_version: str
    status: Literal["success", "empty"]
    unit: Literal["seconds"] = "seconds"
    objective: Objective
    origins: Annotated[list[SnappedOrigin], Field(min_length=4, max_length=4)]
    results: Annotated[list[MeetingResult], Field(max_length=5)]
    timings_ms: Timings
    error_code: Literal["NO_COMMON_REACHABLE_NODE"] | None = None
    message: str | None = None
    min_required_seconds: Seconds | str | None = None


class Polygon(ContractModel):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[tuple[float, float]]]


class ParameterRange(ContractModel):
    min: float
    max: float


class ParameterLimits(ContractModel):
    phi: ParameterRange
    max_travel_seconds: ParameterRange
    top_k: ParameterRange
    min_spacing_meters: ParameterRange


class MapDefaults(Optimization):
    v_access: Annotated[float, Field(gt=0)]


class MapConfig(ContractModel):
    aoi: Polygon
    travel_modes: list[Literal["car"]]
    limits: ParameterLimits
    defaults: MapDefaults
    graph_version: str
    weight_profile_version: str
    source_date: date
