"""Filter and rank every eligible persistent node using existing routing tables."""

from dataclasses import dataclass
from math import isfinite

from app.services.objective import ScoredCandidate, owa_weights, score_candidate
from app.services.shortest_path import RoutingResult


@dataclass(frozen=True)
class CandidateRanking:
    """Complete ordered candidates; spacing and API rank assignment happen later."""

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
