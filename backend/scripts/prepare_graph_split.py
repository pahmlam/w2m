"""Split SCC edges by travel time and AOI boundary without network access."""

import argparse
import json
import shutil
from collections import Counter
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import numpy as np
from pyproj import Transformer
from shapely.ops import transform

from app.config.settings import get_settings
from app.services.area import METRIC_CRS, WGS84_CRS, load_aoi
from app.services.graph_reverse_edges import identify_reverse_edges
from app.services.graph_split import BOUNDARY_TOLERANCE_METERS, split_graph_edges
from scripts.download_osm import _sha256
from scripts.prepare_graph_scc import NUMERIC_EDGE_FIELDS


def prepare_graph_split(
    scc_dir: Path, reverse_dir: Path, output_dir: Path, max_edge_seconds: float = 60.0,
) -> Path:
    """Publish split GraphML, lineage, reverse mapping and validated metadata atomically."""
    if output_dir.exists() or output_dir.resolve() in (scc_dir.resolve(), reverse_dir.resolve()):
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new directory")
    metadata_path = scc_dir / "metadata.json"
    source = json.loads(metadata_path.read_text(encoding="utf-8"))
    reverse_metadata_path = reverse_dir / "metadata.json"
    reverse_meta = json.loads(reverse_metadata_path.read_text(encoding="utf-8"))
    if (not isinstance(source, dict) or not isinstance(reverse_meta, dict)
            or source.get("stage") != "scc" or reverse_meta.get("stage") != "reverse-edges"):
        raise ValueError("Expected SCC graph and reverse-edge mapping artifacts")
    for filename, field in (("graph.graphml", "graph_sha256"),
                            ("speed_profile.yaml", "weight_profile_sha256"),
                            ("aoi.geojson", "aoi_sha256")):
        if _sha256(scc_dir / filename) != source[field]:
            raise ValueError(f"SCC input checksum mismatch: {filename}")
    if (
        reverse_meta["source_graph_sha256"] != source["graph_sha256"]
        or reverse_meta["source_metadata_sha256"] != _sha256(metadata_path)
        or reverse_meta["mapping_sha256"] != _sha256(reverse_dir / "reverse_edges.json")
        or reverse_meta["weight_profile_version"] != source["weight_profile_version"]
    ):
        raise ValueError("Reverse mapping checksum or source version mismatch")
    mapping = json.loads((reverse_dir / "reverse_edges.json").read_text(encoding="utf-8"))
    aoi = load_aoi(scc_dir / "aoi.geojson")
    projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    ox = import_module("osmnx")
    load_options = {
        "node_dtypes": {"lon": float, "lat": float},
        "edge_dtypes": {
            **dict.fromkeys(NUMERIC_EDGE_FIELDS, float),
            **dict.fromkeys(("parent_u", "parent_v", "parent_key", "segment_index"), int),
        },
    }
    graph = ox.load_graphml(filepath=scc_dir / "graph.graphml", **load_options)
    if (
        graph.number_of_nodes() != source["node_count"]
        or graph.number_of_edges() != source["edge_count"]
        or graph.graph.get("weight_profile_version") != source["weight_profile_version"]
        or graph.graph.get("travel_mode") != "car"
    ):
        raise ValueError("Graph does not match SCC metadata")
    result, lineage = split_graph_edges(graph, mapping, transform(projector.transform, aoi),
                                        max_edge_seconds)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-split-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for filename in ("aoi.geojson", "speed_profile.yaml"):
            shutil.copyfile(scc_dir / filename, staging / filename)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(result, filepath=graph_path)
        restored = ox.load_graphml(filepath=graph_path, **load_options)
        if (
            not nx.is_strongly_connected(restored)
            or set(restored.nodes) != set(result.nodes)
            or set(restored.edges) != set(result.edges)
            or restored.graph.get("weight_profile_version") != source["weight_profile_version"]
            or str(restored.graph["crs"]) != METRIC_CRS
            or any(any(restored.nodes[node][field] != data[field]
                       for field in ("x", "y", "lon", "lat", "aoi_relation"))
                   for node, data in result.nodes(data=True))
            or any(
                any(restored.edges[edge][field] != result.edges[edge][field]
                    for field in (*NUMERIC_EDGE_FIELDS, "length", "aoi_relation"))
                or not restored.edges[edge]["geometry"].equals_exact(
                    result.edges[edge]["geometry"], 0,
                )
                or any(restored.edges[edge].get(field) != result.edges[edge].get(field)
                       for field in ("parent_u", "parent_v", "parent_key", "segment_index"))
                for edge in result.edges
            )
        ):
            raise ValueError("Split GraphML failed the offline reload check")
        reverse_mapping = identify_reverse_edges(restored)
        for filename, payload in (("edge_splits.json", lineage),
                                  ("reverse_edges.json", reverse_mapping)):
            path = staging / filename
            path.write_text(json.dumps(payload, allow_nan=False) + "\n", encoding="utf-8")
            if json.loads(path.read_text(encoding="utf-8")) != payload:
                raise ValueError(f"Split mapping failed the offline reload check: {filename}")
        times = [data["travel_time_seconds"] for _, _, data in restored.edges(data=True)]
        if max(times) > max_edge_seconds:
            raise ValueError("Reloaded edges exceed max_edge_seconds")
        report = {
            "schema_version": 1, "stage": "split",
            "source_snapshot_id": source["source_snapshot_id"],
            "source": source["source"], "source_date": source["source_date"],
            "build_date": datetime.now(UTC).isoformat(),
            "source_graph_sha256": source["graph_sha256"],
            "source_metadata_sha256": _sha256(metadata_path),
            "source_reverse_metadata_sha256": _sha256(reverse_metadata_path),
            "source_reverse_mapping_sha256": reverse_meta["mapping_sha256"],
            "graph_sha256": _sha256(graph_path),
            "aoi_sha256": _sha256(staging / "aoi.geojson"),
            "weight_profile_sha256": _sha256(staging / "speed_profile.yaml"),
            "edge_splits_sha256": _sha256(staging / "edge_splits.json"),
            "reverse_edges_sha256": _sha256(staging / "reverse_edges.json"),
            "weight_profile_version": source["weight_profile_version"],
            "crs": METRIC_CRS, "travel_mode": "car",
            "input_node_count": graph.number_of_nodes(),
            "input_edge_count": graph.number_of_edges(),
            "node_count": restored.number_of_nodes(), "edge_count": restored.number_of_edges(),
            "added_nodes": restored.number_of_nodes() - graph.number_of_nodes(),
            "split_parent_edges": sum(len(item["children"]) > 1 for item in lineage),
            "max_edge_seconds": max_edge_seconds,
            "tau_p50": float(np.percentile(times, 50)),
            "tau_p99": float(np.percentile(times, 99)), "tau_max": max(times),
            "boundary_tolerance_meters": BOUNDARY_TOLERANCE_METERS,
            "node_aoi_relations": dict(sorted(Counter(
                data["aoi_relation"] for _, data in restored.nodes(data=True)).items())),
            "edge_aoi_relations": dict(sorted(Counter(
                data["aoi_relation"] for _, _, data in restored.edges(data=True)).items())),
            "reverse_pair_count": len(reverse_mapping["pairs"]),
            "scc_removed_nodes": source["scc_removed_nodes"],
            "scc_removed_edges": source["scc_removed_edges"],
            "node_id_rule": "descending negative IDs below all source nodes, sorted parent groups",
            "edge_id_rule": "child endpoints and original directed edge key",
            "attribution": source["attribution"], "license": source["license"],
        }
        (staging / "metadata.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run explicit offline subdivision with a new output directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scc-dir", type=Path, required=True)
    parser.add_argument("--reverse-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-edge-seconds", type=float, default=get_settings().max_edge_seconds)
    args = parser.parse_args(argv)
    try:
        result = prepare_graph_split(args.scc_dir, args.reverse_dir, args.output_dir,
                                     args.max_edge_seconds)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Split graph artifact: {result}")
    print(f"Validation metadata: {result / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
