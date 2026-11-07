"""Reverse-edge identity is based on OSM data and oriented metric geometry."""

import copy
import json
from pathlib import Path

import networkx as nx
import pytest
from shapely.geometry import LineString

from app.services.graph_reverse_edges import identify_reverse_edges
from scripts.download_osm import _sha256
from scripts.prepare_reverse_edges import main, prepare_reverse_edges


@pytest.fixture
def graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:32648", travel_mode="car", weight_profile_version="car-v1")
    graph.add_node(1, x=500000.0, y=2300000.0)
    graph.add_node(2, x=500100.0, y=2300000.0)
    line = LineString([(500000, 2300000), (500050, 2300010), (500100, 2300000)])
    graph.add_edge(1, 2, key=7, osmid=123, oneway=False, geometry=line, travel_time_seconds=20.0)
    graph.add_edge(2, 1, key=9, osmid=123, oneway=False,
                   geometry=LineString(list(line.coords)[::-1]), travel_time_seconds=40.0)
    return graph


def test_pair_preserves_directional_weights_and_input(graph: nx.MultiDiGraph) -> None:
    before = copy.deepcopy(graph)
    report = identify_reverse_edges(graph)
    assert report == {"pairs": [{"forward": [1, 2, 7], "reverse": [2, 1, 9]}], "unpaired": []}
    assert nx.utils.graphs_equal(before, graph)
    reordered = nx.MultiDiGraph(**graph.graph)
    reordered.add_nodes_from(reversed(list(graph.nodes(data=True))))
    reordered.add_edges_from(reversed(list(graph.edges(keys=True, data=True))))
    assert identify_reverse_edges(reordered) == report


@pytest.mark.parametrize("field,value", [
    ("osmid", 999), ("osmid", None), ("osmid", True), ("oneway", True), ("oneway", None),
    ("layer", "1"), ("bridge", "yes"), ("tunnel", "yes"), ("level", "1"),
])
def test_opposite_endpoints_are_insufficient(
    graph: nx.MultiDiGraph, field: str, value: object,
) -> None:
    graph.edges[2, 1, 9][field] = value
    report = identify_reverse_edges(graph)
    assert not report["pairs"]
    assert len(report["unpaired"]) == 2


def test_different_geometry_and_parallel_keys(graph: nx.MultiDiGraph) -> None:
    different = LineString([(500100, 2300000), (500050, 2300020), (500000, 2300000)])
    graph.add_edge(2, 1, key=0, osmid=123, oneway=False, geometry=different)
    report = identify_reverse_edges(graph)
    assert report["pairs"] == [{"forward": [1, 2, 7], "reverse": [2, 1, 9]}]
    assert report["unpaired"] == [{"edge": [2, 1, 0], "reason": "no_compatible_reverse",
                                    "candidates": []}]
    graph.remove_edge(2, 1, 9)
    assert not identify_reverse_edges(graph)["pairs"]


def test_ambiguous_parallel_edges_are_not_arbitrarily_paired(graph: nx.MultiDiGraph) -> None:
    graph.add_edge(2, 1, key=10, **graph.edges[2, 1, 9])
    report = identify_reverse_edges(graph)
    assert not report["pairs"]
    assert len(report["unpaired"]) == 3
    assert {item["reason"] for item in report["unpaired"]} == {"ambiguous"}
    assert report["unpaired"][0]["candidates"] == [[2, 1, 9], [2, 1, 10]]


def test_two_distinct_parallel_physical_roads(graph: nx.MultiDiGraph) -> None:
    for source, target, key in [(1, 2, 11), (2, 1, 12)]:
        base = graph.edges[1, 2, 7] if source == 1 else graph.edges[2, 1, 9]
        graph.add_edge(source, target, key=key, **{**base, "osmid": 456})
    assert len(identify_reverse_edges(graph)["pairs"]) == 2


def test_id_lists_and_equivalent_structure_defaults(graph: nx.MultiDiGraph) -> None:
    graph.edges[1, 2, 7].update(osmid=[123, 456, 123])
    graph.edges[2, 1, 9].update(osmid=[456, 123], bridge="no", tunnel=False, layer=0)
    assert len(identify_reverse_edges(graph)["pairs"]) == 1


