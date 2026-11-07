"""Publish a reverse-edge mapping bound to an existing SCC artifact by checksum."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx

from app.services.graph_geometry import ENDPOINT_TOLERANCE_METERS
from app.services.graph_reverse_edges import identify_reverse_edges
from scripts.download_osm import _sha256


def prepare_reverse_edges(scc_dir: Path, output_dir: Path) -> Path:
    """Export mapping and provenance without rewriting or copying the source graph."""
    if output_dir.exists() or output_dir.resolve() == scc_dir.resolve():
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new directory")
    metadata_path = scc_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("stage") != "scc":
        raise ValueError("Expected an SCC input artifact")
    graph_path = scc_dir / "graph.graphml"
    if _sha256(graph_path) != metadata["graph_sha256"]:
        raise ValueError("SCC GraphML checksum does not match its metadata")
    ox = import_module("osmnx")
    graph = ox.load_graphml(filepath=graph_path)
    if (
        graph.number_of_nodes() != metadata["node_count"]
        or graph.number_of_edges() != metadata["edge_count"]
        or graph.graph.get("weight_profile_version") != metadata["weight_profile_version"]
        or graph.graph.get("travel_mode") != "car"
        or not nx.is_strongly_connected(graph)
    ):
        raise ValueError("Graph does not match SCC metadata or is not strongly connected")
    mapping = identify_reverse_edges(graph)
    counts = Counter(item["reason"] for item in mapping["unpaired"])
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".reverse-edges-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        mapping_path = staging / "reverse_edges.json"
        mapping_path.write_text(json.dumps(mapping, allow_nan=False) + "\n", encoding="utf-8")
        if json.loads(mapping_path.read_text(encoding="utf-8")) != mapping:
            raise ValueError("Reverse-edge mapping failed the offline reload check")
        report = {
            "schema_version": 1, "stage": "reverse-edges",
            "source_scc_artifact": scc_dir.name,
            "source_graph_sha256": _sha256(graph_path),
            "source_metadata_sha256": _sha256(metadata_path),
            "mapping_sha256": _sha256(mapping_path),
            "source_snapshot_id": metadata["source_snapshot_id"],
            "weight_profile_version": metadata["weight_profile_version"],
            "build_date": datetime.now(UTC).isoformat(),
            "crs": str(graph.graph["crs"]), "travel_mode": "car",
            "node_count": graph.number_of_nodes(), "edge_count": graph.number_of_edges(),
            "geometry_tolerance_meters": ENDPOINT_TOLERANCE_METERS,
            "pair_count": len(mapping["pairs"]),
            "paired_edge_count": 2 * len(mapping["pairs"]),
            "unpaired_edge_count": len(mapping["unpaired"]),
            "unpaired_reasons": dict(sorted(counts.items())),
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
    """Run offline identification; graph geometry and directional weights stay unchanged."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scc-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_reverse_edges(args.scc_dir, args.output_dir)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Reverse-edge mapping: {result / 'reverse_edges.json'}")
    print(f"Validation metadata: {result / 'metadata.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
