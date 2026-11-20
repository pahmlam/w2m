"""Verify directed request-local sources over an immutable CSR bundle."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse.csgraph import dijkstra
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.services.coordinate_snapper import SnapResult
from app.services.csr_overlay import SourceFragment, build_csr_overlay
from app.services.graph_loader import load_csr_graph


def _two_way_snap(origin_id: str = "A") -> SnapResult:
    return SnapResult(
        origin_id, (105, 20.8), (-3, 7, 0), (7, -3, 0), 0.25,
        (500005, 2300000), (105, 20.8), 14, 10, None,
    )


def test_overlay_preserves_directed_weights_parallel_edges_and_base(csr_bundle: Path) -> None:
    graph = load_csr_graph(csr_bundle)
    first = _two_way_snap()
    parallel = replace(first, origin_id="C", edge_id=(-3, 7, 1), reverse_edge_id=None,
                       theta=0.5, snapped_xy=(500010, 2300005))
    endpoint = replace(first, origin_id="D", theta=1, source_node_id=7,
                       snapped_xy=(500020, 2300000))
    overlay = build_csr_overlay(graph, [first, _two_way_snap("B"), parallel, endpoint])

    assert overlay.sources == {"A": 2, "B": 3, "C": 4, "D": 1}
    assert overlay.csr.has_canonical_format
    np.testing.assert_array_equal(overlay.csr.toarray(), [
        [0, 5, 0, 0, 0],
        [11, 0, 0, 0, 0],
        [2.75, 3.75, 0, 0, 0],
        [2.75, 3.75, 0, 0, 0],
        [0, 10, 0, 0, 0],
    ])
    assert overlay.fragments == {
        (2, 0): SourceFragment(2, 0.75), (2, 1): SourceFragment(0, 0.25),
        (3, 0): SourceFragment(2, 0.75), (3, 1): SourceFragment(0, 0.25),
        (4, 1): SourceFragment(1, 0.5),
    }
    np.testing.assert_array_equal(dijkstra(overlay.csr, directed=True, indices=4),
                                  [21, 10, np.inf, np.inf, 0])
    np.testing.assert_array_equal(overlay.csr.indptr[:3], graph.csr.indptr)
    overlay.csr.data[0] = 999
    independent = build_csr_overlay(graph, [parallel])
    assert independent.sources == {"C": 2}
    assert independent.csr.data.tolist() == [5, 11, 10]
    assert graph.csr.data.tolist() == [5, 11]


def test_all_endpoint_sources_reuse_base_rows(csr_bundle: Path) -> None:
    graph = load_csr_graph(csr_bundle)
    origin = replace(_two_way_snap(), theta=0, source_node_id=-3, snapped_xy=(500000, 2300000))
    overlay = build_csr_overlay(graph, [origin, replace(origin, origin_id="B")])
    assert overlay.sources == {"A": 0, "B": 0}
    assert not overlay.fragments
    assert overlay.csr.shape == (2, 2)
    assert np.shares_memory(overlay.csr.data, graph.csr.data)


@pytest.mark.parametrize("changes", [
    {"theta": np.nan}, {"reverse_edge_id": None}, {"reverse_edge_id": (7, -3, 99)},
    {"source_node_id": 7}, {"snapped_xy": (500006, 2300000)}, {"access_seconds": -1},
])
def test_rejects_inconsistent_snap(csr_bundle: Path, changes: dict) -> None:
    graph = load_csr_graph(csr_bundle)
    with pytest.raises(ValueError):
        build_csr_overlay(graph, [replace(_two_way_snap(), **changes)])


def test_rejects_too_many_or_duplicate_source_ids(csr_bundle: Path) -> None:
    graph = load_csr_graph(csr_bundle)
    with pytest.raises(ValueError, match="one to four"):
        build_csr_overlay(graph, [_two_way_snap(str(i)) for i in range(5)])
    with pytest.raises(ValueError, match="unique"):
        build_csr_overlay(graph, [_two_way_snap(), _two_way_snap()])
