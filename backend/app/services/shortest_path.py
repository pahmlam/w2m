"""Directed NetworkX reference routing with access-adjusted cutoffs."""

from dataclasses import dataclass
from math import isfinite

import networkx as nx

from app.models.requests import MeetingRequest
from app.services.coordinate_snapper import CoordinateSnapper, SnapResult
from app.services.request_overlay import NodeId, RequestOverlay, build_request_overlay


@dataclass(frozen=True)
class ShortestPaths:
    """Raw network distances to persistent nodes and one exact incoming edge per node."""

    distances_seconds: dict[int, float]
    predecessors: dict[int, tuple[NodeId, int]]


@dataclass(frozen=True)
class SourcePaths:
    """Keep access time separate from the network search and its computed cutoff."""

    snap: SnapResult
    source_node: NodeId
    network_cutoff_seconds: float
    paths: ShortestPaths


@dataclass(frozen=True)
class RoutingResult:
    """Request-local data needed by the later scorer and route builder."""

    overlay: RequestOverlay
    sources: tuple[SourcePaths, ...]
    graph_version: str
    weight_profile_version: str


def dijkstra_paths(
    overlay: RequestOverlay, source: NodeId, cutoff_seconds: float,
) -> ShortestPaths:
    """Run directed Dijkstra; omit temporary nodes and unreachable/out-of-cutoff nodes."""
    if isinstance(cutoff_seconds, bool) or not isfinite(cutoff_seconds):
        raise ValueError("Network cutoff must be finite")
    if source not in overlay.graph:
        raise ValueError("Unknown routing source")
    if cutoff_seconds < 0:
        return ShortestPaths({}, {})
    parents, distances = nx.dijkstra_predecessor_and_distance(
        overlay.graph, source, cutoff=cutoff_seconds, weight="travel_time",
    )
    persistent = {node: seconds for node, seconds in distances.items()
                  if node in overlay.reference.graph}
    predecessors = {}
    for node in persistent:
        if node == source:
            continue
        parent = parents[node][0]
        edges = overlay.graph[parent][node]
        key = min(edges, key=lambda k: (edges[k]["travel_time"], k))
        predecessors[node] = (parent, key)
    return ShortestPaths(persistent, predecessors)


def route_origins(snapper: CoordinateSnapper, request: MeetingRequest) -> RoutingResult:
    """Snap once and compute a separate reference distance table for every origin."""
    snaps = snapper.snap_origins(request)
    overlay = build_request_overlay(snapper.reference, snaps)
    sources = []
    for snap in snaps:
        source = overlay.sources[snap.origin_id]
        cutoff = request.optimization.max_travel_seconds - snap.access_seconds
        sources.append(SourcePaths(snap, source, cutoff, dijkstra_paths(overlay, source, cutoff)))
    return RoutingResult(overlay, tuple(sources), snapper.reference.graph_version,
                         snapper.reference.weight_profile_version)
