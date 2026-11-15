"""Selected routes preserve geometry, raw costs, and decisecond API accounting."""

import copy
from dataclasses import replace

import networkx as nx
import pytest
from shapely.geometry import LineString
from test_coordinate_snapper import TO_WGS84, make_snapper, request_at
from test_meeting_optimizer import routing_for

from app.models.responses import Route
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.meeting_optimizer import (
    build_meeting_results,
    rank_candidates,
    select_candidates,
)
from app.services.request_overlay import RequestOverlay
from app.services.route_builder import build_route
from app.services.shortest_path import ShortestPaths, SourcePaths, route_origins


def prepare_snapper(*, reverse: bool = False, curved: bool = False) -> CoordinateSnapper:
    snapper = make_snapper(reverse=reverse, curved=curved)
    for _, node in snapper.reference.graph.nodes(data=True):
        node['lon'], node['lat'] = TO_WGS84.transform(node['x'], node['y'])
        node.update(in_aoi=True, is_candidate=True)
    for _, _, edge in snapper.reference.graph.edges(data=True):
        edge['length_m'] = edge['geometry'].length
    return snapper


@pytest.mark.parametrize('spacing,expected', [
    (500., [1, 3, 5]), (500.000001, [1, 5]), (0., [1, 2, 3, 4, 5]),
])
def test_spacing_boundary_order_and_no_relaxation(spacing: float, expected: list[int]) -> None:
    routing = routing_for({i: (float(i),)*4 for i in range(1, 7)})
    # The second point fails spacing, but must not prevent the third from being selected.
    for node, x in zip(range(1, 7), [0., 499.999999, 500., 500., 1000.000001, 1100.]):
        routing.overlay.reference.graph.nodes[node].update(x=500000+x, y=2300000.)
    ranking = rank_candidates(routing, phi=.5, max_travel_seconds=300)
    selected = select_candidates(ranking, top_k=5, min_spacing_meters=spacing)
    assert [c.node_id for c in selected] == expected
    assert select_candidates(ranking, top_k=1, min_spacing_meters=spacing) == selected[:1]
    assert len(ranking.candidates) == 6


@pytest.mark.parametrize('top_k,spacing', [
    (0, 500), (6, 500), (True, 500), (1.5, 500),
    (5, -1), (5, 5001), (5, float('nan')), (5, float('inf')), (5, True),
])
def test_invalid_selection_parameters(top_k: int, spacing: float) -> None:
    ranking = rank_candidates(routing_for({}), phi=.5, max_travel_seconds=300)
    with pytest.raises(ValueError):
        select_candidates(ranking, top_k=top_k, min_spacing_meters=spacing)


@pytest.mark.parametrize('two_way', [False, True])
def test_curved_fragments_direction_access_and_exact_geometry(two_way: bool) -> None:
    snapper = prepare_snapper(reverse=two_way, curved=True)
    line = snapper.reference.graph.edges[1, 2, 7]['geometry']
    point = line.interpolate(.3, normalized=True)
    request = request_at(point.x, point.y)
    # A separate access segment must never become part of the network polyline or distance.
    request.origins[1] = request_at(500030, 2300070).origins[1]
    routing = route_origins(snapper, request)
    for source in routing.sources:
        for target, seconds in source.paths.distances_seconds.items():
            route = build_route(routing.overlay, source, target)
            fragment = routing.overlay.graph.edges[source.source_node, target,
                                                    7 if target == 2 else 9]
            expected = [TO_WGS84.transform(*xy) for xy in fragment['geometry'].coords]
            assert route.geometry.coordinates == expected
            assert route.geometry.coordinates[0] == pytest.approx(source.snap.snapped_lonlat)
            assert route.distance_meters == pytest.approx(fragment['geometry'].length)
            assert route.duration_seconds == round(10*(seconds + source.snap.access_seconds))/10
            assert round(10*route.access_seconds) + round(10*route.network_seconds) == (
                round(10*route.duration_seconds))
    if not two_way:
        with pytest.raises(ValueError, match='unreachable'):
            build_route(routing.overlay, routing.sources[0], 1)


def test_parallel_key_and_multiedge_polyline_are_taken_from_saved_tree() -> None:
    snapper = prepare_snapper()
    graph = snapper.reference.graph
    graph.add_node(3, x=500200., y=2300000.)
    line = LineString([(500100, 2300000), (500150, 2300040), (500200, 2300000)])
    graph.add_edge(2, 3, key=8, geometry=line, length_m=line.length, travel_time=10.)
    graph.add_edge(2, 3, key=2, geometry=line, length_m=line.length, travel_time=10.)
    graph.add_edge(2, 3, key=0, geometry=LineString([line.coords[0], line.coords[-1]]),
                   length_m=100., travel_time=20.)
    routing = route_origins(snapper, request_at(500000, 2300000))
    source = routing.sources[0]
    assert source.paths.predecessors[3] == (2, 2)
    # Altering an unused parallel must have no effect on the route.
    routing.overlay.graph.edges[2, 3, 0]['travel_time'] = 1.
    route = build_route(routing.overlay, source, 3)
    assert route.network_seconds == 110
    assert route.distance_meters == pytest.approx(100 + line.length)
    assert route.geometry.coordinates == [TO_WGS84.transform(*xy) for xy in [
        (500000, 2300000), *line.coords]]


