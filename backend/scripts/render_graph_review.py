"""Export a tile-free SVG for reviewing the technical AOI and discarded SCC roads."""

import argparse
import json
from html import escape
from importlib import import_module
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely import STRtree, transform
from shapely.geometry import shape

from app.services.area import METRIC_CRS, WGS84_CRS, load_aoi
from scripts.download_osm import _sha256

SNAP_REVIEW_MAX_METERS = 150


def render_graph_review(scc_dir: Path, output: Path) -> Path:
    """Draw retained streets, removed features and the exact configured AOI in metric space."""
    stats_output = output.with_suffix(".json")
    if output.exists() or stats_output.exists():
        raise FileExistsError(f"Choose a new review output: {output}")
    metadata = json.loads((scc_dir / "metadata.json").read_bytes())
    for filename, field in (("graph.graphml", "graph_sha256"), ("aoi.geojson", "aoi_sha256"),
                            ("removed_in_aoi.geojson", "removed_in_aoi_sha256")):
        if _sha256(scc_dir / filename) != metadata[field]:
            raise ValueError(f"SCC checksum mismatch: {filename}")
    projector = Transformer.from_crs(WGS84_CRS, METRIC_CRS, always_xy=True)
    aoi = transform(load_aoi(scc_dir / "aoi.geojson"), projector.transform, interleaved=False)
    xmin, ymin, xmax, ymax = aoi.bounds
    scale = min(1400 / (xmax - xmin), 1400 / (ymax - ymin))

    def screen(x: float, y: float) -> tuple[float, float]:
        return 60 + (x - xmin) * scale, 100 + (ymax - y) * scale

    def path(coordinates) -> str:
        return "M" + "L".join(f"{x:.2f},{y:.2f}" for x, y in
                               (screen(*point[:2]) for point in coordinates))

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1520" height="1600" '
        'viewBox="0 0 1520 1600" role="img" aria-labelledby="title description">',
        '<title id="title">Hanoi Ring 3 technical AOI and SCC review</title>',
        '<desc id="description">North up. Blue: AOI boundary. Grey: retained streets. '
        'Orange: major roads. Red: discarded SCC roads and nodes. No live tiles.</desc>',
        '<rect width="1520" height="1600" fill="white"/>',
        '<g font-family="sans-serif" fill="#172b4d">',
        '<text x="40" y="35" font-size="24">Hanoi Ring 3 — technical review polygon</text>',
        '<text x="40" y="65" font-size="16">North ↑ | Blue: AOI | Grey: retained | '
        'Orange: major roads | Red: SCC removed</text></g>',
    ]
    graph = import_module("osmnx").load_graphml(filepath=scc_dir / "graph.graphml")
    road_index = STRtree([data["geometry"] for _, _, data in graph.edges(data=True)])
    removed_distances = {"node": [], "edge_midpoint": []}
    major = []
    parts.append('<g fill="none" stroke="#c6cdd5" stroke-width="0.45">')
    for _, _, data in graph.edges(data=True):
        line = data["geometry"].intersection(aoi)
        lines = [line] if line.geom_type == "LineString" else getattr(line, "geoms", [])
        highway = data.get("highway", [])
        types = [highway] if isinstance(highway, str) else highway
        for segment in lines:
            if segment.geom_type == "LineString" and not segment.is_empty:
                element = f'<path d="{path(segment.coords)}"/>'
                if any(kind in {"motorway", "trunk", "primary"} for kind in types):
                    major.append(element)
                else:
                    parts.append(element)
    parts.append('</g><g fill="none" stroke="#db9300" stroke-width="1">')
    parts.extend(major)
    parts.append('</g><g fill="none" stroke="#d51d35" stroke-width="1.8">')
    removed = json.loads((scc_dir / "removed_in_aoi.geojson").read_bytes())
    for feature in removed["features"]:
        geometry = transform(shape(feature["geometry"]), projector.transform, interleaved=False)
        point = (geometry if geometry.geom_type == "Point"
                 else geometry.interpolate(0.5, normalized=True))
        nearest = road_index.nearest(point)
        kind = "node" if geometry.geom_type == "Point" else "edge_midpoint"
        removed_distances[kind].append(point.distance(road_index.geometries[nearest]))
        if geometry.geom_type == "Point":
            x, y = screen(geometry.x, geometry.y)
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2"/>')
        else:
            lines = [geometry] if geometry.geom_type == "LineString" else geometry.geoms
            parts.extend(f'<path d="{path(line.coords)}"/>' for line in lines)
    parts.append(f'</g><path d="{path(aoi.exterior.coords)}Z" '
                 'fill="none" stroke="#1767ce" stroke-width="3"/>')
    parts.append('<g font-family="sans-serif" font-size="15" fill="#172b4d">')
    # Keep provenance visible without embedding any user input coordinates.
    for index, text in enumerate([
        f'AOI {aoi.area / 1e6:.2f} km²; removed '
        f'{metadata["removed_nodes_in_aoi"]} nodes / '
        f'{metadata["removed_edges_in_aoi"]} edge features in AOI.',
        'Technical approximation; owner boundary review required.',
        '© OpenStreetMap contributors — ODbL 1.0. No external tile service.',
    ]):
        parts.append(f'<text x="40" y="{1515 + index * 22}">{escape(text)}</text>')
    parts.append('</g></svg>')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(parts) + "\n")
    statistics = {
        "source_metadata_sha256": _sha256(scc_dir / "metadata.json"),
        "svg_sha256": _sha256(output), "implementation_sha256": _sha256(Path(__file__)),
        "note": ("Geometric distance to retained roads; "
                 "edge midpoints are samples, not full coverage"),
        "distance_to_retained_road_meters": {
            kind: {"sample_count": len(values),
                   "over_150_meters": sum(value > SNAP_REVIEW_MAX_METERS for value in values),
                   "p50": float(np.median(values)) if values else None,
                   "max": max(values) if values else None}
            for kind, values in removed_distances.items()
        },
    }
    with stats_output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(statistics, indent=2, allow_nan=False) + "\n")
    return output


def main(argv: list[str] | None = None) -> int:
    """Render a static review artifact without network access."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scc-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        render_graph_review(args.scc_dir, args.output)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Review map: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
