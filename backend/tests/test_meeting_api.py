"""Exercise the fresh meeting-points endpoint with a real offline CSR fixture."""

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_coordinate_snapper import TO_WGS84
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.config.settings import Settings
from app.main import create_app

MEETING_URL = "/api/v1/meeting-points"
ORIGIN_IDS = ("visitor-1", "visitor-2", "visitor-3", "visitor-4")


@pytest.fixture
def meeting_client(csr_bundle: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # A low access speed lets this short fixture exceed the API's minimum cutoff.
    settings = Settings(_env_file=None, graph_dir=csr_bundle, default_phi=0.7, access_speed_mps=0.1)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.models.requests.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        yield client


def test_create_meeting_points_returns_snaps_and_matched_routes(meeting_client: TestClient) -> None:
    lon, lat = TO_WGS84.transform(500004, 2299999)
    response = meeting_client.post(MEETING_URL, json={"origins": [
        {"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS
    ]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["unit"] == "seconds"
    assert UUID(body["request_id"]).version == 4
    assert body["request_id"] != response.headers["X-Request-ID"]
    assert body["graph_version"] == "fixture-v1"
    assert body["weight_profile_version"] == "car-v1"
    assert body["objective"]["type"] == "owa_geometric"
    assert body["objective"]["phi"] == 0.7
    weights = body["objective"]["weights"]
    assert len(weights) == 4
    assert sum(weights) == pytest.approx(1)
    assert weights[1:] == pytest.approx([weight * 0.37 for weight in weights[:-1]])
    assert [origin["id"] for origin in body["origins"]] == list(ORIGIN_IDS)
    assert set(body["timings_ms"]) == {"snap", "dijkstra", "scan", "rank", "routes", "total"}
    assert all(value >= 0 for value in body["timings_ms"].values())

    result, = body["results"]
    assert result["rank"] == 1
    assert result["node_id"] == 7
    assert result["travel_times"] == dict.fromkeys(ORIGIN_IDS, 14)
    assert set(result["routes"]) == set(ORIGIN_IDS)
    for origin in body["origins"]:
        origin_id = origin["id"]
        route = result["routes"][origin_id]
        assert origin["snap_distance_m"] == pytest.approx(1)
        assert origin["access_seconds"] == route["access_seconds"] == 10
        assert route["duration_seconds"] == result["travel_times"][origin_id]
        assert route["duration_seconds"] == pytest.approx(
            route["access_seconds"] + route["network_seconds"]
        )
        assert route["geometry"]["type"] == "LineString"
        start, end = route["geometry"]["coordinates"]
        assert start == [origin["snapped"]["lon"], origin["snapped"]["lat"]]
        assert start == pytest.approx(TO_WGS84.transform(500004, 2300000), rel=0, abs=1e-8)
        assert end == pytest.approx(TO_WGS84.transform(500020, 2300000), rel=0, abs=1e-8)


def test_create_meeting_points_returns_cutoff_bound_when_empty(meeting_client: TestClient) -> None:
    lon, lat = TO_WGS84.transform(500005, 2299950)
    response = meeting_client.post(MEETING_URL, json={
        "origins": [{"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS],
        "optimization": {"max_travel_seconds": 300},
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["error_code"] == "NO_COMMON_REACHABLE_NODE"
    assert body["results"] == []
    assert len(body["origins"]) == 4
    assert body["min_required_seconds"] == "> 300"


@pytest.mark.parametrize(("lon", "lat", "code"), [
    (107.0, 20.8, "OUT_OF_COVERAGE"),
    (105.1, 20.8, "SNAP_FAILED"),
])
def test_create_meeting_points_reports_snap_errors(
    meeting_client: TestClient, lon: float, lat: float, code: str,
) -> None:
    response = meeting_client.post(MEETING_URL, json={"origins": [
        {"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS
    ]})

    assert response.status_code == 422
    assert response.json()["error_code"] == code
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
