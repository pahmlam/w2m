"""Export versioned CSR, reference graph and lossless mappings without network access."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import numpy as np
from scipy.sparse import load_npz, save_npz
from scipy.sparse.csgraph import dijkstra

from app.services.graph_csr import build_graph_csr
from scripts.download_osm import _sha256
from scripts.prepare_graph_candidates import FLAG_NAMES, SPLIT_FILES, mark_candidate_nodes
from scripts.prepare_graph_split import SPLIT_GRAPHML_DTYPES

VALIDATION_SEED = 20261111
VALIDATION_SOURCE_COUNT = 20


def prepare_graph_csr(candidates_dir: Path, output_dir: Path, graph_version: str) -> Path:
    """Publish a new CSR artifact only after reload and NetworkX distance checks."""
    if not graph_version.strip():
        raise ValueError("graph_version must be non-empty")
    if output_dir.exists() or output_dir.resolve().is_relative_to(candidates_dir.resolve()):
        raise FileExistsError(f"Choose a new output directory outside the input: {output_dir}")
    metadata_path = candidates_dir / "metadata.json"
    source = json.loads(metadata_path.read_bytes())
    if not isinstance(source, dict) or source.get("stage") != "candidates":
        raise ValueError("Expected a candidate input artifact")
    files = {**SPLIT_FILES, "excluded_node_ids.json": "excluded_node_ids_sha256"}
    for filename, field in files.items():
        if _sha256(candidates_dir / filename) != source[field]:
            raise ValueError(f"Candidate input checksum mismatch: {filename}")
    ox = import_module("osmnx")
    options = {
        "node_dtypes": {**SPLIT_GRAPHML_DTYPES["node_dtypes"],
                        **dict.fromkeys(FLAG_NAMES, {"True": True, "False": False}.__getitem__)},
        "edge_dtypes": SPLIT_GRAPHML_DTYPES["edge_dtypes"],
    }
    graph = ox.load_graphml(filepath=candidates_dir / "graph.graphml", **options)
    if (
        graph.number_of_nodes() != source["node_count"]
        or graph.number_of_edges() != source["edge_count"]
        or graph.graph.get("weight_profile_version") != source["weight_profile_version"]
        or graph.graph.get("travel_mode") != "car"
        or not nx.is_strongly_connected(graph)
    ):
        raise ValueError("Graph does not match candidate metadata or is not strongly connected")
    flags = [(data["in_aoi"], data["is_candidate"]) for _, data in graph.nodes(data=True)]
    excluded = json.loads((candidates_dir / "excluded_node_ids.json").read_bytes())
    if not isinstance(excluded, list):
        raise ValueError("Exclusions must be a JSON array")
    mark_candidate_nodes(graph, excluded)
    if flags != [(data["in_aoi"], data["is_candidate"]) for _, data in graph.nodes(data=True)]:
        raise ValueError("Candidate flags disagree with AOI relations or exclusion list")
    csr, mappings, geometry = build_graph_csr(graph)
    candidate_count = int(np.count_nonzero(mappings["is_candidate"]))
    if candidate_count != source["candidate_node_count"]:
        raise ValueError("Candidate count does not match metadata")
    graph.graph["graph_version"] = graph_version

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-csr-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(graph, filepath=graph_path)
        if not nx.utils.graphs_equal(ox.load_graphml(filepath=graph_path, **options), graph):
            raise ValueError("Reference GraphML failed the offline reload check")
        save_npz(staging / "csr.npz", csr)
        restored = load_npz(staging / "csr.npz")
        if (restored.shape != csr.shape or restored.format != "csr"
                or any(not np.array_equal(getattr(restored, field), getattr(csr, field))
                       for field in ("data", "indices", "indptr"))):
            raise ValueError("CSR failed the offline reload check")
        for filename, arrays in (("mappings.npz", mappings), ("geometry.npz", geometry)):
            np.savez_compressed(staging / filename, **arrays)
            with np.load(staging / filename, allow_pickle=False) as reloaded:
                if set(reloaded.files) != arrays.keys() or any(
                    not np.array_equal(reloaded[name], value) for name, value in arrays.items()
                ):
                    raise ValueError(f"Mapping failed the offline reload check: {filename}")
        sample = np.random.default_rng(VALIDATION_SEED).choice(
            len(graph), size=min(VALIDATION_SOURCE_COUNT, len(graph)), replace=False,
        )
        max_error = 0.0
        for index in sample:
            actual = dijkstra(restored, directed=True, indices=int(index))
            expected_by_node = nx.single_source_dijkstra_path_length(
                graph, int(mappings["node_ids"][index]), weight="travel_time",
            )
            expected = np.array([expected_by_node[int(node)] for node in mappings["node_ids"]])
            if not np.allclose(actual, expected, rtol=1e-12, atol=1e-9):
                raise ValueError("CSR distances differ from NetworkX")
            max_error = max(max_error, float(np.max(np.abs(actual - expected))))
        for filename in files.keys() - {"graph.graphml"}:
            shutil.copyfile(candidates_dir / filename, staging / filename)
        report = dict(
            source, stage="csr", graph_version=graph_version,
            build_date=datetime.now(UTC).isoformat(),
            source_candidates_graph_sha256=source["graph_sha256"],
            source_candidates_metadata_sha256=_sha256(metadata_path),
            graph_sha256=_sha256(graph_path),
            csr_sha256=_sha256(staging / "csr.npz"),
            mappings_sha256=_sha256(staging / "mappings.npz"),
            geometry_sha256=_sha256(staging / "geometry.npz"),
            csr_arc_count=csr.nnz,
            collapsed_parallel_edge_count=graph.number_of_edges() - csr.nnz,
            csr_parallel_edge_rule="minimum (travel_time, edge_key)",
            geometry_crs=source["crs"],
            validation_seed=VALIDATION_SEED,
            validation_source_count=len(sample),
            validation_max_distance_error_seconds=max_error,
        )
        (staging / "metadata.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Export an offline graph bundle with an explicit graph version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--graph-version", required=True)
    args = parser.parse_args(argv)
    try:
        output = prepare_graph_csr(args.candidates_dir, args.output_dir, args.graph_version)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, OverflowError) as exc:
        parser.error(str(exc))
    print(f"CSR graph artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
