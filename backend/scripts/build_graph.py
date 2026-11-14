"""Build a versioned offline bundle using the existing validated preparation stages."""

import argparse
import json
from importlib import import_module
from pathlib import Path

from app.services.area import load_aoi, prepare_area
from scripts.download_osm import _sha256
from scripts.prepare_graph_candidates import prepare_graph_candidates
from scripts.prepare_graph_csr import prepare_graph_csr
from scripts.prepare_graph_geometry import prepare_graph_geometry
from scripts.prepare_graph_scc import prepare_graph_scc
from scripts.prepare_graph_split import prepare_graph_split
from scripts.prepare_graph_weights import prepare_graph_weights
from scripts.prepare_reverse_edges import prepare_reverse_edges
from scripts.validate_graph import validate_graph


def build_graph(
    snapshot_dir: Path, area_dir: Path, profile: Path, output_dir: Path, graph_version: str,
) -> Path:
    """Crop one raw snapshot to a prepared routing area and run all offline stages.

    Both TC-15 builds can use the same larger snapshot, avoiding differences in
    OSM data or download filters. Original node IDs are preserved before splitting.
    """
    if output_dir.exists():
        raise FileExistsError(f"Choose a new output directory: {output_dir}")
    if not graph_version.strip():
        raise ValueError("graph_version must be non-empty")
    manifest_path = snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for filename, field in (("graph.graphml", "graph_sha256"),
                            ("routing_area.geojson", "routing_area_sha256")):
        if _sha256(snapshot_dir / filename) != manifest[field]:
            raise ValueError(f"Snapshot checksum mismatch: {filename}")
    routing = load_aoi(area_dir / "routing_area.geojson")
    area_metadata = json.loads((area_dir / "aoi.metadata.json").read_bytes())
    expected = prepare_area(load_aoi(area_dir / "aoi.geojson"), area_metadata["buffer_m"])
    if not expected.routing_area_wgs84.equals_exact(routing, tolerance=1e-10):
        raise ValueError("Routing polygon does not match the AOI and configured metric buffer")
    if not load_aoi(snapshot_dir / "routing_area.geojson").buffer(1e-10).covers(routing):
        raise ValueError("Snapshot must cover the entire requested routing area")
    if manifest["graph_options"] != {
        "network_type": "drive", "simplify": False, "retain_all": True,
        "truncate_by_edge": False,
    }:
        raise ValueError("Expected a raw unsimplified drive snapshot retaining all components")
    ox = import_module("osmnx")
    graph = ox.load_graphml(filepath=snapshot_dir / "graph.graphml")
    cropped = ox.truncate.truncate_graph_polygon(graph, routing, truncate_by_edge=False)
    raw = output_dir / "snapshot"
    raw.mkdir(parents=True)
    ox.save_graphml(cropped, filepath=raw / "graph.graphml")
    (raw / "routing_area.geojson").write_bytes((area_dir / "routing_area.geojson").read_bytes())
    manifest.update(
        derivation="offline node-induced crop; original download provenance retained",
        parent_manifest_sha256=_sha256(manifest_path),
        parent_graph_sha256=_sha256(snapshot_dir / "graph.graphml"),
        graph_sha256=_sha256(raw / "graph.graphml"),
        routing_area_sha256=_sha256(raw / "routing_area.geojson"),
        node_count=len(cropped), edge_count=cropped.number_of_edges(),
    )
    (raw / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    del graph, cropped
    stages = [
        ("geometry", lambda: prepare_graph_geometry(raw, output_dir / "geometry")),
        ("weighted", lambda: prepare_graph_weights(
            output_dir / "geometry", profile, output_dir / "weighted")),
        ("scc", lambda: prepare_graph_scc(
            output_dir / "weighted", area_dir / "aoi.geojson", output_dir / "scc")),
        ("reverse", lambda: prepare_reverse_edges(output_dir / "scc", output_dir / "reverse")),
        ("split", lambda: prepare_graph_split(
            output_dir / "scc", output_dir / "reverse", output_dir / "split")),
        ("candidates", lambda: prepare_graph_candidates(
            output_dir / "split", output_dir / "candidates")),
        ("csr", lambda: prepare_graph_csr(
            output_dir / "candidates", output_dir / "csr", graph_version)),
        ("validated", lambda: validate_graph(
            output_dir / "csr", area_dir / "aoi.metadata.json", output_dir / "validated")),
    ]
    for name, prepare in stages:
        print(f"Preparing {name}...", flush=True)
        prepare()
    return output_dir / "validated"


def main(argv: list[str] | None = None) -> int:
    """Run offline preparation; completed stages remain inspectable if a later stage fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--area-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--graph-version", required=True)
    args = parser.parse_args(argv)
    try:
        output = build_graph(args.snapshot_dir, args.area_dir, args.profile,
                             args.output_dir, args.graph_version)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Validated bundle: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
