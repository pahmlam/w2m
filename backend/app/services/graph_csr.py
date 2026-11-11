"""Build deterministic directed CSR weights and mappings from an offline road graph."""

from math import hypot, isfinite

import networkx as nx
import numpy as np
from pyproj import CRS
from scipy.sparse import csr_matrix
from shapely.geometry import LineString

from app.services.area import METRIC_CRS
from app.services.graph_geometry import ENDPOINT_TOLERANCE_METERS


def build_graph_csr(
    graph: nx.MultiDiGraph,
) -> tuple[csr_matrix, dict[str, np.ndarray], dict[str, np.ndarray]]:
    """Return CSR, node/edge mappings and packed geometry, without modifying the graph.

    Each CSR data offset maps to one row in edge_ids. Geometry includes every
    directed edge, including parallel edges omitted from shortest-path weights,
    so a later snapping index can still use their distinct physical geometries.
    """
    if not graph.is_directed() or not graph.is_multigraph() or not graph.number_of_edges():
        raise ValueError("Expected a non-empty directed multigraph")
    if CRS.from_user_input(graph.graph.get("crs", "")) != CRS(METRIC_CRS):
        raise ValueError("Graph geometry must use EPSG:32648")
    edge_ids = list(graph.edges(keys=True))
    if any(type(value) is not int for edge in edge_ids for value in edge):
        raise ValueError("Node IDs and edge keys must be integers")
    if any(type(node) is not int for node in graph):
        raise ValueError("Node IDs must be integers")
    edge_ids.sort()
    node_ids = sorted(graph.nodes)
    node_indices = {node: index for index, node in enumerate(node_ids)}
    edge_indices = {edge: index for index, edge in enumerate(edge_ids)}
    node_xy = []
    node_lonlat = []
    in_aoi = []
    is_candidate = []
    for node in node_ids:
        data = graph.nodes[node]
        coordinates = [data.get(field) for field in ("x", "y", "lon", "lat")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not isfinite(value) for value in coordinates):
            raise ValueError(f"Invalid coordinates for node {node}")
        if not -180 <= coordinates[2] <= 180 or not -90 <= coordinates[3] <= 90:
            raise ValueError(f"Invalid WGS84 coordinates for node {node}")
        if any(type(data.get(field)) is not bool for field in ("in_aoi", "is_candidate")):
            raise ValueError(f"Expected boolean candidate flags for node {node}")
        if data["is_candidate"] and not data["in_aoi"]:
            raise ValueError(f"Candidate outside AOI: {node}")
        node_xy.append(coordinates[:2])
        node_lonlat.append(coordinates[2:])
        in_aoi.append(data["in_aoi"])
        is_candidate.append(data["is_candidate"])

    geometry_coordinates = []
    geometry_offsets = [0]
    for edge in edge_ids:
        data = graph.edges[edge]
        seconds = data.get("travel_time")
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not isfinite(seconds) or seconds <= 0
                or data.get("travel_time_seconds") != seconds):
            raise ValueError(f"Invalid or inconsistent travel time for edge {edge}")
        line = data.get("geometry")
        if (not isinstance(line, LineString) or line.is_empty or not line.is_valid
                or line.has_z or not isfinite(line.length) or line.length <= 0
                or any(not isfinite(value) for point in line.coords for value in point)):
            raise ValueError(f"Invalid geometry for edge {edge}")
        for node, point in ((edge[0], line.coords[0]), (edge[1], line.coords[-1])):
            x, y = node_xy[node_indices[node]]
            if hypot(point[0] - x, point[1] - y) > ENDPOINT_TOLERANCE_METERS:
                raise ValueError(f"Geometry is not oriented source to target for edge {edge}")
        geometry_coordinates.extend(line.coords)
        geometry_offsets.append(len(geometry_coordinates))

    weights = []
    targets = []
    indptr = [0]
    arc_edge_indices = []
    for source in node_ids:
        for target in sorted(graph[source]):
            key = min(graph[source][target], key=lambda key: (
                graph.edges[source, target, key]["travel_time"], key,
            ))
            weights.append(graph.edges[source, target, key]["travel_time"])
            targets.append(node_indices[target])
            arc_edge_indices.append(edge_indices[source, target, key])
        indptr.append(len(weights))
    # Construct from row pointers directly to avoid summing parallel-edge weights.
    csr = csr_matrix((np.asarray(weights, dtype=np.float64),
                      np.asarray(targets, dtype=np.int64),
                      np.asarray(indptr, dtype=np.int64)),
                     shape=(len(node_ids), len(node_ids)))
    mappings = {
        "node_ids": np.asarray(node_ids, dtype=np.int64),
        "node_xy": np.asarray(node_xy, dtype=np.float64),
        "node_lonlat": np.asarray(node_lonlat, dtype=np.float64),
        "in_aoi": np.asarray(in_aoi, dtype=np.bool_),
        "is_candidate": np.asarray(is_candidate, dtype=np.bool_),
        "edge_ids": np.asarray(edge_ids, dtype=np.int64),
        "arc_edge_indices": np.asarray(arc_edge_indices, dtype=np.int64),
    }
    geometry = {
        "coordinates": np.asarray(geometry_coordinates, dtype=np.float64),
        "offsets": np.asarray(geometry_offsets, dtype=np.int64),
    }
    return csr, mappings, geometry
