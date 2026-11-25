"""Snap validated origins to directed roads without mutating shared graph data."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Literal

import numpy as np
from pyproj import Transformer
from shapely import Point, STRtree
from shapely.geometry import LineString

from app.config.settings import Settings
from app.models.requests import MeetingRequest, Origin
from app.services.area import METRIC_CRS, WGS84_CRS, covers_location
from app.services.graph_loader import CSRGraph

if TYPE_CHECKING:
    from app.services.graph_loader import ReferenceGraph
    from app.services.graph_reverse_edges import EdgeId

ENDPOINT_ROUNDOFF_METERS = 1e-7
_TO_METERS = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
_TO_WGS84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)


class SnapError(ValueError):
    """Expose a domain error code without including input coordinates."""

    def __init__(self, error_code: Literal["OUT_OF_COVERAGE", "SNAP_FAILED"]) -> None:
        self.error_code = error_code
        super().__init__("Vị trí ngoài phạm vi hỗ trợ." if error_code == "OUT_OF_COVERAGE"
                         else "Không tìm thấy đường trong bán kính cho phép.")


@dataclass(frozen=True)
class SnapResult:
    """Unquantized source information for the subsequent request overlay."""

    origin_id: str
    input_lonlat: tuple[float, float]
    edge_id: EdgeId
    reverse_edge_id: EdgeId | None
    theta: float
    snapped_xy: tuple[float, float]
    snapped_lonlat: tuple[float, float]
    snap_distance_m: float
    access_seconds: float
    source_node_id: int | None


class CoordinateSnapper[GraphT: (ReferenceGraph, CSRGraph)]:
    """Build a reusable index of all physical roads, including non-candidate roads."""

    def __init__(self, reference: GraphT, settings: Settings) -> None:
        self.reference = reference
        self.snap_max_m = settings.snap_max_m
        self.access_speed_mps = settings.access_speed_mps
        if isinstance(reference, CSRGraph):
            edge_ids = [tuple(row) for row in reference.mappings["edge_ids"].tolist()]
            geometry = reference.geometry
            coords, offsets = geometry["coordinates"], geometry["offsets"]
            self.reverse = {edge_ids[a]: edge_ids[b]
                            for a, b in reference.reverse_edge_indices.items()}
            roads = []
            for edge in sorted(reference.edge_indices):
                opposite = self.reverse.get(edge)
                if opposite is not None and edge > opposite:
                    continue
                i = reference.edge_indices[edge]
                points = coords[offsets[i]:offsets[i + 1]]
                if opposite is not None:
                    j = reference.edge_indices[opposite]
                    if not np.array_equal(points, coords[offsets[j]:offsets[j + 1]][::-1]):
                        raise ValueError("Paired snapping roads require exactly reversed geometry")
                roads.append((edge, LineString(points)))
        else:
            self.reverse = {}
            for pair in reference.reverse_mapping["pairs"]:
                forward, reverse = tuple(pair["forward"]), tuple(pair["reverse"])
                line = reference.graph.edges[forward]["geometry"]
                other = reference.graph.edges[reverse]["geometry"]
                if not line.equals_exact(LineString(list(other.coords)[::-1]), 0):
                    raise ValueError("Paired snapping roads require exactly reversed geometry")
                self.reverse[forward] = reverse
                self.reverse[reverse] = forward
            roads = [(edge, reference.graph.edges[edge]["geometry"])
                     for edge in sorted(reference.graph.edges(keys=True))
                     if edge not in self.reverse or edge < self.reverse[edge]]
        self.edge_ids = tuple(edge for edge, _ in roads)
        self._tree_indices = {edge: i for i, edge in enumerate(self.edge_ids)}
        tree_started = perf_counter()
        self.tree = STRtree([line for _, line in roads])
        self.tree_build_ms = (perf_counter() - tree_started) * 1000

    def snap_origins(self, request: MeetingRequest) -> tuple[SnapResult, ...]:
        """Check every origin's coverage before snapping; preserve input order and duplicates."""
        for origin in request.origins:
            if not covers_location(self.reference.aoi, latitude=origin.lat, longitude=origin.lon):
                raise SnapError("OUT_OF_COVERAGE")
        return tuple(self._snap_origin(origin) for origin in request.origins)

    def _snap_origin(self, origin: Origin) -> SnapResult:
        point = Point(*_TO_METERS.transform(origin.lon, origin.lat, errcheck=True))
        edge, along, projected, distance = self._project(point)
        line = self.tree.geometries[self._tree_indices[edge]]
        node_id = None
        # WGS84 roundtrips of generated M1 nodes can differ by a few nanometers.
        endpoint = 0 if along <= line.length / 2 else 1
        endpoint_along = endpoint * line.length
        if abs(along - endpoint_along) <= ENDPOINT_ROUNDOFF_METERS:
            candidate = Point(line.coords[0 if endpoint == 0 else -1])
            candidate_distance = point.distance(candidate)
            if candidate_distance <= self.snap_max_m:
                along, projected, distance = endpoint_along, candidate, candidate_distance
                node_id = edge[endpoint]
        return SnapResult(
            origin.id, (origin.lon, origin.lat), edge, self.reverse.get(edge), along / line.length,
            (projected.x, projected.y),
            _TO_WGS84.transform(projected.x, projected.y, errcheck=True),
            distance, distance / self.access_speed_mps, node_id,
        )

    def _project(self, point: Point) -> tuple[EdgeId, float, Point, float]:
        candidates = self.tree.query(point, predicate="dwithin", distance=self.snap_max_m)
        if not len(candidates):
            raise SnapError("SNAP_FAILED")
        index = min(candidates, key=lambda i: (
            self.tree.geometries[i].distance(point), self.edge_ids[i],
        ))
        line = self.tree.geometries[index]
        along = line.project(point)
        projected = line.interpolate(along)
        return self.edge_ids[index], along, projected, point.distance(projected)
