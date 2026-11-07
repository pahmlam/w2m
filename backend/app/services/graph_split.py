"""Subdivide metric road edges without introducing connections across physical roads."""

from math import ceil, fsum, isclose, isfinite

import networkx as nx
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring

from app.services.area import METRIC_CRS, WGS84_CRS
from app.services.graph_reverse_edges import identify_reverse_edges

CUT_TOLERANCE_METERS = 1e-8
BOUNDARY_TOLERANCE_METERS = 1e-7
# Leave enough arithmetic headroom to enforce the strict time cap after interpolation.
TIME_ROUNDOFF_FRACTION = 1e-12
_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)


def _boundary_distances(line: LineString, aoi: Polygon) -> list[float]:
    """Locate every boundary crossing, including repeated visits and boundary overlaps."""
    distances = []
    offset = 0.0
    for start, end in zip(line.coords, list(line.coords)[1:]):
        segment = LineString([start, end])
        intersection = segment.intersection(aoi.boundary)
        parts = [intersection]
        while parts:
            part = parts.pop()
            if part.is_empty:
                continue
            if hasattr(part, "geoms"):
                parts.extend(part.geoms)
            elif isinstance(part, Point):
                distances.append(offset + segment.project(part))
            elif isinstance(part, LineString):
                distances.extend(offset + segment.project(Point(coordinate))
                                 for coordinate in (part.coords[0], part.coords[-1]))
        offset += segment.length
    return distances


def _relation(geometry: Point | LineString, aoi: Polygon) -> str:
    point = geometry if isinstance(geometry, Point) else geometry.interpolate(0.5, normalized=True)
    if aoi.boundary.distance(point) <= BOUNDARY_TOLERANCE_METERS:
        return "boundary"
    return "inside" if aoi.covers(point) else "outside"


