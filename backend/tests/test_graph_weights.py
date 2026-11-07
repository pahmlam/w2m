"""Deterministic tests for static speeds and offline weighting without network calls."""

import copy
import json
from pathlib import Path

import networkx as nx
import pytest
import yaml
from shapely.geometry import LineString

from app.services.graph_weights import (
    apply_speed_profile,
    load_speed_profile,
    parse_maxspeed_kmh,
)
from scripts.download_osm import _sha256
from scripts.prepare_graph_weights import main, prepare_graph_weights

PROFILE_PATH = Path(__file__).resolve().parents[1] / "app/config/speed_profiles/car-v1.yaml"


@pytest.mark.parametrize(("value", "expected"), [
    (40, 40.0), (40.5, 40.5), ("40", 40.0), (" 40 km/h ", 40.0),
    ("40 kmh", 40.0), ("40 kph", 40.0), ("10 mph", 16.09),
    ("10 MPH", 16.09), ("0.5", 0.5), (".5", 0.5),
    (["50", "10 mph", "signals"], 16.09), (["none", 30, 20], 20.0),
    ("50;20;signals", 20.0), ((40, 30), 30.0),
    (None, None), (True, None), (False, None), ("none", None),
    ("signals", None), ("walk", None), ("", None), ("40 knots", None),
    ("30 mph garbage", None), ("NaN", None), ("inf", None),
    (float("nan"), None), (float("inf"), None), (0, None), (-1, None),
    ("0 mph", None), ("-40", None), ([], None), ({}, None),
    (["none", -1, True], None), (["0", "20"], 20.0),
])
def test_maxspeed_parser(value: object, expected: float | None) -> None:
    actual = parse_maxspeed_kmh(value)
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


def test_profile_matches_spec() -> None:
    profile = load_speed_profile(PROFILE_PATH)
    assert profile.version == "car-v1"
    assert profile.speeds_kmh == {
        "motorway": 60, "trunk": 40, "primary": 30, "secondary": 25, "tertiary": 22,
        "motorway_link": 25, "trunk_link": 25, "primary_link": 25,
        "secondary_link": 25, "tertiary_link": 25, "residential": 18,
        "living_street": 18, "service": 12, "unclassified": 12, "default": 15,
    }


@pytest.mark.parametrize("changes", [
    {"weight_profile_version": ""}, {"weight_profile_version": 1},
    {"travel_mode": "bike"}, {"unit": "mph"}, {"maxspeed_cap": False},
    {"maxspeed_cap": 1}, {"speeds": {}}, {"speeds": []},
    {"speeds": {"default": 0}}, {"speeds": {"default": -1}},
    {"speeds": {"default": float("nan")}}, {"speeds": {"default": float("inf")}},
    {"speeds": {"default": True}}, {"speeds": {"default": "15"}},
    {"speeds": {"default": 15, "primary": 0}},
    {"speeds": {"default": 15, 1: 30}},
])
def test_reject_invalid_profile(tmp_path: Path, changes: dict) -> None:
    document = yaml.safe_load(PROFILE_PATH.read_text())
    document.update(changes)
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(ValueError):
        load_speed_profile(path)


@pytest.mark.parametrize("document", ["[]", "null", "car", "speeds: ["])
def test_reject_nonmapping_or_malformed_profile(tmp_path: Path, document: str) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(document)
    with pytest.raises((ValueError, yaml.YAMLError)):
        load_speed_profile(path)


@pytest.fixture
def metric_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph(crs="EPSG:32648", simplified=False)
    graph.add_node(1, x=588000.0, y=2326000.0, lon=105.84, lat=21.03)
    graph.add_node(2, x=588100.0, y=2326000.0, lon=105.841, lat=21.03)
    graph.add_edge(
        1, 2, key=7, osmid=123, highway="primary", maxspeed="90",
        length=100.0, length_m=100.0, oneway=True,
        geometry=LineString([(588000, 2326000), (588100, 2326000)]),
    )
    return graph


@pytest.mark.parametrize(("highway", "expected"), [
    ("primary", 30), (["primary", "service"], 12),
    ("mystery", 15), (["primary", "mystery"], 15),
    (["service", "mystery"], 12), (None, 15), ([], 15),
    (["mystery", "unknown"], 15), ({"bad": "type"}, 15),
])
def test_highway_speed_selection(
    metric_graph: nx.MultiDiGraph, highway: object, expected: float,
) -> None:
    metric_graph.edges[1, 2, 7]["highway"] = highway
    weighted = apply_speed_profile(metric_graph, load_speed_profile(PROFILE_PATH))
    edge = weighted.edges[1, 2, 7]
    assert edge["estimated_speed_kmh"] == expected
    assert edge["travel_time_seconds"] == pytest.approx(100 / (expected / 3.6))
    assert edge["travel_time"] == edge["travel_time_seconds"]


