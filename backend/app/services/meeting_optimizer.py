"""Filter and rank every eligible persistent node using existing routing tables."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from math import fsum, hypot, isfinite
from time import perf_counter_ns
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from app.models.requests import Location, ObjectiveType
from app.models.responses import MeetingResult
from app.services.csr_shortest_path import CSRRoutingResult
from app.services.objective import ScoredCandidate, owa_weights, quantize_seconds, score_candidate
from app.services.route_builder import build_csr_route, build_route

if TYPE_CHECKING:
    from app.services.shortest_path import RoutingResult

PARETO_SWEEP_COUNT = 16
PARETO_TREE_LEAF_SIZE = 24


@dataclass(frozen=True, eq=False)
class _CSRScoredCandidates:
    node_ids: np.ndarray
    raw_times: np.ndarray
    travel_times: np.ndarray
    scores: np.ndarray
    averages: np.ndarray
    order: np.ndarray
    differences: np.ndarray | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, _CSRScoredCandidates):
            return NotImplemented
        return all(np.array_equal(left[self.order], right[other.order]) for left, right in (
            (self.node_ids, other.node_ids), (self.raw_times, other.raw_times),
            (self.travel_times, other.travel_times), (self.scores, other.scores),
            (self.averages, other.averages),
        )) and (
            self.differences is None and other.differences is None
            or self.differences is not None and other.differences is not None
            and np.array_equal(self.differences[self.order], other.differences[other.order])
        )

    def candidate(self, row: int | np.integer) -> ScoredCandidate:
        times = tuple(self.travel_times[row].tolist())
        maximum, minimum = max(times), min(times)
        return ScoredCandidate(
            int(self.node_ids[row]), tuple(self.raw_times[row].tolist()), times,
            float(self.scores[row]), maximum, minimum,
            (float(self.differences[row]) if self.differences is not None
             else quantize_seconds(maximum - minimum)),
            float(self.averages[row]),
        )


@dataclass(frozen=True)
class CandidateRanking[RoutingT: (RoutingResult, CSRRoutingResult)]:
    """Complete ordered candidates, retained for selection with different spacing."""

    routing: RoutingT
    origin_ids: tuple[str, ...]
    phi: float
    max_travel_seconds: float
    weights: tuple[float, ...]
    _scored: tuple[ScoredCandidate, ...] | _CSRScoredCandidates = field(repr=False)
    scan_ms: float = field(default=0.0, compare=False)
    rank_ms: float = field(default=0.0, compare=False)

    @property
    def candidates(self) -> tuple[ScoredCandidate, ...]:
        """Materialize the complete ranking for callers that need to inspect it."""
        if isinstance(self._scored, _CSRScoredCandidates):
            return tuple(self._scored.candidate(row) for row in self._scored.order)
        return self._scored


def _candidate_network_times(
    routing: RoutingResult,
) -> Iterator[tuple[int, tuple[float, ...]]]:
    distances = tuple(source.paths.distances_seconds for source in routing.sources)
    for node, data in routing.overlay.reference.graph.nodes(data=True):
        if type(data.get("in_aoi")) is not bool or type(data.get("is_candidate")) is not bool:
            raise ValueError("Expected validated boolean candidate flags")
        if data["in_aoi"] and data["is_candidate"] and all(node in table for table in distances):
            yield node, tuple(table[node] for table in distances)


def _scan_csr_candidates(
    routing: CSRRoutingResult, access_times: tuple[float, ...],
    network_limits: tuple[float, ...], travel_limit: float, weights: tuple[float, ...],
    phi: float,
) -> tuple[_CSRScoredCandidates, int]:
    mappings = routing.graph.mappings
    indices = np.flatnonzero(mappings["in_aoi"] & mappings["is_candidate"])
    network_times = np.column_stack([
        source.distances_seconds[indices] for source in routing.sources
    ])
    if np.any(network_times < 0):
        raise ValueError("Network travel times cannot be negative")

    raw_times = network_times + access_times
    valid = np.all(np.isfinite(raw_times) & (raw_times <= travel_limit), axis=1)
    if travel_limit < routing.max_travel_seconds:
        # Match a fresh Dijkstra cutoff even when adding access rounds down to the limit.
        valid &= np.all(network_times <= network_limits, axis=1)
    node_ids = mappings["node_ids"][indices[valid]]
    raw_times = raw_times[valid]
    if not weights:
        return _score_csr_mean_spread(node_ids, raw_times, phi)

    travel_times = (np.rint(10 * raw_times) + 0.0) / 10
    sorted_raw = np.sort(raw_times, axis=1)[:, ::-1]
    sorted_times = np.rint(10 * sorted_raw) / 10
    # Keep the scalar scorer's fsum before rounding, including half-decisecond ties.
    scores = np.fromiter(
        map(fsum, (sorted_times * weights).tolist()), dtype=np.float64, count=len(node_ids),
    )
    averages = np.fromiter(
        map(fsum, travel_times.tolist()), dtype=np.float64, count=len(node_ids),
    ) / len(weights)
    scores = np.rint(10 * scores) / 10
    averages = np.rint(10 * averages) / 10

    rank_started = perf_counter_ns()
    # lexsort takes the primary key last, including the slowest raw time within ties.
    order = np.lexsort((node_ids, *sorted_raw.T[::-1], averages, sorted_times[:, 0], scores))
    scored = _CSRScoredCandidates(node_ids, raw_times, travel_times, scores, averages, order)
    return scored, rank_started


def _pareto_rows(times: np.ndarray) -> np.ndarray:
    # Low sums discard many candidates early. Lexicographic ties ensure every
    # possible dominator precedes its target, even when their float sums tie.
    pending = np.lexsort((*times.T[::-1], times.sum(axis=1)))
    kept = []
    for _ in range(PARETO_SWEEP_COUNT):
        if not pending.size:
            return np.asarray(kept, dtype=np.intp)
        row = pending[0]
        kept.append(row)
        pending = pending[1:]
        pending = pending[~_dominated_by(times[pending], times[row])]
    if not pending.size:
        return np.asarray(kept, dtype=np.intp)
    return np.concatenate((kept, pending[_pareto_tree_mask(times[pending])]))


def _dominated_by(times: np.ndarray, lower: np.ndarray) -> np.ndarray:
    return np.all(times >= lower, axis=1) & np.any(times > lower, axis=1)


def _pareto_tree_mask(times: np.ndarray) -> np.ndarray:
    """Search remaining vectors for strict dominators using subtree bounds."""
    tree = cKDTree(times, leafsize=PARETO_TREE_LEAF_SIZE)
    alive = np.ones(len(times), dtype=bool)

    def visit(node, rows: np.ndarray) -> None:
        rows = rows[alive[rows]]
        if not rows.size:
            return
        points = node.data_points
        # A dominator in this subtree must fit below the query on every axis.
        rows = rows[np.all(times[rows] >= points.min(axis=0), axis=1)]
        if not rows.size:
            return
        if node.split_dim < 0:
            # An unsplittable leaf can contain many copies of one vector.
            if len(points) > PARETO_TREE_LEAF_SIZE:
                points = np.unique(points, axis=0)
            for point in points:
                dominated = _dominated_by(times[rows], point)
                alive[rows[dominated]] = False
                rows = rows[~dominated]
                if not rows.size:
                    return
            return

        # A query strictly above the upper bound is dominated by every point in the subtree.
        dominated = _dominated_by(times[rows], points.max(axis=0))
        alive[rows[dominated]] = False
        rows = rows[~dominated]
        visit(node.lesser, rows)
        visit(node.greater, rows)

    visit(tree.tree, np.arange(len(times)))
    return alive


def _score_csr_mean_spread(
    node_ids: np.ndarray, raw_times: np.ndarray, phi: float,
) -> tuple[_CSRScoredCandidates, int]:
    keep = _pareto_rows(raw_times)
    node_ids, raw_times = node_ids[keep], raw_times[keep]
    sorted_raw = np.sort(raw_times, axis=1)[:, ::-1]
    averages = np.fromiter(map(fsum, raw_times.tolist()), dtype=np.float64,
                           count=len(node_ids)) / raw_times.shape[1]
    differences = sorted_raw[:, 0] - sorted_raw[:, -1]
    scores = (1 - phi) * averages + phi * differences
    rank_started = perf_counter_ns()
    order = np.lexsort((node_ids, *sorted_raw.T[::-1], differences, averages, scores))
    return _CSRScoredCandidates(
        node_ids, raw_times, np.rint(10 * raw_times) / 10, np.rint(10 * scores) / 10,
        np.rint(10 * averages) / 10, order, np.rint(10 * differences) / 10,
    ), rank_started


def rank_mean_spread_reference(
    candidates: list[tuple[int, tuple[float, ...]]], phi: float,
) -> tuple[ScoredCandidate, ...]:
    """Rank eligible raw times with a direct pairwise Pareto reference."""
    frontier: list[tuple[float, ...]] = []
    ordered = []
    # Every possible dominator precedes its target when ordered by raw time vector.
    for node, times in sorted(candidates, key=lambda item: item[1]):
        if any(other != times and all(a <= b for a, b in zip(other, times, strict=True))
               for other in frontier):
            continue
        if not frontier or frontier[-1] != times:
            frontier.append(times)
        average = fsum(times) / len(times)
        minimum, maximum = min(times), max(times)
        difference = maximum - minimum
        score = (1 - phi) * average + phi * difference
        candidate = ScoredCandidate(
            node, times, tuple(map(quantize_seconds, times)), quantize_seconds(score),
            quantize_seconds(maximum), quantize_seconds(minimum), quantize_seconds(difference),
            quantize_seconds(average),
        )
        key = (score, average, difference, tuple(sorted(times, reverse=True)), node)
        ordered.append((key, candidate))
    return tuple(candidate for _, candidate in sorted(ordered, key=lambda item: item[0]))


def rank_candidates[RoutingT: (RoutingResult, CSRRoutingResult)](
    routing: RoutingT, *, phi: float, max_travel_seconds: float,
    objective_type: ObjectiveType = "owa_geometric",
) -> CandidateRanking[RoutingT]:
    """Reuse raw distances without rerouting or accepting an uncomputed cutoff."""
    sources = routing.sources
    if objective_type == "mean_spread_v1":
        if isinstance(phi, bool) or not isfinite(phi) or not 0 <= phi <= 1 or not sources:
            raise ValueError("Expected phi within [0, 1] and at least one source")
        weights = ()
    else:
        weights = owa_weights(phi, len(sources))
    ids = tuple(source.snap.origin_id for source in sources)
    if len(set(ids)) != len(ids):
        raise ValueError("Source IDs must be unique")
    if (isinstance(max_travel_seconds, bool) or not isfinite(max_travel_seconds)
            or max_travel_seconds < 0):
        raise ValueError("Travel limit must be finite and nonnegative")
    if not isinstance(routing, CSRRoutingResult):
        reference = routing.overlay.reference
        if (routing.graph_version != reference.graph_version
                or routing.weight_profile_version != reference.weight_profile_version):
            raise ValueError("Routing versions do not match the reference")
    access_times = tuple(source.snap.access_seconds for source in sources)
    network_limits = tuple(max_travel_seconds - access for access in access_times)
    for access, limit, source in zip(access_times, network_limits, sources, strict=True):
        cutoff = source.network_cutoff_seconds
        if not isfinite(access) or access < 0 or not isfinite(cutoff):
            raise ValueError("Invalid source access time or computed cutoff")
        if limit > cutoff:
            raise ValueError("Requested limit exceeds computed routing coverage")
    scan_start = perf_counter_ns()
    if isinstance(routing, CSRRoutingResult):
        scored, rank_start = _scan_csr_candidates(
            routing, access_times, network_limits, max_travel_seconds, weights, phi,
        )
        return CandidateRanking(
            routing, ids, phi, max_travel_seconds, weights, scored,
            (rank_start - scan_start) / 1e6, (perf_counter_ns() - rank_start) / 1e6,
        )

    eligible = []
    for node, network_times in _candidate_network_times(routing):
        if any(value < 0 for value in network_times):
            raise ValueError("Network travel times cannot be negative")
        raw_times = tuple(access + value
                          for access, value in zip(access_times, network_times, strict=True))
        if any(not isfinite(value) or value > max_travel_seconds for value in raw_times):
            continue
        if not weights and any(value > limit for value, limit in zip(
            network_times, network_limits, strict=True,
        )):
            continue
        eligible.append((node, raw_times))
    if weights:
        candidates = [score_candidate(node, raw_times, weights) for node, raw_times in eligible]
    rank_start = perf_counter_ns()
    if weights:
        ordered = tuple(sorted(candidates, key=lambda candidate: candidate.sort_key))
    else:
        ordered = rank_mean_spread_reference(eligible, phi)
    return CandidateRanking(
        routing, ids, phi, max_travel_seconds, weights, ordered,
        (rank_start - scan_start) / 1e6, (perf_counter_ns() - rank_start) / 1e6,
    )


def select_candidates(
    ranking: CandidateRanking[RoutingResult] | CandidateRanking[CSRRoutingResult],
    *, top_k: int, min_spacing_meters: float,
) -> tuple[ScoredCandidate, ...]:
    """Greedily keep ranked nodes at least the requested metric distance apart."""
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("Top k must be an integer within [1, 5]")
    if (isinstance(min_spacing_meters, bool) or not isfinite(min_spacing_meters)
            or not 0 <= min_spacing_meters <= 5000):
        raise ValueError("Spacing must be finite and within [0, 5000] meters")
    routing = ranking.routing
    scored = ranking._scored
    if isinstance(scored, _CSRScoredCandidates):
        assert isinstance(routing, CSRRoutingResult)
        node_xy = routing.graph.mappings["node_xy"]
        node_indices = routing.graph.node_indices
        rows = scored.order
        node_ids = scored.node_ids[rows]
    else:
        assert not isinstance(routing, CSRRoutingResult)
        nodes = routing.overlay.reference.graph.nodes
        rows = range(len(scored))
        node_ids = (candidate.node_id for candidate in scored)
    selected: list[ScoredCandidate] = []
    selected_xy: list[tuple[float, float]] = []
    for row, node_id in zip(rows, node_ids, strict=True):
        if isinstance(scored, _CSRScoredCandidates):
            x, y = node_xy[node_indices[node_id]]
        else:
            point = nodes[node_id]
            x, y = point["x"], point["y"]
        if all(hypot(x - other_x, y - other_y) >= min_spacing_meters
               for other_x, other_y in selected_xy):
            selected.append(scored.candidate(row) if isinstance(scored, _CSRScoredCandidates)
                            else scored[row])
            selected_xy.append((x, y))
            if len(selected) == top_k:
                break
    return tuple(selected)


def build_meeting_results(
    ranking: CandidateRanking[RoutingResult] | CandidateRanking[CSRRoutingResult],
    *, top_k: int, min_spacing_meters: float,
) -> list[MeetingResult]:
    """Select first, then build routes from the exact trees used for ranking."""
    selected = select_candidates(ranking, top_k=top_k, min_spacing_meters=min_spacing_meters)
    return build_selected_meeting_results(ranking, selected)


def build_selected_meeting_results(
    ranking: CandidateRanking[RoutingResult] | CandidateRanking[CSRRoutingResult],
    selected: tuple[ScoredCandidate, ...],
) -> list[MeetingResult]:
    """Build the response entries for the candidates already selected."""
    routing = ranking.routing
    results = []
    for rank, candidate in enumerate(selected, start=1):
        target = candidate.node_id
        if isinstance(routing, CSRRoutingResult):
            lon, lat = routing.graph.mappings["node_lonlat"][routing.graph.node_indices[target]]
            routes = {label: build_csr_route(routing, label, target)
                      for label in ranking.origin_ids}
        else:
            node = routing.overlay.reference.graph.nodes[target]
            lon, lat = node["lon"], node["lat"]
            routes = {source.snap.origin_id: build_route(routing.overlay, source, target)
                      for source in routing.sources}
        travel_times = dict(zip(ranking.origin_ids, candidate.travel_times_seconds))
        if any(route.duration_seconds != travel_times[label] for label, route in routes.items()):
            raise ValueError("Route duration does not match ranked travel time")
        results.append(MeetingResult(
            rank=rank, node_id=candidate.node_id,
            location=Location(lat=lat, lon=lon),
            travel_times=travel_times, max_time=candidate.max_time, min_time=candidate.min_time,
            difference=candidate.difference, avg_time=candidate.avg_time, score=candidate.score,
            routes=routes,
        ))
    return results
