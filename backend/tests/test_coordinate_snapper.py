"""Reference snapping checks use deterministic synthetic metric roads."""

import copy

import networkx as nx
import pytest
from pyproj import Transformer
from shapely import Point
from shapely.geometry import LineString, Polygon, box

from app.config.settings import Settings
from app.models.requests import MeetingRequest
from app.services.coordinate_snapper import CoordinateSnapper, SnapError
from app.services.graph_loader import ReferenceGraph
from app.services.graph_reverse_edges import identify_reverse_edges

TO_WGS84 = Transformer.from_crs(32648, 4326, always_xy=True)


def make_snapper(reverse: bool = False, curved: bool = False) -> CoordinateSnapper:
    graph = nx.MultiDiGraph(crs="EPSG:32648")
    graph.add_node(1, x=500000.0, y=2300000.0)
    graph.add_node(2, x=500100.0, y=2300000.0)
    coords = [(500000, 2300000), (500040, 2300040), (500100, 2300000)] if curved else [
        (500000, 2300000), (500100, 2300000)]
    graph.add_edge(1, 2, key=7, geometry=LineString(coords), oneway=not reverse,
                   osmid=123, travel_time=100.0)
    if reverse:
        graph.add_edge(2, 1, key=9, geometry=LineString(coords[::-1]), oneway=False,
                       osmid=123, travel_time=40.0)
    ref = ReferenceGraph(graph, box(104, 19, 106, 22), identify_reverse_edges(graph), "test", "car")
    return CoordinateSnapper(ref, Settings(_env_file=None))


def request_at(x: float, y: float) -> MeetingRequest:
    lon, lat = TO_WGS84.transform(x, y)
    return MeetingRequest.model_validate({"origins": [
        {"id": label, "lat": lat, "lon": lon} for label in "ABCD"
    ]})


@pytest.mark.parametrize("reverse", [False, True])
def test_projection_offset_duplicates_and_immutability(reverse: bool) -> None:
    snapper = make_snapper(reverse)
    before = copy.deepcopy(snapper.reference.graph)
    request = request_at(500030, 2300070)
    results = snapper.snap_origins(request)
    assert [result.origin_id for result in results] == list("ABCD")
    for result in results:
        assert result.edge_id == (1, 2, 7)
        assert result.reverse_edge_id == ((2, 1, 9) if reverse else None)
        assert result.theta == pytest.approx(0.3)
        assert result.snap_distance_m == pytest.approx(70)
        assert result.access_seconds == pytest.approx(50)
        assert result.source_node_id is None
    assert snapper.snap_origins(request) == results
    assert nx.utils.graphs_equal(before, snapper.reference.graph)
    assert len(snapper.edge_ids) == 1


@pytest.mark.parametrize("meters,accepted", [(149.999999, True), (150, True), (150.000001, False)])
def test_radius_boundary_in_metric_units(meters: float, accepted: bool) -> None:
    snapper = make_snapper()
    point = Point(500030, 2300000 + meters)
    if accepted:
        assert snapper._project(point)[3] == pytest.approx(meters)
    else:
        with pytest.raises(SnapError) as exc:
            snapper._project(point)
        assert exc.value.error_code == "SNAP_FAILED"


@pytest.mark.parametrize("x,node,theta", [(500000, 1, 0), (500100, 2, 1)])
def test_endpoint_roundtrip_reuses_node(x: float, node: int, theta: int) -> None:
    result = make_snapper().snap_origins(request_at(x, 2300000))[0]
    assert result.source_node_id == node
    assert result.theta == theta


def test_curve_uses_geometry_length() -> None:
    snapper = make_snapper(curved=True)
    line = snapper.tree.geometries[0]
    point = line.interpolate(0.3, normalized=True)
    result = snapper.snap_origins(request_at(point.x, point.y))[0]
    assert result.theta == pytest.approx(0.3)
    assert result.snap_distance_m < 1e-7


def test_parallel_geometry_and_ties_ignore_insertion_order() -> None:
    snapper = make_snapper()
    graph = snapper.reference.graph
    graph.add_edge(1, 2, key=2, **dict(graph.edges[1, 2, 7]))
    # A distinct curved parallel must remain searchable even if it is slower.
    graph.add_edge(1, 2, key=12, geometry=LineString([
        (500000, 2300000), (500050, 2300050), (500100, 2300000)]),
        oneway=True, osmid=456, travel_time=200)
    refs = []
    reordered = nx.MultiDiGraph(**graph.graph)
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    for ordered in (graph, reordered):
        refs.append(CoordinateSnapper(ReferenceGraph(
            ordered, snapper.reference.aoi, identify_reverse_edges(ordered), "test", "car"),
            Settings(_env_file=None)))
    assert all(s._project(Point(500050, 2299990))[0] == (1, 2, 2) for s in refs)
    assert all(s._project(Point(500050, 2300050))[0] == (1, 2, 12) for s in refs)


def test_coverage_precedes_any_snapping_and_does_not_echo_input(monkeypatch) -> None:
    snapper = make_snapper()
    req = request_at(500030, 2300000)
    req.origins[-1].lon = 107.123456
    monkeypatch.setattr(snapper, "_snap_origin", lambda origin: pytest.fail("Snapped too early"))
    with pytest.raises(SnapError) as exc:
        snapper.snap_origins(req)
    assert exc.value.error_code == "OUT_OF_COVERAGE"
    assert "107.123456" not in str(exc.value)


def test_aoi_boundary_and_hole() -> None:
    snapper = make_snapper()
    origin = request_at(500030, 2300000).origins[0]
    lon, lat = origin.lon, origin.lat
    polygon = Polygon([(lon, lat), (lon + .01, lat), (lon + .01, lat + .01),
                       (lon, lat + .01)], holes=[[(lon + .002, lat + .002),
                       (lon + .004, lat + .002), (lon + .004, lat + .004),
                       (lon + .002, lat + .004)]])
    snapper.reference = ReferenceGraph(snapper.reference.graph, polygon,
                                      snapper.reference.reverse_mapping, "test", "car")
    assert len(snapper.snap_origins(request_at(500030, 2300000))) == 4
    req = request_at(500030, 2300000)
    req.origins[0].lon, req.origins[0].lat = lon + .003, lat + .003
    with pytest.raises(SnapError, match="phạm vi"):
        snapper.snap_origins(req)


def test_reverse_geometry_mismatch_is_not_silently_moved() -> None:
    snapper = make_snapper(reverse=True)
    graph = snapper.reference.graph
    graph.edges[2, 1, 9]["geometry"] = LineString([
        (500100, 2300000), (500050, 2300000.001), (500000, 2300000)])
    with pytest.raises(ValueError, match="exactly reversed"):
        CoordinateSnapper(snapper.reference, Settings(_env_file=None))
