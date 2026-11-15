"""Load the validated M1 graph for offline NetworkX reference work."""

import hashlib
import json
from dataclasses import dataclass
from importlib import import_module
from math import isfinite
from pathlib import Path

import networkx as nx
from shapely.geometry import Polygon

from app.services.area import METRIC_CRS, load_aoi
from app.services.graph_reverse_edges import identify_reverse_edges


@dataclass(frozen=True)
class ReferenceGraph:
    """Locally loaded graph and its verified support geometry and provenance."""

    graph: nx.MultiDiGraph
    aoi: Polygon
    reverse_mapping: dict
    graph_version: str
    weight_profile_version: str


def load_reference_graph(bundle_dir: Path) -> ReferenceGraph:
    """Read a validated bundle without downloading data or modifying artifact files."""
    metadata = json.loads((bundle_dir / "metadata.json").read_bytes())
    if metadata["stage"] != "csr" or metadata["crs"] != METRIC_CRS:
        raise ValueError("Expected a validated metric CSR bundle")
    for filename, field in (("graph.graphml", "graph_sha256"), ("aoi.geojson", "aoi_sha256"),
                            ("reverse_edges.json", "reverse_edges_sha256"),
                            ("validation.json", "validation_sha256")):
        with (bundle_dir / filename).open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != metadata[field]:
            raise ValueError(f"Bundle checksum mismatch: {filename}")
    report = json.loads((bundle_dir / "validation.json").read_bytes())
    if (report["status"] != "passed" or any(v != "passed" for v in report["checks"].values())
            or any(report[k] != metadata[k]
                   for k in ("graph_version", "weight_profile_version"))):
        raise ValueError("Bundle has no matching successful validation report")
    numeric = ("length_m", "estimated_speed_kmh", "travel_time_seconds", "travel_time")
    graph = import_module("osmnx").load_graphml(
        filepath=bundle_dir / "graph.graphml",
        node_dtypes={"lon": float, "lat": float,
                     **dict.fromkeys(("in_aoi", "is_candidate"),
                                     {"True": True, "False": False}.__getitem__)},
        edge_dtypes={**dict.fromkeys(numeric, float),
                     **dict.fromkeys(("parent_u", "parent_v", "parent_key", "segment_index"), int)},
    )
    if (str(graph.graph["crs"]) != METRIC_CRS or graph.graph.get("travel_mode") != "car"
            or graph.number_of_nodes() != metadata["node_count"]
            or graph.number_of_edges() != metadata["edge_count"]
            or any(graph.graph.get(k) != metadata[k]
                   for k in ("graph_version", "weight_profile_version"))
            or not nx.is_strongly_connected(graph)):
        raise ValueError("Reference graph does not match metadata or SCC")
    for _, _, data in graph.edges(data=True):
        if (any(not isfinite(data[k]) or data[k] <= 0 for k in numeric)
                or data["travel_time"] != data["travel_time_seconds"]):
            raise ValueError("Invalid reference edge weights")
    reverse = json.loads((bundle_dir / "reverse_edges.json").read_bytes())
    if identify_reverse_edges(graph) != reverse:
        raise ValueError("Reverse mapping does not match reference graph")
    return ReferenceGraph(nx.freeze(graph), load_aoi(bundle_dir / "aoi.geojson"), reverse,
                          metadata["graph_version"], metadata["weight_profile_version"])
