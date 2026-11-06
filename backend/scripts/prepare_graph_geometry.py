"""Project an existing OSM snapshot offline; this is not a production graph build."""

import argparse
import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.graph_geometry import normalize_graph_geometry
from scripts.download_osm import _sha256


def prepare_graph_geometry(snapshot_dir: Path, output_dir: Path) -> Path:
    """Publish projected GraphML and provenance only after an offline reload check."""
    if snapshot_dir.resolve() == output_dir.resolve() or output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}; choose a new directory")
    manifest_path = snapshot_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_path = snapshot_dir / "graph.graphml"
    source_checksum = _sha256(source_path)
    if source_checksum != manifest["graph_sha256"]:
        raise ValueError("Snapshot GraphML checksum does not match its manifest")
    ox = import_module("osmnx")
    raw_graph = ox.load_graphml(filepath=source_path)
    graph = normalize_graph_geometry(raw_graph)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".graph-geometry-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        graph_path = staging / "graph.graphml"
        ox.save_graphml(graph, filepath=graph_path)
        restored = ox.load_graphml(
            filepath=graph_path,
            node_dtypes={"lon": float, "lat": float},
            edge_dtypes={"length_m": float},
        )
        if (
            set(restored.nodes) != set(graph.nodes)
            or set(restored.edges) != set(graph.edges)
            or str(restored.graph["crs"]) != str(graph.graph["crs"])
            or any(
                not restored.edges[edge]["geometry"].equals_exact(
                    graph.edges[edge]["geometry"], 1e-8,
                )
                or abs(restored.edges[edge]["length_m"] - graph.edges[edge]["length_m"]) > 1e-8
                for edge in graph.edges
            )
        ):
            raise ValueError("Projected GraphML failed the offline reload check")
        lengths = [data["length_m"] for _, _, data in graph.edges(data=True)]
        metadata = {
            "schema_version": 1,
            "stage": "geometry-only",
            "source_snapshot_id": manifest["snapshot_id"],
            "source": manifest["source"],
            "source_date": manifest["source_date"],
            "source_graph_sha256": source_checksum,
            "source_manifest_sha256": _sha256(manifest_path),
            "graph_sha256": _sha256(graph_path),
            "build_date": datetime.now(UTC).isoformat(),
            "crs": str(graph.graph["crs"]),
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "length_m_min": min(lengths),
            "length_m_max": max(lengths),
            "length_m_total": sum(lengths),
            "attribution": manifest["attribution"],
            "license": manifest["license"],
        }
        (staging / "metadata.json").write_text(
            json.dumps(metadata, indent=2, allow_nan=False) + "\n", encoding="utf-8",
        )
        if output_dir.exists():
            raise FileExistsError(f"Output already exists: {output_dir}")
        staging.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    """Run geometry preparation without downloading or modifying the source snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare_graph_geometry(args.snapshot_dir, args.output_dir)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Geometry artifact: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
