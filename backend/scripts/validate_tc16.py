"""Compare production CSR and NetworkX on reproducible offline TC-16 requests."""

import argparse
import asyncio
import json
import platform
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely import covers, distance, get_coordinates, line_interpolate_point, points, transform

from app.config.settings import Settings
from app.models.requests import MeetingRequest, Optimization, Origin
from app.models.responses import MeetingResult
from app.services.area import METRIC_CRS, WGS84_CRS
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.csr_meeting_service import CSRMeetingService
from app.services.graph_loader import CSRGraph, load_csr_graph, load_reference_graph
from app.services.meeting_optimizer import build_meeting_results, rank_candidates
from app.services.shortest_path import route_origins
from scripts.download_osm import _sha256

REQUEST_COUNT = 1000
DEFAULT_SEED = 20261120
BOUNDARY_METERS = 1000
SCENARIOS = ("near", "far", "boundary")
SCORE_TOLERANCE_TICKS = 1


def sample_requests(
    snapper: CoordinateSnapper[CSRGraph], request_count: int, seed: int,
) -> Iterator[tuple[str, MeetingRequest]]:
    """Draw four sources from in-AOI road interiors in each spatial scenario."""
    aoi = snapper.reference.aoi
    to_wgs84 = Transformer.from_crs(METRIC_CRS, WGS84_CRS, always_xy=True)
    to_metric = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    samples = line_interpolate_point(snapper.tree.geometries, 0.5, normalized=True)
    xy = np.unique(get_coordinates(samples), axis=0)
    lonlat = np.column_stack(to_wgs84.transform(xy[:, 0], xy[:, 1], errcheck=True))
    in_aoi = covers(aoi, points(lonlat))
    xy, lonlat = xy[in_aoi], lonlat[in_aoi]
    metric_boundary = transform(aoi, to_metric.transform, interleaved=False).boundary
    boundary = np.flatnonzero(distance(points(xy), metric_boundary) <= BOUNDARY_METERS)
    if len(xy) < 4 or len(boundary) < 4:
        raise ValueError("TC-16 needs four distinct road samples in both AOI and boundary band")
    major_axis = int(np.argmax(np.ptp(xy, axis=0)))
    bands = np.array_split(np.argsort(xy[:, major_axis], kind="stable"), 4)
    tree = cKDTree(xy)
    rng = np.random.default_rng(seed)
    for case in range(request_count):
        scenario = SCENARIOS[case % len(SCENARIOS)]
        if scenario == "near":
            anchor = int(rng.integers(len(xy)))
            _, neighbors = tree.query(xy[anchor], k=min(16, len(xy)))
            indices = rng.choice(neighbors, size=4, replace=False)
        elif scenario == "far":
            indices = [rng.choice(band) for band in bands]
        else:
            indices = rng.choice(boundary, size=4, replace=False)
        origins = [
            Origin(id=label, lon=float(lon), lat=float(lat))
            for label, (lon, lat) in zip("ABCD", lonlat[indices], strict=True)
        ]
        yield scenario, MeetingRequest(
            origins=origins, travel_mode="car",
            optimization=Optimization(
                phi=int(rng.integers(11)) / 10,
                max_travel_seconds=int(rng.choice((300, 900, 1800, 3600, 7200))),
                top_k=5, min_spacing_meters=500,
            ),
        )


def compare_results(
    actual: list[MeetingResult], expected: list[MeetingResult], origin_ids: set[str],
) -> tuple[int, int]:
    """Check ordered nodes, score tolerance and route fields after raw-cost validation."""
    actual_order = [(result.rank, result.node_id) for result in actual]
    expected_order = [(result.rank, result.node_id) for result in expected]
    if actual_order != expected_order:
        raise ValueError(f"Ranked nodes differ: CSR {actual_order}, NetworkX {expected_order}")
    score_error = max((
        abs(round(10 * csr.score) - round(10 * nx.score))
        for csr, nx in zip(actual, expected, strict=True)
    ), default=0)
    if score_error > SCORE_TOLERANCE_TICKS:
        raise ValueError(f"Score difference exceeds 0.1 seconds: {score_error / 10}s")
    for result in actual:
        if result.routes.keys() != origin_ids or result.travel_times.keys() != origin_ids:
            raise ValueError("CSR result does not include exactly the requested origins")
        for origin, route in result.routes.items():
            if (route.duration_seconds != result.travel_times[origin]
                    or round(10 * route.access_seconds) + round(10 * route.network_seconds)
                    != round(10 * route.duration_seconds)):
                raise ValueError(f"CSR route times differ at node {result.node_id}")
    return score_error, sum(len(result.routes) for result in actual)


