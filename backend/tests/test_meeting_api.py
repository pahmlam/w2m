"""Exercise fresh and cached meeting-points requests on an offline CSR fixture."""

import json
import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_coordinate_snapper import TO_WGS84
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.config.settings import Settings
from app.main import create_app
from app.models.requests import MeetingRequest, Optimization
from app.services import csr_shortest_path

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


@pytest.mark.parametrize("enabled", [False, True])
def test_ready_benchmark_diagnostics_are_opt_in_and_track_cache(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool,
) -> None:
    settings = Settings(_env_file=None, graph_dir=csr_bundle, benchmark_diagnostics=enabled)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    header = "X-W2M-Benchmark"
    lon, lat = TO_WGS84.transform(500004, 2300000)
    body = {"origins": [
        {"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS
    ]}
    with TestClient(create_app()) as client:
        assert header not in client.get("/ready").headers
        fresh = client.post(MEETING_URL, json=body)
        assert fresh.status_code == 200
        rerank = client.post(
            f"{MEETING_URL}/{fresh.json()['request_id']}/rerank", json={"optimization": {}},
        )
        assert rerank.status_code == 200
        assert client.post("/api/v1/meeting-points/unknown/rerank",
                           json={"optimization": {}}).status_code == 409
        assert client.post(MEETING_URL, json=body).status_code == 200
        ready = client.get("/ready", headers={header: "1"})
        assert ready.json() == {"status": "ready"}
        if not enabled:
            assert header not in ready.headers
            return
        stats = json.loads(ready.headers[header])
        assert stats["graph_version"] == "fixture-v1"
        assert stats["graph_load_ms"] >= 0
        assert 0 <= stats["strtree_build_ms"] <= stats["coordinate_snapper_init_ms"]
        assert stats["peak_active_workers"] == 1
        assert stats["cache"]["request_hits"] == 1
        assert stats["cache"]["request_misses"] == 1
        assert stats["cache"]["source_hits"] == stats["cache"]["source_misses"] == 4
        assert 0 < stats["cache"]["peak_bytes"] <= stats["cache"]["max_bytes"]


def test_map_config_returns_bundle_aoi_and_runtime_parameters(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None, graph_dir=csr_bundle, default_phi=0.8,
        default_max_travel_seconds=1200, default_top_k=2,
        default_min_spacing_meters=725, access_speed_mps=2,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    monkeypatch.setattr("app.models.requests.get_settings", lambda: settings)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/map/config")
        assert response.status_code == 200
        config = response.json()
        assert config["aoi"] == {"type": "Polygon", "coordinates": [[
            [106, 20], [106, 22], [104, 22], [104, 20], [106, 20],
        ]]}
        assert config["travel_modes"] == ["car"]
        assert config["graph_version"] == "fixture-v1"
        assert config["weight_profile_version"] == "car-v1"
        assert config["source_date"] == "2026-11-06"
        assert config["limits"] == {
            "phi": {"min": 0, "max": 1},
            "max_travel_seconds": {"min": 300, "max": 7200},
            "top_k": {"min": 1, "max": 5},
            "min_spacing_meters": {"min": 0, "max": 5000},
        }
        for boundary in ("min", "max"):
            Optimization.model_validate({name: limits[boundary]
                                         for name, limits in config["limits"].items()})

        defaults = config["defaults"]
        assert defaults == {
            "phi": 0.8, "max_travel_seconds": 1200, "top_k": 2,
            "min_spacing_meters": 725, "v_access": 2,
        }
        optimization = {name: defaults[name] for name in config["limits"]}
        assert Optimization().model_dump() == optimization
        lon, lat = TO_WGS84.transform(500004, 2299996)
        meeting = client.post(MEETING_URL, json={"origins": [
            {"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS
        ]})
        assert meeting.status_code == 200
        result = meeting.json()
        assert result["objective"]["phi"] == defaults["phi"]
        assert result["origins"][0]["access_seconds"] == 2
        rerank = client.post(f"{MEETING_URL}/{result['request_id']}/rerank",
                             json={"optimization": optimization})
        assert rerank.status_code == 200
        assert rerank.json()["results"] == result["results"]


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
    assert meeting_client.portal is not None
    routing = meeting_client.portal.call(
        meeting_client.app.state.meeting_routing_cache.get, body["request_id"],
    )
    assert routing is not None
    assert all(source.reachable_node_count == 0 for source in routing.sources)


def test_rerank_reuses_tables_and_matches_a_fresh_request(
    meeting_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"origins": [
        {"id": origin_id, "lon": lon, "lat": lat}
        for origin_id, (lon, lat) in zip(ORIGIN_IDS, (
            TO_WGS84.transform(500004, 2300000 - offset) for offset in (1, 2, 1, 1)
        ), strict=True)
    ]}
    response = meeting_client.post(MEETING_URL, json=payload)
    assert response.status_code == 200
    body = response.json()
    cache = meeting_client.app.state.meeting_routing_cache
    assert meeting_client.portal is not None
    assert meeting_client.portal.call(cache.get, response.headers["X-Request-ID"]) is None
    routing = meeting_client.portal.call(cache.get, body["request_id"])
    assert routing is not None
    assert routing.graph.graph_version == body["graph_version"]
    assert routing.graph.weight_profile_version == body["weight_profile_version"]
    first, second, *_ = routing.sources
    assert first.snap.snapped_xy == pytest.approx(second.snap.snapped_xy)
    assert (first.snap.access_seconds, second.snap.access_seconds) == pytest.approx((10, 20))
    assert first.network_cutoff_seconds == pytest.approx(3590)
    assert all(len(source.distances_seconds) == len(source.predecessors) == 2
               for source in routing.sources)

    optimization = {"phi": 0, "max_travel_seconds": 300, "top_k": 1, "min_spacing_meters": 0}
    fresh = meeting_client.post(MEETING_URL, json={**payload, "optimization": optimization})
    assert fresh.status_code == 200

    def unexpected_routing(*args: object) -> None:
        pytest.fail("Rerank must reuse the cached snaps and paths")

    monkeypatch.setattr("app.services.csr_meeting_service.route_csr_origins", unexpected_routing)
    monkeypatch.setattr("app.services.csr_shortest_path.dijkstra", unexpected_routing)
    monkeypatch.setattr("app.services.coordinate_snapper.CoordinateSnapper.snap_origins",
                        unexpected_routing)
    url = f"{MEETING_URL}/{body['request_id']}/rerank"
    reranked = meeting_client.post(url, json={"optimization": optimization})
    assert reranked.status_code == 200
    updated = reranked.json()
    assert updated["request_id"] == body["request_id"]
    assert updated["timings_ms"]["snap"] == updated["timings_ms"]["dijkstra"] == 0
    for field in ("results", "objective", "origins", "graph_version", "weight_profile_version"):
        assert updated[field] == fresh.json()[field]
    assert updated["results"][0]["score"] == 16.5
    assert updated["results"][0]["score"] != body["results"][0]["score"]

    restored = meeting_client.post(url, json={"optimization": {}})
    assert restored.status_code == 200
    assert restored.json()["objective"] == body["objective"]
    assert restored.json()["results"] == body["results"]


def test_tc14_rerank_requires_recompute_above_original_cutoff(meeting_client: TestClient) -> None:
    lon, lat = TO_WGS84.transform(500005, 2299900)
    origins = [{"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS]
    short_options = {"max_travel_seconds": 900}
    long_options = {"max_travel_seconds": 1800}
    short = meeting_client.post(
        MEETING_URL, json={"origins": origins, "optimization": short_options},
    )
    assert short.status_code == 200
    assert short.json()["status"] == "empty"
    rejected = meeting_client.post(f"{MEETING_URL}/{short.json()['request_id']}/rerank",
                                   json={"optimization": long_options})
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == "RECOMPUTE_REQUIRED"
    assert rejected.json()["request_id"] == rejected.headers["X-Request-ID"]

    long = meeting_client.post(MEETING_URL, json={"origins": origins, "optimization": long_options})
    assert long.status_code == 200
    assert long.json()["status"] == "success"
    url = f"{MEETING_URL}/{long.json()['request_id']}/rerank"
    for options, expected in ((short_options, short.json()), (long_options, long.json())):
        reranked = meeting_client.post(url, json={"optimization": options})
        assert reranked.status_code == 200
        for field in ("status", "error_code", "min_required_seconds", "results", "origins"):
            assert reranked.json()[field] == expected[field]


def test_rerank_conflicts_on_missing_id_or_graph_change(meeting_client: TestClient) -> None:
    options = {"optimization": {}}
    missing = meeting_client.post(f"{MEETING_URL}/missing/rerank", json=options)
    assert missing.status_code == 409
    assert missing.json()["error_code"] == "RECOMPUTE_REQUIRED"

    lon, lat = TO_WGS84.transform(500004, 2299999)
    created = meeting_client.post(MEETING_URL, json={"origins": [
        {"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS
    ]})
    assert created.status_code == 200
    state = meeting_client.app.state
    assert meeting_client.portal is not None
    meeting_client.portal.call(setattr, state, "csr_graph",
                               replace(state.csr_graph, graph_version="fixture-v2"))
    url = f"{MEETING_URL}/{created.json()['request_id']}/rerank"
    stale = meeting_client.post(url, json=options)
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "RECOMPUTE_REQUIRED"


def test_new_request_reuses_unchanged_sources_after_a_move(
    meeting_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    origins = []
    for origin_id, x in zip(ORIGIN_IDS, (500004, 500008, 500012, 500016), strict=True):
        lon, lat = TO_WGS84.transform(x, 2300000)
        origins.append({"id": origin_id, "lon": lon, "lat": lat})
    lon, lat = TO_WGS84.transform(500000, 2300000)
    moved = [{"id": ORIGIN_IDS[0], "lon": lon, "lat": lat}, *origins[1:]]
    changed = {"origins": moved, "optimization": {"max_travel_seconds": 300}}
    with TestClient(create_app()) as cold_client:
        reference = cold_client.post(MEETING_URL, json=changed)
        assert reference.status_code == 200

    initial = meeting_client.post(MEETING_URL, json={
        "origins": origins, "optimization": {"max_travel_seconds": 600},
    })
    assert initial.status_code == 200
    dijkstra = Mock(wraps=csr_shortest_path.dijkstra)
    monkeypatch.setattr(csr_shortest_path, "dijkstra", dijkstra)
    updated = meeting_client.post(MEETING_URL, json=changed)
    assert updated.status_code == 200
    assert [call.kwargs["indices"] for call in dijkstra.call_args_list] == [0]
    assert updated.json()["request_id"] != initial.json()["request_id"]
    assert updated.json()["results"] == reference.json()["results"]
    assert updated.json()["origins"] == reference.json()["origins"]

    dijkstra.reset_mock()
    longer = meeting_client.post(MEETING_URL, json={
        "origins": moved, "optimization": {"max_travel_seconds": 900},
    })
    assert longer.status_code == 200
    assert [call.kwargs["indices"] for call in dijkstra.call_args_list] == [0, 2, 3, 4]


def test_internal_error_keeps_coordinates_out_of_response_and_logs(
    meeting_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    latitude = 20.800123456
    longitude = 105.000654321

    async def fail(body: MeetingRequest) -> None:
        raise RuntimeError(f"Could not process {body.origins[0]}")

    monkeypatch.setattr(meeting_client.app.state.csr_meeting_service, "compute_request", fail)
    response = meeting_client.post(MEETING_URL, json={"origins": [
        {"id": origin_id, "lat": latitude, "lon": longitude} for origin_id in ORIGIN_IDS
    ]}, headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    request_id = response.headers["X-Request-ID"]
    assert response.json()["request_id"] == request_id
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert response.headers["Access-Control-Expose-Headers"] == "X-Request-ID"
    assert request_id in caplog.text
    assert all(str(value) not in response.text and str(value) not in caplog.text
               for value in (latitude, longitude))


def test_request_logs_use_route_templates_and_safe_metadata(
    meeting_client: TestClient, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error.w2m")
    positions = [TO_WGS84.transform(500004, 2300000 - offset) for offset in (1, 2, 3, 4)]
    secret = "synthetic-secret-m6"
    body = {"origins": [
        {"id": origin_id, "lon": lon, "lat": lat}
        for origin_id, (lon, lat) in zip(ORIGIN_IDS, positions, strict=True)
    ]}
    fresh = meeting_client.post(MEETING_URL, params={"token": secret}, json=body,
                                headers={"Authorization": f"Bearer {secret}"})
    assert fresh.status_code == 200
    cache_id = fresh.json()["request_id"]
    rerank = meeting_client.post(
        f"{MEETING_URL}/{cache_id}/rerank", json={"optimization": {"phi": 0}},
    )
    assert rerank.status_code == 200
    lon, lat = TO_WGS84.transform(500005, 2299950)
    empty = meeting_client.post(MEETING_URL, json={
        "origins": [{"id": origin_id, "lon": lon, "lat": lat} for origin_id in ORIGIN_IDS],
        "optimization": {"max_travel_seconds": 300},
    })
    assert empty.status_code == 200 and empty.json()["status"] == "empty"
    unknown = meeting_client.get(f"/{secret}", params={"latitude": lat})
    assert unknown.status_code == 404
    rejected = meeting_client.post(MEETING_URL, json={**body, "token": secret})
    assert rejected.status_code == 400

    records = {}
    for record in caplog.records:
        message = record.getMessage()
        if record.name == "uvicorn.error.w2m" and message.startswith("request "):
            entry = json.loads(message.removeprefix("request "))
            records[entry["request_id"]] = entry
    for response, route in (
        (fresh, MEETING_URL), (rerank, f"{MEETING_URL}/{{request_id}}/rerank"),
        (empty, MEETING_URL), (unknown, None), (rejected, MEETING_URL),
    ):
        entry = records[response.headers["X-Request-ID"]]
        assert entry["route"] == route
        assert entry["status"] == response.status_code
        assert entry["graph_version"] == "fixture-v1"
        assert entry["weight_profile_version"] == "car-v1"
        assert entry["server_ms"] >= 0
        expected_timings = response.json().get("timings_ms")
        assert entry["timings_ms"] == expected_timings
    for response, options in ((fresh, {}), (rerank, {"phi": 0}),
                              (empty, {"max_travel_seconds": 300})):
        entry = records[response.headers["X-Request-ID"]]["meeting_result"]
        payload = response.json()
        assert entry["status"] == payload["status"]
        assert entry["optimization"] == Optimization(**options).model_dump()
        assert entry["owa_weights"] == payload["objective"]["weights"]
        assert entry["min_required_seconds"] == payload["min_required_seconds"]
        assert entry["results"] == [
            {
                "rank": result["rank"],
                "score_seconds": result["score"],
                "min_seconds": result["min_time"],
                "max_seconds": result["max_time"],
                "avg_seconds": result["avg_time"],
                "difference_seconds": result["difference"],
                "travel_times_seconds": [result["travel_times"][key] for key in ORIGIN_IDS],
                "routes": [
                    {field: result["routes"][key][field] for field in (
                        "access_seconds", "network_seconds", "duration_seconds",
                    )}
                    for key in ORIGIN_IDS
                ],
            }
            for result in payload["results"]
        ]
    assert all("meeting_result" not in records[response.headers["X-Request-ID"]]
               for response in (unknown, rejected))
    assert all(value not in caplog.text for value in (secret, cache_id, *ORIGIN_IDS))
    assert all(str(value) not in caplog.text for position in [*positions, (lon, lat)]
               for value in position)


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
