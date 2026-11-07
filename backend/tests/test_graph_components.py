"""Offline SCC regressions, including discarded roads crossing the AOI."""

import copy
import json
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import transform

from app.services.graph_components import keep_largest_scc, removed_features_in_aoi
from scripts.download_osm import _sha256
from scripts.prepare_graph_scc import main, prepare_graph_scc

PROFILE_PATH = Path("backend/app/config/speed_profiles/car-v1.yaml")
TO_WGS84 = Transformer.from_crs("EPSG:32648", "EPSG:4326", always_xy=True)


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    result = nx.MultiDiGraph(crs="EPSG:32648", weight_profile_version="car-v1", travel_mode="car")
    for node, x, y in [(1, 500000, 2300000), (2, 500010, 2300000), (3, 500020, 2300000),
                       (4, 500005, 2300005), (5, 499990, 2300005), (6, 500030, 2300005)]:
        lon, lat = TO_WGS84.transform(x, y)
        result.add_node(node, x=x, y=y, lon=lon, lat=lat)
    for source, target, key in [(1, 2, 0), (1, 2, 1), (2, 3, 0), (3, 1, 0),
                                (3, 4, 0), (5, 6, 0)]:
        geometry = LineString([
            (result.nodes[node]["x"], result.nodes[node]["y"]) for node in (source, target)
        ])
        result.add_edge(source, target, key=key, geometry=geometry, length_m=geometry.length,
                        length=geometry.length, estimated_speed_kmh=18,
                        travel_time_seconds=geometry.length / 5, travel_time=geometry.length / 5)
    return result


def test_largest_scc_preserves_attributes_and_input(graph: nx.MultiDiGraph) -> None:
    before = copy.deepcopy(graph)
    retained = keep_largest_scc(graph)
    assert set(retained) == {1, 2, 3}
    assert set(retained.edges) == {(1, 2, 0), (1, 2, 1), (2, 3, 0), (3, 1, 0)}
    assert nx.is_strongly_connected(retained)
    for edge in retained.edges:
        assert retained.edges[edge] == graph.edges[edge]
    retained.nodes[1]["x"] = 0
    retained.edges[1, 2, 0]["travel_time"] = 999
    assert nx.utils.graphs_equal(graph, before)


def test_tied_scc_ignores_insertion_order() -> None:
    for edges in [[(8, 9), (9, 8), (2, 3), (3, 2)], [(3, 2), (2, 3), (9, 8), (8, 9)]]:
        assert set(keep_largest_scc(nx.MultiDiGraph(edges))) == {2, 3}


@pytest.mark.parametrize("invalid", [nx.Graph(), nx.DiGraph([(1, 2)]), nx.MultiDiGraph(),
                                   nx.MultiDiGraph([("1", "2")])])
def test_invalid_graph_rejected(invalid: nx.Graph) -> None:
    with pytest.raises(ValueError):
        keep_largest_scc(invalid)


def test_already_connected_and_single_node() -> None:
    for graph in [nx.MultiDiGraph([(1, 2), (2, 1)]), nx.MultiDiGraph()]:
        if not graph:
            graph.add_node(1)
        assert nx.utils.graphs_equal(keep_largest_scc(graph), graph)


