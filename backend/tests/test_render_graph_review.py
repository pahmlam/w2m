"""The review map is a self-contained attributed SVG from checksum-verified data."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from pyproj import Transformer
from test_build_graph import built_graph as built_graph
from test_build_graph import raw_inputs as raw_inputs

from scripts.download_osm import _sha256
from scripts.render_graph_review import render_graph_review


def test_review_map_is_valid_svg_without_external_tiles(built_graph: Path, tmp_path: Path) -> None:
    output = render_graph_review(built_graph / "scc", tmp_path / "review.svg")
    root = ET.fromstring(output.read_text())
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.findall(".//{http://www.w3.org/2000/svg}path")
    assert "OpenStreetMap contributors" in output.read_text()
    assert "http" not in output.read_text().replace("http://www.w3.org/2000/svg", "")
    with pytest.raises(FileExistsError):
        render_graph_review(built_graph / "scc", output)


def test_review_rejects_modified_source(built_graph: Path, tmp_path: Path) -> None:
    (built_graph / "scc/removed_in_aoi.geojson").write_text("corrupt")
    with pytest.raises(ValueError, match="checksum"):
        render_graph_review(built_graph / "scc", tmp_path / "review.svg")


def test_removed_node_distance_exposes_snap_gaps(built_graph: Path, tmp_path: Path) -> None:
    directory = built_graph / "scc"
    projector = Transformer.from_crs(32648, 4326, always_xy=True)
    features = [{"type": "Feature", "properties": {"kind": "node"},
                 "geometry": {"type": "Point", "coordinates": projector.transform(500050, y)}}
                for y in (2300100, 2300180)]
    path = directory / "removed_in_aoi.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["removed_in_aoi_sha256"] = _sha256(path)
    metadata_path.write_text(json.dumps(metadata))
    render_graph_review(directory, tmp_path / "review.svg")
    statistics = json.loads((tmp_path / "review.json").read_bytes())
    nodes = statistics["distance_to_retained_road_meters"]["node"]
    assert nodes["sample_count"] == 2
    assert nodes["over_150_meters"] == 1
    assert nodes["max"] == pytest.approx(180)
