"""Exercise reproducible sampling and TC-16 verdicts without external data."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely import STRtree
from shapely.geometry import LineString, box

from app.models.responses import Location, MeetingResult, Route
from scripts import validate_tc16 as validator


def test_sampling_is_seeded_and_covers_all_spatial_scenarios() -> None:
    snapper = SimpleNamespace(
        reference=SimpleNamespace(aoi=box(104.995, 20.795, 105.015, 20.810)),
        tree=STRtree([LineString([(500000 + i * 100, 2300000),
                                  (500010 + i * 100, 2300000)]) for i in range(8)]),
    )
    first = list(validator.sample_requests(snapper, 6, 57))
    assert first == list(validator.sample_requests(snapper, 6, 57))
    assert first != list(validator.sample_requests(snapper, 6, 58))
    assert [scenario for scenario, _ in first] == ["near", "far", "boundary"] * 2
    for _, request in first:
        assert len({(origin.lon, origin.lat) for origin in request.origins}) == 4


def _result(node_id: int, score: float) -> MeetingResult:
    route = Route(
        duration_seconds=2.3, access_seconds=1.1, network_seconds=1.2,
        distance_meters=2, geometry={"coordinates": [(105, 20), (105, 20)]},
    )
    return MeetingResult(
        rank=1, node_id=node_id, location=Location(lon=105, lat=20),
        travel_times=dict.fromkeys("ABCD", 2.3), max_time=2.3, min_time=2.3,
        difference=0, avg_time=2.3, score=score, routes=dict.fromkeys("ABCD", route),
    )


def test_comparison_checks_order_score_ticks_and_route_times() -> None:
    expected = [_result(1, 1.2)]
    assert validator.compare_results([_result(1, 1.3)], expected, set("ABCD")) == (1, 4)
    assert validator.compare_results([], [], set("ABCD")) == (0, 0)
    with pytest.raises(ValueError, match="Ranked nodes"):
        validator.compare_results([_result(2, 1.2)], expected, set("ABCD"))
    with pytest.raises(ValueError, match="Score difference"):
        validator.compare_results([_result(1, 1.4)], expected, set("ABCD"))
    broken = _result(1, 1.2)
    broken.routes["A"].network_seconds = 2.2
    with pytest.raises(ValueError, match="route times"):
        validator.compare_results([broken], expected, set("ABCD"))


def test_cli_preserves_failed_smoke_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "metadata.json").write_text("{}")
    output = tmp_path / "report.json"

    async def failed(*args: object) -> dict:
        return {"status": "failed", "cases": [{"index": 1, "error": "Ranked nodes differ"}]}

    monkeypatch.setattr(validator, "_compare_bundle", failed)
    monkeypatch.setattr(validator, "version", lambda name: "fixture")
    args = ["--bundle-dir", str(bundle), "--output", str(output), "--requests", "3"]
    assert validator.main(args) == 1
    report = json.loads(output.read_text())
    assert report["scope"] == "smoke"
    assert report["status"] == "failed"
    assert report["early_stopping_enabled"] is False
    assert report["cases"][0]["error"] == "Ranked nodes differ"
    with pytest.raises(SystemExit):
        validator.main(args)
    assert json.loads(output.read_text()) == report