def test_removed_map_clips_crossing_edges_and_includes_boundary(graph: nx.MultiDiGraph) -> None:
    aoi = box(500000, 2300000, 500020, 2300010)
    graph.add_node(7, x=500000, y=2300010)
    report = removed_features_in_aoi(graph, keep_largest_scc(graph), aoi)
    nodes = [f["properties"]["node_id"] for f in report["features"]
             if f["properties"]["kind"] == "node"]
    assert nodes == [4, 7]
    crossing = next(f for f in report["features"] if f["properties"].get("source") == 5)
    assert shape(crossing["geometry"]).geom_type == "LineString"
    expected = transform(TO_WGS84.transform, LineString([(500000, 2300005), (500020, 2300005)]))
    assert shape(crossing["geometry"]).equals_exact(expected, 1e-10)
    assert report == removed_features_in_aoi(graph, keep_largest_scc(graph), aoi)
    assert removed_features_in_aoi(graph, graph.copy(), aoi)["features"] == []
    graph.graph["crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="EPSG:32648"):
        removed_features_in_aoi(graph, graph, aoi)


@pytest.fixture
def artifact(graph: nx.MultiDiGraph, tmp_path: Path) -> tuple[Path, Path]:
    ox = pytest.importorskip("osmnx")
    weighted = tmp_path / "weighted"
    weighted.mkdir()
    ox.save_graphml(graph, filepath=weighted / "graph.graphml")
    (weighted / "speed_profile.yaml").write_bytes(PROFILE_PATH.read_bytes())
    (weighted / "metadata.json").write_text(json.dumps({
        "stage": "weighted", "source_snapshot_id": "fixture", "source": "OpenStreetMap",
        "source_date": "2026-11-06", "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0", "weight_profile_version": "car-v1",
        "graph_sha256": _sha256(weighted / "graph.graphml"),
        "weight_profile_sha256": _sha256(weighted / "speed_profile.yaml"),
        "node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges(),
    }))
    aoi_path = tmp_path / "aoi.geojson"
    aoi_path.write_text(json.dumps(mapping(transform(
        TO_WGS84.transform, box(499995, 2299995, 500025, 2300015),
    ))))
    return weighted, aoi_path


def test_cli_roundtrip_and_provenance(artifact: tuple[Path, Path], tmp_path: Path) -> None:
    weighted, aoi = artifact
    before = {p.name: p.read_bytes() for p in weighted.iterdir()}
    output = tmp_path / "scc"
    assert main(["--weighted-dir", str(weighted), "--aoi", str(aoi),
                 "--output-dir", str(output)]) == 0
    report = json.loads((output / "metadata.json").read_text())
    assert report["stage"] == "scc"
    assert (report["node_count"], report["edge_count"]) == (3, 4)
    assert (report["scc_removed_nodes"], report["scc_removed_edges"]) == (3, 2)
    assert report["scc_count"] == 4
    assert report["removed_nodes_in_aoi"] == 1
    assert report["removed_edges_in_aoi"] == 2
    for filename, field in [("graph.graphml", "graph_sha256"),
                            ("speed_profile.yaml", "weight_profile_sha256"),
                            ("aoi.geojson", "aoi_sha256"),
                            ("removed_in_aoi.geojson", "removed_in_aoi_sha256")]:
        assert _sha256(output / filename) == report[field]
    ox = pytest.importorskip("osmnx")
    restored = ox.load_graphml(filepath=output / "graph.graphml")
    assert nx.is_strongly_connected(restored)
    assert restored.edges[1, 2, 1]["travel_time"] == 2
    assert {p.name: p.read_bytes() for p in weighted.iterdir()} == before
    assert Point(restored.nodes[1]["lon"], restored.nodes[1]["lat"]).is_valid
    with pytest.raises(FileExistsError):
        prepare_graph_scc(weighted, aoi, output)


@pytest.mark.parametrize("field,value", [
    ("stage", "geometry-only"), ("graph_sha256", "bad"), ("weight_profile_sha256", "bad"),
    ("weight_profile_version", "car-v2"), ("node_count", 999),
])
def test_reject_bad_metadata(
    artifact: tuple[Path, Path], tmp_path: Path, field: str, value: object,
) -> None:
    weighted, aoi = artifact
    path = weighted / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata[field] = value
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        prepare_graph_scc(weighted, aoi, tmp_path / "scc")
    assert not (tmp_path / "scc").exists()


def test_failed_export_is_not_published(artifact: tuple[Path, Path], tmp_path: Path) -> None:
    weighted, aoi = artifact
    aoi.write_text('{"type":"Point","coordinates":[105,21]}')
    with pytest.raises(ValueError, match="Polygon"):
        prepare_graph_scc(weighted, aoi, tmp_path / "scc")
    assert not (tmp_path / "scc").exists()
    assert not list(tmp_path.glob(".graph-scc-*"))


@pytest.mark.parametrize("problem", ["invalid_weight", "edgeless_scc", "reload_failure"])
def test_bad_graph_is_not_published(
    artifact: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str,
) -> None:
    weighted, aoi = artifact
    ox = pytest.importorskip("osmnx")
    graph_path = weighted / "graph.graphml"
    graph = ox.load_graphml(filepath=graph_path)
    if problem == "invalid_weight":
        graph.edges[1, 2, 0]["travel_time_seconds"] = -1
    elif problem == "edgeless_scc":
        graph.remove_edges_from([(3, 1, 0), (1, 2, 1)])
    if problem != "reload_failure":
        ox.save_graphml(graph, filepath=graph_path)
        metadata_path = weighted / "metadata.json"
        metadata = json.loads(metadata_path.read_text())
        metadata.update(graph_sha256=_sha256(graph_path), edge_count=graph.number_of_edges())
        metadata_path.write_text(json.dumps(metadata))
    else:
        save = ox.save_graphml

        def corrupt_save(graph: nx.MultiDiGraph, *, filepath: Path) -> None:
            corrupted = graph.copy()
            corrupted.nodes[1]["x"] += 1
            save(corrupted, filepath=filepath)

        monkeypatch.setattr(ox, "save_graphml", corrupt_save)
    with pytest.raises(ValueError):
        prepare_graph_scc(weighted, aoi, tmp_path / "scc")
    assert not (tmp_path / "scc").exists()
    assert not list(tmp_path.glob(".graph-scc-*"))
