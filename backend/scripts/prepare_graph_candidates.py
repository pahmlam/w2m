"""Mark meeting candidates in an offline split graph artifact."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx

from scripts.download_osm import _sha256
from scripts.prepare_graph_split import SPLIT_GRAPHML_DTYPES

SPLIT_FILES = {
    "graph.graphml": "graph_sha256",
    "aoi.geojson": "aoi_sha256",
    "speed_profile.yaml": "weight_profile_sha256",
    "edge_splits.json": "edge_splits_sha256",
    "reverse_edges.json": "reverse_edges_sha256",
}
FLAG_NAMES = ("in_aoi", "is_candidate")


def mark_candidate_nodes(graph: nx.MultiDiGraph, excluded_ids: list[int]) -> None:
    """Set candidate and coverage flags on an offline graph without removing roads."""
    if any(type(node_id) is not int for node_id in excluded_ids):
        raise ValueError("Exclusion list must contain only integer node IDs")
    excluded = set(excluded_ids)
    if len(excluded) != len(excluded_ids):
        raise ValueError("Exclusion list contains duplicate node IDs")
    if unknown := excluded.difference(graph.nodes):
        raise ValueError(f"Unknown excluded node IDs: {sorted(unknown)}")
    for node_id, data in graph.nodes(data=True):
        if data.get("aoi_relation") not in ("inside", "boundary", "outside"):
            raise ValueError(f"Invalid aoi_relation for node {node_id}")
        in_aoi = data["aoi_relation"] != "outside"
        data.update(in_aoi=in_aoi, is_candidate=in_aoi and node_id not in excluded)


def prepare_graph_candidates(
    split_dir: Path, output_dir: Path, exclusions_path: Path | None = None,
) -> Path:
    """Publish a flagged GraphML and its source mappings after validating the reload."""
    if output_dir.exists() or output_dir.resolve().is_relative_to(split_dir.resolve()):
        raise FileExistsError(f"Choose a new output directory outside the input: {output_dir}")
    metadata_path = split_dir / "metadata.json"
    source = json.loads(metadata_path.read_bytes())
    if not isinstance(source, dict) or source.get("stage") != "split":
        raise ValueError("Expected a split input artifact")
    for filename, field in SPLIT_FILES.items():
        if _sha256(split_dir / filename) != source[field]:
            raise ValueError(f"Split input checksum mismatch: {filename}")
    exclusions = exclusions_path.read_bytes() if exclusions_path is not None else b"[]\n"
    excluded_ids = json.loads(exclusions)
    if not isinstance(excluded_ids, list):
        raise ValueError("Exclusions must be a JSON array of integer node IDs")

    ox = import_module("osmnx")
    graph = ox.load_graphml(filepath=split_dir / "graph.graphml", **SPLIT_GRAPHML_DTYPES)
    if (graph.number_of_nodes(), graph.number_of_edges()) != (
        source["node_count"], source["edge_count"],
    ) or graph.graph.get("weight_profile_version") != source["weight_profile_version"]:
        raise ValueError("Graph does not match split metadata")
    mark_candidate_nodes(graph, excluded_ids)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-candidates-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(graph, filepath=graph_path)
        parse_bool = {"True": True, "False": False}.__getitem__
        restored = ox.load_graphml(
            filepath=graph_path,
            node_dtypes={**SPLIT_GRAPHML_DTYPES["node_dtypes"],
                         **dict.fromkeys(FLAG_NAMES, parse_bool)},
            edge_dtypes=SPLIT_GRAPHML_DTYPES["edge_dtypes"],
        )
        if not nx.utils.graphs_equal(restored, graph):
            raise ValueError("Candidate GraphML failed the offline reload check")
        for filename in SPLIT_FILES.keys() - {"graph.graphml"}:
            shutil.copyfile(split_dir / filename, staging / filename)
        exclusions_file = staging / "excluded_node_ids.json"
        exclusions_file.write_bytes(exclusions)
        in_aoi_count = sum(data["in_aoi"] for _, data in restored.nodes(data=True))
        candidate_count = sum(data["is_candidate"] for _, data in restored.nodes(data=True))
        report = dict(
            source,
            stage="candidates",
            build_date=datetime.now(UTC).isoformat(),
            graph_sha256=_sha256(graph_path),
            source_split_graph_sha256=source["graph_sha256"],
            source_split_metadata_sha256=_sha256(metadata_path),
            excluded_node_ids_sha256=_sha256(exclusions_file),
            excluded_node_count=len(excluded_ids),
            excluded_in_aoi_count=in_aoi_count - candidate_count,
            candidate_node_count=candidate_count,
        )
        (staging / "metadata.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run offline candidate preparation with an optional JSON exclusion list."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--exclude-node-ids", type=Path)
    args = parser.parse_args(argv)
    try:
        output = prepare_graph_candidates(args.split_dir, args.output_dir, args.exclude_node_ids)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Candidate graph artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
