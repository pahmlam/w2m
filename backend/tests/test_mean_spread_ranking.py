"""Verify the P3.1 ranking against its scalar reference."""

from math import fsum

import numpy as np

from app.services.meeting_optimizer import _score_csr_mean_spread, rank_mean_spread_reference


def test_p3_f01_ranks_a_tradeoff_at_all_slider_steps() -> None:
    first = (495.7, 141.6, 294.7, 516.6)
    dominated = (536.1, 376.5, 507.7, 530.9)
    balanced = (536.1, 376.5, 507.7, 510.9)
    times = [first, dominated, balanced]
    ids = np.array([1, 2, 3])
    previous_average = 0.0
    previous_spread = float("inf")
    for step in range(11):
        phi = step / 10
        expected = rank_mean_spread_reference(list(zip(ids.tolist(), times, strict=True)), phi)
        scored, _ = _score_csr_mean_spread(ids, np.asarray(times), phi)
        actual = tuple(scored.candidate(row) for row in scored.order)
        assert actual == expected
        assert [result.node_id for result in actual] == ([1, 3] if step < 4 else [3, 1])
        winner = actual[0].raw_times_seconds
        average = fsum(winner) / len(winner)
        spread = max(winner) - min(winner)
        assert previous_average <= average and spread <= previous_spread
        previous_average, previous_spread = average, spread


def test_p3_f02_f03_keep_equal_vectors_and_exclude_raw_dominance() -> None:
    ids = np.array([3, 1, 4, 2, 0])
    times = np.array([
        (10, 20, 30, 40), (10.04, 20, 30, 40), (10, 20, 20, 20),
        (10, 20, 20, 20), (9.96, 20, 30, 40),
    ])
    for phi in (0, 0.5, 1):
        scored, _ = _score_csr_mean_spread(ids, times, phi)
        assert [int(scored.node_ids[row]) for row in scored.order] == [2, 4, 0]


def test_batch_matches_reference_when_candidates_and_people_are_reordered() -> None:
    rng = np.random.default_rng(20261126)
    times = rng.integers(0, 1000, size=(400, 4)) / 200
    ids = np.arange(len(times))
    shuffled = rng.permutation(len(times))
    permutation = [3, 0, 2, 1]
    rows = [tuple(row) for row in times.tolist()]
    expected_ids = {node for node, row in enumerate(rows) if not any(
        row != other and all(a <= b for a, b in zip(other, row, strict=True)) for other in rows
    )}
    for phi in (0.0, 0.3, 0.5, 1.0):
        reference = rank_mean_spread_reference(list(zip(ids.tolist(), rows, strict=True)), phi)
        expected = [(candidate.node_id, candidate.score) for candidate in reference]
        scored, _ = _score_csr_mean_spread(ids[shuffled], times[shuffled][:, permutation], phi)
        actual = [scored.candidate(row) for row in scored.order]
        assert [(candidate.node_id, candidate.score) for candidate in actual] == expected
        assert {candidate.node_id for candidate in actual} == expected_ids


def test_equal_vectors_survive_tree_pruning_and_use_node_ids() -> None:
    ids = np.arange(80)[::-1]
    times = np.repeat([[11.0, 20.0, 1.0, 32.0]], len(ids), axis=0)
    scored, _ = _score_csr_mean_spread(ids, times, 0.5)
    assert scored.node_ids[scored.order].tolist() == list(range(len(ids)))
