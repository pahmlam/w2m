"""Retain request-local routing tables within a process-local byte budget."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from app.models.requests import ObjectiveType
from app.services.coordinate_snapper import SnapResult
from app.services.csr_shortest_path import CSRRoutingResult, CSRSourcePaths
from app.services.graph_loader import CSRGraph

type _SourceLocation = tuple[str, str, tuple[int, int, int], float, tuple[float, float]]

# Allow for the small Python objects and temporary-source rows in a request.
ENTRY_OVERHEAD_BYTES = 8192


@dataclass(frozen=True)
class _Entry:
    routing: CSRRoutingResult
    objective_type: ObjectiveType
    fixed_phi: float | None
    sources: dict[tuple[_SourceLocation, float], CSRSourcePaths]
    size_bytes: int
    expires_at: float
    expiry: asyncio.TimerHandle


def _routing_size_bytes(routing: CSRRoutingResult) -> int:
    matrix = routing.overlay.csr
    arrays = [matrix.data, matrix.indices, matrix.indptr]
    for source in routing.sources:
        arrays.extend((source.distances_seconds, source.predecessors))
    return ENTRY_OVERHEAD_BYTES + sum(array.nbytes for array in arrays)


def _source_location(graph: CSRGraph, snap: SnapResult) -> _SourceLocation:
    return (
        graph.graph_version, graph.weight_profile_version,
        snap.edge_id, snap.theta, snap.snapped_xy,
    )


class MeetingRoutingCache:
    """Manage expiry on the event loop and share read-only paths with routing workers."""

    def __init__(self, *, ttl_seconds: int, max_bytes: int) -> None:
        self._loop = asyncio.get_running_loop()
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._size_bytes = 0
        self._peak_bytes = 0
        self._evictions = 0
        self._source_hits = 0
        self._source_misses = 0
        self._request_hits = 0
        self._request_misses = 0
        self._lock = Lock()

    def statistics(self) -> dict[str, int]:
        """Snapshot cache accounting and lookup outcomes without request data."""
        with self._lock:
            return {
                "max_bytes": self._max_bytes,
                "ttl_seconds": self._ttl_seconds,
                "size_bytes": self._size_bytes,
                "peak_bytes": self._peak_bytes,
                "entries": len(self._entries),
                "evictions": self._evictions,
                "source_hits": self._source_hits,
                "source_misses": self._source_misses,
                "request_hits": self._request_hits,
                "request_misses": self._request_misses,
            }

    def put(
        self, request_id: str, routing: CSRRoutingResult,
        *, objective_type: ObjectiveType = "owa_geometric", fixed_phi: float | None = None,
    ) -> None:
        """Store the full routing result under its response ID if it fits."""
        size_bytes = _routing_size_bytes(routing)
        with self._lock:
            self._remove(request_id)
            if size_bytes > self._max_bytes:
                return
            while self._size_bytes + size_bytes > self._max_bytes:
                self._remove(next(iter(self._entries)))
                self._evictions += 1
            sources = {
                (_source_location(routing.graph, paths.snap), paths.network_cutoff_seconds): paths
                for paths in routing.sources
            }
            expires_at = monotonic() + self._ttl_seconds
            expiry = self._loop.call_later(self._ttl_seconds, self._expire, request_id)
            self._entries[request_id] = _Entry(
                routing, objective_type, fixed_phi, sources, size_bytes, expires_at, expiry,
            )
            self._size_bytes += size_bytes
            self._peak_bytes = max(self._peak_bytes, self._size_bytes)

    def get(self, request_id: str) -> CSRRoutingResult | None:
        """Retrieve routing tables for the request."""
        cached = self.get_request(request_id)
        return cached[0] if cached is not None else None

    def get_request(
        self, request_id: str,
    ) -> tuple[CSRRoutingResult, ObjectiveType, float | None] | None:
        """Retrieve current tables and refresh recency without extending expiry."""
        with self._lock:
            entry = self._entries.get(request_id)
            if entry is None:
                self._request_misses += 1
                return None
            if entry.expires_at <= monotonic():
                self._remove(request_id)
                self._request_misses += 1
                return None
            self._entries.move_to_end(request_id)
            self._request_hits += 1
            return entry.routing, entry.objective_type, entry.fixed_phi

    def get_source(
        self, graph: CSRGraph, snap: SnapResult, cutoff_seconds: float,
    ) -> CSRSourcePaths | None:
        """Find an exact source in a live request whose search covered this cutoff."""
        location = _source_location(graph, snap)
        with self._lock:
            now = monotonic()
            for entry in reversed(self._entries.values()):
                if entry.routing.graph is not graph or entry.expires_at <= now:
                    continue
                for (cached_location, cached_cutoff), source in entry.sources.items():
                    if cached_location == location and cached_cutoff >= cutoff_seconds:
                        self._source_hits += 1
                        return source
            self._source_misses += 1
        return None

    def clear(self) -> None:
        """Release all results and cancel their expiry callbacks on shutdown."""
        with self._lock:
            for entry in self._entries.values():
                entry.expiry.cancel()
            self._entries.clear()
            self._size_bytes = 0

    def _expire(self, request_id: str) -> None:
        with self._lock:
            self._remove(request_id)

    def _remove(self, request_id: str) -> None:
        entry = self._entries.pop(request_id, None)
        if entry is not None:
            entry.expiry.cancel()
            self._size_bytes -= entry.size_bytes
