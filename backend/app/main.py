import asyncio
import json
import logging
import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import file_digest
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.meeting import router, unavailable
from app.config.settings import get_settings
from app.models.responses import ErrorResponse
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.csr_meeting_service import CSRMeetingService
from app.services.graph_loader import load_csr_graph
from app.services.meeting_routing_cache import MeetingRoutingCache

logger = logging.getLogger("uvicorn.error.w2m")


def _container_resources() -> dict[str, str]:
    cgroup = Path("/sys/fs/cgroup")
    resources = {}
    # cgroup v2 exposes the kernel-recorded peak even between HTTP samples.
    for name in ("cpu.max", "memory.max", "memory.current", "memory.peak", "memory.events"):
        try:
            resources[name] = (cgroup / name).read_text(encoding="ascii").strip()
        except OSError:
            continue
    return resources


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        cache = MeetingRoutingCache(ttl_seconds=settings.cache_ttl_seconds,
                                    max_bytes=settings.cache_max_bytes)
        app.state.meeting_routing_cache = cache
        app.state.csr_graph = None
        app.state.csr_meeting_service = None
        service = None
        try:
            load_started = perf_counter()
            graph = await asyncio.to_thread(load_csr_graph, settings.graph_dir)
            index_started = perf_counter()
            snapper = await asyncio.to_thread(CoordinateSnapper, graph, settings)
            index_finished = perf_counter()
        except (BadZipFile, EOFError, KeyError, OSError, ParseError, TypeError, ValueError) as exc:
            logger.warning("CSR graph unavailable (%s)", type(exc).__name__)
        else:
            service = CSRMeetingService(
                graph, settings.csr_max_concurrent_tasks, snapper=snapper, routing_cache=cache,
                track_workers=settings.benchmark_diagnostics,
            )
            if settings.benchmark_diagnostics:
                with (settings.graph_dir / "metadata.json").open("rb") as metadata:
                    metadata_sha256 = file_digest(metadata, "sha256").hexdigest()
                app.state.benchmark_startup = {
                    "graph_load_ms": (index_started - load_started) * 1000,
                    "coordinate_snapper_init_ms": (index_finished - index_started) * 1000,
                    "strtree_build_ms": snapper.tree_build_ms,
                    "graph_version": graph.graph_version,
                    "weight_profile_version": graph.weight_profile_version,
                    "metadata_sha256": metadata_sha256,
                    "worker_limit": settings.csr_max_concurrent_tasks,
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "libraries": {name: version(name) for name in (
                        "fastapi", "uvicorn", "numpy", "scipy", "shapely", "pyproj",
                    )},
                }
            app.state.csr_graph = graph
            app.state.csr_meeting_service = service
            logger.info(
                "CSR graph ready graph=%s profile=%s load_ms=%.2f strtree_ms=%.2f",
                graph.graph_version, graph.weight_profile_version,
                (index_started - load_started) * 1000, snapper.tree_build_ms,
            )
        try:
            yield
        finally:
            cache.clear()
            app.state.csr_graph = None
            app.state.csr_meeting_service = None
            if service is not None:
                await service.close()

    app = FastAPI(title="W2M API", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings

    @app.middleware("http")
    async def request_identity(request: Request, call_next):
        started = perf_counter()
        request.state.request_id = uuid4().hex
        error_type = None
        try:
            response = await call_next(request)
        except Exception as exc:
            # Exception messages may contain precise request coordinates.
            error_type = type(exc).__name__
            response = JSONResponse(status_code=500, content={
                "error_code": "INTERNAL_ERROR", "message": "Không thể xử lý yêu cầu.",
                "request_id": request.state.request_id,
            })
        response.headers["X-Request-ID"] = request.state.request_id
        # The registered template excludes the raw path/query and the rerank cache ID.
        route = getattr(request.scope.get("route"), "path", None)
        if response.status_code >= 400 or route not in {"/health", "/ready"}:
            graph = getattr(request.app.state, "csr_graph", None)
            timings = getattr(request.state, "meeting_timings", None)
            record = {
                "request_id": request.state.request_id,
                "route": route,
                "status": response.status_code,
                "server_ms": round((perf_counter() - started) * 1000, 3),
                "graph_version": graph.graph_version if graph is not None else None,
                "weight_profile_version": (
                    graph.weight_profile_version if graph is not None else None
                ),
                "timings_ms": timings.model_dump() if timings is not None else None,
                "error_type": error_type,
            }
            level = logging.ERROR if response.status_code >= 500 else logging.INFO
            logger.log(level, "request %s", json.dumps(record, separators=(",", ":")))
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        coordinate_error = any(
            len(location) == 4 and location[:2] == ("body", "origins")
            and location[3] in ("lat", "lon")
            for location in (error["loc"] for error in exc.errors())
        )
        return JSONResponse(status_code=400, content={
            "error_code": "INVALID_COORDINATES" if coordinate_error else "INVALID_PARAMETERS",
            "message": "Tọa độ không hợp lệ." if coordinate_error else "Tham số không hợp lệ.",
            "request_id": request.state.request_id,
        })

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "w2m", "version": "0.2.0"}

    @app.get("/ready", responses={503: {"model": ErrorResponse}})
    def ready(request: Request) -> JSONResponse:
        if getattr(request.app.state, "csr_graph", None) is None:
            return unavailable(request)
        response = JSONResponse(content={"status": "ready"})
        if settings.benchmark_diagnostics and request.headers.get("X-W2M-Benchmark") == "1":
            state = request.app.state
            response.headers["X-W2M-Benchmark"] = json.dumps({
                **state.benchmark_startup,
                "cache": state.meeting_routing_cache.statistics(),
                "peak_active_workers": state.csr_meeting_service.peak_active_workers(),
                "cgroup": _container_resources(),
            }, ensure_ascii=True, separators=(",", ":"))
        return response

    app.include_router(router)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    return app


app = create_app()
