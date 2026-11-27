"""Measure the Docker meeting API on deterministic Hanoi road-network requests."""

import argparse
import json
import platform
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import file_digest
from math import ceil
from pathlib import Path
from statistics import median
from threading import Barrier
from time import perf_counter
from typing import Any

import httpx

from app.config.settings import Settings
from app.models.requests import MeetingRequest
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.graph_loader import load_csr_graph
from scripts.validate_tc16 import DEFAULT_SEED, REQUEST_COUNT, sample_requests

MEETING_PATH = "/api/v1/meeting-points"
WARMUP_COUNT = 20
CONCURRENT_COUNT = 50
COMPUTE_P95_MS = 5000
RERANK_P95_MS = 300
MEMORY_LIMIT_BYTES = 8 * 1024 ** 3
BENCHMARK_HEADER = "X-W2M-Benchmark"


def _diagnostics(client: httpx.Client) -> dict[str, Any]:
    response = client.get("/ready", headers={BENCHMARK_HEADER: "1"})
    if response.status_code != 200 or BENCHMARK_HEADER not in response.headers:
        raise ValueError("Backend must be ready with benchmark diagnostics enabled")
    return json.loads(response.headers[BENCHMARK_HEADER])


def _post(
    client: httpx.Client, path: str, payload: dict[str, Any], scenario: str,
) -> tuple[dict[str, Any], str | None]:
    started = perf_counter()
    try:
        response = client.post(path, json=payload)
    except httpx.RequestError as exc:
        return {
            "scenario": scenario,
            "http_status": None,
            "transport_error": type(exc).__name__,
            "http_ms": (perf_counter() - started) * 1000,
        }, None
    sample = {
        "scenario": scenario,
        "http_status": response.status_code,
        "http_ms": (perf_counter() - started) * 1000,
        "response_bytes": len(response.content),
    }
    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = {}
        error_code = body.get("error_code") if isinstance(body, dict) else None
        return {**sample, "error_code": error_code}, None
    body = response.json()
    return {
        **sample,
        "timings_ms": body["timings_ms"],
        "result_status": body["status"],
    }, body["request_id"]


