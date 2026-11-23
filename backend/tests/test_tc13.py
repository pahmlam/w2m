"""Verify graph immutability across 50 concurrent meeting-points requests."""

import asyncio
import hashlib
import pickle
from collections.abc import Sequence
from os import getenv
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Response
from shapely.geometry import LineString
from starlette.types import ASGIApp, Receive, Scope, Send
from test_coordinate_snapper import TO_WGS84
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.config.settings import Settings
from app.main import create_app
from app.models.requests import MeetingRequest, Optimization, Origin
from app.services.graph_loader import CSRGraph

REQUEST_COUNT = 50


def _graph_fingerprint(graph: CSRGraph) -> str:
    matrix = graph.csr
    snapshot = (
        matrix.shape, matrix.data, matrix.indices, matrix.indptr,
        dict(graph.mappings), dict(graph.geometry), graph._edge_seconds,
        dict(graph.node_indices), dict(graph.edge_indices), dict(graph.reverse_edge_indices),
        graph.aoi.wkb, graph.graph_version, graph.weight_profile_version, graph.source_date,
    )
    return hashlib.sha256(pickle.dumps(snapshot, protocol=5)).hexdigest()


def _sample_origins(graph: CSRGraph) -> list[Origin]:
    mappings = graph.mappings
    candidates = np.flatnonzero(mappings["is_candidate"])
    xy = mappings["node_xy"][candidates]
    center_index = candidates[np.argmin(np.linalg.norm(xy - xy.mean(axis=0), axis=1))]
    target_id = mappings["node_ids"][center_index]
    edge_index = int(np.flatnonzero(mappings["edge_ids"][:, 1] == target_id)[0])
    geometry = graph.geometry
    start, end = geometry["offsets"][edge_index:edge_index + 2]
    road = LineString(geometry["coordinates"][start:end])
    origins = []
    for label, fraction in zip("ABCD", (0.25, 0.35, 0.45, 0.55), strict=True):
        point = road.interpolate(fraction, normalized=True)
        lon, lat = TO_WGS84.transform(point.x, point.y, errcheck=True)
        origins.append(Origin(id=label, lon=lon, lat=lat))
    return origins


async def _submit_together(app: ASGIApp, payloads: Sequence[MeetingRequest]) -> list[Response]:
    all_arrived = asyncio.Event()
    arrivals = 0

    async def synchronized_app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal arrivals
        arrivals += 1
        if arrivals == len(payloads):
            all_arrived.set()
        await all_arrived.wait()
        await app(scope, receive, send)

    async with AsyncClient(transport=ASGITransport(app=synchronized_app),
                           base_url="http://testserver") as client:
        return await asyncio.gather(*(
            client.post("/api/v1/meeting-points", json=payload.model_dump(mode="json"))
            for payload in payloads
        ))


def test_tc13_shared_graph_unchanged_after_50_requests(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_dir = Path(getenv("W2M_TC13_BUNDLE_DIR", str(csr_bundle)))
    settings = Settings(_env_file=None, graph_dir=bundle_dir, csr_max_concurrent_tasks=2)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        graph = app.state.csr_graph
        origins = _sample_origins(graph)
        payloads = [MeetingRequest(origins=origins, optimization=Optimization(
            phi=index / (REQUEST_COUNT - 1), max_travel_seconds=300, top_k=1, min_spacing_meters=500,
        )) for index in range(REQUEST_COUNT)]
        before = _graph_fingerprint(graph)
        assert client.portal is not None
        started = perf_counter()
        responses = client.portal.call(_submit_together, app, payloads)
        elapsed_seconds = perf_counter() - started
        assert app.state.csr_graph is graph
        after = _graph_fingerprint(graph)

    assert before == after
    result_ids = set()
    for response, payload in zip(responses, payloads, strict=True):
        body = response.json()
        assert response.status_code == 200, body.get("error_code")
        assert body["status"] == "success"
        assert body["graph_version"] == graph.graph_version
        assert body["weight_profile_version"] == graph.weight_profile_version
        assert body["objective"]["phi"] == payload.optimization.phi
        result, = body["results"]
        assert set(result["routes"]) == set("ABCD")
        result_ids.add(body["request_id"])
    assert len(result_ids) == REQUEST_COUNT
    print(f"TC-13 {graph.graph_version} / {graph.weight_profile_version}: "
          f"{REQUEST_COUNT}/{REQUEST_COUNT} HTTP 200 in {elapsed_seconds:.2f}s\n"
          f"SHA-256 before: {before}\nSHA-256 after:  {after}")
