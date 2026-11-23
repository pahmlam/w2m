"""Verify byte-budget eviction and fixed TTL for cached routing tables."""

import asyncio
from pathlib import Path
from weakref import ref

import pytest
from test_coordinate_snapper import TO_WGS84
from test_csr_graph_loader import csr_bundle as csr_bundle

from app.config.settings import Settings
from app.models.requests import MeetingRequest, Origin
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.csr_shortest_path import CSRRoutingResult, route_csr_origins
from app.services.graph_loader import load_csr_graph
from app.services.meeting_routing_cache import MeetingRoutingCache, _routing_size_bytes


def _compute_routing(csr_bundle: Path) -> CSRRoutingResult:
    graph = load_csr_graph(csr_bundle)
    snapper = CoordinateSnapper(graph, Settings(_env_file=None))
    lon, lat = TO_WGS84.transform(500004, 2300000)
    request = MeetingRequest(origins=[Origin(id=label, lon=lon, lat=lat) for label in "ABCD"])
    return route_csr_origins(graph, snapper.snap_origins(request), 3600)


def test_byte_budget_evicts_least_recently_used_result(csr_bundle: Path) -> None:
    routing = _compute_routing(csr_bundle)
    size_bytes = _routing_size_bytes(routing)

    async def verify() -> None:
        cache = MeetingRoutingCache(ttl_seconds=900, max_bytes=2 * size_bytes)
        cache.put("first", routing)
        cache.put("second", routing)
        assert cache.get("first") is routing
        cache.put("third", routing)
        assert cache.get("first") is routing
        assert cache.get("second") is None
        assert cache.get("third") is routing
        cache.clear()
        assert cache.get("first") is None
        assert cache.get("third") is None

        cache = MeetingRoutingCache(ttl_seconds=900, max_bytes=size_bytes - 1)
        cache.put("oversized", routing)
        assert cache.get("oversized") is None

    asyncio.run(verify())


def test_cache_releases_routing_at_original_expiry(
    csr_bundle: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify() -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        with monkeypatch.context() as clock:
            clock.setattr(loop, "time", lambda: now)
            cache = MeetingRoutingCache(ttl_seconds=900, max_bytes=100_000)
            routing = _compute_routing(csr_bundle)
            retained = ref(routing)
            cache.put("original", routing)
            del routing

            now += 899
            assert cache.get("original") is retained() is not None
            now += 1
            # Advance the loop without reading the cache, as during idle expiry.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert retained() is None
            assert cache.get("original") is None

    asyncio.run(verify())
