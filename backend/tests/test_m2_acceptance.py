"""Close reference acceptance gaps without live OSM or a production HTTP API."""

import networkx as nx
import pytest
from test_coordinate_snapper import request_at
from test_route_builder import prepare_snapper

from app.models.responses import MeetingResult
from app.services.graph_loader import ReferenceGraph
from app.services.meeting_optimizer import build_meeting_results, rank_candidates
from app.services.request_overlay import RequestOverlay
from app.services.shortest_path import dijkstra_paths, route_origins


def test_tc01_tc02_known_directed_distances_and_parallel_ties(road_graph: nx.MultiDiGraph) -> None:
    reference = ReferenceGraph(road_graph, None, {}, 'test', 'car')
    overlay = RequestOverlay(reference, road_graph, {'A': 1})
    forward = dijkstra_paths(overlay, 1, 1000)
    assert forward.distances_seconds == {1: 0., 2: 80., 3: 130.}
    assert forward.predecessors == {2: (1, 1), 3: (2, 0)}
    assert dijkstra_paths(overlay, 2, 1000).distances_seconds == {2: 0., 1: 120., 3: 50.}
    assert dijkstra_paths(overlay, 3, 1000).distances_seconds == {3: 0.}
    assert dijkstra_paths(overlay, 1, 129.999).distances_seconds == {1: 0., 2: 80.}


@pytest.mark.parametrize('reverse_seconds', [None, 100., 200.])
def test_tc11_documented_thirty_percent_split(reverse_seconds: float | None) -> None:
    snapper = prepare_snapper(reverse=reverse_seconds is not None)
    if reverse_seconds is not None:
        snapper.reference.graph.edges[2, 1, 9]['travel_time'] = reverse_seconds
    routing = route_origins(snapper, request_at(500030, 2300000))
    for source in routing.sources:
        assert source.snap.theta == pytest.approx(.3)
        outgoing = routing.overlay.graph[source.source_node]
        assert outgoing[2][7]['travel_time'] == pytest.approx(70.)
        if reverse_seconds is None:
            assert set(outgoing) == {2}
        else:
            assert set(outgoing) == {1, 2}
            assert outgoing[1][9]['travel_time'] == pytest.approx(.3 * reverse_seconds)


def test_tc12_access_offset_for_every_common_node() -> None:
    snapper = prepare_snapper(reverse=True)
    request = request_at(500030, 2300000)
    request.origins[1] = request_at(500030, 2300070).origins[1]
    routing = route_origins(snapper, request)
    on_road, off_road = routing.sources[:2]
    assert off_road.snap.snap_distance_m == pytest.approx(70.)
    assert on_road.paths.distances_seconds.keys() == off_road.paths.distances_seconds.keys()
    ranking = rank_candidates(routing, phi=.5, max_travel_seconds=3600)
    assert len(ranking.candidates) == 2
    for candidate in ranking.candidates:
        assert candidate.raw_times_seconds[1] - candidate.raw_times_seconds[0] == pytest.approx(50.)
        assert candidate.travel_times_seconds[1] - candidate.travel_times_seconds[0] == 50.


@pytest.mark.parametrize('phi', [0., .5, 1.])
def test_tc07_full_pipeline_repeatability_and_label_symmetry(phi: float) -> None:
    snapper = prepare_snapper(reverse=True, curved=True)
    line = snapper.reference.graph.edges[1, 2, 7]['geometry']
    request = request_at(500000, 2300000)
    for index, fraction in enumerate((.1, .3, .6, .9)):
        point = line.interpolate(fraction, normalized=True)
        request.origins[index] = request_at(point.x, point.y).origins[index]

    def results_for_request() -> list[MeetingResult]:
        routing = route_origins(snapper, request)
        ranking = rank_candidates(routing, phi=phi, max_travel_seconds=3600)
        return build_meeting_results(ranking, top_k=5, min_spacing_meters=0)

    original = results_for_request()
    assert results_for_request() == original
    labels = dict(zip('ABCD', 'DCBA'))
    request.origins = [origin.model_copy(update={'id': labels[origin.id]})
                       for origin in reversed(request.origins)]
    permuted = results_for_request()
    assert [(r.node_id, r.score, r.rank) for r in permuted] == [
        (r.node_id, r.score, r.rank) for r in original]
    for before, after in zip(original, permuted):
        assert after.travel_times == {labels[k]: v for k, v in before.travel_times.items()}
        assert after.routes == {labels[k]: v for k, v in before.routes.items()}


def test_raw_cutoff_reuse_matches_fresh_reference_routing() -> None:
    snapper = prepare_snapper(reverse=True)
    for _, _, edge in snapper.reference.graph.edges(data=True):
        edge['travel_time'] *= 20
    request = request_at(500030, 2300000)
    routing = route_origins(snapper, request)
    request.optimization.max_travel_seconds = 900
    fresh = route_origins(snapper, request)
    for data in (routing, fresh):
        ranking = rank_candidates(data, phi=.5, max_travel_seconds=900)
        results = build_meeting_results(ranking, top_k=5, min_spacing_meters=0)
        if data is routing:
            cached_results = results
        else:
            assert results == cached_results
    with pytest.raises(ValueError, match='coverage'):
        rank_candidates(fresh, phi=.5, max_travel_seconds=3600)
