"""CSR must retain directed distances and identify the exact chosen parallel edge."""

import copy
import json
from pathlib import Path

import networkx as nx
import numpy as np
import pytest
from pyproj import Transformer
from scipy.sparse import load_npz
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString
from shapely.strtree import STRtree

from app.services.graph_csr import build_graph_csr
from scripts.download_osm import _sha256
from scripts.prepare_graph_csr import main, prepare_graph_csr


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    result = nx.MultiDiGraph(crs="EPSG:32648", travel_mode="car", weight_profile_version="car-v1")
    projector = Transformer.from_crs(32648, 4326, always_xy=True)
    for node, x in ((-4, 500000), (10, 500010), (20, 500020)):
        lon, lat = projector.transform(x, 2300000)
        result.add_node(node, x=x, y=2300000, lon=lon, lat=lat,
                        aoi_relation="inside", in_aoi=True, is_candidate=node != 20)
    for source, target, key, seconds in (
        (-4, 10, 0, 2), (10, 20, 0, 7), (10, 20, 5, 3),
        (10, 20, 2, 3), (20, 10, 0, 9), (20, -4, 0, 6),
    ):
        start = (result.nodes[source]["x"], 2300000)
        end = (result.nodes[target]["x"], 2300000)
        line = LineString([start, ((start[0] + end[0]) / 2, 2300000 + key), end])
        result.add_edge(source, target, key=key, travel_time=float(seconds),
                        travel_time_seconds=float(seconds), geometry=line, oneway=True)
    return result


def test_parallel_choice_geometry_and_no_mutation(graph: nx.MultiDiGraph) -> None:
    before = copy.deepcopy(graph)
    csr, mapping, geometry = build_graph_csr(graph)
    assert nx.utils.graphs_equal(graph, before)
    assert mapping["node_ids"].tolist() == [-4, 10, 20]
    assert csr.dtype == np.float64
    assert csr[1, 2] == 3
    assert csr[2, 1] == 9
    assert csr.nnz == 4
    assert mapping["is_candidate"].tolist() == [True, True, False]
    arc = csr.indptr[1]
    edge = mapping["arc_edge_indices"][arc]
    assert mapping["edge_ids"][edge].tolist() == [10, 20, 2]
    assert len(mapping["edge_ids"]) == 6
    for index, edge_id in enumerate(mapping["edge_ids"]):
        start, end = geometry["offsets"][index:index + 2]
        assert np.array_equal(geometry["coordinates"][start:end],
                              graph.edges[tuple(edge_id)]["geometry"].coords)
    lines = [LineString(geometry["coordinates"][start:end])
             for start, end in zip(geometry["offsets"], geometry["offsets"][1:])]
    assert len(STRtree(lines).geometries) == len(graph.edges)


def test_directed_distances_predecessors_and_isolated_node(graph: nx.MultiDiGraph) -> None:
    graph.add_node(30, **dict(graph.nodes[20]))
    csr, mapping, _ = build_graph_csr(graph)
    distances, predecessors = dijkstra(csr, directed=True, indices=0, return_predecessors=True)
    assert distances[:3].tolist() == [0, 2, 5]
    assert np.isinf(distances[3])
    assert not csr[1, 0]
    target = 2
    route = []
    while target != 0:
        source = predecessors[target]
        offset = csr.indptr[source] + np.searchsorted(
            csr.indices[csr.indptr[source]:csr.indptr[source + 1]], target,
        )
        route.append(tuple(mapping["edge_ids"][mapping["arc_edge_indices"][offset]]))
        target = source
    assert route[::-1] == [(-4, 10, 0), (10, 20, 2)]


def test_csr_is_deterministic(graph: nx.MultiDiGraph) -> None:
    reordered = nx.MultiDiGraph(**graph.graph)
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    left, left_mapping, left_geometry = build_graph_csr(graph)
    right, right_mapping, right_geometry = build_graph_csr(reordered)
    for field in ("data", "indices", "indptr"):
        assert np.array_equal(getattr(left, field), getattr(right, field))
    for lhs, rhs in ((left_mapping, right_mapping), (left_geometry, right_geometry)):
        assert all(np.array_equal(lhs[name], rhs[name]) for name in lhs)


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), True])
def test_invalid_weight_rejected(graph: nx.MultiDiGraph, seconds: float) -> None:
    graph.edges[10, 20, 0].update(travel_time=seconds, travel_time_seconds=seconds)
    with pytest.raises(ValueError, match="travel time"):
        build_graph_csr(graph)