def test_caps_direction_parallel_edges_stats_and_immutability(
    metric_graph: nx.MultiDiGraph,
) -> None:
    metric_graph.add_edge(
        2, 1, key=2, highway="primary", maxspeed="10 mph", length_m=100,
    )
    metric_graph.add_edge(
        1, 2, key=9, highway=["service", "mystery"], maxspeed=["signals", "0"],
        length_m=100,
    )
    before = copy.deepcopy(metric_graph)
    weighted = apply_speed_profile(metric_graph, load_speed_profile(PROFILE_PATH))
    assert nx.utils.graphs_equal(metric_graph, before)
    assert set(weighted.edges) == {(1, 2, 7), (2, 1, 2), (1, 2, 9)}
    assert set(weighted.nodes) == set(metric_graph.nodes)
    assert weighted.edges[1, 2, 7]["estimated_speed_kmh"] == 30
    assert weighted.edges[2, 1, 2]["estimated_speed_kmh"] == pytest.approx(16.09)
    assert weighted.edges[2, 1, 2]["travel_time_seconds"] > weighted.edges[1, 2, 7][
        "travel_time_seconds"
    ]
    assert weighted.edges[1, 2, 7]["geometry"] == metric_graph.edges[1, 2, 7]["geometry"]
    assert weighted.graph["default_speed_edge_count"] == 1
    assert weighted.graph["maxspeed_capped_edge_count"] == 1
    assert weighted.graph["ignored_maxspeed_edge_count"] == 1
    assert weighted.graph["weight_profile_version"] == "car-v1"


@pytest.mark.parametrize("value", [
    None, True, "100", 0, -1, float("nan"), float("inf"),
])
def test_reject_invalid_length(metric_graph: nx.MultiDiGraph, value: object) -> None:
    metric_graph.edges[1, 2, 7]["length_m"] = value
    with pytest.raises(ValueError, match=r"edge \(1, 2, 7\)"):
        apply_speed_profile(metric_graph, load_speed_profile(PROFILE_PATH))
    assert "travel_time_seconds" not in metric_graph.edges[1, 2, 7]


def test_reject_nonfinite_or_underflowed_travel_time(metric_graph: nx.MultiDiGraph) -> None:
    metric_graph.edges[1, 2, 7].update(length_m=1e308, maxspeed=1e-300)
    with pytest.raises(ValueError, match="travel_time_seconds"):
        apply_speed_profile(metric_graph, load_speed_profile(PROFILE_PATH))
    metric_graph.edges[1, 2, 7].update(length_m=5e-324, maxspeed=None)
    with pytest.raises(ValueError, match="travel_time_seconds"):
        apply_speed_profile(metric_graph, load_speed_profile(PROFILE_PATH))


@pytest.mark.parametrize("graph", [
    nx.Graph(), nx.DiGraph(), nx.MultiGraph(), nx.MultiDiGraph(crs="EPSG:4326"),
    nx.MultiDiGraph(crs="EPSG:32648"),
])
def test_reject_wrong_graph(graph: nx.Graph) -> None:
    with pytest.raises(ValueError):
        apply_speed_profile(graph, load_speed_profile(PROFILE_PATH))


def test_weighting_cli_roundtrip_and_checksum(
    metric_graph: nx.MultiDiGraph, tmp_path: Path,
) -> None:
    ox = pytest.importorskip("osmnx")
    geometry_dir = tmp_path / "geometry"
    geometry_dir.mkdir()
    ox.save_graphml(metric_graph, filepath=geometry_dir / "graph.graphml")
    graph_checksum = _sha256(geometry_dir / "graph.graphml")
    metadata = {
        "stage": "geometry-only", "source_snapshot_id": "fixture",
        "graph_sha256": graph_checksum, "source": "OpenStreetMap",
        "source_date": "2026-11-06", "attribution": "© OpenStreetMap contributors",
        "license": "ODbL-1.0",
    }
    metadata_path = geometry_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    output = tmp_path / "weighted"
    assert main([
        "--geometry-dir", str(geometry_dir), "--profile", str(PROFILE_PATH),
        "--output-dir", str(output),
    ]) == 0
    report = json.loads((output / "metadata.json").read_text())
    assert report["stage"] == "weighted"
    assert report["weight_profile_version"] == "car-v1"
    assert report["tau_p50"] == pytest.approx(12.0)
    assert report["tau_p99"] == report["tau_max"] == pytest.approx(12.0)
    assert report["default_speed_edge_count"] == 0
    assert report["maxspeed_capped_edge_count"] == 0
    assert report["invalid_edge_count"] == report["removed_edge_count"] == 0
    assert report["graph_sha256"] == _sha256(output / "graph.graphml")
    assert report["weight_profile_sha256"] == _sha256(output / "speed_profile.yaml")
    assert (output / "speed_profile.yaml").read_bytes() == PROFILE_PATH.read_bytes()
    assert _sha256(geometry_dir / "graph.graphml") == graph_checksum
    restored = ox.load_graphml(
        filepath=output / "graph.graphml",
        edge_dtypes={"travel_time_seconds": float, "estimated_speed_kmh": float},
    )
    assert restored.edges[1, 2, 7]["travel_time_seconds"] == pytest.approx(12.0)
    with pytest.raises(FileExistsError):
        prepare_graph_weights(geometry_dir, PROFILE_PATH, output)
    metadata["graph_sha256"] = "incorrect"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="checksum"):
        prepare_graph_weights(geometry_dir, PROFILE_PATH, tmp_path / "bad-checksum")
    assert not (tmp_path / "bad-checksum").exists()


def test_invalid_weight_is_not_published(metric_graph: nx.MultiDiGraph, tmp_path: Path) -> None:
    ox = pytest.importorskip("osmnx")
    geometry_dir = tmp_path / "geometry"
    geometry_dir.mkdir()
    metric_graph.edges[1, 2, 7]["length_m"] = 0
    ox.save_graphml(metric_graph, filepath=geometry_dir / "graph.graphml")
    (geometry_dir / "metadata.json").write_text(json.dumps({
        "stage": "geometry-only", "graph_sha256": _sha256(geometry_dir / "graph.graphml"),
    }))
    output = tmp_path / "invalid-output"
    with pytest.raises(ValueError, match="length_m"):
        prepare_graph_weights(geometry_dir, PROFILE_PATH, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".graph-weights-*"))
