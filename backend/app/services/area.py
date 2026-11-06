"""Load WGS84 support polygons and prepare metric routing buffers offline."""

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import Point, Polygon, shape
from shapely.geometry.polygon import orient
from shapely.ops import transform

WGS84_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32648"
BUFFER_QUAD_SEGS = 64
_TO_METERS = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)


@dataclass(frozen=True)
class PreparedArea:
    """Keep exported WGS84 geometry separate from geometry measured in meters."""

    aoi_wgs84: Polygon
    aoi_meters: Polygon
    routing_area_wgs84: Polygon
    routing_area_meters: Polygon
    buffer_meters: float


def _reject_constant(value: str) -> None:
    raise ValueError("AOI GeoJSON must not contain non-finite numbers")


def _validate_position(position: object) -> None:
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        raise ValueError("AOI positions must be [longitude, latitude] pairs")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in position):
        raise ValueError("AOI coordinates must be numbers")
    longitude, latitude = position
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("AOI coordinates must be finite WGS84 longitude/latitude")


def load_aoi(path: Path) -> Polygon:
    """Read a valid 2D Polygon or Polygon Feature without repairing invalid input."""
    document = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(document, dict):
        raise ValueError("AOI must be a GeoJSON Polygon or Polygon Feature")
    geometry = document.get("geometry") if document.get("type") == "Feature" else document
    if not isinstance(geometry, dict) or geometry.get("type") != "Polygon":
        raise ValueError("AOI geometry must be a Polygon")
    rings = geometry.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise ValueError("AOI must contain a non-empty exterior ring")
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("AOI rings must contain at least four positions")
        for position in ring:
            _validate_position(position)
        if ring[0] != ring[-1]:
            raise ValueError("AOI rings must be explicitly closed")
    polygon = shape(geometry)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise ValueError("AOI Polygon must have positive area and valid topology")
    # RFC 7946 exterior rings use counterclockwise orientation.
    return orient(polygon, sign=1.0)


def covers_location(aoi_wgs84: Polygon, *, latitude: float, longitude: float) -> bool:
    """Accept locations on the AOI boundary; coordinates are explicitly named."""
    _validate_position((longitude, latitude))
    return bool(aoi_wgs84.covers(Point(longitude, latitude)))


def prepare_area(aoi_wgs84: Polygon, buffer_meters: float) -> PreparedArea:
    """Buffer in EPSG:32648, then transform the result back to WGS84 for export."""
    if isinstance(buffer_meters, bool) or not isfinite(buffer_meters) or buffer_meters <= 0:
        raise ValueError("Routing buffer must be finite and positive, in meters")
    if not isinstance(aoi_wgs84, Polygon) or aoi_wgs84.is_empty or not aoi_wgs84.is_valid:
        raise ValueError("AOI must be a valid non-empty Polygon")
    for ring in (aoi_wgs84.exterior, *aoi_wgs84.interiors):
        for position in ring.coords:
            _validate_position(position)
    aoi_meters = transform(_TO_METERS.transform, aoi_wgs84)
    if not aoi_meters.is_valid or not isfinite(aoi_meters.area) or aoi_meters.area <= 0:
        raise ValueError("AOI cannot be projected to EPSG:32648")
    routing_meters = aoi_meters.buffer(buffer_meters, quad_segs=BUFFER_QUAD_SEGS)
    if (
        not isinstance(routing_meters, Polygon)
        or routing_meters.is_empty
        or not routing_meters.is_valid
        or not isfinite(routing_meters.area)
    ):
        raise ValueError("Routing area must remain a valid Polygon")
    routing_wgs84 = orient(transform(_TO_WGS84.transform, routing_meters), sign=1.0)
    if routing_wgs84.is_empty or not routing_wgs84.is_valid or not isfinite(routing_wgs84.area):
        raise ValueError("Routing area cannot be exported as WGS84")
    return PreparedArea(
        aoi_wgs84=aoi_wgs84,
        aoi_meters=aoi_meters,
        routing_area_wgs84=routing_wgs84,
        routing_area_meters=routing_meters,
        buffer_meters=float(buffer_meters),
    )
