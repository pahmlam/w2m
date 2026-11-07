"""Subdivision must preserve directed paths, geometry, weights and shared reverse cuts."""

import copy
import json
from math import fsum
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, box, mapping
from shapely.ops import transform

from app.services.graph_reverse_edges import identify_reverse_edges
from app.services.graph_split import split_graph_edges
from scripts.download_osm import _sha256
from scripts.prepare_graph_split import main, prepare_graph_split
from scripts.prepare_reverse_edges import prepare_reverse_edges

PROFILE = Path("backend/app/config/speed_profiles/car-v1.yaml")
TO_WGS84 = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True)
AOI = box(499990, 2299990, 500160, 2300050)


def add_road(
    graph: nx.MultiDiGraph, source: int, target: int, key: int, coordinates: list,
    seconds: float, *, osmid: int = 123, oneway: bool = False,
) -> None:
    line = LineString(coordinates)
    graph.add_edge(source, target, key=key, geometry=line, length=line.length,
                   length_m=line.length, travel_time=seconds, travel_time_seconds=seconds,
                   estimated_speed_kmh=line.length / seconds * 3.6, osmid=osmid, oneway=oneway)


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:32648", travel_mode="car", weight_profile_version="car-v1")
    for node, x in [(1, 500000), (2, 500150)]:
        lon, lat = TO_WGS84.transform(x, 2300000)
        graph.add_node(node, x=float(x), y=2300000.0, lon=lon, lat=lat)
    coordinates = [(500000, 2300000), (500070, 2300030), (500150, 2300000)]
    add_road(graph, 1, 2, 7, coordinates, 125)
    add_road(graph, 2, 1, 9, coordinates[::-1], 40)
    return graph


def assert_conserved(original: nx.MultiDiGraph, result: nx.MultiDiGraph, lineage: list) -> None:
    seen = set()
    assert {tuple(item["parent"]) for item in lineage} == set(original.edges)
    for item in lineage:
        edge = tuple(item["parent"])
        children = [tuple(child) for child in item["children"]]
        assert children[0][0] == edge[0] and children[-1][1] == edge[1]
        assert all(a[1] == b[0] for a, b in zip(children, children[1:]))
        for field in ("length_m", "travel_time_seconds"):
            assert fsum(result.edges[child][field] for child in children) == pytest.approx(
                original.edges[edge][field], rel=1e-12, abs=1e-7,
            )
        for child in children:
            assert child not in seen
            seen.add(child)
            data = result.edges[child]
            assert data["length_m"] == data["length"] == data["geometry"].length
            assert data["estimated_speed_kmh"] == original.edges[edge]["estimated_speed_kmh"]
            assert data["travel_time"] == data["travel_time_seconds"]
            for node, position in ((child[0], data["geometry"].coords[0]),
                                   (child[1], data["geometry"].coords[-1])):
                assert position == (result.nodes[node]["x"], result.nodes[node]["y"])
    assert seen == set(result.edges)
    assert all(0 < data["travel_time"] <= 60 for _, _, data in result.edges(data=True))
    assert nx.is_strongly_connected(result)
    for node in original:
        actual = nx.single_source_dijkstra_path_length(result, node, weight="travel_time")
        expected = nx.single_source_dijkstra_path_length(original, node, weight="travel_time")
        for target, seconds in expected.items():
            assert actual[target] == pytest.approx(seconds, rel=1e-12, abs=1e-9)


def test_paired_curves_share_nodes_and_preserve_directional_times(graph: nx.MultiDiGraph) -> None:
    before = copy.deepcopy(graph)
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    assert_conserved(graph, result, lineage)
    assert len(result) == 4
    forward, reverse = [[tuple(child) for child in item["children"]] for item in lineage]
    assert [edge[0] for edge in forward] + [2] == ([edge[0] for edge in reverse] + [1])[::-1]
    assert len(identify_reverse_edges(result)["pairs"]) == 3
    assert nx.utils.graphs_equal(graph, before)


def test_aoi_crossings_on_short_road_and_hole(graph: nx.MultiDiGraph) -> None:
    for _, _, data in graph.edges(data=True):
        data["travel_time"] = data["travel_time_seconds"] = 30.0
    aoi = Polygon([(500020, 2299990), (500130, 2299990), (500130, 2300050),
                   (500020, 2300050)], holes=[[(500060, 2299995), (500080, 2299995),
                                             (500080, 2300040), (500060, 2300040)]])
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), aoi)
    assert_conserved(graph, result, lineage)
    assert len(result) == 6
    assert sum(data["aoi_relation"] == "boundary" for _, data in result.nodes(data=True)) == 4
    assert {data["aoi_relation"] for _, _, data in result.edges(data=True)} == {"inside", "outside"}


