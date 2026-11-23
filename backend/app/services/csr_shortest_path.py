"""Directed shortest paths over a request-local CSR overlay."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from math import isfinite
from time import perf_counter_ns

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

    @property
    def reachable_node_count(self) -> int:
        """Count persistent nodes with a finite distance within this source's cutoff."""
        return int(np.count_nonzero(np.isfinite(self.distances_seconds)))


@dataclass(frozen=True)
class CSRRoutingResult:
    """Keep the bundle and overlay used to compute the per-source paths."""

    graph: CSRGraph
    overlay: CSROverlay
    sources: tuple[CSRSourcePaths, ...]
    max_travel_seconds: float
    dijkstra_ms: float = field(default=0.0, compare=False)


type SourceLookup = Callable[[CSRGraph, SnapResult, float], CSRSourcePaths | None]


def _reuse_paths(
    cached: CSRSourcePaths, source_index: int, cutoff_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    distances, predecessors = cached.distances_seconds, cached.predecessors
    if cutoff_seconds < cached.network_cutoff_seconds:
        within_cutoff = distances <= cutoff_seconds
        distances = np.where(within_cutoff, distances, np.inf)
        predecessors = np.where(within_cutoff, predecessors, NO_PREDECESSOR)
    if source_index != cached.source_index:
        # Temporary source rows move when an earlier origin changes its snap type.
        predecessors = np.where(predecessors == cached.source_index, source_index, predecessors)
    return distances, predecessors


def route_csr_origins(
    graph: CSRGraph, snaps: Sequence[SnapResult], max_travel_seconds: float,
    *, get_cached_source: SourceLookup | None = None,
) -> CSRRoutingResult:
    """Reuse covered paths or run a directed search with the source's network cutoff."""
    if (isinstance(max_travel_seconds, bool) or not isfinite(max_travel_seconds)
            or max_travel_seconds < 0):
        raise ValueError("Travel cutoff must be finite and non-negative")

    overlay = build_csr_overlay(graph, snaps)
    node_count = len(graph.node_indices)
    sources = []
    started = perf_counter_ns()
    for snap in snaps:
        source = overlay.sources[snap.origin_id]
        cutoff = max_travel_seconds - snap.access_seconds
        if cutoff < 0:
            distances = np.full(node_count, np.inf)
            predecessors = np.full(node_count, NO_PREDECESSOR, dtype=np.int32)
        else:
            cached = get_cached_source(graph, snap, cutoff) if get_cached_source else None
            if cached is not None:
                distances, predecessors = _reuse_paths(cached, source, cutoff)
            else:
                distances, predecessors = dijkstra(
                    overlay.csr, directed=True, indices=source, limit=cutoff,
                    return_predecessors=True,
                )
        distances, predecessors = distances[:node_count], predecessors[:node_count]
        distances.setflags(write=False)
        predecessors.setflags(write=False)
        sources.append(CSRSourcePaths(snap, source, cutoff, distances, predecessors))
    return CSRRoutingResult(
        graph, overlay, tuple(sources), max_travel_seconds, (perf_counter_ns() - started) / 1e6,
    )
