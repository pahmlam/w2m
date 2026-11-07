"""Identify unambiguous reverse road edges without changing graph data."""

from math import hypot, isfinite

import networkx as nx
from pyproj import CRS
from shapely.geometry import LineString

from app.services.area import METRIC_CRS
from app.services.graph_geometry import ENDPOINT_TOLERANCE_METERS

EdgeId = tuple[int, int, int]


def _osm_ids(value: object) -> tuple[int, ...] | None:
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values or any(type(item) is not int or item <= 0 for item in values):
        return None
    return tuple(sorted(set(values)))


def _structure_tag(data: dict, tag: str) -> tuple[str, ...]:
    default = "0" if tag == "layer" else ""
    value = data.get(tag, default)
    values = value if isinstance(value, (list, tuple)) else [value]
    normalized = {str(item).strip().lower() for item in values}
    if tag in ("bridge", "tunnel"):
        normalized = {"" if item in ("no", "false", "0", "none", "") else item
                      for item in normalized}
    return tuple(sorted(normalized))


def identify_reverse_edges(graph: nx.MultiDiGraph) -> dict:
    """Return deterministic pairs and reasons for every unpaired directed edge.

    Pair only mutual unique matches: reversed endpoints, equal OSM way ID sets,
    explicit two-way flags, equal structure tags, and reversed coordinate sequences
    within the geometry normalization tolerance. Weights and edge keys do not decide
    physical road identity. Ambiguous parallels remain unpaired for manual review.
    """
    if not graph.is_directed() or not graph.is_multigraph() or not graph.number_of_edges():
        raise ValueError("Expected a non-empty directed multigraph")
    if CRS.from_user_input(graph.graph.get("crs", "")) != CRS(METRIC_CRS):
        raise ValueError("Graph geometry must use EPSG:32648")
    if any(type(node) is not int for node in graph):
        raise ValueError("Graph node IDs must be integers")
    edges = list(graph.edges(keys=True))
    if any(type(key) is not int for _, _, key in edges):
        raise ValueError("Graph edge keys must be integers")
    edges.sort()
    candidates: dict[EdgeId, list[EdgeId]] = {}
    reasons: dict[EdgeId, str] = {}
    osm_ids = {}
    structures = {}
    for edge in edges:
        source, target, _ = edge
        data = graph.edges[edge]
        line = data.get("geometry")
        if (
            not isinstance(line, LineString) or line.is_empty or not line.is_valid
            or line.has_z or not isfinite(line.length) or line.length <= 0
            or any(not isfinite(value) for coordinate in line.coords for value in coordinate)
        ):
            raise ValueError(f"Invalid geometry for edge {edge}")
        for node, coordinate in ((source, line.coords[0]), (target, line.coords[-1])):
            position = graph.nodes[node]
            x, y = position["x"], position["y"]
            if (
                not isfinite(x) or not isfinite(y)
                or hypot(coordinate[0] - x, coordinate[1] - y) > ENDPOINT_TOLERANCE_METERS
            ):
                raise ValueError(f"Geometry is not oriented source to target for edge {edge}")
        osm_ids[edge] = _osm_ids(data.get("osmid"))
        structures[edge] = tuple(_structure_tag(data, tag)
                                 for tag in ("layer", "level", "bridge", "tunnel"))
        if source == target:
            reasons[edge] = "self_loop"
        elif data.get("oneway") is True:
            reasons[edge] = "oneway"
        elif data.get("oneway") is not False:
            reasons[edge] = "unknown_oneway"
        elif osm_ids[edge] is None:
            reasons[edge] = "missing_or_invalid_osmid"
        else:
            candidates[edge] = []

    for edge in candidates:
        source, target, _ = edge
        if source > target:
            continue
        for key in graph.get_edge_data(target, source, default={}):
            reverse = (target, source, key)
            if (
                reverse in candidates and osm_ids[edge] == osm_ids[reverse]
                and structures[edge] == structures[reverse]
                and graph.edges[edge]["geometry"].equals_exact(
                    LineString(list(graph.edges[reverse]["geometry"].coords)[::-1]),
                    ENDPOINT_TOLERANCE_METERS,
                )
            ):
                candidates[edge].append(reverse)
                candidates[reverse].append(edge)

    pairs = []
    unpaired = []
    for edge in edges:
        matches = sorted(candidates.get(edge, []))
        if len(matches) == 1 and candidates[matches[0]] == [edge]:
            if edge < matches[0]:
                pairs.append({"forward": list(edge), "reverse": list(matches[0])})
            continue
        reason = reasons.get(edge)
        if reason is None:
            reason = "ambiguous" if matches else "no_compatible_reverse"
        unpaired.append({"edge": list(edge), "reason": reason,
                         "candidates": [list(match) for match in matches]})
    return {"pairs": pairs, "unpaired": unpaired}
