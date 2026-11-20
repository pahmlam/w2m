"""Recover original directed edges along a stored CSR predecessor chain."""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum, isfinite
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from scipy.sparse import csr_matrix

    from app.services.csr_shortest_path import CSRRoutingResult
    from app.services.graph_reverse_edges import EdgeId


@dataclass(frozen=True)
class CSRRouteEdge:
    """Original directed edge, retained fraction start, and raw traversal time."""

    edge_id: EdgeId
    edge_index: int
    start_fraction: float
    travel_time_seconds: float


def csr_arc_offset(csr: csr_matrix, source_index: int, target_index: int) -> int:
    """Locate a directed arc in CSR with sorted column indices."""
    start, end = (int(value) for value in csr.indptr[source_index:source_index + 2])
    offset = start + int(np.searchsorted(csr.indices[start:end], target_index))
    if offset >= end or csr.indices[offset] != target_index:
        raise ValueError("Predecessor has no corresponding CSR arc")
    return offset


def trace_csr_route_edges(
    routing: CSRRoutingResult, origin_id: str, target_node_id: int,
) -> tuple[CSRRouteEdge, ...]:
    """Return ordered edges for a reachable persistent target using saved predecessors."""
    source = next((paths for paths in routing.sources if paths.snap.origin_id == origin_id), None)
    if source is None:
        raise ValueError("Unknown route origin")
    target = routing.graph.node_indices.get(target_node_id)
    if target is None:
        raise ValueError("Unknown route target node")
    network_seconds = float(source.distances_seconds[target])
    if not isfinite(network_seconds) or network_seconds < 0:
        raise ValueError("Route target is unreachable within the computed cutoff")

    mappings = routing.graph.mappings
    node_ids, edge_ids = mappings["node_ids"], mappings["edge_ids"]
    arc_edge_indices = mappings["arc_edge_indices"]
    matrix = routing.overlay.csr
    seen: set[int] = set()
    edges: list[CSRRouteEdge] = []
    current = target
    while current != source.source_index:
        previous = int(source.predecessors[current])
        if (current in seen or previous < 0 or previous >= matrix.shape[0]
                or (previous >= len(node_ids) and previous != source.source_index)):
            raise ValueError("Broken or cyclic CSR predecessor chain")
        seen.add(current)
        offset = csr_arc_offset(matrix, previous, current)
        if previous < len(node_ids):
            edge_index, start = int(arc_edge_indices[offset]), 0.0
        else:
            fragment = routing.overlay.fragments.get((previous, current))
            if fragment is None:
                raise ValueError("Temporary predecessor arc has no original edge mapping")
            edge_index, start = fragment.edge_index, fragment.start_fraction
        u, v, key = (int(value) for value in edge_ids[edge_index])
        if v != node_ids[current] or (previous < len(node_ids) and u != node_ids[previous]):
            raise ValueError("CSR arc maps to a different directed edge")
        edges.append(CSRRouteEdge((u, v, key), edge_index, start, float(matrix.data[offset])))
        current = previous
    if abs(fsum(edge.travel_time_seconds for edge in edges) - network_seconds) > (
        1e-6 * network_seconds + 1e-3
    ):
        raise ValueError("Route edge times do not match the stored network duration")
    return tuple(reversed(edges))