def split_graph_edges(
    graph: nx.MultiDiGraph, reverse_mapping: dict, aoi_meters: Polygon,
    max_edge_seconds: float = 60.0,
) -> tuple[nx.MultiDiGraph, list[dict]]:
    """Return a split copy and ordered parent-to-child edge lineage.

    Use common cuts for confirmed reverse pairs, based on the slower direction.
    New negative node IDs follow sorted source edge IDs. Original edge keys persist
    on children whose new endpoints make the full (u, v, key) IDs unique. Unpaired
    roads never share generated nodes. AOI crossings are cut even on short edges;
    aoi_relation records coverage only, not candidate eligibility.
    """
    if (isinstance(max_edge_seconds, bool) or not isfinite(max_edge_seconds)
            or max_edge_seconds <= 0):
        raise ValueError("max_edge_seconds must be finite and positive")
    if (
        not isinstance(aoi_meters, Polygon) or aoi_meters.is_empty
        or not aoi_meters.is_valid or not isfinite(aoi_meters.area) or aoi_meters.area <= 0
    ):
        raise ValueError("Expected a valid AOI Polygon in EPSG:32648")
    if identify_reverse_edges(graph) != reverse_mapping:
        raise ValueError("Reverse-edge mapping does not match the source graph")
    if any(item["reason"] in ("ambiguous", "unknown_oneway", "missing_or_invalid_osmid")
           for item in reverse_mapping["unpaired"]):
        raise ValueError("Unresolved reverse edges require review before splitting")
    if not nx.is_strongly_connected(graph):
        raise ValueError("Source graph must be strongly connected")
    for edge in graph.edges(keys=True):
        data = graph.edges[edge]
        for field in ("length", "length_m", "travel_time", "travel_time_seconds",
                      "estimated_speed_kmh"):
            value = data.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Invalid {field} for edge {edge}")
            if not isfinite(value) or value <= 0:
                raise ValueError(f"Invalid {field} for edge {edge}")
        if (
            data["travel_time"] != data["travel_time_seconds"]
            or not isclose(data["length_m"], data["geometry"].length, rel_tol=1e-9, abs_tol=1e-6)
            or data["length"] != data["length_m"]
        ):
            raise ValueError(f"Inconsistent geometry, length or time for edge {edge}")

    groups = [(tuple(pair["forward"]), tuple(pair["reverse"]))
              for pair in reverse_mapping["pairs"]]
    groups.extend((tuple(item["edge"]),) for item in reverse_mapping["unpaired"])
    groups.sort()
    result = graph.copy()
    lineage = []
    next_node_id = min(0, min(graph.nodes)) - 1
    for node, data in result.nodes(data=True):
        data["aoi_relation"] = _relation(Point(data["x"], data["y"]), aoi_meters)

    for group in groups:
        reference = graph.edges[group[0]]["geometry"]
        longest_seconds = max(graph.edges[edge]["travel_time_seconds"] for edge in group)
        count = (ceil(longest_seconds / (max_edge_seconds * (1 - TIME_ROUNDOFF_FRACTION)))
                 if longest_seconds > max_edge_seconds else 1)
        cuts = [reference.length * index / count for index in range(count + 1)]
        for distance in sorted(_boundary_distances(reference, aoi_meters)):
            if all(abs(distance - cut) > CUT_TOLERANCE_METERS for cut in cuts):
                cuts.append(distance)
        cuts.sort()
        if len(cuts) == 2:
            for edge in group:
                result.edges[edge]["aoi_relation"] = _relation(graph.edges[edge]["geometry"],
                                                               aoi_meters)
                lineage.append({"parent": list(edge), "children": [list(edge)]})
            continue
        if len(group) == 2 and not reference.equals_exact(
            LineString(list(graph.edges[group[1]]["geometry"].coords)[::-1]), 0,
        ):
            # Moving an approximate match onto the other line would alter its length and speed.
            raise ValueError(f"Split pair requires exactly reversed geometry: {group}")
        nodes = [group[0][0]]
        for distance in cuts[1:-1]:
            point = reference.interpolate(distance)
            lon, lat = _TO_WGS84.transform(point.x, point.y, errcheck=True)
            result.add_node(next_node_id, x=point.x, y=point.y, lon=lon, lat=lat,
                            generated_by="edge_split", aoi_relation=_relation(point, aoi_meters))
            nodes.append(next_node_id)
            next_node_id -= 1
        nodes.append(group[0][1])
        geometries = [substring(reference, start, end) for start, end in zip(cuts, cuts[1:])]
        for direction, edge in enumerate(group):
            source = graph.edges[edge]
            path_nodes = nodes if direction == 0 else nodes[::-1]
            pieces = geometries if direction == 0 else [
                LineString(list(piece.coords)[::-1]) for piece in geometries[::-1]
            ]
            result.remove_edge(*edge)
            children = []
            times = []
            for index, (start, end, piece) in enumerate(zip(path_nodes, path_nodes[1:], pieces)):
                if not isinstance(piece, LineString) or piece.length <= 0:
                    raise ValueError(f"Degenerate child geometry for edge {edge}")
                seconds = (source["travel_time_seconds"] * piece.length / source["geometry"].length
                           if index < len(pieces) - 1
                           else source["travel_time_seconds"] - fsum(times))
                if not 0 < seconds <= max_edge_seconds:
                    raise ValueError(f"Child time outside (0, max_edge_seconds] for edge {edge}")
                attributes = dict(source)
                attributes.update(geometry=piece, length=piece.length, length_m=piece.length,
                                  travel_time=seconds, travel_time_seconds=seconds,
                                  parent_u=edge[0], parent_v=edge[1], parent_key=edge[2],
                                  segment_index=index,
                                  aoi_relation=_relation(piece, aoi_meters))
                child = (start, end, edge[2])
                if result.has_edge(*child):
                    raise ValueError(f"Generated edge ID collision: {child}")
                result.add_edge(*child, **attributes)
                children.append(list(child))
                times.append(seconds)
            length_total = fsum(result.edges[tuple(child)]["length_m"] for child in children)
            if (
                not isclose(length_total, source["length_m"], rel_tol=1e-9, abs_tol=1e-6)
                or not isclose(fsum(times), source["travel_time_seconds"],
                               rel_tol=1e-12, abs_tol=1e-9)
            ):
                raise ValueError(f"Subdivision did not conserve length/time for edge {edge}")
            lineage.append({"parent": list(edge), "children": children})
    if not nx.is_strongly_connected(result):
        raise ValueError("Subdivision broke strong connectivity")
    result.graph["max_edge_seconds"] = max_edge_seconds
    return result, sorted(lineage, key=lambda item: item["parent"])
