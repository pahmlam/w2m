"""Raw mathematical invariants are separate from quantized candidate ranking."""

from math import fsum

import numpy as np
import pytest

from app.services.objective import owa_score, owa_weights, quantize_seconds, score_candidate


@pytest.mark.parametrize("phi,expected,quantized", [(0, 10.750, 10.8),
                                                   (.5, 11.263, 11.3), (1, 11.890, 11.9)])
def test_tc03_raw_and_quantized(phi: float, expected: float, quantized: float) -> None:
    times = (10., 12., 11., 10.)
    assert owa_score(times, phi) == pytest.approx(expected, abs=.001)
    assert score_candidate(1, times, owa_weights(phi, 4)).score == quantized


def test_tc08_ten_thousand_pareto_pairs_eleven_phi_values() -> None:
    rng = np.random.default_rng(20261115)
    for _ in range(10000):
        u = tuple(rng.uniform(0, 5000, 4))
        v = tuple(np.array(u) + rng.uniform(.01, 100, 4))
        for phi in np.linspace(0, 1, 11):
            assert owa_score(u, float(phi)) < owa_score(v, float(phi))


def test_tc09_fairness_and_tc10_bounds_translation() -> None:
    rng = np.random.default_rng(20261115)
    for count in (1, 2, 3, 4, 7):
        for _ in range(100):
            times = tuple(rng.uniform(0, 5000, count))
            for phi in (0., .5, 1.):
                weights = owa_weights(phi, count)
                assert fsum(weights) == pytest.approx(1)
                assert all(w > 0 for w in weights)
                assert list(weights) == sorted(weights, reverse=True)
                score = owa_score(times, phi)
                assert fsum(times)/count - 1e-9 <= score <= max(times) + 1e-9
                assert owa_score(tuple(t + 37 for t in times), phi) == pytest.approx(score + 37)
                if phi == 0:
                    assert score == pytest.approx(fsum(times)/count)
    for phi in (0., .5, 1.):
        assert owa_score((11., 20., 30., 39.), phi) <= owa_score((10., 20., 30., 40.), phi)
        if phi > 0:
            assert owa_score((11., 20., 30., 39.), phi) < owa_score((10., 20., 30., 40.), phi)


@pytest.mark.parametrize("value,expected", [(.05, 0), (.15, .2), (.25, .2), (.35, .4),
                                           (.149999, .1), (.150001, .2)])
def test_half_even(value: float, expected: float) -> None:
    assert quantize_seconds(value) == expected


@pytest.mark.parametrize("times,phi", [((), .5), ((-1.,), .5), ((float('nan'),), .5),
                                      ((float('inf'),), .5), ((1.,), -1), ((1.,), True)])
def test_invalid_objective_inputs(times: tuple, phi: float) -> None:
    with pytest.raises(ValueError):
        owa_score(times, phi)


def test_raw_vector_breaks_quantization_tie_before_unfavorable_id() -> None:
    weights = owa_weights(.5, 4)
    better = score_candidate(2, (100., 100., 100., 100.), weights)
    worse = score_candidate(1, (100.01, 100., 100., 100.), weights)
    assert better.score == worse.score
    assert better.sort_key < worse.sort_key