@pytest.mark.parametrize("offset,expected", [(0.005, 1), (0.02, 0)])
def test_metric_geometry_tolerance(graph: nx.MultiDiGraph, offset: float, expected: int) -> None:
    graph.edges[2, 1, 9]["geometry"] = LineString([
        (500100, 2300000), (500050, 2300010 + offset), (500000, 2300000),
    ])
    assert len(identify_reverse_edges(graph)["pairs"]) == expected


def test_oneway_and_self_loop_are_reported(graph: nx.MultiDiGraph) -> None:
    graph.remove_edge(2, 1, 9)
    graph.edges[1, 2, 7]["oneway"] = True
    graph.add_edge(1, 1, key=0, osmid=987, oneway=False,
                   geometry=LineString([(500000, 2300000), (500001, 2300001), (500000, 2300000)]))
    report = identify_reverse_edges(graph)
    assert not report["pairs"]
    assert {item["reason"] for item in report["unpaired"]} == {"oneway", "self_loop"}


@pytest.mark.parametrize("invalid", [nx.MultiDiGraph(), nx.DiGraph([(1, 2)]), nx.Graph()])
def test_invalid_graph_rejected(invalid: nx.Graph) -> None:
    with pytest.raises(ValueError):
        identify_reverse_edges(invalid)


@pytest.mark.parametrize("problem", ["crs", "geometry", "orientation", "node_position"])
def test_invalid_metric_geometry_rejected(graph: nx.MultiDiGraph, problem: str) -> None:
    if problem == "crs":
        graph.graph["crs"] = "EPSG:4326"
    elif problem == "geometry":
        graph.edges[1, 2, 7]["geometry"] = None
    elif problem == "orientation":
        graph.edges[1, 2, 7]["geometry"] = graph.edges[2, 1, 9]["geometry"]
    else:
        graph.nodes[1]["x"] = float("nan")
    with pytest.raises(ValueError):
        identify_reverse_edges(graph)


@pytest.fixture
def artifact(graph: nx.MultiDiGraph, tmp_path: Path) -> Path:
    ox = pytest.importorskip("osmnx")
    source = tmp_path / "scc"
    source.mkdir()
    ox.save_graphml(graph, filepath=source / "graph.graphml")
    (source / "metadata.json").write_text(json.dumps({
        "stage": "scc", "graph_sha256": _sha256(source / "graph.graphml"),
        "node_count": 2, "edge_count": 2, "weight_profile_version": "car-v1",
        "source_snapshot_id": "fixture", "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
    }))
    return source


def test_cli_roundtrip_and_source_unchanged(artifact: Path, tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in artifact.iterdir()}
    output = tmp_path / "reverse"
    assert main(["--scc-dir", str(artifact), "--output-dir", str(output)]) == 0
    report = json.loads((output / "metadata.json").read_text())
    mapping = json.loads((output / "reverse_edges.json").read_text())
    assert report["pair_count"] == 1
    assert report["paired_edge_count"] == 2
    assert report["unpaired_edge_count"] == 0
    assert report["unpaired_reasons"] == {}
    assert report["mapping_sha256"] == _sha256(output / "reverse_edges.json")
    assert report["source_graph_sha256"] == _sha256(artifact / "graph.graphml")
    assert report["source_metadata_sha256"] == _sha256(artifact / "metadata.json")
    assert mapping["pairs"] == [{"forward": [1, 2, 7], "reverse": [2, 1, 9]}]
    assert {p.name: p.read_bytes() for p in artifact.iterdir()} == before
    with pytest.raises(FileExistsError):
        prepare_reverse_edges(artifact, output)


@pytest.mark.parametrize("field,value", [
    ("stage", "weighted"), ("graph_sha256", "bad"), ("node_count", 99),
    ("weight_profile_version", "car-v2"),
])
def test_bad_metadata_is_not_published(
    artifact: Path, tmp_path: Path, field: str, value: object,
) -> None:
    metadata_path = artifact / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata[field] = value
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        prepare_reverse_edges(artifact, tmp_path / "reverse")
    assert not (tmp_path / "reverse").exists()


def test_failed_mapping_reload_is_not_published(
    artifact: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_text = Path.read_text

    def corrupt_read(path: Path, *args: object, **kwargs: object) -> str:
        if path.name == "reverse_edges.json":
            return "{}"
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", corrupt_read)
    with pytest.raises(ValueError, match="reload"):
        prepare_reverse_edges(artifact, tmp_path / "reverse")
    assert not (tmp_path / "reverse").exists()
    assert not list(tmp_path.glob(".reverse-edges-*"))
