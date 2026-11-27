from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class MeetingRequest(ContractModel):
    origins: Annotated[list[Origin], Field(min_length=4, max_length=4)]
    travel_mode: Literal["car"] = "car"
    optimization: MeetingOptimization = Field(default_factory=MeetingOptimization)

    @model_validator(mode="after")
    def unique_origin_ids(self) -> "MeetingRequest":
        if len({origin.id for origin in self.origins}) != len(self.origins):
            raise ValueError("Origin IDs must be unique")
        return self


class RerankRequest(ContractModel):
    optimization: MeetingOptimization
