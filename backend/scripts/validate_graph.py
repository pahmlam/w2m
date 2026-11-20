"""Validate an offline CSR bundle and publish complete metadata with its report."""

import argparse
import json
import platform
import shutil
from datetime import UTC, date, datetime
from importlib import import_module
from importlib.metadata import version
from math import fsum, isclose, isfinite
from pathlib import Path
from tempfile import TemporaryDirectory

import networkx as nx
import numpy as np
from pyproj import Transformer
from scipy.sparse import csr_matrix, load_npz
from scipy.sparse.csgraph import dijkstra
from shapely import Point, transform

from app.services.area import METRIC_CRS, WGS84_CRS, load_aoi
from app.services.csr_route_edges import csr_arc_offset
from app.services.graph_csr import build_graph_csr
from app.services.graph_split import BOUNDARY_TOLERANCE_METERS
from app.services.graph_weights import apply_speed_profile, load_speed_profile
from scripts.download_osm import _sha256
from scripts.prepare_graph_candidates import FLAG_NAMES, SPLIT_FILES, mark_candidate_nodes
from scripts.prepare_graph_csr import VALIDATION_SEED, VALIDATION_SOURCE_COUNT
from scripts.prepare_graph_split import SPLIT_GRAPHML_DTYPES

ROUTES_PER_SOURCE = 10


def validate_sample_routes(
    graph: nx.MultiDiGraph, csr: csr_matrix, mappings: dict[str, np.ndarray],
) -> dict:
    """Compare all distances for seeded sources and reconstruct sample CSR routes."""
    rng = np.random.default_rng(VALIDATION_SEED)
    sources = rng.choice(len(graph), size=min(VALIDATION_SOURCE_COUNT, len(graph)), replace=False)
    samples = []
    max_error = 0.0
    node_ids = mappings["node_ids"]
    for source in sources:
        distances, predecessors = dijkstra(
            csr, directed=True, indices=int(source), return_predecessors=True,
        )
        expected = nx.single_source_dijkstra_path_length(
            graph, int(node_ids[source]), weight="travel_time",
        )
        reference = np.array([expected.get(int(node), np.inf) for node in node_ids])
        if not np.allclose(distances, reference, rtol=1e-12, atol=1e-9):
            raise ValueError("CSR distances differ from NetworkX")
        finite = np.isfinite(reference)
        max_error = max(max_error, float(np.max(np.abs(distances[finite] - reference[finite]))))
        targets = rng.choice(np.flatnonzero(finite),
                             size=min(ROUTES_PER_SOURCE, int(finite.sum())), replace=False)
        for target in targets:
            current = int(target)
            edges = []
            while current != source:
                previous = int(predecessors[current])
                if previous < 0 or len(edges) >= len(graph):
                    raise ValueError("Invalid CSR predecessor chain")
                offset = csr_arc_offset(csr, previous, current)
                edge = tuple(int(value) for value in mappings["edge_ids"][
                    mappings["arc_edge_indices"][offset]
                ])
                if edge[:2] != (int(node_ids[previous]), int(node_ids[current])):
                    raise ValueError("CSR arc maps to a different directed edge")
                best_key = min(graph[edge[0]][edge[1]], key=lambda key: (
                    graph.edges[edge[0], edge[1], key]["travel_time"], key,
                ))
                if edge[2] != best_key:
                    raise ValueError("CSR route chose an incorrect parallel edge")
                edges.append(edge)
                current = previous
            edges.reverse()
            seconds = fsum(graph.edges[edge]["travel_time"] for edge in edges)
            error = abs(seconds - distances[target])
            if error > 1e-6 * distances[target] + 1e-3:
                raise ValueError("Route edge weights differ from Dijkstra duration")
            samples.append({
                "source_node_id": int(node_ids[source]), "target_node_id": int(node_ids[target]),
                "edge_ids": edges, "network_seconds": float(distances[target]),
                "edge_time_sum_seconds": seconds, "error_seconds": float(error),
                "distance_meters": fsum(graph.edges[edge]["length_m"] for edge in edges),
            })
    return {
        "seed": VALIDATION_SEED, "source_count": len(sources),
        "distance_comparison_count": len(sources) * len(graph),
        "max_distance_error_seconds": max_error, "route_count": len(samples), "routes": samples,
    }


