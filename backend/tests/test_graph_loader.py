"""Reference loading verifies M1 provenance and never changes source artifacts."""

import json
from pathlib import Path

import networkx as nx
import pytest
from test_build_graph import built_graph as built_graph
from test_build_graph import raw_inputs as raw_inputs

from app.services.graph_loader import load_reference_graph
from scripts.download_osm import _sha256


def test_reference_loads_and_freezes_structure(built_graph: Path) -> None:
    directory = built_graph / "validated"
    before = {p.name: _sha256(p) for p in directory.iterdir()}
    result = load_reference_graph(directory)
    assert result.graph_version == "fixture-v1"
    assert len(result.graph) == 16
    assert nx.is_frozen(result.graph)
    assert before == {p.name: _sha256(p) for p in directory.iterdir()}


@pytest.mark.parametrize("filename", ["graph.graphml", "aoi.geojson", "reverse_edges.json",
                                     "validation.json"])
def test_corruption_rejected(built_graph: Path, filename: str) -> None:
    directory = built_graph / "validated"
    (directory / filename).write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        load_reference_graph(directory)


def test_forged_mapping_checksum_still_checks_identity(built_graph: Path) -> None:
    directory = built_graph / "validated"
    path = directory / "reverse_edges.json"
    path.write_text(json.dumps({"pairs": [], "unpaired": []}))
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["reverse_edges_sha256"] = _sha256(path)
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Reverse mapping"):
        load_reference_graph(directory)


@pytest.mark.parametrize("change", ["crs", "weight", "disconnected"])
def test_graph_semantics_checked_after_checksum(built_graph: Path, change: str) -> None:
    import osmnx as ox

    directory = built_graph / "validated"
    path = directory / "graph.graphml"
    graph = ox.load_graphml(filepath=path)
    if change == "crs":
        graph.graph["crs"] = "EPSG:4326"
    elif change == "weight":
        next(iter(graph.edges(data=True)))[2]["travel_time"] = -1
    else:
        graph.remove_edge(*next(iter(graph.edges(keys=True))))
    ox.save_graphml(graph, filepath=path)
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["graph_sha256"] = _sha256(path)
    metadata["edge_count"] = graph.number_of_edges()
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        load_reference_graph(directory)
