"""Download a versioned raw driving-network snapshot for offline graph preparation."""

import argparse
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

from app.config.settings import get_settings
from app.services.area import load_aoi

MAX_DOWNLOAD_ATTEMPTS = 4
INITIAL_RETRY_DELAY_SECONDS = 10


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _parse_snapshot_at(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timezone required")
        timestamp = timestamp.astimezone(UTC).replace(microsecond=0)
        if timestamp > datetime.now(UTC):
            raise ValueError("future timestamp")
        return timestamp
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Snapshot time must be an ISO timestamp with timezone, not in the future"
        ) from exc


def download_snapshot(routing_area_path: Path, output_dir: Path, snapshot_at: datetime) -> Path:
    """Publish a complete raw snapshot; retain all components and directed parallel edges."""
    if snapshot_at.tzinfo is None or snapshot_at.utcoffset() is None:
        raise ValueError("Snapshot time must include a timezone")
    snapshot_at = snapshot_at.astimezone(UTC).replace(microsecond=0)
    if snapshot_at > datetime.now(UTC):
        raise ValueError("Snapshot time cannot be in the future")
    if output_dir.exists():
        raise FileExistsError(f"Snapshot already exists: {output_dir}; choose a new directory")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(UTC)
    cutoff = snapshot_at.isoformat().replace("+00:00", "Z")
    with TemporaryDirectory(prefix=".osm-download-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        saved_polygon = staging / "routing_area.geojson"
        shutil.copyfile(routing_area_path, saved_polygon)
        # Query exactly the bytes saved in the snapshot, even if the source changes later.
        polygon = load_aoi(saved_polygon)
        try:
            ox = import_module("osmnx")
        except ModuleNotFoundError as exc:
            if exc.name != "osmnx":
                raise
            raise RuntimeError(
                "OSMnx is missing. Run: uv sync --project backend --locked --extra data"
            ) from exc

        overrides = {
            "use_cache": True,
            "cache_folder": staging / "responses",
            "log_console": False,
            "log_file": False,
            "all_oneway": False,
            "bidirectional_network_types": ["walk"],
            "overpass_rate_limit": True,
            "requests_timeout": 180,
            "overpass_settings": '[out:json][timeout:{timeout}]{maxsize}[date:"' + cutoff + '"]',
            "useful_tags_way": list(dict.fromkeys([
                *ox.settings.useful_tags_way,
                "highway", "maxspeed", "oneway", "junction", "bridge", "tunnel", "access",
            ])),
        }
        previous = {name: getattr(ox.settings, name) for name in overrides}
        try:
            # OSMnx settings are process-global: only this offline command changes them.
            for name, value in overrides.items():
                setattr(ox.settings, name, value)
            options = {
                "network_type": "drive",
                "simplify": False,
                "retain_all": True,
                "truncate_by_edge": False,
            }
            for download_attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
                try:
                    graph = ox.graph_from_polygon(polygon, **options)
                    break
                except ox._errors.ResponseStatusCodeError as exc:
                    # OSMnx 2.x exposes the HTTP status in its error message, not a field.
                    status = re.match(r"^'[^']+' responded:\s+(500|502|503)\b", str(exc))
                    if status is None or download_attempt == MAX_DOWNLOAD_ATTEMPTS:
                        raise
                    delay_seconds = INITIAL_RETRY_DELAY_SECONDS * 2 ** (download_attempt - 1)
                    print(
                        f"Overpass HTTP {status.group(1)}; waiting {delay_seconds}s before "
                        f"download attempt {download_attempt + 1}/{MAX_DOWNLOAD_ATTEMPTS}...",
                        flush=True,
                    )
                    # Keep the cutoff and response cache unchanged across retries.
                    sleep(delay_seconds)
            if not graph.is_directed() or not graph.is_multigraph():
                raise ValueError("OSMnx must return a directed multigraph")
            if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
                raise ValueError("No drivable road network found in the routing area")
            graph_path = staging / "graph.graphml"
            ox.save_graphml(graph, filepath=graph_path)
            restored = ox.load_graphml(filepath=graph_path)
            if (
                not restored.is_directed()
                or not restored.is_multigraph()
                or restored.number_of_nodes() != graph.number_of_nodes()
                or restored.number_of_edges() != graph.number_of_edges()
            ):
                raise ValueError("Saved GraphML failed the offline reload check")
            manifest = {
                "schema_version": 1,
                "snapshot_id": output_dir.name,
                "source": "OpenStreetMap",
                "source_date": snapshot_at.date().isoformat(),
                "snapshot_at": cutoff,
                "download_started_at": started_at.isoformat(),
                "download_completed_at": datetime.now(UTC).isoformat(),
                "download_attempts": download_attempt,
                "overpass_url": ox.settings.overpass_url,
                "overpass_settings": ox.settings.overpass_settings,
                "requests_timeout_seconds": ox.settings.requests_timeout,
                "osmnx_version": ox.__version__,
                "graph_options": options,
                "useful_tags_way": ox.settings.useful_tags_way,
                "crs": str(graph.graph.get("crs", "")),
                "node_count": graph.number_of_nodes(),
                "edge_count": graph.number_of_edges(),
                "routing_area_sha256": _sha256(saved_polygon),
                "graph_sha256": _sha256(graph_path),
                "response_cache_file_count": len(list((staging / "responses").glob("*.json"))),
                "attribution": "© OpenStreetMap contributors",
                "license": "ODbL-1.0",
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
        finally:
            for name, value in previous.items():
                setattr(ox.settings, name, value)
        if output_dir.exists():
            raise FileExistsError(f"Snapshot already exists: {output_dir}")
        # Downstream builds only see the snapshot after every write and reload succeeds.
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run the explicit offline CLI; tests replace OSMnx to prevent network access."""
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routing-area", type=Path, default=settings.routing_area_path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--snapshot-at", type=_parse_snapshot_at)
    args = parser.parse_args(argv)
    started_at = datetime.now(UTC).replace(microsecond=0)
    snapshot_at = args.snapshot_at or started_at
    output_dir = args.output_dir or (
        settings.osm_snapshot_dir / f"drive-{started_at:%Y%m%dT%H%M%SZ}"
    )
    print(f"Downloading OSM drive snapshot as of {snapshot_at.isoformat()}...", flush=True)
    try:
        result = download_snapshot(args.routing_area, output_dir, snapshot_at)
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Snapshot: {result}")
    print(f"Manifest: {result / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
