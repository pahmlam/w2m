"""Assign static car travel times to an existing geometry artifact offline."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import yaml

from app.config.settings import get_settings
from app.services.graph_weights import apply_speed_profile, load_speed_profile
from scripts.download_osm import _sha256


def prepare_graph_weights(geometry_dir: Path, profile_path: Path, output_dir: Path) -> Path:
    """Publish weighted GraphML, its profile and validation metadata after reload."""
    if output_dir.exists() or geometry_dir.resolve() == output_dir.resolve():
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new directory")
    metadata_path = geometry_dir / "metadata.json"
    source_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(source_metadata, dict) or source_metadata.get("stage") != "geometry-only":
        raise ValueError("Expected a geometry-only input artifact")
    source_path = geometry_dir / "graph.graphml"
    source_checksum = _sha256(source_path)
    if source_checksum != source_metadata["graph_sha256"]:
        raise ValueError("Geometry GraphML checksum does not match its metadata")
    ox = import_module("osmnx")
    graph = ox.load_graphml(
        filepath=source_path,
        node_dtypes={"lon": float, "lat": float},
        edge_dtypes={"length_m": float},
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-weights-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        saved_profile = staging / "speed_profile.yaml"
        shutil.copyfile(profile_path, saved_profile)
        profile = load_speed_profile(saved_profile)
        weighted = apply_speed_profile(graph, profile)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(weighted, filepath=graph_path)
        numeric_fields = ("length_m", "estimated_speed_kmh", "travel_time_seconds", "travel_time")
        restored = ox.load_graphml(
            filepath=graph_path,
            node_dtypes={"lon": float, "lat": float},
            edge_dtypes=dict.fromkeys(numeric_fields, float),
        )
        if (
            set(restored.nodes) != set(weighted.nodes)
            or set(restored.edges) != set(weighted.edges)
            or str(restored.graph["crs"]) != str(weighted.graph["crs"])
            or restored.graph.get("weight_profile_version") != profile.version
            or any(
                any(
                    restored.edges[edge][field] != weighted.edges[edge][field]
                    for field in numeric_fields
                )
                or not restored.edges[edge]["geometry"].equals_exact(
                    weighted.edges[edge]["geometry"], 1e-8,
                )
                for edge in weighted.edges
            )
        ):
            raise ValueError("Weighted GraphML failed the offline reload check")
        times = [data["travel_time_seconds"] for _, _, data in weighted.edges(data=True)]
        metadata = {
            "schema_version": 1,
            "stage": "weighted",
            "source_snapshot_id": source_metadata["source_snapshot_id"],
            "source": source_metadata["source"],
            "source_date": source_metadata["source_date"],
            "source_geometry_sha256": source_checksum,
            "source_metadata_sha256": _sha256(metadata_path),
            "graph_sha256": _sha256(graph_path),
            "weight_profile_sha256": _sha256(saved_profile),
            "weight_profile_version": profile.version,
            "build_date": datetime.now(UTC).isoformat(),
            "crs": str(weighted.graph["crs"]),
            "travel_mode": "car",
            "node_count": weighted.number_of_nodes(),
            "edge_count": weighted.number_of_edges(),
            "default_speed_edge_count": weighted.graph["default_speed_edge_count"],
            "maxspeed_capped_edge_count": weighted.graph["maxspeed_capped_edge_count"],
            "ignored_maxspeed_edge_count": weighted.graph["ignored_maxspeed_edge_count"],
            "invalid_edge_count": 0,
            "removed_edge_count": 0,
            "tau_p50": float(np.percentile(times, 50)),
            "tau_p99": float(np.percentile(times, 99)),
            "tau_max": max(times),
            "attribution": source_metadata["attribution"],
            "license": source_metadata["license"],
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run explicit offline weighting; never download OSM or overwrite input data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, default=get_settings().speed_profile_path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_graph_weights(args.geometry_dir, args.profile, args.output_dir)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    print(f"Weighted artifact: {result}")
    print(f"Validation metadata: {result / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
