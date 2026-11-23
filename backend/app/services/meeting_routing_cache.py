"""Retain request-local routing tables within a process-local byte budget."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from app.services.csr_shortest_path import CSRRoutingResult

# Allow for the small Python objects and temporary-source rows in a request.
ENTRY_OVERHEAD_BYTES = 8192


@dataclass(frozen=True)
class _Entry:
    routing: CSRRoutingResult
    size_bytes: int
    expiry: asyncio.TimerHandle


def _routing_size_bytes(routing: CSRRoutingResult) -> int:
    matrix = routing.overlay.csr
    arrays = [matrix.data, matrix.indices, matrix.indptr]
    for source in routing.sources:
        arrays.extend((source.distances_seconds, source.predecessors))
    return ENTRY_OVERHEAD_BYTES + sum(array.nbytes for array in arrays)


class MeetingRoutingCache:
    """Use from the owning event loop so reads, writes, and expiry stay atomic."""

    def __init__(self, *, ttl_seconds: int, max_bytes: int) -> None:
        self._loop = asyncio.get_running_loop()
        self._ttl_seconds = ttl_seconds
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._size_bytes = 0

    def put(self, request_id: str, routing: CSRRoutingResult) -> None:
        """Store the full routing result under its response ID if it fits."""
        size_bytes = _routing_size_bytes(routing)
        self._remove(request_id)
        if size_bytes > self._max_bytes:
            return
        while self._size_bytes + size_bytes > self._max_bytes:
            self._remove(next(iter(self._entries)))
        expiry = self._loop.call_later(self._ttl_seconds, self._remove, request_id)
        self._entries[request_id] = _Entry(routing, size_bytes, expiry)
        self._size_bytes += size_bytes

    def get(self, request_id: str) -> CSRRoutingResult | None:
        """Retrieve current tables and refresh recency without extending expiry."""
        entry = self._entries.get(request_id)
        if entry is None:
            return None
        if entry.expiry.when() <= self._loop.time():
            self._remove(request_id)
            return None
        self._entries.move_to_end(request_id)
        return entry.routing

    def clear(self) -> None:
        """Release all results and cancel their expiry callbacks on shutdown."""
        for entry in self._entries.values():
            entry.expiry.cancel()
        self._entries.clear()
        self._size_bytes = 0

    def _remove(self, request_id: str) -> None:
        entry = self._entries.pop(request_id, None)
        if entry is not None:
            entry.expiry.cancel()
            self._size_bytes -= entry.size_bytes
