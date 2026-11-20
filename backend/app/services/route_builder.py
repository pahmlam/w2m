"""Reconstruct selected routes without searching the graph again."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import fsum, hypot, isfinite
from typing import TYPE_CHECKING

from pyproj import Transformer
from shapely.geometry import LineString as RoadLine
from shapely.ops import substring

from app.models.responses import LineString, Route
from app.services.area import METRIC_CRS, WGS84_CRS
from app.services.coordinate_snapper import ENDPOINT_ROUNDOFF_METERS
from app.services.csr_route_edges import trace_csr_route_edges

if TYPE_CHECKING:
    from app.services.csr_shortest_path import CSRRoutingResult
    from app.services.request_overlay import NodeId, RequestOverlay
    from app.services.shortest_path import SourcePaths

_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)
type PointXY = tuple[float, float]
type RouteSegment = tuple[Sequence[PointXY], float]


def build_route(overlay: RequestOverlay, source: SourcePaths, target: int) -> Route:
    """Follow stored edge keys, check raw cost, and return network-only GeoJSON."""
    if target not in source.paths.distances_seconds:
        raise ValueError("Route target is unreachable within the computed cutoff")
    edges = []
    node: NodeId = target
    seen: set[NodeId] = set()
    while node != source.source_node:
        if node in seen or node not in source.paths.predecessors:
            raise ValueError("Broken or cyclic route predecessor chain")
        seen.add(node)
        parent, key = source.paths.predecessors[node]
        if not overlay.graph.has_edge(parent, node, key):
            raise ValueError("Route predecessor edge is missing")
        edges.append(overlay.graph.edges[parent, node, key])
        node = parent
    edges.reverse()
    network_raw = source.paths.distances_seconds[target]
    if not isfinite(network_raw) or network_raw < 0:
        raise ValueError("Invalid raw network duration")
    if any(not isfinite(edge["travel_time"]) or edge["travel_time"] <= 0 for edge in edges):
        raise ValueError("Invalid route edge weight")
    if abs(fsum(edge["travel_time"] for edge in edges) - network_raw) > (
        1e-6 * network_raw + 1e-3
    ):
        raise ValueError("Route edge times do not match the stored network duration")

    destination = overlay.reference.graph.nodes[target]
    segments = ((list(edge["geometry"].coords), edge["length_m"]) for edge in edges)
    return _make_route(
        source.snap.snapped_xy, (destination["x"], destination["y"]), segments,
        source.snap.access_seconds, network_raw,
    )


def build_csr_route(routing: CSRRoutingResult, origin_id: str, target: int) -> Route:
    """Build network-only GeoJSON from the original edge geometry and saved CSR paths."""
    edges = trace_csr_route_edges(routing, origin_id, target)
    source = next(paths for paths in routing.sources if paths.snap.origin_id == origin_id)
    target_index = routing.graph.node_indices[target]
    x, y = routing.graph.mappings["node_xy"][target_index]
    geometry = routing.graph.geometry
    xy, offsets = geometry["coordinates"], geometry["offsets"]
    segments: list[RouteSegment] = []
    for edge in edges:
        index = edge.edge_index
        line = RoadLine(xy[offsets[index]:offsets[index + 1]])
        if edge.start_fraction != 0:
            fragment = substring(line, edge.start_fraction, 1, normalized=True)
            if not isinstance(fragment, RoadLine):
                raise ValueError("Invalid source fragment geometry")
            points = list(fragment.coords)
            if _farther_than_roundoff(points[0], source.snap.snapped_xy):
                raise ValueError("Source fragment does not start at the snapped point")
            # Preserve the exact projected source used in the overlay.
            line = RoadLine([source.snap.snapped_xy, *points[1:]])
        segments.append((list(line.coords), line.length))
    return _make_route(
        source.snap.snapped_xy, (float(x), float(y)), segments,
        source.snap.access_seconds, float(source.distances_seconds[target_index]),
    )


def _farther_than_roundoff(first: PointXY, second: PointXY) -> bool:
    return hypot(first[0] - second[0], first[1] - second[1]) > ENDPOINT_ROUNDOFF_METERS


def _make_route(
    start: PointXY, destination: PointXY, segments: Iterable[RouteSegment],
    access_raw: float, network_raw: float,
) -> Route:
    coordinates = [start]
    lengths = []
    for segment, length in segments:
        if not isfinite(length) or length <= 0:
            raise ValueError("Invalid route edge length")
        if _farther_than_roundoff(coordinates[-1], segment[0]):
            raise ValueError("Route geometry is disconnected or reversed")
        coordinates.extend(segment[1:])
        lengths.append(length)
    if _farther_than_roundoff(coordinates[-1], destination):
        raise ValueError("Route geometry does not end at its target")
    if len(coordinates) == 1:
        coordinates.append(coordinates[0])
    lonlat = [_TO_WGS84.transform(*point, errcheck=True) for point in coordinates]
    if not isfinite(access_raw) or access_raw < 0:
        raise ValueError("Invalid raw access duration")
    # Integer deciseconds keep the displayed components consistent with the total.
    duration_ticks = round(10 * (access_raw + network_raw))
    access_ticks = round(10 * access_raw)
    return Route(
        duration_seconds=duration_ticks / 10, access_seconds=access_ticks / 10,
        network_seconds=(duration_ticks - access_ticks) / 10,
        distance_meters=fsum(lengths),
        geometry=LineString(coordinates=lonlat),
    )
