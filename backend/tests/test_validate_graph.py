"""Validation reports must verify exported data and contain complete graph metadata."""

import json
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer
from scipy.sparse import load_npz, save_npz
from shapely import transform
from shapely.geometry import box, mapping
from test_graph_csr import candidate_artifact as candidate_artifact
from test_graph_csr import graph as graph

from app.services.graph_weights import apply_speed_profile, load_speed_profile
from scripts.download_osm import _sha256
from scripts.prepare_graph_csr import prepare_graph_csr
from scripts.validate_graph import main, validate_graph


@pytest.fixture
def bundle(candidate_artifact: Path, tmp_path: Path) -> tuple[Path, Path]:
    ox = pytest.importorskip("osmnx")
    graph = ox.load_graphml(candidate_artifact / "graph.graphml")
    for _, data in graph.nodes(data=True):
        for field in ("in_aoi", "is_candidate"):
            data[field] = data[field] == "True"
    for source, target, data in graph.edges(data=True):
        data["length_m"] = data["length"] = data["geometry"].length
        data["highway"] = "unknown" if (source, target) == (-4, 10) else "residential"
    profile = candidate_artifact / "speed_profile.yaml"
    profile_source = Path(__file__).parents[1] / "app/config/speed_profiles/car-v1.yaml"
    profile.write_bytes(profile_source.read_bytes())
    graph = apply_speed_profile(graph, load_speed_profile(profile))
    ox.save_graphml(graph, filepath=candidate_artifact / "graph.graphml")
    projector = Transformer.from_crs(32648, 4326, always_xy=True)
    aoi = transform(box(499990, 2299990, 500030, 2300020), projector.transform, interleaved=False)
    (candidate_artifact / "aoi.geojson").write_text(json.dumps(mapping(aoi)))
    metadata_path = candidate_artifact / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for filename, field in (("graph.graphml", "graph_sha256"),
                            ("speed_profile.yaml", "weight_profile_sha256"),
                            ("aoi.geojson", "aoi_sha256")):
        metadata[field] = _sha256(candidate_artifact / filename)
    metadata.update(source="OpenStreetMap", source_date="2026-11-06", max_edge_seconds=60,
                    travel_mode="car", scc_removed_nodes=2, scc_removed_edges=3)
    metadata_path.write_text(json.dumps(metadata))
    csr_dir = prepare_graph_csr(candidate_artifact, tmp_path / "csr", "fixture-v1")
    area_dir = tmp_path / "area"
    area_dir.mkdir()
    (area_dir / "aoi.geojson").write_text(json.dumps(mapping(aoi)))
    metric = transform(aoi, Transformer.from_crs(4326, 32648, always_xy=True).transform,
                       interleaved=False)
    area_metadata = area_dir / "aoi.metadata.json"
    area_metadata.write_text(json.dumps({
        "area_id": "fixture", "buffer_m": 3000, "boundary_rule": "covers",
        "geometry_crs": "EPSG:4326", "measurement_crs": "EPSG:32648", "aoi_area_m2": metric.area,
    }))
    return csr_dir, area_metadata


