"""Filter directed road graphs and describe discarded geometry inside the AOI."""

import networkx as nx
from pyproj import CRS, Transformer
from shapely.geometry import Point, Polygon, mapping
from shapely.ops import transform

from app.services.area import METRIC_CRS, WGS84_CRS

_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)


def keep_largest_scc(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Return an independent SCC copy; ties choose the smallest integer node ID."""
    if not graph.is_directed() or not graph.is_multigraph() or not graph:
        raise ValueError("Expected a non-empty directed multigraph")
    if any(type(node) is not int for node in graph):
        raise ValueError("Graph node IDs must be integers")
    component = max(nx.strongly_connected_components(graph), key=lambda c: (len(c), -min(c)))
    return graph.subgraph(component).copy()


def removed_features_in_aoi(
    graph: nx.MultiDiGraph, retained: nx.MultiDiGraph, aoi_meters: Polygon,
) -> dict:
    """Export discarded nodes and clipped road portions in WGS84 for map review.

    Include edges crossing the AOI even if both endpoints lie outside it. Point-only
    touches are omitted from edge features; discarded boundary nodes are included.
    """
    if CRS.from_user_input(graph.graph.get("crs", "")) != CRS(METRIC_CRS):
        raise ValueError("Graph geometry must use EPSG:32648")
    features = []
    for node, data in sorted(graph.nodes(data=True)):
        if node in retained:
            continue
        point = Point(data["x"], data["y"])
        if aoi_meters.covers(point):
            features.append({
                "type": "Feature", "properties": {"kind": "node", "node_id": node},
                "geometry": mapping(transform(_TO_WGS84.transform, point)),
            })
    for source, target, key, data in sorted(graph.edges(keys=True, data=True)):
        if retained.has_edge(source, target, key):
            continue
        clipped = data["geometry"].intersection(aoi_meters)
        if clipped.is_empty or clipped.length == 0:
            continue
        features.append({
            "type": "Feature",
            "properties": {"kind": "edge", "source": source, "target": target, "key": key},
            "geometry": mapping(transform(_TO_WGS84.transform, clipped)),
        })
    return {"type": "FeatureCollection", "features": features}
