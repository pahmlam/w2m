"""Candidate filtering trusts M1 flags but always applies raw total-time limits."""

import copy
from dataclasses import replace

import pytest
from test_coordinate_snapper import make_snapper, request_at

from app.services.meeting_optimizer import rank_candidates
from app.services.shortest_path import RoutingResult, ShortestPaths, route_origins


def routing_for(table: dict[int, tuple], offsets: tuple = (0., 0., 0., 0.)) -> RoutingResult:
    snapper = make_snapper(reverse=True)
    routing = route_origins(snapper, request_at(500000, 2300000))
    graph = routing.overlay.reference.graph
    for node in table:
        graph.add_node(node)
    for node in graph:
        graph.nodes[node].update(in_aoi=True, is_candidate=True)
    sources = tuple(replace(source, snap=replace(source.snap, access_seconds=offsets[i]),
                            network_cutoff_seconds=1000-offsets[i],
                            paths=ShortestPaths({n: times[i] for n, times in table.items()
                                                 if times[i] is not None}, {}))
                    for i, source in enumerate(routing.sources))
    return replace(routing, sources=sources)


def test_flags_missing_distances_nonfinite_and_persistent_split_nodes() -> None:
    routing = routing_for({-1: (10.,)*4, 1: (20.,)*4, 2: (20.,)*4,
                           3: (None, 20., 20., 20.), 4: (float('inf'),)*4, 5: (float('nan'),)*4})
    graph = routing.overlay.reference.graph
    graph.nodes[1]['is_candidate'] = False
    graph.nodes[2]['in_aoi'] = False
    ranked = rank_candidates(routing, phi=.5, max_travel_seconds=300)
    assert [c.node_id for c in ranked.candidates] == [-1]


def test_raw_cutoff_precedes_quantization_and_access_added_once() -> None:
    routing = routing_for({1: (250.04,)*4, 2: (250.,)*4}, offsets=(50.,)*4)
    ranked = rank_candidates(routing, phi=.5, max_travel_seconds=300)
    assert [c.node_id for c in ranked.candidates] == [2]
    assert ranked.candidates[0].travel_times_seconds == (300.,)*4


def test_zero_coincident_origin_wins_and_no_temp_candidates() -> None:
    routing = routing_for({1: (0.,)*4, -1: (.01,)*4})
    # Even if an overlay source advertises itself as a candidate, it is not persistent.
    graph = routing.overlay.graph.copy()
    graph.add_node('origin:fake', in_aoi=True, is_candidate=True)
    routing = replace(routing, overlay=replace(routing.overlay, graph=graph))
    ranked = rank_candidates(routing, phi=1, max_travel_seconds=300)
    assert ranked.candidates[0].node_id == 1
    assert ranked.candidates[0].score == 0


def test_reranking_is_readonly_and_label_symmetric(monkeypatch) -> None:
    routing = routing_for({1: (10., 20., 30., 40.), 2: (30.,)*4})
    before = copy.deepcopy(routing)
    monkeypatch.setattr('networkx.dijkstra_predecessor_and_distance',
                        lambda *a, **k: pytest.fail('Rerouted'))
    first = rank_candidates(routing, phi=0, max_travel_seconds=300)
    second = rank_candidates(routing, phi=1, max_travel_seconds=300)
    assert first.candidates[0].node_id == 1
    assert second.candidates[0].node_id == 2
    permuted = rank_candidates(replace(routing, sources=tuple(reversed(routing.sources))),
                               phi=1, max_travel_seconds=300)
    assert [(c.node_id, c.score) for c in permuted.candidates] == [
        (c.node_id, c.score) for c in second.candidates]
    assert routing.sources == before.sources
    assert list(routing.overlay.reference.graph.nodes(data=True)) == list(
        before.overlay.reference.graph.nodes(data=True))
    assert rank_candidates(routing, phi=1, max_travel_seconds=35).candidates
    assert rank_candidates(routing, phi=1, max_travel_seconds=300).candidates == second.candidates


def test_empty_and_exceeding_computed_cutoff() -> None:
    routing = routing_for({1: (400.,)*4})
    assert rank_candidates(routing, phi=.5, max_travel_seconds=300).candidates == ()
    with pytest.raises(ValueError, match='coverage'):
        rank_candidates(routing, phi=.5, max_travel_seconds=1001)


@pytest.mark.parametrize('limit', [-1., float('inf'), float('nan'), True])
def test_invalid_limits(limit: float) -> None:
    with pytest.raises(ValueError):
        rank_candidates(routing_for({1: (10.,)*4}), phi=.5, max_travel_seconds=limit)


def test_malformed_routing_tables_rejected() -> None:
    routing = routing_for({1: (-1., 0., 0., 0.)})
    with pytest.raises(ValueError, match='negative'):
        rank_candidates(routing, phi=.5, max_travel_seconds=300)
    with pytest.raises(ValueError, match='unique'):
        rank_candidates(replace(routing, sources=(routing.sources[0],)*4),
                        phi=.5, max_travel_seconds=300)
    with pytest.raises(ValueError):
        rank_candidates(replace(routing, sources=()), phi=.5, max_travel_seconds=300)