def test_validation_report_and_complete_metadata(bundle: tuple[Path, Path], tmp_path: Path) -> None:
    source, area = bundle
    before = {path: path.read_bytes() for path in source.iterdir()}
    output = tmp_path / "validated"
    assert main(["--csr-dir", str(source), "--aoi-metadata", str(area),
                 "--output-dir", str(output)]) == 0
    report = json.loads((output / "validation.json").read_text())
    metadata = json.loads((output / "metadata.json").read_text())
    required = {"graph_version", "source", "source_date", "build_date", "area_id", "buffer_m",
                "crs", "travel_mode", "node_count", "edge_count", "scc_removed_nodes",
                "max_edge_seconds", "tau_p50", "tau_p99", "tau_max", "weight_profile_version"}
    assert required <= metadata.keys()
    assert metadata["area_id"] == "fixture"
    assert metadata["buffer_m"] == 3000
    assert report["status"] == "passed"
    assert report["implementation_sha256"]["scripts/validate_graph.py"] == _sha256(
        Path(__file__).parents[1] / "scripts/validate_graph.py",
    )
    assert report["environment"]["libraries"]["networkx"]
    assert report["default_speed_edge_count"] == 1
    assert report["scc_count"] == 1
    assert report["routes"]["route_count"] == 9
    assert report["routes"]["distance_comparison_count"] == 9
    assert report["routes"]["max_distance_error_seconds"] == 0
    assert any(not route["edge_ids"] for route in report["routes"]["routes"])
    assert all(route["error_seconds"] <= 1e-3 for route in report["routes"]["routes"])
    assert _sha256(output / "validation.json") == metadata["validation_sha256"]
    assert _sha256(output / "aoi.metadata.json") == metadata["aoi_metadata_sha256"]
    for path, content in before.items():
        assert path.read_bytes() == content
        if path.name != "metadata.json":
            assert (output / path.name).read_bytes() == content
    with pytest.raises(FileExistsError):
        validate_graph(source, area, output)


@pytest.mark.parametrize("filename", ["csr.npz", "geometry.npz", "speed_profile.yaml"])
def test_checksum_failure_not_published(
    bundle: tuple[Path, Path], tmp_path: Path, filename: str,
) -> None:
    source, area = bundle
    (source / filename).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        validate_graph(source, area, tmp_path / "validated")
    assert not (tmp_path / "validated").exists()


def test_wrong_csr_with_updated_checksum_rejected(
    bundle: tuple[Path, Path], tmp_path: Path,
) -> None:
    source, area = bundle
    csr = load_npz(source / "csr.npz")
    csr.data[0] += 1
    save_npz(source / "csr.npz", csr)
    path = source / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["csr_sha256"] = _sha256(source / "csr.npz")
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="CSR does not match"):
        validate_graph(source, area, tmp_path / "validated")


def test_wrong_geometry_mapping_rejected(bundle: tuple[Path, Path], tmp_path: Path) -> None:
    source, area = bundle
    with np.load(source / "geometry.npz", allow_pickle=False) as packed:
        arrays = dict(packed)
    arrays["coordinates"][0, 0] += 1
    np.savez_compressed(source / "geometry.npz", **arrays)
    path = source / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["geometry_sha256"] = _sha256(source / "geometry.npz")
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Mapping does not match"):
        validate_graph(source, area, tmp_path / "validated")


def test_wrong_aoi_rejected(bundle: tuple[Path, Path], tmp_path: Path) -> None:
    source, area = bundle
    (area.parent / "aoi.geojson").write_text(json.dumps(mapping(box(105, 20, 106, 21))))
    with pytest.raises(ValueError, match="different polygon"):
        validate_graph(source, area, tmp_path / "validated")


@pytest.mark.parametrize("field", ["length_m", "estimated_speed_kmh"])
def test_inconsistent_units_rejected(
    bundle: tuple[Path, Path], tmp_path: Path, field: str,
) -> None:
    ox = pytest.importorskip("osmnx")
    source, area = bundle
    graph = ox.load_graphml(source / "graph.graphml")
    edge = next(iter(graph.edges(keys=True)))
    graph.edges[edge][field] = float(graph.edges[edge][field]) * 1000
    ox.save_graphml(graph, filepath=source / "graph.graphml")
    path = source / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["graph_sha256"] = _sha256(source / "graph.graphml")
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="geometry, units, speed or weight"):
        validate_graph(source, area, tmp_path / "validated")


@pytest.mark.parametrize("field,value", [("buffer_m", -1), ("buffer_m", float("nan")),
                                        ("area_id", ""), ("measurement_crs", "EPSG:4326")])
def test_invalid_area_metadata_rejected(
    bundle: tuple[Path, Path], tmp_path: Path, field: str, value: object,
) -> None:
    source, area = bundle
    metadata = json.loads(area.read_text())
    metadata[field] = value
    area.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="Invalid AOI metadata"):
        validate_graph(source, area, tmp_path / "validated")
