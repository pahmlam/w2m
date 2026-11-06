"""Offline regression tests for metric, directed edge geometry."""

import copy
import json
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, Point

from app.services.graph_geometry import normalize_graph_geometry
from scripts.download_osm import _sha256
from scripts.prepare_graph_geometry import main, prepare_graph_geometry


@pytest.fixture
def raw_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="epsg:4326", simplified=False)
    graph.add_node(1, x=105.85, y=21.03)
    graph.add_node(2, x=105.851, y=21.031)
    graph.add_edge(1, 2, key=7, length=999, oneway=True, highway="primary")
    return graph


def test_projection_preserves_topology_and_input(raw_graph: nx.MultiDiGraph) -> None:
    original = copy.deepcopy(raw_graph)
    graph = normalize_graph_geometry(raw_graph)
    assert nx.utils.graphs_equal(raw_graph, original)
    assert set(graph.edges) == {(1, 2, 7)}
    assert graph.graph["crs"] == "EPSG:32648"
    assert graph.nodes[1]["lon"] == 105.85
    assert graph.nodes[1]["lat"] == 21.03
    projector = Transformer.from_crs(4326, 32648, always_xy=True)
    expected = LineString([
        projector.transform(105.85, 21.03), projector.transform(105.851, 21.031),
    ])
    edge = graph.edges[1, 2, 7]
    assert edge["geometry"].equals_exact(expected, 1e-8)
    assert edge["length_m"] == pytest.approx(expected.length)
    assert edge["length"] == edge["length_m"]
    assert 140 < edge["length_m"] < 160
    assert edge["oneway"] is True
    assert edge["highway"] == "primary"


def test_reversed_curves_parallel_edges_and_reverse_direction(
    raw_graph: nx.MultiDiGraph,
) -> None:
    curve = [(105.85, 21.03), (105.852, 21.03), (105.851, 21.031)]
    raw_graph.edges[1, 2, 7]["geometry"] = LineString(curve[::-1])
    raw_graph.add_edge(1, 2, key=9, geometry=LineString([curve[0], curve[-1]]))
    raw_graph.add_edge(2, 1, key=3, geometry=LineString(curve))
    graph = normalize_graph_geometry(raw_graph)
    assert set(graph.edges) == set(raw_graph.edges)
    for source, target, key, data in graph.edges(keys=True, data=True):
        coordinates = list(data["geometry"].coords)
        assert coordinates[0] == (graph.nodes[source]["x"], graph.nodes[source]["y"])
        assert coordinates[-1] == (graph.nodes[target]["x"], graph.nodes[target]["y"])
    assert graph.edges[1, 2, 7]["length_m"] > graph.edges[1, 2, 9]["length_m"]
    assert graph.edges[1, 2, 7]["length_m"] == graph.edges[2, 1, 3]["length_m"]


@pytest.mark.parametrize("geometry", [
    None,
    LineString(),
    Point(105.85, 21.03),
    LineString([(105.85, 21.03), (float("inf"), 21.031)]),
    LineString([(105.85, 21.03), (181, 21.031)]),
    LineString([(105.85, 21.03, 0), (105.851, 21.031, 0)]),
    LineString([(105.84, 21.03), (105.851, 21.031)]),
])
def test_reject_invalid_edge_geometry(raw_graph: nx.MultiDiGraph, geometry: object) -> None:
    raw_graph.edges[1, 2, 7]["geometry"] = geometry
    with pytest.raises(ValueError, match="edge"):
        normalize_graph_geometry(raw_graph)


@pytest.mark.parametrize("value", [None, True, "105.85", float("nan"), float("inf"), 181])
def test_reject_invalid_node(raw_graph: nx.MultiDiGraph, value: object) -> None:
    raw_graph.nodes[1]["x"] = value
    with pytest.raises(ValueError, match="node 1"):
        normalize_graph_geometry(raw_graph)


def test_reject_zero_length(raw_graph: nx.MultiDiGraph) -> None:
    raw_graph.nodes[2].update(raw_graph.nodes[1])
    with pytest.raises(ValueError, match="edge"):
        normalize_graph_geometry(raw_graph)


@pytest.mark.parametrize("graph", [
    nx.Graph(), nx.DiGraph(), nx.MultiGraph(), nx.MultiDiGraph(crs="EPSG:32648"),
    nx.MultiDiGraph(crs="EPSG:4326"),
])
def test_reject_unsupported_graph(graph: nx.Graph) -> None:
    with pytest.raises(ValueError):
        normalize_graph_geometry(graph)


def test_offline_cli_roundtrip(raw_graph: nx.MultiDiGraph, tmp_path: Path) -> None:
    ox = pytest.importorskip("osmnx")
    snapshot = tmp_path / "raw"
    snapshot.mkdir()
    raw_graph.edges[1, 2, 7]["osmid"] = 123
    ox.save_graphml(raw_graph, filepath=snapshot / "graph.graphml")
    checksum = _sha256(snapshot / "graph.graphml")
    manifest = {
        "graph_sha256": checksum, "snapshot_id": "fixture",
        "source": "OpenStreetMap", "source_date": "2026-11-06",
        "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0",
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    output = tmp_path / "projected"
    assert main(["--snapshot-dir", str(snapshot), "--output-dir", str(output)]) == 0
    metadata = json.loads((output / "metadata.json").read_text())
    assert metadata["stage"] == "geometry-only"
    assert metadata["node_count"] == 2
    assert metadata["edge_count"] == 1
    assert metadata["graph_sha256"] == _sha256(output / "graph.graphml")
    assert _sha256(snapshot / "graph.graphml") == checksum
    restored = ox.load_graphml(filepath=output / "graph.graphml", edge_dtypes={"length_m": float})
    assert restored.edges[1, 2, 7]["length_m"] > 0
    with pytest.raises(FileExistsError):
        prepare_graph_geometry(snapshot, output)
    manifest["graph_sha256"] = "incorrect"
    (snapshot / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="checksum"):
        prepare_graph_geometry(snapshot, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