def test_boundary_overlap_and_tangent(graph: nx.MultiDiGraph) -> None:
    for edge in list(graph.edges):
        graph.edges[edge].update(travel_time=30.0, travel_time_seconds=30.0)
    aoi = box(500000, 2300000, 500070, 2300030)
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), aoi)
    assert_conserved(graph, result, lineage)
    assert {data["aoi_relation"] for _, _, data in result.edges(data=True)} == {"inside", "outside"}
    # A road along the polygon boundary is retained and classified as boundary.
    for source, target, key in list(graph.edges):
        coords = [(graph.nodes[n]["x"], graph.nodes[n]["y"]) for n in (source, target)]
        add_road(graph, source, target, key, coords, 30)
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), AOI.intersection(
        box(500020, 2300000, 500130, 2300050),
    ))
    assert_conserved(graph, result, lineage)
    assert any(data["aoi_relation"] == "boundary" for _, _, data in result.edges(data=True))


def test_oneway_parallels_do_not_share_new_nodes(graph: nx.MultiDiGraph) -> None:
    for _, _, data in graph.edges(data=True):
        data["oneway"] = True
        data["travel_time"] = data["travel_time_seconds"] = 125.0
    add_road(graph, 1, 2, 11, list(graph.edges[1, 2, 7]["geometry"].coords), 130,
             osmid=456, oneway=True)
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    assert_conserved(graph, result, lineage)
    generated_sets = [{tuple(child)[1] for child in item["children"][:-1]} for item in lineage]
    assert all(not a & b for i, a in enumerate(generated_sets) for b in generated_sets[i + 1:])


def test_self_loop_and_repeated_boundary_visits() -> None:
    graph = nx.MultiDiGraph(crs="EPSG:32648")
    graph.add_node(1, x=500000.0, y=2300000.0)
    add_road(graph, 1, 1, 0, [(500000, 2300000), (500100, 2300000), (500000, 2300000)],
             125, oneway=True)
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph),
                                        box(500020, 2299990, 500080, 2300010))
    assert_conserved(graph, result, lineage)
    assert sum(data["aoi_relation"] == "boundary" for _, data in result.nodes(data=True)) == 4


@pytest.mark.parametrize("seconds", [59.999, 60.0, 60.001, 120.0, 180.0])
def test_time_threshold_and_roundoff(graph: nx.MultiDiGraph, seconds: float) -> None:
    for _, _, data in graph.edges(data=True):
        data["travel_time"] = data["travel_time_seconds"] = seconds
    result, lineage = split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    assert_conserved(graph, result, lineage)
    assert (len(result) == len(graph)) == (seconds <= 60)


def test_deterministic_ids_with_existing_negative_nodes(graph: nx.MultiDiGraph) -> None:
    graph = nx.relabel_nodes(graph, {1: -9})
    reordered = nx.MultiDiGraph(**graph.graph)
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    a, a_lineage = split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    b, b_lineage = split_graph_edges(reordered, identify_reverse_edges(reordered), AOI)
    assert nx.utils.graphs_equal(a, b)
    assert a_lineage == b_lineage
    assert min(a) < -9


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf"), True])
def test_invalid_time_limit(graph: nx.MultiDiGraph, limit: float) -> None:
    with pytest.raises(ValueError):
        split_graph_edges(graph, identify_reverse_edges(graph), AOI, limit)


def test_reject_stale_ambiguous_and_approximate_pairs(graph: nx.MultiDiGraph) -> None:
    mapping = identify_reverse_edges(graph)
    with pytest.raises(ValueError, match="mapping"):
        split_graph_edges(graph, {"pairs": [], "unpaired": []}, AOI)
    graph.add_edge(2, 1, key=10, **graph.edges[2, 1, 9])
    with pytest.raises(ValueError, match="review"):
        split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    graph.remove_edge(2, 1, 10)
    coords = list(graph.edges[2, 1, 9]["geometry"].coords)
    coords[1] = (coords[1][0], coords[1][1] + 0.001)
    line = LineString(coords)
    graph.edges[2, 1, 9].update(geometry=line, length=line.length, length_m=line.length)
    with pytest.raises(ValueError, match="exactly reversed"):
        split_graph_edges(graph, mapping, AOI)


