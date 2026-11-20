"""Verify CSR worker-pool isolation, capacity, and application lifecycle."""

import asyncio
from pathlib import Path
from threading import Event, Lock, get_ident

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_coordinate_snapper import TO_WGS84
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.config.settings import Settings
from app.main import create_app
from app.models.requests import MeetingRequest, Optimization
from app.models.responses import MeetingResult
from app.services.coordinate_snapper import SnapResult
from app.services.csr_meeting_service import CSRMeetingService
from app.services.graph_loader import load_csr_graph


def test_app_service_runs_the_csr_pipeline(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, graph_dir=csr_bundle, csr_max_concurrent_tasks=1)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    snaps = tuple(
        SnapResult(label, (105, 20.8), (-3, 7, 0), (7, -3, 0), 1,
                   (500020, 2300000), (105, 20.8), 0, 0, 7)
        for label in "ABCD"
    )
    optimization = Optimization()
    with TestClient(app) as client:
        service = app.state.csr_meeting_service
        assert client.portal is not None
        result, = client.portal.call(service.compute, snaps, optimization)
        assert result.node_id == 7
        assert result.travel_times == dict.fromkeys("ABCD", 0)
        assert set(result.routes) == set("ABCD")
    assert app.state.csr_meeting_service is None
    with pytest.raises(RuntimeError, match="after shutdown"):
        asyncio.run(service.compute(snaps, optimization))


def test_worker_limit_survives_request_cancellation(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = CSRMeetingService(load_csr_graph(csr_bundle), max_concurrent_tasks=2)

    async def verify() -> None:
        loop = asyncio.get_running_loop()
        loop_thread = get_ident()
        first_started, both_started, extra_started = (asyncio.Event() for _ in range(3))
        release = Event()
        lock = Lock()
        active = peak = started = 0

        def block(*args: object) -> list[MeetingResult]:
            nonlocal active, peak, started
            assert get_ident() != loop_thread
            with lock:
                active += 1
                peak = max(peak, active)
                started += 1
                signals = (first_started, both_started, extra_started)
                loop.call_soon_threadsafe(signals[min(started - 1, 2)].set)
            try:
                assert release.wait(timeout=5)
                return []
            finally:
                with lock:
                    active -= 1

        monkeypatch.setattr(service, "_compute", block)
        options = Optimization()
        first = asyncio.create_task(service.compute((), options))
        jobs = []
        try:
            await asyncio.wait_for(first_started.wait(), timeout=3)
            jobs = [asyncio.create_task(service.compute((), options)) for _ in range(3)]
            await asyncio.wait_for(both_started.wait(), timeout=3)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(extra_started.wait(), timeout=0.05)
        finally:
            release.set()
            await asyncio.gather(first, *jobs, return_exceptions=True)
            await service.close()

        assert peak == 2
        assert started == 4
        assert [job.result() for job in jobs] == [[], [], []]

    asyncio.run(verify())


def test_worker_limit_requires_positive_setting() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, csr_max_concurrent_tasks=0)


def test_compute_request_measures_the_actual_pipeline_boundaries(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, graph_dir=csr_bundle)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    # First origin is on a slower curved parallel edge that still belongs to the snapping index.
    lonlat = [TO_WGS84.transform(500005, 2300000 + delta) for delta in (2.5, 0, 0, 0)]
    request = MeetingRequest.model_validate({"origins": [
        {"id": label, "lon": lon, "lat": lat}
        for label, (lon, lat) in zip("ABCD", lonlat, strict=True)
    ]})
    ticks = iter((
        0, 125_000, 2_125_000, 3_125_000, 4_125_000, 6_125_000, 9_125_000,
        10_125_000, 14_125_000, 19_125_000,
    ))
    for module in ("csr_meeting_service", "csr_shortest_path", "meeting_optimizer"):
        monkeypatch.setattr(f"app.services.{module}.perf_counter_ns", lambda: next(ticks))

    with TestClient(create_app()) as client:
        service = client.app.state.csr_meeting_service
        assert client.portal is not None
        computation = client.portal.call(service.compute_request, request)
    assert computation.timings_ms.model_dump() == {
        "snap": 0.125, "dijkstra": 1.0, "scan": 2.0, "rank": 7.0, "routes": 5.0, "total": 19.125,
    }
    assert computation.reachable_nodes_by_origin == dict.fromkeys("ABCD", 2)
    result, = computation.results
    assert result.node_id == 7
    assert result.travel_times == {"A": 15, "B": 3.8, "C": 3.8, "D": 3.8}
    assert len(result.routes["A"].geometry.coordinates) == 3
