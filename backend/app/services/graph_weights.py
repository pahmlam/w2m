"""Apply a versioned static car speed profile to metric road edges offline."""

import re
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

import networkx as nx
import yaml
from pyproj import CRS

from app.services.area import METRIC_CRS

MPH_TO_KMH = 1.609
KMH_PER_MPS = 3.6
_SPEED = re.compile(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(km/h|kmh|kph|mph)?", re.IGNORECASE)


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite and positive") from exc
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


@dataclass(frozen=True)
class SpeedProfile:
    """A validated car profile; speeds are in km/h."""

    version: str
    speeds_kmh: dict[str, float]


def load_speed_profile(path: Path) -> SpeedProfile:
    """Load the YAML car profile, rejecting invalid units, flags and speeds."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Speed profile must be a mapping")
    version = document.get("weight_profile_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("weight_profile_version must be a non-empty string")
    if (
        document.get("travel_mode") != "car"
        or document.get("unit") != "kmh"
        or document.get("maxspeed_cap") is not True
    ):
        raise ValueError("Speed profile requires travel_mode=car, unit=kmh and maxspeed_cap=true")
    speeds = document.get("speeds")
    if not isinstance(speeds, dict) or "default" not in speeds:
        raise ValueError("Speed profile requires a speeds mapping with default")
    if any(not isinstance(key, str) or not key.strip() for key in speeds):
        raise ValueError("Speed profile road types must be non-empty strings")
    return SpeedProfile(
        version=version.strip(),
        speeds_kmh={
            key: _positive_number(value, f"Speed for {key}")
            for key, value in speeds.items()
        },
    )


def parse_maxspeed_kmh(value: object) -> float | None:
    """Return the smallest valid limit; ignore text, booleans and nonpositive values.

    OSMnx lists and semicolon-separated OSM values may mix units and invalid text.
    The mph factor follows specification 3.2.1 exactly.
    """
    if isinstance(value, (list, tuple)):
        limits = [parsed for item in value if (parsed := parse_maxspeed_kmh(item)) is not None]
        return min(limits) if limits else None
    if isinstance(value, str):
        if ";" in value:
            return parse_maxspeed_kmh(value.split(";"))
        match = _SPEED.fullmatch(value.strip())
        if match is None:
            return None
        number = float(match.group(1))
        if (match.group(2) or "").lower() == "mph":
            number *= MPH_TO_KMH
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
        except OverflowError:
            return None
    else:
        return None
    return number if isfinite(number) and number > 0 else None


def apply_speed_profile(graph: nx.MultiDiGraph, profile: SpeedProfile) -> nx.MultiDiGraph:
    """Return a weighted copy, preserving topology, geometry and source attributes.

    Count an edge as using default if any highway entry needs the fallback, even
    when another entry supplies a slower speed. Never remove invalid edges silently.
    """
    if not graph.is_directed() or not graph.is_multigraph():
        raise ValueError("Expected a directed multigraph")
    if CRS.from_user_input(graph.graph.get("crs", "")) != CRS(METRIC_CRS):
        raise ValueError("Input geometry must use EPSG:32648")
    if not graph.number_of_nodes() or not graph.number_of_edges():
        raise ValueError("Input graph must contain nodes and edges")
    result = graph.copy()
    default_count = capped_count = ignored_count = 0
    for source, target, key, attributes in graph.edges(keys=True, data=True):
        try:
            length_meters = _positive_number(attributes.get("length_m"), "length_m")
            highway = attributes.get("highway")
            types = list(highway) if isinstance(highway, (list, tuple)) else [highway]
            types = types or [None]
            known = [isinstance(kind, str) and kind in profile.speeds_kmh for kind in types]
            speeds = [
                profile.speeds_kmh[kind] if found else profile.speeds_kmh["default"]
                for kind, found in zip(types, known)
            ]
            speed_kmh = min(speeds)
            default_count += int(not all(known) or "default" in types)
            limit_kmh = parse_maxspeed_kmh(attributes.get("maxspeed"))
            ignored_count += int("maxspeed" in attributes and limit_kmh is None)
            if limit_kmh is not None and limit_kmh < speed_kmh:
                speed_kmh = limit_kmh
                capped_count += 1
            speed_mps = _positive_number(speed_kmh / KMH_PER_MPS, "speed_mps")
            travel_seconds = _positive_number(length_meters / speed_mps, "travel_time_seconds")
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"Invalid weight for edge {(source, target, key)}: {exc}") from exc
        result.edges[source, target, key].update(
            estimated_speed_kmh=speed_kmh,
            travel_time_seconds=travel_seconds,
            travel_time=travel_seconds,
        )
    result.graph.update(
        weight_profile_version=profile.version,
        travel_mode="car",
        default_speed_edge_count=default_count,
        maxspeed_capped_edge_count=capped_count,
        ignored_maxspeed_edge_count=ignored_count,
    )
    return result