async def _compare_bundle(bundle: Path, request_count: int, seed: int) -> dict:
    settings = Settings(_env_file=None)
    graph = load_csr_graph(bundle)
    reference = load_reference_graph(bundle)
    csr_snapper = CoordinateSnapper(graph, settings)
    reference_snapper = CoordinateSnapper(reference, settings)
    service = CSRMeetingService(graph, max_concurrent_tasks=1, snapper=csr_snapper)
    cases = []
    try:
        for index, (scenario, request) in enumerate(
            sample_requests(csr_snapper, request_count, seed), start=1,
        ):
            options = request.optimization
            case = {"index": index, "scenario": scenario, "optimization": options.model_dump()}
            try:
                csr = await service.compute_request(request)
                routing = route_origins(reference_snapper, request)
                ranking = rank_candidates(
                    routing, phi=options.phi, max_travel_seconds=options.max_travel_seconds,
                )
                expected = build_meeting_results(
                    ranking, top_k=options.top_k, min_spacing_meters=options.min_spacing_meters,
                )
                score_error, route_count = compare_results(
                    csr.results, expected, {origin.id for origin in request.origins},
                )
            except ValueError as exc:
                cases.append({**case, "error": str(exc)})
                break
            cases.append({
                **case, "result_count": len(csr.results), "validated_routes": route_count,
                "max_score_error_seconds": score_error / 10,
            })
            if index % 25 == 0:
                print(f"Compared {index}/{request_count} requests", flush=True)
    finally:
        await service.close()
    passed = [case for case in cases if "error" not in case]
    return {
        "status": "passed" if len(passed) == request_count else "failed",
        "graph_version": graph.graph_version,
        "weight_profile_version": graph.weight_profile_version,
        "snap_max_m": settings.snap_max_m,
        "access_speed_mps": settings.access_speed_mps,
        "passed_requests": len(passed),
        "validated_routes": sum(case["validated_routes"] for case in passed),
        "max_score_error_seconds": max(
            (case["max_score_error_seconds"] for case in passed), default=None,
        ),
        "cases": cases,
    }


def validate_tc16(bundle: Path, output: Path, request_count: int, seed: int) -> dict:
    """Write offline comparison evidence, preserving the first mismatch if one occurs."""
    if request_count < 1 or seed < 0:
        raise ValueError("Expected a positive request count and a non-negative seed")
    if output.exists():
        raise FileExistsError(f"Choose a new report path: {output}")
    started_at = datetime.now(UTC)
    backend = Path(__file__).resolve().parents[1]
    report = {
        "schema_version": 1,
        "scope": "tc16" if request_count >= REQUEST_COUNT else "smoke",
        "started_at": started_at.isoformat(),
        "seed": seed,
        "requested_requests": request_count,
        "early_stopping_enabled": False,
        "source_metadata_sha256": _sha256(bundle / "metadata.json"),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=backend, text=True,
        ).strip(),
        "implementation_sha256": {
            str(path.relative_to(backend)): _sha256(path)
            for path in (Path(__file__).resolve(), *sorted((backend / "app/services").glob("*.py")))
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "libraries": {name: version(name) for name in (
                "networkx", "numpy", "scipy", "shapely", "pyproj", "osmnx",
            )},
        },
        **asyncio.run(_compare_bundle(bundle, request_count, seed)),
        "finished_at": datetime.now(UTC).isoformat(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    """Run the offline CLI with the full TC-16 request count by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests", type=int, default=REQUEST_COUNT)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    try:
        report = validate_tc16(args.bundle_dir, args.output, args.requests, args.seed)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(f"{report['scope']}: {report['status']}, report: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
