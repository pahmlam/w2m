"""Check the benchmark client's contract and metrics without Docker."""

import httpx

from app.models.requests import MeetingRequest, RerankRequest
from scripts.benchmark_meeting_api import MEETING_PATH, _post, _rerank_payload, _summarize


def test_reports_http_errors_without_using_them_for_success_latency():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == MEETING_PATH:
            return httpx.Response(200, json={
                "request_id": "cached",
                "status": "success",
                "timings_ms": {key: 1 for key in (
                    "snap", "dijkstra", "scan", "rank", "routes", "total",
                )},
            })
        return httpx.Response(502, text="Service unavailable")

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        success, request_id = _post(client, MEETING_PATH, {}, "near")
        failure, missing_id = _post(client, f"{MEETING_PATH}/cached/rerank", {}, "near")
    stats = _summarize([success, failure])
    assert request_id == "cached" and missing_id is None
    assert stats["http_status_counts"] == {"200": 1, "502": 1}
    assert stats["http_ms"]["p95"] == success["http_ms"]
    assert stats["timings_ms"]["routes"]["p95"] == 1


def test_rerank_options_are_valid_and_fit_the_original_cutoff(meeting_payload):
    request = MeetingRequest.model_validate(meeting_payload)
    options = [
        RerankRequest.model_validate(_rerank_payload(request, index)).optimization
        for index in range(30)
    ]
    assert all(option.phi != request.optimization.phi for option in options)
    assert all(option.max_travel_seconds <= request.optimization.max_travel_seconds
               for option in options)
    assert {option.top_k for option in options} == set(range(1, 6))
    assert {option.min_spacing_meters for option in options} == {0, 500, 1000}
