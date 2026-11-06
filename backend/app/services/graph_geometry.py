"""Normalize raw OSM edge geometry offline without changing graph topology."""

from math import isfinite

import networkx as nx
from pyproj import CRS, Transformer
from shapely.geometry import LineString
from shapely.ops import transform

from app.services.area import METRIC_CRS, WGS84_CRS

# Allow serialization noise, but reject geometry belonging to another road segment.
ENDPOINT_TOLERANCE_METERS = 0.01


def _position(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Coordinates must be 2D WGS84 longitude/latitude pairs")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError("Coordinates must be numeric")
    longitude, latitude = value
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("Coordinates must be finite and within WGS84 bounds")
    return float(longitude), float(latitude)


def normalize_graph_geometry(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Return a metric copy with edge geometry oriented source to target.

    Raw OSMnx x/y are longitude/latitude. Preserve them as lon/lat and replace
    x/y with EPSG:32648 meters. Both length and length_m use projected geometry,
    so downstream OSMnx code cannot accidentally use the old geodesic length.
    """
    if not graph.is_directed() or not graph.is_multigraph():
        raise ValueError("Expected a directed multigraph")
    if CRS.from_user_input(graph.graph.get("crs", "")) != CRS(WGS84_CRS):
        raise ValueError("Input graph must use EPSG:4326")
    if not graph.number_of_nodes() or not graph.number_of_edges():
        raise ValueError("Input graph must contain nodes and edges")
    projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    result = graph.copy()
    result.graph["crs"] = METRIC_CRS
    for node_id, attributes in graph.nodes(data=True):
        try:
            longitude, latitude = _position((attributes.get("x"), attributes.get("y")))
            x, y = projector.transform(longitude, latitude, errcheck=True)
            if not isfinite(x) or not isfinite(y):
                raise ValueError("Projected node must be finite")
        except (ValueError, RuntimeError) as exc:
            raise ValueError(f"Invalid coordinates for node {node_id}: {exc}") from exc
        result.nodes[node_id].update(lon=longitude, lat=latitude, x=x, y=y)

    for source, target, key, attributes in graph.edges(keys=True, data=True):
        try:
            if "geometry" in attributes:
                line = attributes["geometry"]
                if not isinstance(line, LineString) or line.is_empty:
                    raise ValueError("Geometry must be a non-empty LineString")
                for coordinate in line.coords:
                    _position(coordinate)
            else:
                line = LineString([
                    (graph.nodes[source]["x"], graph.nodes[source]["y"]),
                    (graph.nodes[target]["x"], graph.nodes[target]["y"]),
                ])
            projected = transform(projector.transform, line)
            if not projected.is_valid:
                raise ValueError("Geometry must be valid")
            coordinates = list(projected.coords)
            start = (result.nodes[source]["x"], result.nodes[source]["y"])
            end = (result.nodes[target]["x"], result.nodes[target]["y"])
            forward = (
                LineString([start, coordinates[0]]).length <= ENDPOINT_TOLERANCE_METERS
                and LineString([end, coordinates[-1]]).length <= ENDPOINT_TOLERANCE_METERS
            )
            backward = (
                LineString([start, coordinates[-1]]).length <= ENDPOINT_TOLERANCE_METERS
                and LineString([end, coordinates[0]]).length <= ENDPOINT_TOLERANCE_METERS
            )
            if not forward:
                if not backward:
                    raise ValueError("Geometry endpoints do not match source and target")
                coordinates.reverse()
            # Exact endpoints avoid tiny gaps when assembling successive route segments.
            coordinates[0], coordinates[-1] = start, end
            projected = LineString(coordinates)
            length_meters = projected.length
            if not isfinite(length_meters) or length_meters <= 0:
                raise ValueError("Projected edge length must be finite and positive")
        except (ValueError, RuntimeError) as exc:
            raise ValueError(f"Invalid geometry for edge {(source, target, key)}: {exc}") from exc
        result.edges[source, target, key].update(
            geometry=projected, length_m=length_meters, length=length_meters,
        )
    return result
