"""Pure geometric OWA scoring and deterministic decisecond ranking."""

from collections.abc import Sequence
from dataclasses import dataclass
from math import fsum, isfinite


def quantize_seconds(value: float) -> float:
    """Quantize seconds using the contract's round-half-to-even operation."""
    if isinstance(value, bool) or not isfinite(value) or value < 0:
        raise ValueError("Time must be finite and nonnegative")
    return round(10 * value) / 10


def owa_weights(phi: float, source_count: int) -> tuple[float, ...]:
    """Return positive geometric weights, largest for the slowest traveler."""
    if isinstance(phi, bool) or not isfinite(phi) or not 0 <= phi <= 1:
        raise ValueError("Phi must be finite and within [0, 1]")
    if type(source_count) is not int or source_count < 1:
        raise ValueError("Expected a positive integer source count")
    beta = 1 - 0.9 * phi
    raw = tuple(beta ** k for k in range(source_count))
    denominator = fsum(raw)
    weights = tuple(value / denominator for value in raw)
    if any(value <= 0 for value in weights):
        raise ValueError("Source count exceeds positive float64 weight precision")
    return weights


def _weighted_score(times: Sequence[float], weights: tuple[float, ...]) -> float:
    if not times or len(times) != len(weights):
        raise ValueError("Expected matching non-empty travel times and weights")
    if any(isinstance(t, bool) or not isfinite(t) or t < 0 for t in times):
        raise ValueError("Travel times must be finite and nonnegative")
    return fsum(w * t for w, t in zip(weights, sorted(times, reverse=True)))


def owa_score(times: Sequence[float], phi: float) -> float:
    """Evaluate raw OWA without quantization, for mathematical reference checks."""
    return _weighted_score(times, owa_weights(phi, len(times)))


@dataclass(frozen=True)
class ScoredCandidate:
    """Keep raw times for Pareto tie-breaking and quantized presentation separately."""

    node_id: int
    raw_times_seconds: tuple[float, ...]
    travel_times_seconds: tuple[float, ...]
    score: float
    max_time: float
    min_time: float
    difference: float
    avg_time: float

    @property
    def sort_key(self) -> tuple[float, float, float, tuple[float, ...], int]:
        """Break quantization ties using the raw sorted vector before node identity."""
        return (self.score, self.max_time, self.avg_time,
                tuple(sorted(self.raw_times_seconds, reverse=True)), self.node_id)


def score_candidate(
    node_id: int, times: tuple[float, ...], weights: tuple[float, ...],
) -> ScoredCandidate:
    """Compute production-style values using already prepared OWA weights."""
    if (not weights or any(not isfinite(w) or w <= 0 for w in weights)
            or abs(fsum(weights) - 1) > 1e-12
            or any(a < b for a, b in zip(weights, weights[1:]))):
        raise ValueError("Expected positive normalized descending OWA weights")
    quantized = tuple(quantize_seconds(value) for value in times)
    score = quantize_seconds(_weighted_score(quantized, weights))
    maximum, minimum = max(quantized), min(quantized)
    return ScoredCandidate(node_id, times, quantized, score, maximum, minimum,
                           quantize_seconds(maximum - minimum),
                           quantize_seconds(fsum(quantized) / len(quantized)))
