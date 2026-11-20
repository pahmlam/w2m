"""Append outgoing snap fragments to a request-local directed CSR matrix."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType

import numpy as np
from scipy.sparse import csr_matrix
from shapely.geometry import LineString, Point

from app.services.coordinate_snapper import ENDPOINT_ROUNDOFF_METERS, SnapResult
from app.services.graph_loader import CSRGraph

MAX_REQUEST_SOURCES = 4


@dataclass(frozen=True)
class SourceFragment:
    """Identify the directed edge and the start of its retained geometry."""

    edge_index: int
    start_fraction: float


@dataclass(frozen=True)
class CSROverlay:
    """Request-local CSR and the indices needed to use its temporary rows."""

    csr: csr_matrix
    sources: Mapping[str, int]
    fragments: Mapping[tuple[int, int], SourceFragment]


def build_csr_overlay(graph: CSRGraph, snaps: Sequence[SnapResult]) -> CSROverlay:
    """Add at most four sources while keeping all persistent CSR offsets unchanged."""
    if (not 1 <= len(snaps) <= MAX_REQUEST_SOURCES
            or len({snap.origin_id for snap in snaps}) != len(snaps)
            or any(not snap.origin_id for snap in snaps)):
        raise ValueError("Expected one to four sources with unique non-empty IDs")

    base = graph.csr
    node_count = base.shape[0]
    geometry = graph.geometry
    coordinates, offsets = geometry["coordinates"], geometry["offsets"]
    sources: dict[str, int] = {}
    fragments: dict[tuple[int, int], SourceFragment] = {}
    weights: list[float] = []
    targets: list[int] = []
    row_ends: list[int] = []
    for snap in snaps:
        edge_index = graph.edge_indices.get(snap.edge_id)
        if (edge_index is None or not isfinite(snap.theta) or not 0 <= snap.theta <= 1
                or not isfinite(snap.access_seconds) or snap.access_seconds < 0
                or any(not isfinite(value) for value in snap.snapped_xy)):
            raise ValueError("Inconsistent snapped source")
        reverse_index = graph.reverse_edge_indices.get(edge_index)
        if (snap.reverse_edge_id is None and reverse_index is not None
                or snap.reverse_edge_id is not None and (
                    reverse_index is None
                    or graph.edge_indices.get(snap.reverse_edge_id) != reverse_index
                )):
            raise ValueError("Snap reverse edge does not match the graph")
        edge_coordinates = coordinates[offsets[edge_index]:offsets[edge_index + 1]]
        projected = LineString(edge_coordinates).interpolate(snap.theta, normalized=True)
        if projected.distance(Point(snap.snapped_xy)) > ENDPOINT_ROUNDOFF_METERS:
            raise ValueError("Snap point does not match its edge fraction")

        u, v, _ = snap.edge_id
        endpoint = (u, v)[int(snap.theta)] if snap.theta in (0, 1) else None
        if snap.source_node_id != endpoint:
            raise ValueError("Snap endpoint identity is inconsistent")
        if endpoint is not None:
            sources[snap.origin_id] = graph.node_indices[endpoint]
            continue

        source = node_count + len(row_ends)
        sources[snap.origin_id] = source
        outgoing = [(graph.node_indices[v], edge_index, snap.theta)]
        if reverse_index is not None:
            reversed_coordinates = coordinates[offsets[reverse_index]:offsets[reverse_index + 1]]
            if not np.array_equal(edge_coordinates, reversed_coordinates[::-1]):
                raise ValueError("Reverse geometry must exactly match the physical road")
            outgoing.append((graph.node_indices[u], reverse_index, 1 - snap.theta))
        for target, index, start in sorted(outgoing):
            seconds = (1 - start) * graph.edge_seconds(index)
            if seconds <= 0:
                raise ValueError("Invalid source fragment travel time")
            targets.append(target)
            weights.append(seconds)
            fragments[source, target] = SourceFragment(index, start)
        row_ends.append(base.nnz + len(weights))

    size = node_count + len(row_ends)
    matrix = base
    if row_ends:
        matrix = csr_matrix((
            np.concatenate((base.data, weights)),
            np.concatenate((base.indices, targets)),
            np.concatenate((base.indptr, row_ends)),
        ), shape=(size, size))
    return CSROverlay(matrix, MappingProxyType(sources), MappingProxyType(fragments))