def test_reversed_geometry_rejected(graph: nx.MultiDiGraph) -> None:
    edge = graph.edges[10, 20, 0]
    edge["geometry"] = LineString(list(edge["geometry"].coords)[::-1])
    with pytest.raises(ValueError, match="oriented"):
        build_graph_csr(graph)


def test_string_flags_rejected(graph: nx.MultiDiGraph) -> None:
    graph.nodes[20]["is_candidate"] = "False"
    with pytest.raises(ValueError, match="boolean"):
        build_graph_csr(graph)


def test_mixed_id_types_rejected(graph: nx.MultiDiGraph) -> None:
    graph.add_edge("bad", 10, travel_time=1)
    with pytest.raises(ValueError, match="integers"):
        build_graph_csr(graph)


@pytest.fixture
def candidate_artifact(graph: nx.MultiDiGraph, tmp_path: Path) -> Path:
    ox = pytest.importorskip("osmnx")
    folder = tmp_path / "candidates"
    folder.mkdir()
    ox.save_graphml(graph, filepath=folder / "graph.graphml")
    for filename, payload in {
        "aoi.geojson": {}, "edge_splits.json": [], "reverse_edges.json": {},
        "excluded_node_ids.json": [20],
    }.items():
        (folder / filename).write_text(json.dumps(payload))
    (folder / "speed_profile.yaml").write_text("weight_profile_version: car-v1\n")
    report = {
        "stage": "candidates", "node_count": 3, "edge_count": 6,
        "weight_profile_version": "car-v1", "candidate_node_count": 2, "crs": "EPSG:32648",
    }
    for filename, field in {
        "graph.graphml": "graph_sha256", "aoi.geojson": "aoi_sha256",
        "edge_splits.json": "edge_splits_sha256", "reverse_edges.json": "reverse_edges_sha256",
        "excluded_node_ids.json": "excluded_node_ids_sha256",
        "speed_profile.yaml": "weight_profile_sha256",
    }.items():
        report[field] = _sha256(folder / filename)
    (folder / "metadata.json").write_text(json.dumps(report))
    return folder


def test_cli_roundtrip_and_provenance(candidate_artifact: Path, tmp_path: Path) -> None:
    ox = pytest.importorskip("osmnx")
    before = {path: path.read_bytes() for path in candidate_artifact.iterdir()}
    output = tmp_path / "csr"
    assert main(["--candidates-dir", str(candidate_artifact), "--output-dir", str(output),
                 "--graph-version", "test-v1"]) == 0
    report = json.loads((output / "metadata.json").read_text())
    assert report["graph_version"] == "test-v1"
    assert report["csr_arc_count"] == 4
    assert report["collapsed_parallel_edge_count"] == 2
    assert report["validation_source_count"] == 3
    assert report["validation_max_distance_error_seconds"] == 0
    assert report["source_candidates_graph_sha256"] == _sha256(candidate_artifact / "graph.graphml")
    assert ox.load_graphml(output / "graph.graphml").graph["graph_version"] == "test-v1"
    csr = load_npz(output / "csr.npz")
    assert csr[1, 2] == 3
    with np.load(output / "mappings.npz", allow_pickle=False) as mappings:
        assert mappings["node_ids"].tolist() == [-4, 10, 20]
        assert mappings["is_candidate"].tolist() == [True, True, False]
    for name in ("csr", "mappings", "geometry"):
        assert _sha256(output / f"{name}.npz") == report[f"{name}_sha256"]
    for path, content in before.items():
        assert path.read_bytes() == content
        if path.name not in ("graph.graphml", "metadata.json"):
            assert (output / path.name).read_bytes() == content
    with pytest.raises(FileExistsError):
        prepare_graph_csr(candidate_artifact, output, "test-v1")


def test_corruption_not_published(candidate_artifact: Path, tmp_path: Path) -> None:
    (candidate_artifact / "reverse_edges.json").write_text("bad")
    output = tmp_path / "csr"
    with pytest.raises(ValueError, match="checksum"):
        prepare_graph_csr(candidate_artifact, output, "test-v1")
    assert not output.exists()


def test_failed_distance_validation_not_published(
    candidate_artifact: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("scripts.prepare_graph_csr.dijkstra", lambda *a, **k: np.zeros(3))
    output = tmp_path / "csr"
    with pytest.raises(ValueError, match="distances differ"):
        prepare_graph_csr(candidate_artifact, output, "test-v1")
    assert not output.exists()


def test_invalid_version_not_published(candidate_artifact: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="graph_version"):
        prepare_graph_csr(candidate_artifact, tmp_path / "csr", " ")
