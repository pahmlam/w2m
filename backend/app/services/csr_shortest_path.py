"""Directed shortest paths over a request-local CSR overlay."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

import numpy as np
from scipy.sparse.csgraph import dijkstra

from app.services.coordinate_snapper import SnapResult
from app.services.csr_overlay import CSROverlay, build_csr_overlay
from app.services.graph_loader import CSRGraph

# Native SciPy sentinel for the source itself and unreachable destinations.
NO_PREDECESSOR = -9999


@dataclass(frozen=True)
class CSRSourcePaths:
    """Distances and predecessors indexed by persistent CSR destination.

    Distances exclude access time. Unreachable destinations have infinite distance.
    Predecessors are overlay indices and can refer to a temporary source row.
    """

    snap: SnapResult
    source_index: int
    network_cutoff_seconds: float
    distances_seconds: np.ndarray
    predecessors: np.ndarray


@dataclass(frozen=True)
class CSRRoutingResult:
    """Keep the bundle and overlay used to compute the per-source paths."""

    graph: CSRGraph
    overlay: CSROverlay
    sources: tuple[CSRSourcePaths, ...]


def route_csr_origins(
    graph: CSRGraph, snaps: Sequence[SnapResult], max_travel_seconds: float,
) -> CSRRoutingResult:
    """Compute one directed search per snapped source using its access-adjusted cutoff."""
    if (isinstance(max_travel_seconds, bool) or not isfinite(max_travel_seconds)
            or max_travel_seconds < 0):
        raise ValueError("Travel cutoff must be finite and non-negative")

    overlay = build_csr_overlay(graph, snaps)
    node_count = len(graph.node_indices)
    sources = []
    for snap in snaps:
        source = overlay.sources[snap.origin_id]
        cutoff = max_travel_seconds - snap.access_seconds
        if cutoff < 0:
            distances = np.full(node_count, np.inf)
            predecessors = np.full(node_count, NO_PREDECESSOR, dtype=np.int32)
        else:
            distances, predecessors = dijkstra(
                overlay.csr, directed=True, indices=source, limit=cutoff,
                return_predecessors=True,
            )
        sources.append(CSRSourcePaths(
            snap, source, cutoff, distances[:node_count], predecessors[:node_count],
        ))
    return CSRRoutingResult(graph, overlay, tuple(sources))
