import networkx as nx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.settings import Settings
from app.main import create_app
from app.models.requests import MeetingRequest, RerankRequest


def test_coincident_origins_and_defaults(meeting_payload):
    request = MeetingRequest.model_validate(meeting_payload)
    assert request.optimization.phi == 0.5
    assert request.optimization.max_travel_seconds == 3600
    assert request.optimization.top_k == 5


@pytest.mark.parametrize("count", [0, 3, 5])
def test_exactly_four_origins(meeting_payload, count):
    meeting_payload["origins"] = [
        {"id": str(i), "lat": 21.03, "lon": 105.84} for i in range(count)
    ]
    with pytest.raises(ValidationError):
        MeetingRequest.model_validate(meeting_payload)


def test_duplicate_ids_rejected(meeting_payload):
    meeting_payload["origins"][1]["id"] = "A"
    with pytest.raises(ValidationError):
        MeetingRequest.model_validate(meeting_payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 91, "21.03", True])
def test_invalid_coordinates(meeting_payload, value):
    meeting_payload["origins"][0]["lat"] = value
    with pytest.raises(ValidationError):
        MeetingRequest.model_validate(meeting_payload)


@pytest.mark.parametrize("options", [
    {"phi": -0.1}, {"phi": 1.1}, {"max_travel_seconds": 299},
    {"max_travel_seconds": 7201}, {"top_k": 0}, {"top_k": 6},
    {"min_spacing_meters": -1}, {"min_spacing_meters": 5001}, {"top_k": True},
])
def test_request_and_rerank_share_bounds(meeting_payload, options):
    with pytest.raises(ValidationError):
        MeetingRequest.model_validate({**meeting_payload, "optimization": options})
    with pytest.raises(ValidationError):
        RerankRequest.model_validate({"optimization": options})


def test_fixture_covers_routing_cases(road_graph):
    assert nx.shortest_path_length(road_graph, 1, 3, weight="travel_time") == 130
    assert nx.shortest_path_length(road_graph, 2, 1, weight="travel_time") == 120
    assert not nx.has_path(road_graph, 3, 1)
    assert not nx.has_path(road_graph, 1, 4)
    assert list(road_graph[1][2]) == [0, 1, 2]


def test_liveness_and_readiness_are_distinct(meeting_payload):
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/ready").status_code == 503
        response = client.post("/api/v1/meeting-points", json=meeting_payload)
        assert response.status_code == 503
        assert response.json()["error_code"] == "GRAPH_UNAVAILABLE"
        assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_validation_does_not_echo_coordinates(meeting_payload):
    meeting_payload["origins"][0]["lat"] = 91.123456
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/meeting-points", json=meeting_payload)
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_COORDINATES"
    assert "91.123456" not in response.text


def test_settings_reject_nonpositive_access_speed():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, access_speed_mps=0)


def test_runtime_defaults_are_shared_with_rerank(monkeypatch, meeting_payload):
    settings = Settings(_env_file=None, default_phi=0.7)
    monkeypatch.setattr("app.models.requests.get_settings", lambda: settings)
    assert MeetingRequest.model_validate(meeting_payload).optimization.phi == 0.7
    assert RerankRequest.model_validate({"optimization": {}}).optimization.phi == 0.7


def test_parameter_errors_and_unavailable_endpoints(meeting_payload):
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/meeting-points", json={
            **meeting_payload, "optimization": {"top_k": 6},
        })
        assert response.status_code == 400
        assert response.json()["error_code"] == "INVALID_PARAMETERS"
        assert client.get("/api/v1/map/config").status_code == 503
        response = client.post(
            "/api/v1/meeting-points/example/rerank", json={"optimization": {}}
        )
        assert response.status_code == 503


def test_openapi_documents_validation_as_400():
    operation = create_app().openapi()["paths"]["/api/v1/meeting-points"]["post"]
    assert "400" in operation["responses"]
    assert "422" not in operation["responses"]