def validate_graph(csr_dir: Path, aoi_metadata_path: Path, output_dir: Path) -> Path:
    """Publish a validated copy with metadata 10.4, preserving source bundle bytes."""
    if output_dir.exists() or output_dir.resolve().is_relative_to(csr_dir.resolve()):
        raise FileExistsError(f"Choose a new output directory outside the input: {output_dir}")
    metadata_path = csr_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    if not isinstance(metadata, dict) or metadata.get("stage") != "csr":
        raise ValueError("Expected a CSR input artifact")
    files = {
        **SPLIT_FILES, "excluded_node_ids.json": "excluded_node_ids_sha256",
        "csr.npz": "csr_sha256", "mappings.npz": "mappings_sha256",
        "geometry.npz": "geometry_sha256",
    }
    for filename, field in files.items():
        if _sha256(csr_dir / filename) != metadata[field]:
            raise ValueError(f"Input checksum mismatch: {filename}")
    area_bytes = aoi_metadata_path.read_bytes()
    area = json.loads(area_bytes)
    if (not isinstance(area, dict)
            or not isinstance(area.get("area_id"), str) or not area["area_id"].strip()
            or isinstance(area.get("buffer_m"), bool)
            or not isinstance(area.get("buffer_m"), (int, float))
            or not isfinite(area["buffer_m"]) or area["buffer_m"] <= 0
            or area.get("geometry_crs") != WGS84_CRS
            or area.get("measurement_crs") != METRIC_CRS
            or area.get("boundary_rule") != "covers"):
        raise ValueError("Invalid AOI metadata")
    aoi = load_aoi(csr_dir / "aoi.geojson")
    if not aoi.equals(load_aoi(aoi_metadata_path.parent / "aoi.geojson")):
        raise ValueError("AOI metadata belongs to a different polygon")
    projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    metric_aoi = transform(aoi, projector.transform, interleaved=False)
    if not isclose(metric_aoi.area, area["aoi_area_m2"], rel_tol=1e-9, abs_tol=1e-6):
        raise ValueError("AOI area does not match metadata")
    ox = import_module("osmnx")
    graph = ox.load_graphml(
        filepath=csr_dir / "graph.graphml",
        node_dtypes={**SPLIT_GRAPHML_DTYPES["node_dtypes"],
                     **dict.fromkeys(FLAG_NAMES, {"True": True, "False": False}.__getitem__)},
        edge_dtypes=SPLIT_GRAPHML_DTYPES["edge_dtypes"],
    )
    if (graph.graph.get("graph_version") != metadata["graph_version"]
            or graph.graph.get("weight_profile_version") != metadata["weight_profile_version"]
            or graph.graph.get("travel_mode") != metadata["travel_mode"]
            or str(graph.graph.get("crs")) != METRIC_CRS
            or metadata["crs"] != METRIC_CRS or not nx.is_strongly_connected(graph)):
        raise ValueError("Graph version, profile, CRS or SCC is inconsistent")
    flags = [(d["in_aoi"], d["is_candidate"]) for _, d in graph.nodes(data=True)]
    excluded = json.loads((csr_dir / "excluded_node_ids.json").read_bytes())
    if not isinstance(excluded, list):
        raise ValueError("Exclusion list must be a JSON array")
    mark_candidate_nodes(graph, excluded)
    if flags != [(d["in_aoi"], d["is_candidate"]) for _, d in graph.nodes(data=True)]:
        raise ValueError("Candidate flags do not match AOI relations and exclusions")
    expected_csr, expected_mappings, expected_geometry = build_graph_csr(graph)
    for node, data in graph.nodes(data=True):
        point = Point(data["x"], data["y"])
        covered = (metric_aoi.covers(point)
                   or metric_aoi.boundary.distance(point) <= BOUNDARY_TOLERANCE_METERS)
        if data["in_aoi"] != covered:
            raise ValueError(f"Node coverage disagrees with AOI geometry: {node}")
    csr = load_npz(csr_dir / "csr.npz")
    if (csr.format != "csr" or csr.shape != expected_csr.shape or csr.dtype != np.float64
            or any(not np.array_equal(getattr(csr, name), getattr(expected_csr, name))
                   for name in ("data", "indices", "indptr"))):
        raise ValueError("CSR does not match the reference graph")
    for filename, arrays in (("mappings.npz", expected_mappings),
                             ("geometry.npz", expected_geometry)):
        with np.load(csr_dir / filename, allow_pickle=False) as actual:
            if set(actual.files) != arrays.keys() or any(
                actual[name].dtype != value.dtype or not np.array_equal(actual[name], value)
                for name, value in arrays.items()
            ):
                raise ValueError(f"Mapping does not match reference graph: {filename}")
    profile = load_speed_profile(csr_dir / "speed_profile.yaml")
    if profile.version != metadata["weight_profile_version"]:
        raise ValueError("Speed profile version mismatch")
    weighted = apply_speed_profile(graph, profile)
    for edge in graph.edges(keys=True):
        actual = graph.edges[edge]
        if (not isclose(actual["length_m"], actual["geometry"].length, rel_tol=1e-9, abs_tol=1e-6)
                or actual["length"] != actual["length_m"]
                or not isclose(actual["estimated_speed_kmh"],
                               weighted.edges[edge]["estimated_speed_kmh"],
                               rel_tol=1e-12, abs_tol=1e-9)
                or not isclose(actual["travel_time"], weighted.edges[edge]["travel_time"],
                               rel_tol=1e-12, abs_tol=1e-9)):
            raise ValueError(f"Inconsistent geometry, units, speed or weight for edge {edge}")
    times = np.array([d["travel_time"] for _, _, d in graph.edges(data=True)])
    cap = metadata["max_edge_seconds"]
    if isinstance(cap, bool) or not isfinite(cap) or cap <= 0 or times.max() > cap:
        raise ValueError("Invalid maximum edge time or edge exceeds configured cap")
    routes = validate_sample_routes(graph, csr, expected_mappings)
    completed = dict(metadata, area_id=area["area_id"], buffer_m=area["buffer_m"],
                     tau_p50=float(np.percentile(times, 50)),
                     tau_p99=float(np.percentile(times, 99)), tau_max=float(times.max()))
    for field, value in (("node_count", len(graph)), ("edge_count", graph.number_of_edges()),
                         ("csr_arc_count", csr.nnz),
                         ("candidate_node_count", int(expected_mappings["is_candidate"].sum()))):
        if metadata[field] != value:
            raise ValueError(f"Metadata count mismatch: {field}")
    for field in ("source", "graph_version", "weight_profile_version"):
        if not isinstance(completed[field], str) or not completed[field].strip():
            raise ValueError(f"Invalid metadata field: {field}")
    date.fromisoformat(completed["source_date"])
    datetime.fromisoformat(completed["build_date"])
    for field in ("scc_removed_nodes", "scc_removed_edges"):
        if type(completed[field]) is not int or completed[field] < 0:
            raise ValueError(f"Invalid SCC removal count: {field}")
    implementation_files = (
        "scripts/validate_graph.py", "app/services/graph_csr.py", "app/services/graph_weights.py",
        "scripts/prepare_graph_candidates.py", "app/services/area.py", "scripts/download_osm.py",
    )
    report = {
        "schema_version": 1, "status": "passed", "validated_at": datetime.now(UTC).isoformat(),
        "graph_version": metadata["graph_version"], "weight_profile_version": profile.version,
        "source_metadata_sha256": _sha256(metadata_path),
        "implementation_sha256": {
            name: _sha256(Path(__file__).parents[1] / name) for name in implementation_files
        },
        "environment": {
            "python": platform.python_version(), "platform": platform.platform(),
            "libraries": {name: version(name) for name in (
                "networkx", "numpy", "scipy", "shapely", "pyproj", "osmnx",
            )},
        },
        "checks": {name: "passed" for name in (
            "checksums", "csr_weights_and_mappings", "geometry_and_units", "speed_profile",
            "scc", "candidate_flags", "aoi_geometry", "metadata",
            "edge_time_cap", "networkx_distances", "sample_routes",
        )},
        "node_count": len(graph), "edge_count": graph.number_of_edges(), "csr_arc_count": csr.nnz,
        "candidate_node_count": metadata["candidate_node_count"],
        "tau_p50": completed["tau_p50"], "tau_p99": completed["tau_p99"],
        "tau_max": completed["tau_max"],
        "default_speed_edge_count": weighted.graph["default_speed_edge_count"],
        "maxspeed_capped_edge_count": weighted.graph["maxspeed_capped_edge_count"],
        "scc_count": nx.number_strongly_connected_components(graph),
        "scc_removed_nodes": completed["scc_removed_nodes"],
        "scc_removed_edges": completed["scc_removed_edges"],
        "input_file_bytes": {name: (csr_dir / name).stat().st_size for name in files},
        "csr_memory_bytes": sum(getattr(csr, name).nbytes
                                for name in ("data", "indices", "indptr")),
        "routes": routes,
        "pending_acceptance": ["AOI and SCC map review", "TC-15", "TC-16", "ETA calibration"],
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-validation-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for filename in files:
            shutil.copyfile(csr_dir / filename, staging / filename)
            if _sha256(staging / filename) != metadata[files[filename]]:
                raise ValueError(f"Copied artifact checksum mismatch: {filename}")
        (staging / "aoi.metadata.json").write_bytes(area_bytes)
        (staging / "validation.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        completed.update(validation_sha256=_sha256(staging / "validation.json"),
                         aoi_metadata_sha256=_sha256(staging / "aoi.metadata.json"))
        (staging / "metadata.json").write_text(
            json.dumps(completed, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Validate a local CSR artifact and enrich its metadata using matching AOI data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csr-dir", type=Path, required=True)
    parser.add_argument("--aoi-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        output = validate_graph(args.csr_dir, args.aoi_metadata, args.output_dir)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Validated graph artifact: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
