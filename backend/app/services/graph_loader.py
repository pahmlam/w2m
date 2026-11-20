"""Load a validated M1 bundle for CSR runtime or NetworkX reference work."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from importlib import import_module
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING
from xml.etree import ElementTree

import numpy as np
from scipy.sparse import csr_matrix, load_npz
from shapely.geometry import Polygon

from app.services.area import METRIC_CRS, load_aoi

if TYPE_CHECKING:
    import networkx as nx

    from app.services.graph_reverse_edges import EdgeId

_GRAPHML_NAMESPACE = "{http://graphml.graphdrawing.org/xmlns}"


@dataclass(frozen=True)
class CSRGraph:
    """Shared routing data with immutable buffers and request-local array views."""

    _csr: tuple[np.ndarray, np.ndarray, np.ndarray]
    _mappings: Mapping[str, np.ndarray]
    _geometry: Mapping[str, np.ndarray]
    _edge_seconds: np.ndarray
    node_indices: Mapping[int, int]
    edge_indices: Mapping[EdgeId, int]
    reverse_edge_indices: Mapping[int, int]
    aoi: Polygon
    graph_version: str
    weight_profile_version: str
    source_date: str

    @property
    def csr(self) -> csr_matrix:
        """Return a fresh SciPy wrapper over the shared read-only buffers."""
        size = len(self.node_indices)
        return csr_matrix(self._csr, shape=(size, size), copy=False)

    @property
    def mappings(self) -> Mapping[str, np.ndarray]:
        """Expose node and edge tables without sharing mutable array headers."""
        return MappingProxyType({name: array.view() for name, array in self._mappings.items()})

    @property
    def geometry(self) -> Mapping[str, np.ndarray]:
        """Expose packed coordinates and offsets for all original directed edges."""
        return MappingProxyType({name: array.view() for name, array in self._geometry.items()})

    def edge_seconds(self, edge_index: int) -> float:
        """Return the full travel time of an original directed edge."""
        return float(self._edge_seconds[edge_index])


def _verify_checksum(path: Path, expected: object) -> None:
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != expected:
        raise ValueError(f"Bundle checksum mismatch: {path.name}")


def _validated_metadata(bundle_dir: Path, files: Mapping[str, str]) -> dict:
    metadata = json.loads((bundle_dir / "metadata.json").read_bytes())
    if (not isinstance(metadata, dict) or metadata.get("stage") != "csr"
            or metadata.get("crs") != METRIC_CRS):
        raise ValueError("Expected a validated metric CSR bundle")
    for filename, field in {
        "aoi.geojson": "aoi_sha256", "validation.json": "validation_sha256", **files,
    }.items():
        _verify_checksum(bundle_dir / filename, metadata.get(field))
    report = json.loads((bundle_dir / "validation.json").read_bytes())
    versions = ("graph_version", "weight_profile_version")
    checks = report.get("checks") if isinstance(report, dict) else None
    if (not isinstance(checks, dict) or not checks or report.get("status") != "passed"
            or any(value != "passed" for value in checks.values())
            or any(not isinstance(metadata.get(key), str) or not metadata[key].strip()
                   or report.get(key) != metadata[key] for key in versions)):
        raise ValueError("Bundle has no matching successful validation report")
    return metadata


def _immutable(array: np.ndarray) -> np.ndarray:
    # An owning NumPy array can have its WRITEABLE flag reset. Bytes cannot.
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def _load_arrays(
    path: Path, fields: Mapping[str, tuple[type, tuple[int, ...]]],
) -> Mapping[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != fields.keys():
            raise ValueError(f"Unexpected array fields: {path.name}")
        arrays = {}
        for name, (dtype, shape) in fields.items():
            array = archive[name]
            if (array.dtype != dtype or array.ndim != len(shape)
                    or any(wanted != -1 and actual != wanted
                           for actual, wanted in zip(array.shape, shape, strict=True))):
                raise ValueError(f"Invalid array shape or dtype: {name}")
            arrays[name] = _immutable(array)
    return MappingProxyType(arrays)


def _load_parallel_weights(
    path: Path, edge_indices: Mapping[EdgeId, int], weights: np.ndarray,
) -> None:
    """Recover weights omitted by CSR from the existing validated GraphML."""
    tag = _GRAPHML_NAMESPACE
    weight_key = None
    with path.open("rb") as stream:
        for _, element in ElementTree.iterparse(stream):
            if (element.tag == tag + "key" and element.get("for") == "edge"
                    and element.get("attr.name") == "travel_time"):
                weight_key = element.get("id")
            elif element.tag == tag + "edge":
                edge = (int(element.attrib["source"]), int(element.attrib["target"]),
                        int(element.attrib["id"]))
                index = edge_indices[edge]
                if np.isnan(weights[index]):
                    value = element.findtext(f"{tag}data[@key='{weight_key}']")
                    if value is None:
                        raise ValueError("Missing travel time for an original edge")
                    weights[index] = float(value)
                element.clear()
            elif element.tag == tag + "node":
                element.clear()
    if not np.all(np.isfinite(weights) & (weights > 0)):
        raise ValueError("Invalid travel times for original edges")


def _load_reverse_indices(path: Path, edge_indices: Mapping[EdgeId, int]) -> Mapping[int, int]:
    reverse: dict[int, int] = {}
    for pair in json.loads(path.read_bytes())["pairs"]:
        forward, backward = tuple(pair["forward"]), tuple(pair["reverse"])
        if (forward not in edge_indices or backward not in edge_indices
                or forward[:2] != backward[:2][::-1] or forward[0] == forward[1]):
            raise ValueError("Invalid reverse edge pair")
        a, b = edge_indices[forward], edge_indices[backward]
        if a in reverse or b in reverse:
            raise ValueError("Duplicate reverse edge pair")
        reverse[a], reverse[b] = b, a
    return MappingProxyType(reverse)


def load_csr_graph(bundle_dir: Path) -> CSRGraph:
    """Read the validated offline CSR bundle without importing NetworkX or OSMnx."""
    metadata = _validated_metadata(bundle_dir, {
        "csr.npz": "csr_sha256",
        "mappings.npz": "mappings_sha256",
        "geometry.npz": "geometry_sha256",
        "reverse_edges.json": "reverse_edges_sha256",
    })
    if metadata.get("geometry_crs") != METRIC_CRS or metadata.get("travel_mode") != "car":
        raise ValueError("Expected metric geometry and car travel mode")
    source_date = metadata.get("source_date")
    if not isinstance(source_date, str):
        raise ValueError("Expected a source date in graph metadata")
    date.fromisoformat(source_date)
    nodes, edges, arcs = (
        metadata.get(key) for key in ("node_count", "edge_count", "csr_arc_count")
    )
    if any(type(count) is not int or count <= 0 for count in (nodes, edges, arcs)) or arcs > edges:
        raise ValueError("Invalid graph counts")
    csr = load_npz(bundle_dir / "csr.npz")
    if csr.format != "csr" or csr.shape != (nodes, nodes) or csr.dtype != np.float64:
        raise ValueError("Expected square float64 CSR weights for all graph nodes")
    csr.check_format(full_check=True)
    if (csr.nnz != arcs or not csr.has_canonical_format
            or not np.all(np.isfinite(csr.data) & (csr.data > 0))):
        raise ValueError("Invalid CSR arcs or weights")

    mappings = _load_arrays(bundle_dir / "mappings.npz", {
        "node_ids": (np.int64, (nodes,)),
        "node_xy": (np.float64, (nodes, 2)),
        "node_lonlat": (np.float64, (nodes, 2)),
        "in_aoi": (np.bool_, (nodes,)),
        "is_candidate": (np.bool_, (nodes,)),
        "edge_ids": (np.int64, (edges, 3)),
        "arc_edge_indices": (np.int64, (arcs,)),
    })
    geometry = _load_arrays(bundle_dir / "geometry.npz", {
        "coordinates": (np.float64, (-1, 2)),
        "offsets": (np.int64, (edges + 1,)),
    })
    node_ids = mappings["node_ids"]
    edge_ids = mappings["edge_ids"]
    arc_indices = mappings["arc_edge_indices"]
    lonlat = mappings["node_lonlat"]
    candidates = mappings["is_candidate"]
    if (np.any(node_ids[1:] <= node_ids[:-1]) or not np.isfinite(mappings["node_xy"]).all()
            or not np.all(np.abs(lonlat) <= (180, 90))
            or np.any(candidates & ~mappings["in_aoi"])
            or candidates.sum() != metadata.get("candidate_node_count")):
        raise ValueError("Invalid CSR node mappings")
    if (np.any(arc_indices < 0) or np.any(arc_indices >= edges)
            or not np.all(np.isin(edge_ids[:, :2], node_ids))):
        raise ValueError("Invalid CSR edge mappings")
    arc_endpoints = edge_ids[arc_indices, :2]
    if (not np.array_equal(arc_endpoints[:, 0], np.repeat(node_ids, np.diff(csr.indptr)))
            or not np.array_equal(arc_endpoints[:, 1], node_ids[csr.indices])):
        raise ValueError("CSR arc endpoints disagree with edge mappings")
    offsets = geometry["offsets"]
    coordinates = geometry["coordinates"]
    if (offsets[0] != 0 or offsets[-1] != len(coordinates)
            or np.any(offsets < 0) or np.any(offsets > len(coordinates))
            or np.any(np.diff(offsets) < 2) or not np.isfinite(coordinates).all()):
        raise ValueError("Invalid packed edge geometry")

    edge_indices = MappingProxyType({tuple(edge): i for i, edge in enumerate(edge_ids.tolist())})
    if len(edge_indices) != edges:
        raise ValueError("Duplicate original edge IDs")
    edge_seconds = np.full(edges, np.nan)
    edge_seconds[arc_indices] = csr.data
    if arcs < edges:
        path = bundle_dir / "graph.graphml"
        _verify_checksum(path, metadata.get("graph_sha256"))
        _load_parallel_weights(path, edge_indices, edge_seconds)

    return CSRGraph(
        _csr=(_immutable(csr.data), _immutable(csr.indices), _immutable(csr.indptr)),
        _mappings=mappings,
        _geometry=geometry,
        _edge_seconds=_immutable(edge_seconds),
        node_indices=MappingProxyType({node_id: i for i, node_id in enumerate(node_ids.tolist())}),
        edge_indices=edge_indices,
        reverse_edge_indices=_load_reverse_indices(bundle_dir / "reverse_edges.json", edge_indices),
        aoi=load_aoi(bundle_dir / "aoi.geojson"),
        graph_version=metadata["graph_version"],
        weight_profile_version=metadata["weight_profile_version"],
        source_date=source_date,
    )


@dataclass(frozen=True)
class ReferenceGraph:
    """Locally loaded graph and its verified support geometry and provenance."""

    graph: "nx.MultiDiGraph"
    aoi: Polygon
    reverse_mapping: dict
    graph_version: str
    weight_profile_version: str


def load_reference_graph(bundle_dir: Path) -> ReferenceGraph:
    """Read a validated bundle without downloading data or modifying artifact files."""
    import networkx as nx

    from app.services.graph_reverse_edges import identify_reverse_edges

    metadata = _validated_metadata(bundle_dir, {
        "graph.graphml": "graph_sha256", "reverse_edges.json": "reverse_edges_sha256",
    })
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
