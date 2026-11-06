"""Generate AOI, routing-area GeoJSON and metadata from a versioned source polygon."""

import argparse
import hashlib
import json
from pathlib import Path

from pyproj.exceptions import ProjError
from shapely.errors import GEOSException
from shapely.geometry import mapping

from app.config.settings import get_settings
from app.services.area import BUFFER_QUAD_SEGS, METRIC_CRS, WGS84_CRS, load_aoi, prepare_area


def main(argv: list[str] | None = None) -> int:
    """Write local area artifacts; return nonzero on invalid input or failed writes."""
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=settings.aoi_source_path)
    parser.add_argument("--aoi-output", type=Path, default=settings.aoi_path)
    parser.add_argument("--routing-output", type=Path, default=settings.routing_area_path)
    parser.add_argument("--metadata-output", type=Path)
    parser.add_argument("--buffer-m", type=float, default=settings.buffer_m)
    args = parser.parse_args(argv)
    metadata_output = args.metadata_output or args.aoi_output.with_suffix(".metadata.json")
    paths = [args.source, args.aoi_output, args.routing_output, metadata_output]
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("Source and output paths must all be distinct")
    try:
        area = prepare_area(load_aoi(args.source), args.buffer_m)
        metadata = {
            "schema_version": 1,
            "area_id": args.source.stem,
            "source_file": args.source.name,
            "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
            "geometry_crs": WGS84_CRS,
            "measurement_crs": METRIC_CRS,
            "buffer_m": area.buffer_meters,
            "buffer_quad_segs": BUFFER_QUAD_SEGS,
            "boundary_rule": "covers",
            "aoi_area_m2": area.aoi_meters.area,
            "routing_area_m2": area.routing_area_meters.area,
            "aoi_bounds_wgs84": list(area.aoi_wgs84.bounds),
            "routing_area_bounds_wgs84": list(area.routing_area_wgs84.bounds),
        }
        outputs = [
            (args.aoi_output, mapping(area.aoi_wgs84)),
            (args.routing_output, mapping(area.routing_area_wgs84)),
            (metadata_output, metadata),
        ]
        for path, payload in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
    except (OSError, ValueError, ProjError, GEOSException) as exc:
        parser.error(str(exc))
    print(f"AOI: {args.aoi_output}")
    print(f"Routing area: {args.routing_output} (buffer {area.buffer_meters:g} m)")
    print(f"Metadata: {metadata_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
