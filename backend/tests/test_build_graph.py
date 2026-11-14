"""The full preparation pipeline runs on a fixed graph without downloading OSM."""

import json
from pathlib import Path

import networkx as nx
import pytest
from pyproj import Transformer
from shapely import transform
from shapely.geometry import box, mapping

from scripts.build_graph import build_graph
from scripts.download_osm import _sha256
from scripts.prepare_aoi import main as prepare_aoi

PROFILE = Path(__file__).parents[1] / "app/config/speed_profiles/car-v1.yaml"


@pytest.fixture
def raw_inputs(tmp_path: Path) -> tuple[Path, Path]:
    ox = pytest.importorskip("osmnx")
    projector = Transformer.from_crs(32648, 4326, always_xy=True)
    polygon = transform(box(499900, 2299900, 500200, 2300200),
                        projector.transform, interleaved=False)
    source = tmp_path / "fixture.geojson"
    source.write_text(json.dumps(mapping(polygon)))
    area = tmp_path / "area"
    prepare_aoi(["--source", str(source), "--aoi-output", str(area / "aoi.geojson"),
                 "--routing-output", str(area / "routing_area.geojson"),
                 "--metadata-output", str(area / "aoi.metadata.json"), "--buffer-m", "3000"])
    snapshot = tmp_path / "raw"
    snapshot.mkdir()
    graph = nx.MultiDiGraph(crs="EPSG:4326", simplified=False)
    for node in range(1, 17):
        lon, lat = projector.transform(500000 + node * 5, 2300000)
        graph.add_node(node, x=lon, y=lat)
    for node in graph:
        graph.add_edge(node, node % 16 + 1, key=0, osmid=node,
                       highway="residential", oneway=True, length=5.0)
    ox.save_graphml(graph, filepath=snapshot / "graph.graphml")
    (snapshot / "routing_area.geojson").write_bytes((area / "routing_area.geojson").read_bytes())
    (snapshot / "manifest.json").write_text(json.dumps({
        "snapshot_id": "fixture", "snapshot_at": "2026-11-06T09:28:34Z",
        "source": "OpenStreetMap", "source_date": "2026-11-06",
        "attribution": "© OpenStreetMap contributors", "license": "ODbL-1.0",
        "graph_sha256": _sha256(snapshot / "graph.graphml"),
        "routing_area_sha256": _sha256(snapshot / "routing_area.geojson"),
        "graph_options": {"network_type": "drive", "simplify": False,
                          "retain_all": True, "truncate_by_edge": False},
    }))
    return snapshot, area


@pytest.fixture
def built_graph(raw_inputs: tuple[Path, Path], tmp_path: Path, monkeypatch) -> Path:
    ox = pytest.importorskip("osmnx")
    monkeypatch.setattr(ox, "graph_from_polygon", lambda *a, **k: pytest.fail("Network called"))
    snapshot, area = raw_inputs
    root = tmp_path / "build"
    build_graph(snapshot, area, PROFILE, root, "fixture-v1")
    return root


def test_offline_pipeline_preserves_source_and_directed_routes(
    built_graph: Path, raw_inputs: tuple[Path, Path], tmp_path: Path,
) -> None:
    snapshot, area = raw_inputs
    manifest = json.loads((built_graph / "snapshot/manifest.json").read_bytes())
    assert manifest["parent_graph_sha256"] == _sha256(snapshot / "graph.graphml")
    report = json.loads((built_graph / "validated/validation.json").read_bytes())
    assert report["status"] == "passed"
    assert report["node_count"] == 16
    assert report["edge_count"] == 16
    assert report["routes"]["max_distance_error_seconds"] == 0
    assert all(b == a % 16 + 1 for route in report["routes"]["routes"]
               for a, b, key in route["edge_ids"])
    with pytest.raises(FileExistsError):
        build_graph(snapshot, area, PROFILE, built_graph, "another-version")


@pytest.mark.parametrize("filename", ["graph.graphml", "routing_area.geojson"])
def test_pipeline_rejects_corrupt_snapshot(
    raw_inputs: tuple[Path, Path], tmp_path: Path, filename: str,
) -> None:
    snapshot, area = raw_inputs
    (snapshot / filename).write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        build_graph(snapshot, area, PROFILE, tmp_path / "build", "fixture-v1")
    assert not (tmp_path / "build").exists()


def test_pipeline_requires_complete_routing_coverage(
    raw_inputs: tuple[Path, Path], tmp_path: Path,
) -> None:
    snapshot, area = raw_inputs
    (area / "routing_area.geojson").write_text(json.dumps(mapping(box(104, 20, 106, 22))))
    with pytest.raises(ValueError, match="Routing polygon"):
        build_graph(snapshot, area, PROFILE, tmp_path / "build", "fixture-v1")


def test_pipeline_rejects_small_source_coverage(
    raw_inputs: tuple[Path, Path], tmp_path: Path,
) -> None:
    snapshot, area = raw_inputs
    (snapshot / "routing_area.geojson").write_bytes((area / "aoi.geojson").read_bytes())
    path = snapshot / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["routing_area_sha256"] = _sha256(snapshot / "routing_area.geojson")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="cover the entire"):
        build_graph(snapshot, area, PROFILE, tmp_path / "build", "fixture-v1")
