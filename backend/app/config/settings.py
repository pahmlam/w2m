from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="W2M_", env_file=".env", extra="ignore")

    aoi_path: Path = Path("backend/data/aoi.geojson")
    graph_dir: Path = Path("backend/data/graph")
    speed_profile_path: Path = Path("backend/app/config/speed_profiles/car-v1.yaml")
    buffer_m: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 3000
    snap_max_m: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 150
    access_speed_mps: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1.4
    max_edge_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60
    default_phi: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.5
    default_max_travel_seconds: Annotated[int, Field(ge=300, le=7200)] = 3600
    default_top_k: Annotated[int, Field(ge=1, le=5)] = 5
    default_min_spacing_meters: Annotated[
        float, Field(ge=0, le=5000, allow_inf_nan=False)
    ] = 500
    cache_ttl_seconds: Annotated[int, Field(gt=0)] = 900
    cache_max_bytes: Annotated[int, Field(gt=0)] = 536870912
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
