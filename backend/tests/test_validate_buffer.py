"""TC-15 uses directed distances and does not hide missing nodes or bad provenance."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import load_npz, save_npz
from test_build_graph import built_graph as built_graph
from test_build_graph import raw_inputs as raw_inputs

from scripts.download_osm import _sha256
from scripts.validate_buffer import main, validate_buffer


@pytest.fixture
def comparison(built_graph: Path, tmp_path: Path) -> tuple[Path, Path]:
    reference = tmp_path / "reference"
    shutil.copytree(built_graph, reference)
    path = reference / "validated/metadata.json"
    metadata = json.loads(path.read_bytes())
    metadata.update(buffer_m=6000, graph_version="fixture-reference-v1")
    path.write_text(json.dumps(metadata))
    return built_graph, reference


def test_seeded_pairs_and_directed_times(comparison: tuple[Path, Path], tmp_path: Path) -> None:
    base, reference = comparison
    report = validate_buffer(base, reference, tmp_path / "first.json")
    repeated = validate_buffer(base, reference, tmp_path / "second.json")
    assert report["status"] == "passed"
    assert report["passed_pair_count"] == 200
    assert report["pairs"] == repeated["pairs"]
    pairs = {(item["source_node_id"], item["target_node_id"]): item for item in report["pairs"]}
    assert len(pairs) == 200
    assert all(a != b for a, b in pairs)
    assert any(pairs[a, b]["base_seconds"] != pairs[b, a]["base_seconds"]
               for a, b in pairs if (b, a) in pairs)
    with pytest.raises(FileExistsError):
        validate_buffer(base, reference, tmp_path / "first.json")


def test_material_buffer_error_fails_and_keeps_report(
    comparison: tuple[Path, Path], tmp_path: Path,
) -> None:
    base, reference = comparison
    directory = reference / "validated"
    matrix = load_npz(directory / "csr.npz")
    matrix.data *= 0.5
    save_npz(directory / "csr.npz", matrix)
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["csr_sha256"] = _sha256(directory / "csr.npz")
    metadata_path.write_text(json.dumps(metadata))
    output = tmp_path / "failed.json"
    assert main(["--base-dir", str(base), "--reference-dir", str(reference),
                 "--output", str(output)]) == 1
    report = json.loads(output.read_bytes())
    assert report["passed_pair_count"] == 0
    assert all(item["relative_error"] == pytest.approx(1) for item in report["pairs"])


@pytest.mark.parametrize("field,value", [("buffer_m", 4500), ("weight_profile_version", "other")])
def test_incompatible_builds_rejected(
    comparison: tuple[Path, Path], tmp_path: Path, field: str, value: object,
) -> None:
    base, reference = comparison
    path = reference / "validated/metadata.json"
    metadata = json.loads(path.read_bytes())
    metadata[field] = value
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        validate_buffer(base, reference, tmp_path / "report.json")
    assert not (tmp_path / "report.json").exists()


def test_snapshot_provenance_mismatch_rejected(
    comparison: tuple[Path, Path], tmp_path: Path,
) -> None:
    base, reference = comparison
    path = reference / "snapshot/manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["parent_graph_sha256"] = "other"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="same original snapshot"):
        validate_buffer(base, reference, tmp_path / "report.json")


def test_corrupt_bundle_rejected(comparison: tuple[Path, Path], tmp_path: Path) -> None:
    base, reference = comparison
    (reference / "validated/csr.npz").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        validate_buffer(base, reference, tmp_path / "report.json")


def test_missing_reference_nodes_are_failures(
    comparison: tuple[Path, Path], tmp_path: Path,
) -> None:
    base, reference = comparison
    directory = reference / "validated"
    with np.load(directory / "mappings.npz", allow_pickle=False) as packed:
        arrays = dict(packed)
    arrays["node_ids"][0] = 999
    np.savez_compressed(directory / "mappings.npz", **arrays)
    path = directory / "metadata.json"
    metadata = json.loads(path.read_bytes())
    metadata["mappings_sha256"] = _sha256(directory / "mappings.npz")
    path.write_text(json.dumps(metadata))
    report = validate_buffer(base, reference, tmp_path / "report.json")
    assert report["status"] == "failed"
    assert len(report["pairs"]) == 200
    assert any(item["reference_seconds"] is None for item in report["pairs"])


@pytest.mark.parametrize("failures,status", [(2, "passed"), (3, "failed")])
def test_acceptance_threshold_is_198_of_200(
    comparison: tuple[Path, Path], tmp_path: Path, monkeypatch, failures: int, status: str,
) -> None:
    import scripts.validate_buffer as validator

    real_dijkstra = validator.dijkstra
    calls = 0

    def distances(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = real_dijkstra(*args, **kwargs)
        if calls % 2 == 0 and calls <= failures * 2:
            result *= 0.5
        return result

    monkeypatch.setattr(validator, "dijkstra", distances)
    report = validate_buffer(*comparison, tmp_path / "report.json")
    assert report["status"] == status
    assert report["passed_pair_count"] == 200 - failures
