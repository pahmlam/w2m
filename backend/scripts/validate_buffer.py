"""Run TC-15 offline on two bundles built from the same larger OSM snapshot."""

import argparse
import json
import platform
from datetime import UTC, datetime
from math import isclose
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.sparse import load_npz
from scipy.sparse.csgraph import dijkstra
from shapely import Point, transform

from app.services.area import METRIC_CRS, WGS84_CRS, load_aoi
from scripts.download_osm import _sha256

PAIR_COUNT = 200
BOUNDARY_BAND_METERS = 1000
RELATIVE_ERROR_LIMIT = 0.01
REQUIRED_PASS_COUNT = 198
SEED = 20261114


def validate_buffer(base_dir: Path, reference_dir: Path, output: Path, seed: int = SEED) -> dict:
    """Compare 200 distinct directed pairs; missing reference nodes count as failures.

    Sample original OSM nodes inside the AOI's 1 km boundary band in the base
    production graph. Generated split nodes are excluded because their IDs need
    not match across builds. Relative error uses the doubled-buffer time.
    """
    if output.exists():
        raise FileExistsError(f"Report already exists: {output}")
    bundles = [directory / "validated" for directory in (base_dir, reference_dir)]
    metadata = [json.loads((directory / "metadata.json").read_bytes()) for directory in bundles]
    manifests = [json.loads((directory / "snapshot/manifest.json").read_bytes())
                 for directory in (base_dir, reference_dir)]
    for field in ("parent_manifest_sha256", "parent_graph_sha256", "snapshot_at"):
        if not manifests[0].get(field) or manifests[0][field] != manifests[1][field]:
            raise ValueError(f"Builds must use the same original snapshot: {field}")
    for field in ("area_id", "aoi_sha256", "weight_profile_sha256", "weight_profile_version",
                  "source_snapshot_id", "source_date", "travel_mode", "crs"):
        if metadata[0][field] != metadata[1][field]:
            raise ValueError(f"Incompatible buffer builds: {field}")
    if (metadata[0]["buffer_m"] <= 0
            or not isclose(metadata[1]["buffer_m"], 2 * metadata[0]["buffer_m"])):
        raise ValueError("Reference buffer must be twice the base buffer")
    for directory, meta in zip(bundles, metadata):
        for filename, field in (("csr.npz", "csr_sha256"), ("mappings.npz", "mappings_sha256"),
                                ("aoi.geojson", "aoi_sha256"),
                                ("speed_profile.yaml", "weight_profile_sha256"),
                                ("validation.json", "validation_sha256")):
            if _sha256(directory / filename) != meta[field]:
                raise ValueError(f"Bundle checksum mismatch: {filename}")
        if json.loads((directory / "validation.json").read_bytes())["status"] != "passed":
            raise ValueError("Both bundles must pass offline validation first")
    matrices = [load_npz(directory / "csr.npz") for directory in bundles]
    mappings = []
    for directory in bundles:
        with np.load(directory / "mappings.npz", allow_pickle=False) as packed:
            mappings.append(dict(packed))
    projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    aoi = transform(load_aoi(bundles[0] / "aoi.geojson"), projector.transform, interleaved=False)
    eligible = np.array([
        index for index, (node, xy) in enumerate(zip(
            mappings[0]["node_ids"], mappings[0]["node_xy"],
        ))
        if node > 0 and aoi.covers(Point(xy))
        and aoi.boundary.distance(Point(xy)) <= BOUNDARY_BAND_METERS
    ])
    count = len(eligible)
    if count * (count - 1) < PAIR_COUNT:
        raise ValueError("Too few original boundary-band nodes for 200 distinct directed pairs")
    # Uniform sampling without replacement from all ordered pairs, excluding self-pairs.
    draws = np.random.default_rng(seed).choice(count * (count - 1), PAIR_COUNT, replace=False)
    sources = draws // (count - 1)
    targets = draws % (count - 1)
    targets += targets >= sources
    lookup = {int(node): index for index, node in enumerate(mappings[1]["node_ids"])}
    pairs = []
    for source, target in zip(eligible[sources], eligible[targets]):
        source_id, target_id = (int(mappings[0]["node_ids"][i]) for i in (source, target))
        base_seconds = float(dijkstra(matrices[0], directed=True, indices=int(source))[target])
        reference_seconds = None
        relative_error = None
        if source_id in lookup and target_id in lookup:
            for node_id, index in ((source_id, source), (target_id, target)):
                if not np.allclose(mappings[0]["node_xy"][index],
                                   mappings[1]["node_xy"][lookup[node_id]], rtol=0, atol=1e-7):
                    raise ValueError("Original OSM node coordinates differ between builds")
            seconds = float(dijkstra(matrices[1], directed=True,
                                     indices=lookup[source_id])[lookup[target_id]])
            if np.isfinite(seconds) and seconds > 0 and np.isfinite(base_seconds):
                reference_seconds = seconds
                relative_error = abs(base_seconds - seconds) / seconds
        pairs.append({
            "source_node_id": source_id, "target_node_id": target_id,
            "base_seconds": base_seconds if np.isfinite(base_seconds) else None,
            "reference_seconds": reference_seconds, "relative_error": relative_error,
            "passed": relative_error is not None and relative_error <= RELATIVE_ERROR_LIMIT + 1e-12,
        })
    passed = sum(pair["passed"] for pair in pairs)
    report = {
        "test_id": "TC-15", "status": "passed" if passed >= REQUIRED_PASS_COUNT else "failed",
        "created_at": datetime.now(UTC).isoformat(), "seed": seed,
        "implementation_sha256": _sha256(Path(__file__)), "python": platform.python_version(),
        "area_id": metadata[0]["area_id"], "snapshot_at": manifests[0]["snapshot_at"],
        "source_manifest_sha256": manifests[0]["parent_manifest_sha256"],
        "weight_profile_version": metadata[0]["weight_profile_version"],
        "graph_versions": [meta["graph_version"] for meta in metadata],
        "metadata_sha256": [_sha256(directory / "metadata.json") for directory in bundles],
        "buffers_meters": [meta["buffer_m"] for meta in metadata],
        "boundary_band_meters": BOUNDARY_BAND_METERS, "eligible_node_count": count,
        "sampling": "uniform distinct directed original-OSM-node pairs; no self pairs",
        "relative_error_definition": "abs(base_seconds - reference_seconds) / reference_seconds",
        "relative_error_limit": RELATIVE_ERROR_LIMIT, "required_pass_count": REQUIRED_PASS_COUNT,
        "pair_count": PAIR_COUNT, "passed_pair_count": passed, "pairs": pairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    """Keep failed reports and return a nonzero status when TC-15 fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = validate_buffer(args.base_dir, args.reference_dir, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"TC-15 {report['status']}: {report['passed_pair_count']}/{PAIR_COUNT} pairs")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