@pytest.mark.parametrize("field,value", [
    ("length_m", 0), ("travel_time_seconds", float("nan")),
    ("travel_time", -1), ("estimated_speed_kmh", True), ("length", 99),
])
def test_reject_invalid_weight_without_mutating_input(
    graph: nx.MultiDiGraph, field: str, value: object,
) -> None:
    graph.edges[1, 2, 7][field] = value
    with pytest.raises(ValueError):
        split_graph_edges(graph, identify_reverse_edges(graph), AOI)
    assert set(graph) == {1, 2} and graph.number_of_edges() == 2


def test_invalid_aoi_rejected(graph: nx.MultiDiGraph) -> None:
    with pytest.raises(ValueError, match="AOI"):
        split_graph_edges(graph, identify_reverse_edges(graph), Polygon())


@pytest.fixture
def artifacts(graph: nx.MultiDiGraph, tmp_path: Path) -> tuple[Path, Path]:
    ox = pytest.importorskip("osmnx")
    source = tmp_path / "scc"
    source.mkdir()
    ox.save_graphml(graph, filepath=source / "graph.graphml")
    (source / "speed_profile.yaml").write_bytes(PROFILE.read_bytes())
    (source / "aoi.geojson").write_text(json.dumps(mapping(transform(TO_WGS84.transform, AOI))))
    (source / "metadata.json").write_text(json.dumps({
        "stage": "scc", "graph_sha256": _sha256(source / "graph.graphml"),
        "weight_profile_sha256": _sha256(source / "speed_profile.yaml"),
        "aoi_sha256": _sha256(source / "aoi.geojson"),
        "weight_profile_version": "car-v1", "node_count": 2, "edge_count": 2,
        "source_snapshot_id": "fixture", "source": "OpenStreetMap", "source_date": "2026-11-07",
        "scc_removed_nodes": 0, "scc_removed_edges": 0,
        "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0",
    }))
    reverse = tmp_path / "reverse"
    prepare_reverse_edges(source, reverse)
    return source, reverse


def test_cli_roundtrip_and_provenance(artifacts: tuple[Path, Path], tmp_path: Path) -> None:
    source, reverse = artifacts
    before = {p: p.read_bytes() for directory in artifacts for p in directory.iterdir()}
    output = tmp_path / "split"
    assert main(["--scc-dir", str(source), "--reverse-dir", str(reverse),
                 "--output-dir", str(output)]) == 0
    report = json.loads((output / "metadata.json").read_text())
    assert report["stage"] == "split"
    assert (report["node_count"], report["edge_count"], report["split_parent_edges"]) == (4, 6, 2)
    assert report["tau_max"] < 60
    for filename, field in (("graph.graphml", "graph_sha256"),
                            ("edge_splits.json", "edge_splits_sha256"),
                            ("reverse_edges.json", "reverse_edges_sha256"),
                            ("aoi.geojson", "aoi_sha256"),
                            ("speed_profile.yaml", "weight_profile_sha256")):
        assert _sha256(output / filename) == report[field]
    assert all(path.read_bytes() == content for path, content in before.items())
    with pytest.raises(FileExistsError):
        prepare_graph_split(source, reverse, output)


@pytest.mark.parametrize("problem", ["graph", "profile", "aoi", "mapping", "source_binding"])
def test_bad_input_not_published(
    artifacts: tuple[Path, Path], tmp_path: Path, problem: str,
) -> None:
    source, reverse = artifacts
    if problem == "source_binding":
        path = reverse / "metadata.json"
        report = json.loads(path.read_text())
        report["source_metadata_sha256"] = "bad"
        path.write_text(json.dumps(report))
    else:
        path = {"graph": source / "graph.graphml", "profile": source / "speed_profile.yaml",
                "aoi": source / "aoi.geojson", "mapping": reverse / "reverse_edges.json"}[problem]
        path.write_text("corrupt")
    with pytest.raises(ValueError, match="checksum|version"):
        prepare_graph_split(source, reverse, tmp_path / "split")
    assert not (tmp_path / "split").exists()


def test_failed_graph_reload_not_published(
    artifacts: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ox = pytest.importorskip("osmnx")
    source, reverse = artifacts
    save = ox.save_graphml

    def corrupt_save(graph: nx.MultiDiGraph, *, filepath: Path) -> None:
        graph = graph.copy()
        edge = next(iter(graph.edges))
        graph.edges[edge]["parent_u"] = 999
        save(graph, filepath=filepath)

    monkeypatch.setattr(ox, "save_graphml", corrupt_save)
    with pytest.raises(ValueError, match="reload"):
        prepare_graph_split(source, reverse, tmp_path / "split")
    assert not (tmp_path / "split").exists()
    assert not list(tmp_path.glob(".graph-split-*"))
