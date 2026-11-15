"""Filter and rank every eligible persistent node using existing routing tables."""

from dataclasses import dataclass
from math import hypot, isfinite

from app.models.requests import Location
from app.models.responses import MeetingResult
from app.services.objective import ScoredCandidate, owa_weights, score_candidate
from app.services.route_builder import build_route
from app.services.shortest_path import RoutingResult


@dataclass(frozen=True)
class CandidateRanking:
    """Complete ordered candidates, retained for selection with different spacing."""

    routing: RoutingResult
    origin_ids: tuple[str, ...]
    phi: float
    max_travel_seconds: float
    weights: tuple[float, ...]
    candidates: tuple[ScoredCandidate, ...]


def rank_candidates(
    routing: RoutingResult, *, phi: float, max_travel_seconds: float,
) -> CandidateRanking:
    """Reuse raw distances without rerouting or accepting an uncomputed cutoff."""
    sources = routing.sources
    weights = owa_weights(phi, len(sources))
    ids = tuple(source.snap.origin_id for source in sources)
    if len(set(ids)) != len(ids):
        raise ValueError("Source IDs must be unique")
    if (isinstance(max_travel_seconds, bool) or not isfinite(max_travel_seconds)
            or max_travel_seconds < 0):
        raise ValueError("Travel limit must be finite and nonnegative")
    reference = routing.overlay.reference
    if (routing.graph_version != reference.graph_version
            or routing.weight_profile_version != reference.weight_profile_version):
        raise ValueError("Routing versions do not match the reference")
    for source in sources:
        access, cutoff = source.snap.access_seconds, source.network_cutoff_seconds
        if not isfinite(access) or access < 0 or not isfinite(cutoff):
            raise ValueError("Invalid source access time or computed cutoff")
        if max_travel_seconds - access > cutoff:
            raise ValueError("Requested limit exceeds computed routing coverage")
    candidates = []
    for node, data in reference.graph.nodes(data=True):
        if type(data.get("in_aoi")) is not bool or type(data.get("is_candidate")) is not bool:
            raise ValueError("Expected validated boolean candidate flags")
        if not data["in_aoi"] or not data["is_candidate"]:
            continue
        if any(node not in source.paths.distances_seconds for source in sources):
            continue
        network_times = tuple(source.paths.distances_seconds[node] for source in sources)
        if any(value < 0 for value in network_times):
            raise ValueError("Network travel times cannot be negative")
        raw_times = tuple(source.snap.access_seconds + value
                          for source, value in zip(sources, network_times))
        if any(not isfinite(value) or value > max_travel_seconds for value in raw_times):
            continue
        candidates.append(score_candidate(node, raw_times, weights))
    candidates.sort(key=lambda candidate: candidate.sort_key)
    return CandidateRanking(routing, ids, phi, max_travel_seconds, weights, tuple(candidates))


def select_candidates(
    ranking: CandidateRanking, *, top_k: int, min_spacing_meters: float,
) -> tuple[ScoredCandidate, ...]:
    """Greedily keep ranked nodes at least the requested metric distance apart."""
    if type(top_k) is not int or not 1 <= top_k <= 5:
        raise ValueError("Top k must be an integer within [1, 5]")
    if (isinstance(min_spacing_meters, bool) or not isfinite(min_spacing_meters)
            or not 0 <= min_spacing_meters <= 5000):
        raise ValueError("Spacing must be finite and within [0, 5000] meters")
    nodes = ranking.routing.overlay.reference.graph.nodes
    selected: list[ScoredCandidate] = []
    for candidate in ranking.candidates:
        point = nodes[candidate.node_id]
        if all(hypot(point["x"] - nodes[other.node_id]["x"],
                     point["y"] - nodes[other.node_id]["y"]) >= min_spacing_meters
               for other in selected):
            selected.append(candidate)
            if len(selected) == top_k:
                break
    return tuple(selected)


def build_meeting_results(
    ranking: CandidateRanking, *, top_k: int, min_spacing_meters: float,
) -> list[MeetingResult]:
    """Select first, then build routes from the exact trees used for ranking."""
    selected = select_candidates(ranking, top_k=top_k, min_spacing_meters=min_spacing_meters)
    routing = ranking.routing
    results = []
    for rank, candidate in enumerate(selected, start=1):
        node = routing.overlay.reference.graph.nodes[candidate.node_id]
        routes = {source.snap.origin_id: build_route(routing.overlay, source, candidate.node_id)
                  for source in routing.sources}
        travel_times = dict(zip(ranking.origin_ids, candidate.travel_times_seconds))
        if any(route.duration_seconds != travel_times[label] for label, route in routes.items()):
            raise ValueError("Route duration does not match ranked travel time")
        results.append(MeetingResult(
            rank=rank, node_id=candidate.node_id,
            location=Location(lat=node["lat"], lon=node["lon"]),
            travel_times=travel_times, max_time=candidate.max_time, min_time=candidate.min_time,
            difference=candidate.difference, avg_time=candidate.avg_time, score=candidate.score,
            routes=routes,
        ))
    return results
