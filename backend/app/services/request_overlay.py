"""Build isolated NetworkX request graphs for the M2 reference implementation."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

import networkx as nx
from shapely.geometry import LineString, Point
from shapely.ops import substring

from app.services.coordinate_snapper import ENDPOINT_ROUNDOFF_METERS, SnapResult
from app.services.graph_loader import ReferenceGraph
from app.services.graph_reverse_edges import EdgeId

NodeId = int | str


@dataclass(frozen=True)
class RequestOverlay:
    """Private graph and source identities, retaining the persistent graph separately."""

    reference: ReferenceGraph
    graph: nx.MultiDiGraph
    sources: dict[str, NodeId]


def build_request_overlay(reference: ReferenceGraph, snaps: Sequence[SnapResult]) -> RequestOverlay:
    """Copy the reference deterministically and add only outgoing source fragments."""
    if not snaps or len({snap.origin_id for snap in snaps}) != len(snaps):
        raise ValueError("Expected non-empty sources with unique IDs")
    # This full copy is intentionally confined to the offline NetworkX reference.
    graph = nx.MultiDiGraph(**reference.graph.graph)
    graph.add_nodes_from(sorted(reference.graph.nodes(data=True)))
    graph.add_edges_from(sorted(reference.graph.edges(keys=True, data=True), key=lambda e: e[:3]))
    reverse = {}
    for pair in reference.reverse_mapping["pairs"]:
        a, b = tuple(pair["forward"]), tuple(pair["reverse"])
        reverse[a], reverse[b] = b, a
    sources: dict[str, NodeId] = {}
    for snap in snaps:
        if (not isfinite(snap.theta) or not 0 <= snap.theta <= 1
                or not isfinite(snap.access_seconds) or snap.access_seconds < 0
                or any(not isfinite(value) for value in snap.snapped_xy)
                or snap.edge_id not in reference.graph.edges
                or reverse.get(snap.edge_id) != snap.reverse_edge_id):
            raise ValueError("Inconsistent snapped source")
        line = reference.graph.edges[snap.edge_id]["geometry"]
        if line.interpolate(snap.theta, normalized=True).distance(Point(snap.snapped_xy)) > (
            ENDPOINT_ROUNDOFF_METERS
        ):
            raise ValueError("Snap point does not match its edge fraction")
        endpoint = snap.edge_id[0 if snap.theta == 0 else 1] if snap.theta in (0, 1) else None
        if snap.source_node_id != endpoint:
            raise ValueError("Snap endpoint identity is inconsistent")
        if endpoint is not None:
            sources[snap.origin_id] = endpoint
            continue
        source = f"origin:{snap.origin_id}"
        sources[snap.origin_id] = source
        graph.add_node(source, x=snap.snapped_xy[0], y=snap.snapped_xy[1],
                       lon=snap.snapped_lonlat[0], lat=snap.snapped_lonlat[1], is_candidate=False)
        _add_fragment(graph, reference, source, snap.edge_id, snap.theta, snap.snapped_xy)
        if snap.reverse_edge_id is not None:
            reverse_line = reference.graph.edges[snap.reverse_edge_id]["geometry"]
            if not line.equals_exact(LineString(list(reverse_line.coords)[::-1]), 0):
                raise ValueError("Reverse geometry must exactly match the physical road")
            _add_fragment(graph, reference, source, snap.reverse_edge_id,
                          1 - snap.theta, snap.snapped_xy)
    return RequestOverlay(reference, nx.freeze(graph), sources)


def _add_fragment(
    graph: nx.MultiDiGraph, reference: ReferenceGraph, source: str, edge: EdgeId,
    start_fraction: float, snapped_xy: tuple[float, float],
) -> None:
    data = reference.graph.edges[edge]
    geometry = substring(data["geometry"], start_fraction, 1, normalized=True)
    seconds = (1 - start_fraction) * data["travel_time"]
    if not isinstance(geometry, LineString) or not isfinite(seconds) or seconds <= 0:
        raise ValueError("Invalid source fragment")
    # Align floating-point interpolation with the stored snap, without changing the base road.
    geometry = LineString([snapped_xy, *list(geometry.coords)[1:]])
    graph.add_edge(source, edge[1], key=edge[2], geometry=geometry, length_m=geometry.length,
                   length=geometry.length, travel_time=seconds, travel_time_seconds=seconds,
                   original_edge_id=edge, start_fraction=start_fraction, end_fraction=1.0)
