"""Run the CSR meeting pipeline in a bounded pool outside the event loop."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from threading import Lock
from time import perf_counter_ns

from app.models.requests import MeetingRequest, Optimization
from app.models.responses import MeetingResult, Timings
from app.services.coordinate_snapper import CoordinateSnapper, SnapResult
from app.services.csr_shortest_path import CSRRoutingResult, route_csr_origins
from app.services.graph_loader import CSRGraph
from app.services.meeting_optimizer import (
    build_selected_meeting_results,
    rank_candidates,
    select_candidates,
)
from app.services.meeting_routing_cache import MeetingRoutingCache


@dataclass(frozen=True)
class CSRMeetingComputation:
    """Meeting results and the source, objective, and timing data behind them."""

    results: list[MeetingResult]
    timings_ms: Timings
    reachable_nodes_by_origin: dict[str, int]
    routing: CSRRoutingResult
    objective_weights: tuple[float, ...]

    @property
    def snaps(self) -> tuple[SnapResult, ...]:
        """Expose the snapped origins in request order."""
        return tuple(source.snap for source in self.routing.sources)


class CSRMeetingService:
    """Own a process-local pool for CPU work on the shared, read-only graph."""

    def __init__(
        self, graph: CSRGraph, max_concurrent_tasks: int,
        *, snapper: CoordinateSnapper[CSRGraph] | None = None,
        routing_cache: MeetingRoutingCache | None = None,
        track_workers: bool = False,
    ) -> None:
        self._graph = graph
        self._snapper = snapper
        self._routing_cache = routing_cache
        self._worker_lock = Lock() if track_workers else None
        self._active_workers = 0
        self._peak_active_workers = 0
        self._executor = ThreadPoolExecutor(
            max_workers=max_concurrent_tasks, thread_name_prefix="w2m-csr",
        )

    async def compute(
        self, snaps: tuple[SnapResult, ...], optimization: Optimization,
    ) -> list[MeetingResult]:
        """Run overlay, routing, ranking and route building in one worker slot."""
        # Cancelling the await leaves a running thread in its slot until it finishes.
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._compute, snaps, optimization,
        )

    async def compute_request(self, request: MeetingRequest) -> CSRMeetingComputation:
        """Snap and compute a request in one worker slot, with stage timings."""
        return await self._submit(partial(self._compute_request, request))

    async def rerank(
        self, routing: CSRRoutingResult, optimization: Optimization,
    ) -> CSRMeetingComputation:
        """Rank cached paths and rebuild selected routes in a worker slot."""
        return await self._submit(partial(self._rerank, routing, optimization))

    async def _submit(self, work: Callable[[], CSRMeetingComputation]) -> CSRMeetingComputation:
        loop = asyncio.get_running_loop()
        lock = self._worker_lock
        if lock is None:
            return await loop.run_in_executor(self._executor, work)

        def run() -> CSRMeetingComputation:
            with lock:
                self._active_workers += 1
                self._peak_active_workers = max(self._peak_active_workers, self._active_workers)
            try:
                return work()
            finally:
                with lock:
                    self._active_workers -= 1

        return await loop.run_in_executor(self._executor, run)

    def peak_active_workers(self) -> int:
        """Return the high-water mark for running HTTP routing jobs."""
        if self._worker_lock is None:
            return 0
        with self._worker_lock:
            return self._peak_active_workers

    async def close(self) -> None:
        """Cancel jobs that have not started and let running jobs finish off-loop."""
        await asyncio.to_thread(self._executor.shutdown, cancel_futures=True)

    def _compute(
        self, snaps: tuple[SnapResult, ...], optimization: Optimization,
    ) -> list[MeetingResult]:
        started = perf_counter_ns()
        return self._finish(snaps, optimization, started, started).results

    def _compute_request(self, request: MeetingRequest) -> CSRMeetingComputation:
        if self._snapper is None:
            raise RuntimeError("CSR snapping index is unavailable")
        started = perf_counter_ns()
        snaps = self._snapper.snap_origins(request)
        return self._finish(snaps, request.optimization, started, perf_counter_ns())

    def _finish(
        self, snaps: tuple[SnapResult, ...], optimization: Optimization,
        started: int, snap_end: int,
    ) -> CSRMeetingComputation:
        routing = route_csr_origins(
            self._graph, snaps, optimization.max_travel_seconds,
            get_cached_source=self._routing_cache.get_source if self._routing_cache else None,
        )
        return self._rank_and_build(
            routing, optimization, started,
            snap_ms=(snap_end - started) / 1e6, dijkstra_ms=routing.dijkstra_ms,
        )

    def _rerank(
        self, routing: CSRRoutingResult, optimization: Optimization,
    ) -> CSRMeetingComputation:
        return self._rank_and_build(routing, optimization, perf_counter_ns())

    def _rank_and_build(
        self, routing: CSRRoutingResult, optimization: Optimization, started: int,
        *, snap_ms: float = 0.0, dijkstra_ms: float = 0.0,
    ) -> CSRMeetingComputation:
        reachable_nodes = {
            source.snap.origin_id: source.reachable_node_count for source in routing.sources
        }
        ranking = rank_candidates(
            routing, phi=optimization.phi, max_travel_seconds=optimization.max_travel_seconds,
        )
        selection_start = perf_counter_ns()
        selected = select_candidates(
            ranking, top_k=optimization.top_k, min_spacing_meters=optimization.min_spacing_meters,
        )
        routes_start = perf_counter_ns()
        results = build_selected_meeting_results(ranking, selected)
        ended = perf_counter_ns()
        timings = Timings(
            snap=snap_ms,
            dijkstra=dijkstra_ms,
            scan=ranking.scan_ms,
            rank=ranking.rank_ms + (routes_start - selection_start) / 1e6,
            routes=(ended - routes_start) / 1e6,
            total=(ended - started) / 1e6,
        )
        return CSRMeetingComputation(results, timings, reachable_nodes, routing, ranking.weights)