def _distribution(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {"p50": median(ordered), "p95": ordered[ceil(len(ordered) * 0.95) - 1],
            "max": ordered[-1]}


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [sample for sample in samples if sample["http_status"] == 200]
    return {
        "requests": len(samples),
        "successful": len(successful),
        "http_status_counts": dict(Counter(
            str(sample["http_status"]) if sample["http_status"] is not None else "transport_error"
            for sample in samples
        )),
        "scenarios": dict(Counter(sample["scenario"] for sample in samples)),
        "http_ms": _distribution([sample["http_ms"] for sample in successful]),
        "response_bytes": _distribution([sample["response_bytes"] for sample in successful]),
        "timings_ms": {
            stage: _distribution([sample["timings_ms"][stage] for sample in successful])
            for stage in ("snap", "dijkstra", "scan", "rank", "routes", "total")
        },
    }


def _rerank_payload(request: MeetingRequest, index: int) -> dict[str, Any]:
    options = request.optimization.model_dump()
    return {"optimization": {
        **options,
        "phi": (round(options["phi"] * 10) + 1 + index % 10) % 11 / 10,
        "top_k": 1 + index % 5,
        "min_spacing_meters": (0, 500, 1000)[index % 3],
        "max_travel_seconds": max(300, options["max_travel_seconds"] - 300 * (index % 2)),
    }}


def _cache_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    return {
        name: after["cache"][name] - before["cache"][name]
        for name in ("evictions", "source_hits", "source_misses", "request_hits", "request_misses")
    }


def _run_workloads(
    client: httpx.Client, cases: list[tuple[str, MeetingRequest]], request_count: int,
    before: dict[str, Any],
) -> dict[str, Any]:
    warmup = []
    warmup_payload = cases[0][1].model_dump(mode="json")
    first_request_id = None
    first_request_started = perf_counter()
    for scenario, request in cases[:WARMUP_COUNT]:
        sample, request_id = _post(client, MEETING_PATH, request.model_dump(mode="json"), scenario)
        warmup.append(sample)
        if len(warmup) == 1:
            first_request_id = request_id
    after_warmup = _diagnostics(client)
    repeats = [_post(client, MEETING_PATH, warmup_payload, "repeat")[0] for _ in range(4)]
    after_repeats = _diagnostics(client)

    compute, rerank = [], []
    eviction_probe = None
    sequential = cases[WARMUP_COUNT:WARMUP_COUNT + request_count]
    for index, (scenario, request) in enumerate(sequential):
        sample, request_id = _post(client, MEETING_PATH, request.model_dump(mode="json"), scenario)
        compute.append(sample)
        if request_id is not None:
            sample, _ = _post(
                client, f"{MEETING_PATH}/{request_id}/rerank", _rerank_payload(request, index),
                scenario,
            )
            rerank.append(sample)
        if (index + 1) % 25 == 0 and first_request_id is not None and eviction_probe is None:
            current = _diagnostics(client)
            if current["cache"]["evictions"] > before["cache"]["evictions"]:
                eviction_probe, _ = _post(
                    client, f"{MEETING_PATH}/{first_request_id}/rerank",
                    {"optimization": warmup_payload["optimization"]}, "old_request",
                )
                eviction_probe["max_age_seconds"] = perf_counter() - first_request_started
        if (index + 1) % 100 == 0:
            print(f"Measured {index + 1}/{request_count} compute/rerank pairs", flush=True)
    before_burst = _diagnostics(client)

    print(f"Starting {CONCURRENT_COUNT} concurrent compute requests", flush=True)
    barrier = Barrier(CONCURRENT_COUNT)

    def concurrent_compute(case: tuple[str, MeetingRequest]) -> dict[str, Any]:
        scenario, request = case
        payload = request.model_dump(mode="json")
        barrier.wait(timeout=30)
        return _post(client, MEETING_PATH, payload, scenario)[0]

    with ThreadPoolExecutor(max_workers=CONCURRENT_COUNT) as pool:
        burst = list(pool.map(concurrent_compute, cases[-CONCURRENT_COUNT:]))
    after_burst = _diagnostics(client)
    return {
        "workloads": {
            "warmup": _summarize(warmup),
            "repeat": _summarize(repeats),
            "compute": _summarize(compute),
            "rerank": _summarize(rerank),
            "compute_concurrent_50": _summarize(burst),
        },
        "cache_deltas": {
            "warmup": _cache_delta(before, after_warmup),
            "repeat": _cache_delta(after_warmup, after_repeats),
            "sequential_pairs_and_eviction_probe": _cache_delta(after_repeats, before_burst),
            "concurrent_50": _cache_delta(before_burst, after_burst),
        },
        "eviction_probe": eviction_probe,
        "server_before_concurrent": before_burst,
        "server_after_concurrent": after_burst,
    }


def _checks(report: dict[str, Any], request_count: int) -> dict[str, bool]:
    phases = report["workloads"]
    server = report["server_after_concurrent"]
    cache = server["cache"]
    cgroup = server["cgroup"]
    cpu_limit = cgroup.get("cpu.max", "").split()
    memory_limit = cgroup.get("memory.max", "")
    memory_peak = cgroup.get("memory.peak", "")
    memory_events = dict(line.split() for line in cgroup.get("memory.events", "").splitlines())
    expected = {
        "warmup": WARMUP_COUNT, "repeat": 4, "compute": request_count,
        "rerank": request_count, "compute_concurrent_50": CONCURRENT_COUNT,
    }
    checks = {
        "all_requests_succeeded": all(
            phases[name]["successful"] == count for name, count in expected.items()
        ),
        "container_has_expected_limits": (
            len(cpu_limit) == 2 and cpu_limit[0].isdigit() and cpu_limit[1].isdigit()
            and int(cpu_limit[0]) == 4 * int(cpu_limit[1])
            and memory_limit == str(MEMORY_LIMIT_BYTES)
        ),
        "cache_respects_byte_budget": 0 < cache["peak_bytes"] <= cache["max_bytes"],
        "repeat_reuses_source_paths": report["cache_deltas"]["repeat"]["source_hits"] > 0,
        "rerank_reuses_cached_routes": (
            report["cache_deltas"]["sequential_pairs_and_eviction_probe"]["request_hits"]
            == request_count
            and (phases["rerank"]["timings_ms"]["dijkstra"] or {}).get("max") == 0
        ),
        "routing_workers_stayed_bounded": (
            0 < server["peak_active_workers"] <= server["worker_limit"]
        ),
        "container_stayed_within_memory_limit": (
            memory_peak.isdigit() and 0 < int(memory_peak) <= MEMORY_LIMIT_BYTES
            and memory_events.get("oom_kill") == "0" and memory_events.get("oom") == "0"
        ),
    }
    if request_count >= REQUEST_COUNT:
        probe = report["eviction_probe"] or {}
        checks.update({
            "compute_http_p95_within_target": (
                (phases["compute"]["http_ms"] or {}).get("p95", float("inf")) <= COMPUTE_P95_MS
            ),
            "rerank_http_p95_within_target": (
                (phases["rerank"]["http_ms"] or {}).get("p95", float("inf")) <= RERANK_P95_MS
            ),
            "old_request_requires_recompute_after_eviction": (
                probe.get("http_status") == 409
                and probe.get("error_code") == "RECOMPUTE_REQUIRED"
                and probe["max_age_seconds"] < cache["ttl_seconds"]
            ),
        })
    return checks


def _host_cpu() -> str:
    if platform.system() == "Darwin":
        try:
            return subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return platform.processor() or platform.machine()


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def main(argv: list[str] | None = None) -> int:
    """Write a new benchmark report and return a failure status for unmet checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument("--requests", type=int, default=REQUEST_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--objective-type", choices=("owa_geometric", "mean_spread_v1"),
                        default="owa_geometric")
    args = parser.parse_args(argv)
    if args.requests < 1 or args.seed < 0:
        parser.error("Expected a positive request count and a non-negative seed")
    if args.output.exists():
        parser.error("Choose a new report path")

    root = Path(__file__).resolve().parents[2]
    source_paths = (
        *sorted((root / "backend/app").rglob("*.py")),
        Path(__file__).resolve(), root / "backend/scripts/validate_tc16.py",
        root / "backend/uv.lock", root / "backend/Dockerfile",
        root / "compose.yaml", root / "compose.benchmark.yaml",
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "m6" if args.requests >= REQUEST_COUNT else "smoke",
        "seed": args.seed,
        "objective_type": args.objective_type,
        "request_pairs": args.requests,
        "sequential_concurrency": 1,
        "burst_concurrency": CONCURRENT_COUNT,
        "http_p95_targets_ms": {"compute": COMPUTE_P95_MS, "rerank": RERANK_P95_MS},
        "host": {"platform": platform.platform(), "cpu": _host_cpu()},
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        ).strip(),
        "git_worktree_dirty": bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True,
        )),
        "host_source_sha256": {
            str(path.relative_to(root)): _file_sha256(path) for path in source_paths
        },
    }
    try:
        metadata_sha256 = _file_sha256(args.bundle_dir / "metadata.json")
        graph = load_csr_graph(args.bundle_dir)
        snapper = CoordinateSnapper(graph, Settings(_env_file=None))
        cases = list(sample_requests(
            snapper, WARMUP_COUNT + args.requests + CONCURRENT_COUNT, args.seed,
            objective_type=args.objective_type,
        ))
        with httpx.Client(
            base_url=args.base_url, timeout=120, trust_env=False,
            limits=httpx.Limits(max_connections=CONCURRENT_COUNT),
        ) as client:
            before = _diagnostics(client)
            report["server_start"] = before
            if (before["graph_version"], before["weight_profile_version"],
                    before["metadata_sha256"]) != (
                graph.graph_version, graph.weight_profile_version, metadata_sha256,
            ):
                raise ValueError("Server graph/profile versions differ from the sample bundle")
            report.update(_run_workloads(client, cases, args.requests, before))
        report["checks"] = _checks(report, args.requests)
        report["status"] = "passed" if all(report["checks"].values()) else "failed"
    except httpx.HTTPError as exc:
        report.update(status="failed", error=type(exc).__name__)
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        report.update(status="failed", error=str(exc))

    report["finished_at"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(f"{report['scope']}: {report['status']}, report: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
