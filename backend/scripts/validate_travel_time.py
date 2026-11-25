"""Prepare public road samples and compare travel times with an independent source."""

import argparse
import asyncio
import csv
import json
import platform
from collections import Counter
from datetime import UTC, datetime
from math import ceil, isfinite
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.csr_meeting_service import CSRMeetingService
from app.services.graph_loader import load_csr_graph
from scripts.download_osm import _sha256
from scripts.validate_tc16 import DEFAULT_SEED, SCENARIOS, sample_requests

MIN_COMPLETE_GROUPS = 25
LOCAL_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


async def prepare_samples(bundle: Path, groups_per_scenario: int, seed: int) -> dict:
    """Select distinct positive-length routes to one meeting point per group."""
    graph = load_csr_graph(bundle)
    snapper = CoordinateSnapper(graph, Settings(_env_file=None))
    service = CSRMeetingService(graph, max_concurrent_tasks=1, snapper=snapper)
    counts: Counter[str] = Counter()
    pairs = set()
    groups = []
    try:
        for index, (scenario, request) in enumerate(
            sample_requests(snapper, groups_per_scenario * len(SCENARIOS) * 10, seed), start=1,
        ):
            if counts[scenario] >= groups_per_scenario:
                continue
            request.optimization = request.optimization.model_copy(
                update={"top_k": 1, "max_travel_seconds": 7200, "phi": 0.5},
            )
            computation = await service.compute_request(request)
            if not computation.results:
                continue
            result = computation.results[0]
            destination = (result.location.lon, result.location.lat)
            routes = []
            target = graph.node_indices[result.node_id]
            for source in computation.routing.sources:
                snap = source.snap
                routes.append({
                    "route_id": f"{index:03d}-{snap.origin_id}",
                    "origin_lonlat": snap.snapped_lonlat,
                    "network_seconds": float(source.distances_seconds[target]),
                    "access_seconds": snap.access_seconds,
                    "distance_meters": result.routes[snap.origin_id].distance_meters,
                })
            group_pairs = {
                (tuple(round(x, 7) for x in row["origin_lonlat"]),
                 tuple(round(x, 7) for x in destination))
                for row in routes
            }
            if (len(group_pairs) != 4 or pairs.intersection(group_pairs)
                    or any(row["distance_meters"] <= 0 for row in routes)):
                continue
            pairs.update(group_pairs)
            groups.append({
                "group_id": index, "scenario": scenario, "meeting_node_id": result.node_id,
                "destination_lonlat": destination, "routes": routes,
            })
            counts[scenario] += 1
            if len(groups) == groups_per_scenario * len(SCENARIOS):
                break
    finally:
        await service.close()
    if len(groups) != groups_per_scenario * len(SCENARIOS):
        raise ValueError(f"Insufficient eligible groups: {dict(counts)}")
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "platform": platform.platform(),
        "graph_version": graph.graph_version,
        "weight_profile_version": graph.weight_profile_version,
        "bundle_metadata_sha256": _sha256(bundle / "metadata.json"),
        "scenario_counts": dict(counts),
        "groups": groups,
    }


def _errors(values: list[float]) -> dict | None:
    if not values:
        return None
    absolute = sorted(abs(value) for value in values)
    return {
        "mean_signed_seconds": mean(values),
        "mean_absolute_seconds": mean(absolute),
        "median_absolute_seconds": median(absolute),
        "p90_absolute_seconds": absolute[ceil(len(values) * 0.9) - 1],
    }


