"""Request overlays and predecessor trees preserve directed reference distances."""

import copy
from dataclasses import replace
from math import fsum

import networkx as nx
import pytest
from shapely.geometry import LineString
from test_coordinate_snapper import make_snapper, request_at

from app.services.graph_loader import ReferenceGraph
from app.services.request_overlay import RequestOverlay, build_request_overlay
from app.services.shortest_path import dijkstra_paths, route_origins


def assert_tree(overlay: RequestOverlay, source, paths) -> None:
    for target, seconds in paths.distances_seconds.items():
        node = target
        seen = set()
        weights = []
        while node != source:
            assert node not in seen
            seen.add(node)
            parent, key = paths.predecessors[node]
            weights.append(overlay.graph.edges[parent, node, key]["travel_time"])
            node = parent
        assert abs(fsum(weights) - seconds) <= 1e-6 * seconds + 1e-3


@pytest.mark.parametrize("two_way", [False, True])
def test_fractional_sources_direction_and_independent_duplicates(two_way: bool) -> None:
    snapper = make_snapper(reverse=two_way)
    if two_way:
        snapper.reference.graph.edges[2, 1, 9]["travel_time"] = 200
    before = copy.deepcopy(snapper.reference.graph)
    snaps = snapper.snap_origins(request_at(500030, 2300000))
    overlay = build_request_overlay(snapper.reference, snaps)
    assert len(overlay.graph) == len(before) + 4
    for snap in snaps:
        source = overlay.sources[snap.origin_id]
        assert overlay.graph.in_degree(source) == 0
        assert overlay.graph.out_degree(source) == (2 if two_way else 1)
        assert overlay.graph.edges[source, 2, 7]["travel_time"] == pytest.approx(70)
        if two_way:
            assert overlay.graph.edges[source, 1, 9]["travel_time"] == pytest.approx(60)
        paths = dijkstra_paths(overlay, source, 1000)
        assert set(paths.distances_seconds) == ({1, 2} if two_way else {2})
        for _, _, data in overlay.graph.out_edges(source, data=True):
            assert data["geometry"].coords[0] == snap.snapped_xy
            assert data["length_m"] == data["geometry"].length
        assert_tree(overlay, source, paths)
    assert nx.utils.graphs_equal(before, snapper.reference.graph)


def test_endpoints_reuse_and_cutoff_zero_negative() -> None:
    snapper = make_snapper()
    overlay = build_request_overlay(snapper.reference,
                                    snapper.snap_origins(request_at(500000, 2300000)))
    assert len(overlay.graph) == 2
    assert set(overlay.sources.values()) == {1}
    assert dijkstra_paths(overlay, 1, 0).distances_seconds == {1: 0}
    assert dijkstra_paths(overlay, 1, -1).distances_seconds == {}
    with pytest.raises(ValueError):
        dijkstra_paths(overlay, 1, float("nan"))


@pytest.mark.parametrize("cutoff,reached", [(99.999999, False), (100, True), (100.000001, True)])
def test_cutoff_uses_raw_network_time(cutoff: float, reached: bool) -> None:
    snapper = make_snapper()
    overlay = build_request_overlay(snapper.reference,
                                    snapper.snap_origins(request_at(500000, 2300000)))
    assert (2 in dijkstra_paths(overlay, 1, cutoff).distances_seconds) == reached


def test_access_reduces_cutoff_and_keeps_network_distances_separate() -> None:
    snapper = make_snapper()
    snapper.reference.graph.edges[1, 2, 7]["travel_time"] = 400
    req = request_at(500030, 2300000)
    offset_origin = request_at(500030, 2300070).origins[0]
    req.origins[1] = offset_origin.model_copy(update={"id": "B"})
    req.optimization.max_travel_seconds = 300
    result = route_origins(snapper, req)
    a, b = result.sources[:2]
    assert a.paths.distances_seconds[2] == pytest.approx(280)
    assert b.snap.access_seconds == pytest.approx(50)
    assert b.network_cutoff_seconds == pytest.approx(250)
    assert 2 not in b.paths.distances_seconds


