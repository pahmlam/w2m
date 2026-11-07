"""Keep the largest SCC of a weighted artifact offline and export discarded AOI roads."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from importlib import import_module
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import numpy as np
import yaml
from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import transform

from app.config.settings import get_settings
from app.services.area import METRIC_CRS, WGS84_CRS, load_aoi
from app.services.graph_components import keep_largest_scc, removed_features_in_aoi
from app.services.graph_weights import load_speed_profile
from scripts.download_osm import _sha256

NUMERIC_EDGE_FIELDS = ("length_m", "estimated_speed_kmh", "travel_time_seconds", "travel_time")


def prepare_graph_scc(weighted_dir: Path, aoi_path: Path, output_dir: Path) -> Path:
    """Publish an SCC artifact with provenance only after validating its GraphML reload."""
    if output_dir.exists() or output_dir.resolve() == weighted_dir.resolve():
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new directory")
    source_metadata_path = weighted_dir / "metadata.json"
    metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("stage") != "weighted":
        raise ValueError("Expected a weighted input artifact")
    source_path = weighted_dir / "graph.graphml"
    profile_path = weighted_dir / "speed_profile.yaml"
    for path, field in ((source_path, "graph_sha256"), (profile_path, "weight_profile_sha256")):
        if _sha256(path) != metadata[field]:
            raise ValueError(f"Input checksum mismatch: {path.name}")
    profile = load_speed_profile(profile_path)
    if metadata["weight_profile_version"] != profile.version:
        raise ValueError("Metadata and speed profile versions differ")
    # Read the AOI once so its exported bytes and provenance describe the same polygon.
    aoi_bytes = aoi_path.read_bytes()
    ox = import_module("osmnx")
    graph = ox.load_graphml(
        filepath=source_path, node_dtypes={"lon": float, "lat": float},
        edge_dtypes=dict.fromkeys(NUMERIC_EDGE_FIELDS, float),
    )
    if (
        graph.number_of_nodes() != metadata["node_count"]
        or graph.number_of_edges() != metadata["edge_count"]
        or graph.graph.get("weight_profile_version") != profile.version
        or graph.graph.get("travel_mode") != "car"
    ):
        raise ValueError("Graph does not match weighted metadata")
    for source, target, key, data in graph.edges(keys=True, data=True):
        if (
            any(not isfinite(data[field]) or data[field] <= 0 for field in NUMERIC_EDGE_FIELDS)
            or data["travel_time"] != data["travel_time_seconds"]
            or not isinstance(data.get("geometry"), LineString)
            or data["geometry"].is_empty
            or not data["geometry"].is_valid
        ):
            raise ValueError(f"Invalid weighted edge {(source, target, key)}")
    retained = keep_largest_scc(graph)
    if not retained.number_of_edges():
        raise ValueError("Largest SCC contains no road edges")
    # These counts describe the pre-filter graph and cannot be reused as SCC statistics.
    for field in ("default_speed_edge_count", "maxspeed_capped_edge_count",
                  "ignored_maxspeed_edge_count"):
        retained.graph.pop(field, None)
    retained.graph.update(
        scc_removed_nodes=graph.number_of_nodes() - retained.number_of_nodes(),
        scc_removed_edges=graph.number_of_edges() - retained.number_of_edges(),
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-scc-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        saved_aoi = staging / "aoi.geojson"
        saved_aoi.write_bytes(aoi_bytes)
        aoi = load_aoi(saved_aoi)
        projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
        removed = removed_features_in_aoi(graph, retained, transform(projector.transform, aoi))
        removed_path = staging / "removed_in_aoi.geojson"
        removed_path.write_text(json.dumps(removed, allow_nan=False) + "\n", encoding="utf-8")
        saved_profile = staging / "speed_profile.yaml"
        shutil.copyfile(profile_path, saved_profile)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(retained, filepath=graph_path)
        restored = ox.load_graphml(
            filepath=graph_path, node_dtypes={"lon": float, "lat": float},
            edge_dtypes=dict.fromkeys(NUMERIC_EDGE_FIELDS, float),
        )
        if (
            not nx.is_strongly_connected(restored)
            or set(restored.nodes) != set(retained.nodes)
            or set(restored.edges) != set(retained.edges)
            or str(restored.graph["crs"]) != str(retained.graph["crs"])
            or restored.graph.get("weight_profile_version") != profile.version
            or any(
                any(restored.nodes[node][field] != retained.nodes[node][field]
                    for field in ("x", "y", "lon", "lat"))
                for node in retained
            )
            or any(
                any(restored.edges[edge][field] != retained.edges[edge][field]
                    for field in NUMERIC_EDGE_FIELDS)
                or not restored.edges[edge]["geometry"].equals_exact(
                    retained.edges[edge]["geometry"], 1e-8,
                )
                for edge in retained.edges
            )
        ):
            raise ValueError("SCC GraphML failed the offline reload check")
        times = [data["travel_time_seconds"] for _, _, data in retained.edges(data=True)]
        report = {
            "schema_version": 1, "stage": "scc",
            "source_snapshot_id": metadata["source_snapshot_id"],
            "source": metadata["source"], "source_date": metadata["source_date"],
            "source_weighted_graph_sha256": _sha256(source_path),
            "source_metadata_sha256": _sha256(source_metadata_path),
            "graph_sha256": _sha256(graph_path),
            "weight_profile_sha256": _sha256(saved_profile),
            "aoi_sha256": _sha256(saved_aoi),
            "removed_in_aoi_sha256": _sha256(removed_path),
            "weight_profile_version": profile.version,
            "build_date": datetime.now(UTC).isoformat(),
            "crs": str(retained.graph["crs"]), "travel_mode": "car",
            "input_node_count": graph.number_of_nodes(),
            "input_edge_count": graph.number_of_edges(),
            "node_count": retained.number_of_nodes(), "edge_count": retained.number_of_edges(),
            "scc_count": nx.number_strongly_connected_components(graph),
            "scc_removed_nodes": graph.number_of_nodes() - retained.number_of_nodes(),
            "scc_removed_edges": graph.number_of_edges() - retained.number_of_edges(),
            "removed_nodes_in_aoi": sum(f["properties"]["kind"] == "node"
                                        for f in removed["features"]),
            "removed_edges_in_aoi": sum(f["properties"]["kind"] == "edge"
                                        for f in removed["features"]),
            "scc_tie_break": "smallest_node_id",
            "tau_p50": float(np.percentile(times, 50)),
            "tau_p99": float(np.percentile(times, 99)), "tau_max": max(times),
            "attribution": metadata["attribution"], "license": metadata["license"],
        }
        (staging / "metadata.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run SCC preparation without network access or overwriting source artifacts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weighted-dir", type=Path, required=True)
    parser.add_argument("--aoi", type=Path, default=get_settings().aoi_path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_graph_scc(args.weighted_dir, args.aoi, args.output_dir)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    print(f"SCC artifact: {result}")
    print(f"Removed AOI geometry: {result / 'removed_in_aoi.geojson'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
