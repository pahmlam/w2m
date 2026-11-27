from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from app.config.settings import (
    MAX_TRAVEL_SECONDS_BOUNDS,
    MIN_SPACING_METERS_BOUNDS,
    PHI_BOUNDS,
    TOP_K_BOUNDS,
    get_settings,
)

type ObjectiveType = Literal["owa_geometric", "mean_spread_v1"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Location(ContractModel):
    lat: Annotated[float, Field(ge=-90, le=90, strict=True)]
    lon: Annotated[float, Field(ge=-180, le=180, strict=True)]


class Origin(Location):
    id: Annotated[str, Field(min_length=1, max_length=64, strict=True)]


class Optimization(ContractModel):
    phi: Annotated[float, Field(ge=PHI_BOUNDS[0], le=PHI_BOUNDS[1], strict=True)] = Field(
        default_factory=lambda: get_settings().default_phi,
    )
    max_travel_seconds: Annotated[
        int, Field(ge=MAX_TRAVEL_SECONDS_BOUNDS[0], le=MAX_TRAVEL_SECONDS_BOUNDS[1], strict=True)
    ] = Field(default_factory=lambda: get_settings().default_max_travel_seconds)
    top_k: Annotated[int, Field(ge=TOP_K_BOUNDS[0], le=TOP_K_BOUNDS[1], strict=True)] = Field(
        default_factory=lambda: get_settings().default_top_k,
    )
    min_spacing_meters: Annotated[
        float, Field(ge=MIN_SPACING_METERS_BOUNDS[0], le=MIN_SPACING_METERS_BOUNDS[1], strict=True)
    ] = Field(default_factory=lambda: get_settings().default_min_spacing_meters)


class MeetingOptimization(Optimization):
    objective_type: ObjectiveType = "owa_geometric"

    @model_validator(mode="before")
    @classmethod
    def accept_base_options(cls, value: object) -> object:
        if isinstance(value, Optimization) and not isinstance(value, cls):
            return value.model_dump()
        return value


class CreateMeetingOptimization(MeetingOptimization):
    fairness_mode: ObjectiveType | None = None

    @model_validator(mode="after")
    def validate_fairness_mode(self) -> "CreateMeetingOptimization":
        if "fairness_mode" in self.model_fields_set and (
            self.fairness_mode is None or self.model_fields_set & {"phi", "objective_type"}
        ):
            raise ValueError("fairness_mode requires a mode and replaces phi and objective_type")
        return self

    @model_serializer(mode="wrap")
    def serialize_request_options(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        options = handler(self)
        if self.fairness_mode is None:
            options.pop("fairness_mode", None)
        else:
            options.pop("phi", None)
            options.pop("objective_type", None)
        return options


class MeetingRequest(ContractModel):
    origins: Annotated[list[Origin], Field(min_length=4, max_length=4)]
    travel_mode: Literal["car"] = "car"
    optimization: CreateMeetingOptimization = Field(default_factory=CreateMeetingOptimization)

    @model_validator(mode="after")
    def unique_origin_ids(self) -> "MeetingRequest":
        if len({origin.id for origin in self.origins}) != len(self.origins):
            raise ValueError("Origin IDs must be unique")
        return self


class RerankRequest(ContractModel):
    optimization: MeetingOptimization