def test_parallel_keys_unreachable_and_stable_equal_paths(road_graph) -> None:
    # Reverse insertion order must not choose another equal-cost predecessor.
    road_graph.add_edge(1, 3, key=8, travel_time=130., length_m=200.)
    refs = []
    for graph in (road_graph, nx.MultiDiGraph()):
        if not graph:
            graph.add_nodes_from(reversed(list(road_graph.nodes(data=True))))
            graph.add_edges_from(reversed(list(road_graph.edges(keys=True, data=True))))
        # No temporary sources are needed to test the core network algorithm.
        ordered = nx.MultiDiGraph()
        ordered.add_nodes_from(sorted(graph.nodes(data=True)))
        ordered.add_edges_from(sorted(graph.edges(keys=True, data=True), key=lambda e: e[:3]))
        ref = ReferenceGraph(graph, None, {}, "test", "car")
        overlay = RequestOverlay(ref, ordered, {"A": 1})
        paths = dijkstra_paths(overlay, 1, 1000)
        assert paths.distances_seconds == {1: 0, 2: 80, 3: 130}
        assert paths.predecessors[2] == (1, 1)
        assert_tree(overlay, 1, paths)
        refs.append(paths)
    assert refs[0] == refs[1]


def test_curved_fragment_and_multiple_positions_match_base_oracle() -> None:
    snapper = make_snapper(reverse=True, curved=True)
    line = snapper.reference.graph.edges[1, 2, 7]["geometry"]
    snaps = []
    for label, fraction in zip("ABCD", (.2, .3, .7, .8)):
        point = line.interpolate(fraction, normalized=True)
        snap = snapper.snap_origins(request_at(point.x, point.y))[0]
        snaps.append(replace(snap, origin_id=label))
    overlay = build_request_overlay(snapper.reference, snaps)
    for snap in snaps:
        paths = dijkstra_paths(overlay, overlay.sources[snap.origin_id], 1000)
        for target, actual in paths.distances_seconds.items():
            expected = min((1-snap.theta)*100 + nx.shortest_path_length(
                snapper.reference.graph, 2, target, weight="travel_time"),
                snap.theta*40 + nx.shortest_path_length(
                    snapper.reference.graph, 1, target, weight="travel_time"))
            assert actual == pytest.approx(expected)
        assert_tree(overlay, overlay.sources[snap.origin_id], paths)


def test_self_loop_fragment() -> None:
    snapper = make_snapper()
    graph = snapper.reference.graph
    line = LineString([(500000, 2300000), (500050, 2300050), (500000, 2300000)])
    graph.add_edge(1, 1, key=11, geometry=line, travel_time=100, oneway=True)
    point = line.interpolate(.3, normalized=True)
    snap = snapper.snap_origins(request_at(500030, 2300000))[0]
    snap = replace(snap, edge_id=(1, 1, 11), theta=.3, snapped_xy=(point.x, point.y))
    overlay = build_request_overlay(snapper.reference, [snap])
    paths = dijkstra_paths(overlay, overlay.sources["A"], 100)
    assert paths.distances_seconds[1] == pytest.approx(70)


@pytest.mark.parametrize("change", [{"theta": float("nan")}, {"source_node_id": 1},
                                   {"reverse_edge_id": (2, 1, 7)}])
def test_bad_snap_never_changes_shared_graph(change: dict) -> None:
    snapper = make_snapper()
    before = copy.deepcopy(snapper.reference.graph)
    snap = snapper.snap_origins(request_at(500030, 2300000))[0]
    with pytest.raises(ValueError):
        build_request_overlay(snapper.reference, [replace(snap, **change)])
    assert nx.utils.graphs_equal(before, snapper.reference.graph)


def test_label_permutation_and_repeatability() -> None:
    snapper = make_snapper(reverse=True)
    req = request_at(500030, 2300000)
    req.origins[1] = request_at(500070, 2300000).origins[0].model_copy(update={"id": "B"})
    first = route_origins(snapper, req)
    repeated = route_origins(snapper, req)
    assert [s.paths for s in first.sources] == [s.paths for s in repeated.sources]
    req.origins.reverse()
    changed = route_origins(snapper, req)
    assert [s.paths for s in first.sources] == [s.paths for s in reversed(changed.sources)]
