from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config.settings import get_settings


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Location(ContractModel):
    lat: Annotated[float, Field(ge=-90, le=90, strict=True)]
    lon: Annotated[float, Field(ge=-180, le=180, strict=True)]


class Origin(Location):
    id: Annotated[str, Field(min_length=1, max_length=64, strict=True)]


class Optimization(ContractModel):
    phi: Annotated[float, Field(ge=0, le=1, strict=True)] = Field(
        default_factory=lambda: get_settings().default_phi
    )
    max_travel_seconds: Annotated[int, Field(ge=300, le=7200, strict=True)] = Field(
        default_factory=lambda: get_settings().default_max_travel_seconds
    )
    top_k: Annotated[int, Field(ge=1, le=5, strict=True)] = Field(
        default_factory=lambda: get_settings().default_top_k
    )
    min_spacing_meters: Annotated[float, Field(ge=0, le=5000, strict=True)] = Field(
        default_factory=lambda: get_settings().default_min_spacing_meters
    )


class MeetingRequest(ContractModel):
    origins: Annotated[list[Origin], Field(min_length=4, max_length=4)]
    travel_mode: Literal["car"] = "car"
    optimization: Optimization = Field(default_factory=Optimization)

    @model_validator(mode="after")
    def unique_origin_ids(self) -> "MeetingRequest":
        if len({origin.id for origin in self.origins}) != len(self.origins):
            raise ValueError("Origin IDs must be unique")
        return self


class RerankRequest(ContractModel):
    optimization: Optimization