def test_zero_length_coincident_results_ranks_and_readonly_reuse(monkeypatch) -> None:
    snapper = prepare_snapper(reverse=True)
    routing = route_origins(snapper, request_at(500000, 2300000))
    before = copy.deepcopy(routing)
    monkeypatch.setattr(nx, 'dijkstra_predecessor_and_distance',
                        lambda *a, **k: pytest.fail('Rerouted'))
    ranking = rank_candidates(routing, phi=.5, max_travel_seconds=300)
    results = build_meeting_results(ranking, top_k=5, min_spacing_meters=0)
    assert [r.rank for r in results] == [1, 2]
    assert results[0].score == 0
    for result in results:
        assert set(result.routes) == set(result.travel_times) == set('ABCD')
        for label, route in result.routes.items():
            assert route.duration_seconds == result.travel_times[label]
            assert route.geometry.coordinates[-1] == (result.location.lon, result.location.lat)
    for route in results[0].routes.values():
        assert route.distance_meters == route.network_seconds == 0
        assert len(route.geometry.coordinates) == 2
        assert route.geometry.coordinates[0] == route.geometry.coordinates[1]
    assert build_meeting_results(ranking, top_k=5, min_spacing_meters=500) == results[:1]
    assert nx.utils.graphs_equal(routing.overlay.graph, before.overlay.graph)
    assert nx.utils.graphs_equal(snapper.reference.graph, before.overlay.reference.graph)
    assert routing.sources == before.sources


def test_empty_skips_route_builder(monkeypatch) -> None:
    ranking = rank_candidates(routing_for({}), phi=.5, max_travel_seconds=300)
    monkeypatch.setattr('app.services.meeting_optimizer.build_route',
                        lambda *a: pytest.fail('Built an unselected route'))
    assert build_meeting_results(ranking, top_k=5, min_spacing_meters=500) == []


def test_routes_only_built_for_selected_nodes(monkeypatch) -> None:
    routing = route_origins(prepare_snapper(reverse=True), request_at(500030, 2300000))
    ranking = rank_candidates(routing, phi=.5, max_travel_seconds=300)
    calls = []

    def record_route(overlay: RequestOverlay, source: SourcePaths, target: int) -> Route:
        calls.append((source.snap.origin_id, target))
        return build_route(overlay, source, target)

    monkeypatch.setattr('app.services.meeting_optimizer.build_route', record_route)
    results = build_meeting_results(ranking, top_k=5, min_spacing_meters=500)
    assert len(results) == 1
    assert calls == [(label, results[0].node_id) for label in 'ABCD']


def test_display_network_uses_residual_ticks() -> None:
    snapper = prepare_snapper()
    snapper.reference.graph.edges[1, 2, 7]['travel_time'] = .06
    routing = route_origins(snapper, request_at(500000, 2300000))
    source = routing.sources[0]
    source = replace(source, snap=replace(source.snap, access_seconds=.06))
    route = build_route(routing.overlay, source, 2)
    assert (route.duration_seconds, route.access_seconds, route.network_seconds) == (.1, .1, 0)


@pytest.mark.parametrize('corruption', ['missing', 'cycle', 'edge', 'cost', 'geometry'])
def test_broken_route_data_is_rejected(corruption: str) -> None:
    routing = route_origins(prepare_snapper(), request_at(500000, 2300000))
    source = routing.sources[0]
    predecessors = dict(source.paths.predecessors)
    if corruption == 'missing':
        predecessors.clear()
    elif corruption == 'cycle':
        predecessors[2] = (2, 7)
        graph = nx.MultiDiGraph(routing.overlay.graph)
        graph.add_edge(2, 2, key=7, **dict(graph.edges[1, 2, 7]))
        routing = replace(routing, overlay=replace(routing.overlay, graph=graph))
    elif corruption == 'edge':
        predecessors[2] = (1, 99)
    elif corruption == 'cost':
        routing.overlay.graph.edges[1, 2, 7]['travel_time'] += 1
    else:
        edge = routing.overlay.graph.edges[1, 2, 7]
        edge['geometry'] = LineString(list(edge['geometry'].coords)[::-1])
    source = replace(source, paths=ShortestPaths(source.paths.distances_seconds, predecessors))
    with pytest.raises(ValueError):
        build_route(routing.overlay, source, 2)
