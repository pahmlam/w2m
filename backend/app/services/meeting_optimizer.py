"""Filter and rank every eligible persistent node using existing routing tables."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from math import hypot, isfinite
from time import perf_counter_ns
from typing import TYPE_CHECKING

import numpy as np

from app.models.requests import Location
from app.models.responses import MeetingResult
from app.services.csr_shortest_path import CSRRoutingResult
from app.services.objective import ScoredCandidate, owa_weights, score_candidate
from app.services.route_builder import build_csr_route, build_route

if TYPE_CHECKING:
    from app.services.shortest_path import RoutingResult


@dataclass(frozen=True)
class CandidateRanking[RoutingT: (RoutingResult, CSRRoutingResult)]:
    """Complete ordered candidates, retained for selection with different spacing."""

    routing: RoutingT
    origin_ids: tuple[str, ...]
    phi: float
    max_travel_seconds: float
    weights: tuple[float, ...]
    candidates: tuple[ScoredCandidate, ...]
    scan_ms: float = field(default=0.0, compare=False)
    rank_ms: float = field(default=0.0, compare=False)


def _candidate_network_times(
    routing: RoutingResult | CSRRoutingResult,
) -> Iterator[tuple[int, tuple[float, ...]]]:
    if isinstance(routing, CSRRoutingResult):
        mappings = routing.graph.mappings
        node_ids = mappings["node_ids"]
        distances = tuple(source.distances_seconds for source in routing.sources)
        for index in np.flatnonzero(mappings["in_aoi"] & mappings["is_candidate"]):
            yield int(node_ids[index]), tuple(float(table[index]) for table in distances)
        return

    distances = tuple(source.paths.distances_seconds for source in routing.sources)
    for node, data in routing.overlay.reference.graph.nodes(data=True):
        if type(data.get("in_aoi")) is not bool or type(data.get("is_candidate")) is not bool:
            raise ValueError("Expected validated boolean candidate flags")
        if data["in_aoi"] and data["is_candidate"] and all(node in table for table in distances):
            yield node, tuple(table[node] for table in distances)


def rank_candidates[RoutingT: (RoutingResult, CSRRoutingResult)](
    routing: RoutingT, *, phi: float, max_travel_seconds: float,
) -> CandidateRanking[RoutingT]:
    """Reuse raw distances without rerouting or accepting an uncomputed cutoff."""
    sources = routing.sources
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
    reduced_csr_cutoff = (
        isinstance(routing, CSRRoutingResult) and max_travel_seconds < routing.max_travel_seconds
    )
    scan_start = perf_counter_ns()
    candidates = []
    for node, network_times in _candidate_network_times(routing):
        if any(value < 0 for value in network_times):
            raise ValueError("Network travel times cannot be negative")
        # Match the fresh search's network cutoff at floating-point boundaries.
        if reduced_csr_cutoff and any(
            value > limit for value, limit in zip(network_times, network_limits, strict=True)
        ):
            continue
        raw_times = tuple(access + value
                          for access, value in zip(access_times, network_times, strict=True))
        if any(not isfinite(value) or value > max_travel_seconds for value in raw_times):
            continue
        candidates.append(score_candidate(node, raw_times, weights))
    rank_start = perf_counter_ns()
    candidates.sort(key=lambda candidate: candidate.sort_key)
    ordered = tuple(candidates)
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
    if isinstance(routing, CSRRoutingResult):
        node_xy = routing.graph.mappings["node_xy"]
        node_indices = routing.graph.node_indices
    else:
        nodes = routing.overlay.reference.graph.nodes
    selected: list[ScoredCandidate] = []
    selected_xy: list[tuple[float, float]] = []
    for candidate in ranking.candidates:
        if isinstance(routing, CSRRoutingResult):
            x, y = node_xy[node_indices[candidate.node_id]]
        else:
            point = nodes[candidate.node_id]
            x, y = point["x"], point["y"]
        if all(hypot(x - other_x, y - other_y) >= min_spacing_meters
               for other_x, other_y in selected_xy):
            selected.append(candidate)
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