def compare_times(sample: dict, observations: list[dict], source: str, kind: str) -> dict:
    """Compare both providers on the same endpoints and offsets for complete groups."""
    known_ids = {row["route_id"] for group in sample["groups"] for row in group["routes"]}
    by_id = {}
    for row in observations:
        route_id = row["route_id"]
        if route_id not in known_ids or route_id in by_id:
            raise ValueError(f"Unexpected or duplicate route ID: {route_id}")
        value = row["reference_seconds"]
        if value:
            seconds = float(value)
            if not isfinite(seconds) or seconds <= 0:
                raise ValueError(f"Invalid duration for {route_id}")
            if kind == "off-peak":
                departure = datetime.fromisoformat(row.get("departure_at", ""))
                if departure.utcoffset() is None:
                    raise ValueError(f"Include a timezone in departure_at for {route_id}")
                row = {**row, "departure_at": departure.astimezone(LOCAL_ZONE).isoformat()}
        by_id[route_id] = row

    routes, groups, missing = [], [], []
    errors_by_scenario: dict[str, list[float]] = {}
    for group in sample["groups"]:
        w2m_times = []
        reference_times = []
        for item in group["routes"]:
            identifier = item["route_id"]
            row = by_id.get(identifier)
            if row is None:
                missing.append({"route_id": identifier, "reason": "missing_observation"})
                continue
            if not row["reference_seconds"]:
                reason = row.get("reason") or "missing_duration"
                missing.append({"route_id": identifier, "reason": reason})
                continue
            reference = float(row["reference_seconds"])
            network = item["network_seconds"]
            access = item["access_seconds"]
            error = network - reference
            w2m_times.append(network + access)
            reference_times.append(reference + access)
            errors_by_scenario.setdefault(group["scenario"], []).append(error)
            routes.append({
                "route_id": identifier, "scenario": group["scenario"],
                "departure_at": row.get("departure_at") or None,
                "network_seconds": network, "reference_seconds": reference,
                "access_seconds": access, "signed_error_seconds": error,
                "absolute_error_seconds": abs(error),
            })
        if len(w2m_times) == 4:
            w2m_spread = max(w2m_times) - min(w2m_times)
            reference_spread = max(reference_times) - min(reference_times)
            groups.append({
                "group_id": group["group_id"], "scenario": group["scenario"],
                "w2m_spread_seconds": w2m_spread, "reference_spread_seconds": reference_spread,
                "signed_error_seconds": w2m_spread - reference_spread,
            })
    sufficient = len(groups) >= MIN_COMPLETE_GROUPS
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "reference_source": source,
        "reference_kind": kind,
        "graph_version": sample["graph_version"],
        "weight_profile_version": sample["weight_profile_version"],
        "bundle_metadata_sha256": sample["bundle_metadata_sha256"],
        "seed": sample["seed"],
        "expected_routes": len(known_ids),
        "compared_routes": len(routes),
        "complete_groups": len(groups),
        "sufficient_complete_groups": sufficient,
        "off_peak_sample_complete": sufficient and kind == "off-peak",
        "network_error_seconds": _errors([row["signed_error_seconds"] for row in routes]),
        "network_error_by_scenario": {name: _errors(values)
                                      for name, values in errors_by_scenario.items()},
        "spread_error_seconds": _errors([row["signed_error_seconds"] for row in groups]),
        "missing": missing,
        "routes": routes,
        "groups": groups,
    }


def main(argv: list[str] | None = None) -> int:
    """Generate the sample or write a report from an existing observation CSV."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("sample")
    prepare.add_argument("--bundle-dir", type=Path, required=True)
    prepare.add_argument("--groups-per-scenario", type=int, default=14)
    prepare.add_argument("--seed", type=int, default=DEFAULT_SEED)
    compare = commands.add_parser("compare")
    compare.add_argument("--sample", type=Path, required=True)
    compare.add_argument("--observations", type=Path, required=True)
    compare.add_argument("--source", required=True)
    compare.add_argument("--kind", choices=("static", "off-peak"), required=True)
    for command in (prepare, compare):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            raise FileExistsError(f"Choose a new output path: {args.output}")
        if args.command == "sample":
            if args.groups_per_scenario < 1 or args.seed < 0:
                raise ValueError("Expected positive groups per scenario and a nonnegative seed")
            report = asyncio.run(prepare_samples(
                args.bundle_dir, args.groups_per_scenario, args.seed,
            ))
        else:
            sample = json.loads(args.sample.read_text(encoding="utf-8"))
            with args.observations.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            report = compare_times(sample, rows, args.source, args.kind)
            report["sample_sha256"] = _sha256(args.sample)
            report["observations_sha256"] = _sha256(args.observations)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    print(args.output)
    return int(args.command == "compare" and not report["sufficient_complete_groups"])


if __name__ == "__main__":
    raise SystemExit(main())
