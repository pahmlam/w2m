"""Run the CSR meeting pipeline in a bounded pool outside the event loop."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.models.requests import Optimization
from app.models.responses import MeetingResult
from app.services.coordinate_snapper import SnapResult
from app.services.csr_shortest_path import route_csr_origins
from app.services.graph_loader import CSRGraph
from app.services.meeting_optimizer import build_meeting_results, rank_candidates


class CSRMeetingService:
    """Own a process-local pool for CPU work on the shared, read-only graph."""

    def __init__(self, graph: CSRGraph, max_concurrent_tasks: int) -> None:
        self._graph = graph
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

    async def close(self) -> None:
        """Cancel jobs that have not started and let running jobs finish off-loop."""
        await asyncio.to_thread(self._executor.shutdown, cancel_futures=True)

    def _compute(
        self, snaps: tuple[SnapResult, ...], optimization: Optimization,
    ) -> list[MeetingResult]:
        limit = optimization.max_travel_seconds
        routing = route_csr_origins(self._graph, snaps, limit)
        ranking = rank_candidates(routing, phi=optimization.phi, max_travel_seconds=limit)
        return build_meeting_results(
            ranking, top_k=optimization.top_k, min_spacing_meters=optimization.min_spacing_meters,
        )
