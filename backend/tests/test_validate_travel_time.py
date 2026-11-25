"""Verify the independent travel-time report without a live routing service."""

import pytest

from scripts.validate_travel_time import compare_times


def test_reports_route_and_group_errors_with_shared_access_offsets():
    sample = {
        "seed": 7,
        "graph_version": "fixture",
        "weight_profile_version": "car-v1",
        "bundle_metadata_sha256": "fixture-hash",
        "groups": [],
    }
    observations = []
    for group_id in range(26):
        group = {"group_id": group_id, "scenario": "near", "routes": []}
        for index, (w2m, reference, access) in enumerate([
            (120, 100, 0), (100, 120, 0), (50, 60, 30), (70, 60, 0),
        ]):
            route_id = f"{group_id}-{index}"
            group["routes"].append({
                "route_id": route_id, "network_seconds": w2m, "access_seconds": access,
            })
            if group_id < 25:
                observations.append({
                    "route_id": route_id, "reference_seconds": str(reference),
                    "departure_at": "2030-01-02T06:30:00+00:00",
                })
        sample["groups"].append(group)
    observations.append({
        "route_id": "25-0", "reference_seconds": "", "reason": "endpoint_shift",
    })

    report = compare_times(sample, observations, "fixture", "off-peak")
    assert report["off_peak_sample_complete"]
    assert report["complete_groups"] == 25
    assert report["compared_routes"] == 100
    assert report["routes"][0]["departure_at"] == "2030-01-02T13:30:00+07:00"
    assert report["network_error_seconds"]["mean_absolute_seconds"] == 15
    assert report["spread_error_seconds"]["mean_signed_seconds"] == -10
    assert report["missing"][0] == {"route_id": "25-0", "reason": "endpoint_shift"}
    assert report["missing"][1]["reason"] == "missing_observation"

    static = compare_times(sample, observations, "fixture", "static")
    assert static["sufficient_complete_groups"]
    assert not static["off_peak_sample_complete"]
    with pytest.raises(ValueError, match="duplicate route ID"):
        compare_times(sample, [observations[0], observations[0]], "fixture", "static")
    with pytest.raises(ValueError, match="timezone"):
        compare_times(sample, [{
            **observations[0], "departure_at": "2030-01-02T13:30:00",
        }], "fixture", "off-peak")
