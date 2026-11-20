"""Run the CSR meeting pipeline in a bounded pool outside the event loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter_ns

from app.models.requests import MeetingRequest, Optimization
from app.models.responses import MeetingResult, Timings
from app.services.coordinate_snapper import CoordinateSnapper, SnapResult
from app.services.csr_shortest_path import route_csr_origins
from app.services.graph_loader import CSRGraph
from app.services.meeting_optimizer import (
    build_selected_meeting_results,
    rank_candidates,
    select_candidates,
)


@dataclass(frozen=True)
class CSRMeetingComputation:
    """Meeting results and elapsed worker time per pipeline stage."""

    results: list[MeetingResult]
    timings_ms: Timings


class CSRMeetingService:
    """Own a process-local pool for CPU work on the shared, read-only graph."""

    def __init__(
        self, graph: CSRGraph, max_concurrent_tasks: int,
        *, snapper: CoordinateSnapper[CSRGraph] | None = None,
    ) -> None:
        self._graph = graph
        self._snapper = snapper
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
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._compute_request, request,
        )

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
        limit = optimization.max_travel_seconds
        routing = route_csr_origins(self._graph, snaps, limit)
        ranking = rank_candidates(routing, phi=optimization.phi, max_travel_seconds=limit)
        selection_start = perf_counter_ns()
        selected = select_candidates(
            ranking, top_k=optimization.top_k, min_spacing_meters=optimization.min_spacing_meters,
        )
        routes_start = perf_counter_ns()
        results = build_selected_meeting_results(ranking, selected)
        ended = perf_counter_ns()
        return CSRMeetingComputation(results, Timings(
            snap=(snap_end - started) / 1e6,
            dijkstra=routing.dijkstra_ms,
            scan=ranking.scan_ms,
            rank=ranking.rank_ms + (routes_start - selection_start) / 1e6,
            routes=(ended - routes_start) / 1e6,
            total=(ended - started) / 1e6,
        ))
