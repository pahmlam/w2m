"""Reconstruct selected reference routes without searching the graph again."""

from __future__ import annotations

from math import fsum, hypot, isfinite
from typing import TYPE_CHECKING

from pyproj import Transformer

from app.models.responses import LineString, Route
from app.services.area import METRIC_CRS, WGS84_CRS
from app.services.coordinate_snapper import ENDPOINT_ROUNDOFF_METERS

if TYPE_CHECKING:
    from app.services.request_overlay import NodeId, RequestOverlay
    from app.services.shortest_path import SourcePaths

_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)


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
    if any(not isfinite(edge[field]) or edge[field] <= 0
           for edge in edges for field in ("travel_time", "length_m")):
        raise ValueError("Invalid route edge weight or length")
    if abs(fsum(edge["travel_time"] for edge in edges) - network_raw) > (
        1e-6 * network_raw + 1e-3
    ):
        raise ValueError("Route edge times do not match the stored network duration")

    coordinates = [source.snap.snapped_xy]
    for edge in edges:
        segment = list(edge["geometry"].coords)
        if hypot(coordinates[-1][0] - segment[0][0],
                 coordinates[-1][1] - segment[0][1]) > ENDPOINT_ROUNDOFF_METERS:
            raise ValueError("Route geometry is disconnected or reversed")
        coordinates.extend(segment[1:])
    destination = overlay.reference.graph.nodes[target]
    if hypot(coordinates[-1][0] - destination["x"],
             coordinates[-1][1] - destination["y"]) > ENDPOINT_ROUNDOFF_METERS:
        raise ValueError("Route geometry does not end at its target")
    if len(coordinates) == 1:
        coordinates.append(coordinates[0])
    lonlat = [_TO_WGS84.transform(*point, errcheck=True) for point in coordinates]
    access_raw = source.snap.access_seconds
    if not isfinite(access_raw) or access_raw < 0:
        raise ValueError("Invalid raw access duration")
    # Integer deciseconds keep the displayed components consistent with the total.
    duration_ticks = round(10 * (access_raw + network_raw))
    access_ticks = round(10 * access_raw)
    return Route(
        duration_seconds=duration_ticks / 10, access_seconds=access_ticks / 10,
        network_seconds=(duration_ticks - access_ticks) / 10,
        distance_meters=fsum(edge["length_m"] for edge in edges),
        geometry=LineString(coordinates=lonlat),
    )
