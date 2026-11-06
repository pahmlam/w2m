"""Exercise snapshot downloads with a fake OSMnx module and no network access."""

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import networkx as nx
import pytest

from app.services.area import load_aoi
from scripts import download_osm

SNAPSHOT_AT = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
PILOT_SOURCE = Path(__file__).resolve().parents[1] / "app/config/areas/hanoi-pilot-v1.geojson"


class _ResponseStatusCodeError(ValueError):
    """Match OSMnx's HTTP error type without importing its optional dependency."""


@pytest.fixture
def fake_osmnx(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Provide real local GraphML IO but replace every download with a tiny graph."""
    module = ModuleType("osmnx")
    module.__version__ = "test-offline"
    module._errors = SimpleNamespace(ResponseStatusCodeError=_ResponseStatusCodeError)
    module.settings = SimpleNamespace(
        use_cache=False, cache_folder="original-cache", log_console=True, log_file=True,
        all_oneway=True, bidirectional_network_types=["drive", "walk"],
        overpass_rate_limit=False, requests_timeout=42,
        overpass_settings="original-query-settings", useful_tags_way=["name"],
        overpass_url="https://example.invalid/api",
    )
    graph = nx.MultiDiGraph(crs="epsg:4326")
    graph.add_node(1, x=105.84, y=21.02)
    graph.add_node(2, x=105.85, y=21.03)
    graph.add_node(3, x=105.86, y=21.04)
    graph.add_edge(1, 2, key=0, oneway=True, highway="primary", maxspeed="30")
    graph.add_edge(1, 2, key=1, oneway=True, highway="service")

    def fake_download(polygon: object, **kwargs: object) -> nx.MultiDiGraph:
        module.observed_settings = vars(module.settings).copy()
        cache = Path(module.settings.cache_folder)
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "test-response.json").write_text('{"elements": []}', encoding="utf-8")
        return graph

    module.graph_from_polygon = Mock(side_effect=fake_download)
    module.save_graphml = Mock(
        side_effect=lambda graph, filepath: nx.write_graphml(graph, filepath)
    )
    module.load_graphml = Mock(side_effect=lambda filepath: nx.read_graphml(
        filepath, node_type=int, force_multigraph=True
    ))
    monkeypatch.setitem(sys.modules, "osmnx", module)
    return module


def test_snapshot_preserves_raw_topology_and_provenance(
    tmp_path: Path, fake_osmnx: ModuleType,
) -> None:
    output = tmp_path / "snapshot"
    previous = vars(fake_osmnx.settings).copy()
    assert download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT) == output
    graph = nx.read_graphml(output / "graph.graphml", node_type=int, force_multigraph=True)
    assert graph.is_directed() and graph.is_multigraph()
    assert graph.number_of_nodes() == 3  # The disconnected node must survive until SCC filtering.
    assert set(graph[1][2]) == {0, 1}
    assert not graph.has_edge(2, 1)
    assert "travel_time" not in graph[1][2][0]
    assert (output / "routing_area.geojson").read_bytes() == PILOT_SOURCE.read_bytes()
    assert (output / "responses/test-response.json").exists()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source"] == "OpenStreetMap"
    assert manifest["source_date"] == "2020-01-02"
    assert manifest["snapshot_at"] == "2020-01-02T03:04:05Z"
    assert manifest["node_count"] == 3 and manifest["edge_count"] == 2
    assert manifest["response_cache_file_count"] == 1
    assert manifest["download_attempts"] == 1
    assert manifest["graph_sha256"] == hashlib.sha256(
        (output / "graph.graphml").read_bytes()
    ).hexdigest()
    assert manifest["routing_area_sha256"] == hashlib.sha256(PILOT_SOURCE.read_bytes()).hexdigest()
    call = fake_osmnx.graph_from_polygon.call_args
    assert call.args[0].equals(load_aoi(PILOT_SOURCE))
    assert call.kwargs == {
        "network_type": "drive", "simplify": False,
        "retain_all": True, "truncate_by_edge": False,
    }
    observed = fake_osmnx.observed_settings
    assert not observed["all_oneway"]
    assert "drive" not in observed["bidirectional_network_types"]
    assert observed["overpass_rate_limit"]
    assert '[date:"2020-01-02T03:04:05Z"]' in observed["overpass_settings"]
    assert {"highway", "maxspeed", "oneway", "bridge"} <= set(observed["useful_tags_way"])
    assert vars(fake_osmnx.settings) == previous


def test_existing_snapshot_is_not_overwritten(tmp_path: Path, fake_osmnx: ModuleType) -> None:
    output = tmp_path / "snapshot"
    output.mkdir()
    sentinel = output / "existing.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    fake_osmnx.graph_from_polygon.assert_not_called()
    assert sentinel.read_text() == "keep"


def test_network_failure_does_not_publish_snapshot(
    tmp_path: Path, fake_osmnx: ModuleType,
) -> None:
    previous = vars(fake_osmnx.settings).copy()
    fake_osmnx.graph_from_polygon.side_effect = TimeoutError("test timeout")
    output = tmp_path / "snapshot"
    with pytest.raises(TimeoutError):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert not output.exists()
    assert not list(tmp_path.glob(".osm-download-*"))
    assert vars(fake_osmnx.settings) == previous


@pytest.mark.parametrize("graph", [nx.MultiDiGraph(), nx.DiGraph([(1, 2)])])
def test_invalid_graph_is_not_published(
    tmp_path: Path, fake_osmnx: ModuleType, graph: nx.Graph,
) -> None:
    fake_osmnx.graph_from_polygon.side_effect = None
    fake_osmnx.graph_from_polygon.return_value = graph
    output = tmp_path / "snapshot"
    with pytest.raises(ValueError):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert not output.exists()


def test_failed_reload_does_not_publish_snapshot(tmp_path: Path, fake_osmnx: ModuleType) -> None:
    fake_osmnx.load_graphml.side_effect = None
    fake_osmnx.load_graphml.return_value = nx.MultiDiGraph()
    output = tmp_path / "snapshot"
    with pytest.raises(ValueError, match="reload"):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert not output.exists()


def test_invalid_polygon_is_rejected_before_download(
    tmp_path: Path, fake_osmnx: ModuleType,
) -> None:
    source = tmp_path / "invalid.geojson"
    source.write_text('{"type":"Polygon","coordinates":[]}', encoding="utf-8")
    output = tmp_path / "snapshot"
    with pytest.raises(ValueError):
        download_osm.download_snapshot(source, output, SNAPSHOT_AT)
    fake_osmnx.graph_from_polygon.assert_not_called()
    assert not output.exists()


def test_missing_extra_has_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_module(name: str) -> ModuleType:
        raise ModuleNotFoundError("OSMnx is not installed", name="osmnx")

    monkeypatch.setattr(download_osm, "import_module", missing_module)
    output = tmp_path / "snapshot"
    with pytest.raises(RuntimeError, match="--extra data"):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert not output.exists()


@pytest.mark.parametrize("timestamp", ["not-a-date", "2020-01-02", "2020-01-02T03:04:05"])
def test_cli_rejects_timestamp_without_timezone(
    timestamp: str, fake_osmnx: ModuleType,
) -> None:
    with pytest.raises(SystemExit) as exc:
        download_osm.main(["--snapshot-at", timestamp])
    assert exc.value.code == 2
    fake_osmnx.graph_from_polygon.assert_not_called()


def test_cli_rejects_future_timestamp(fake_osmnx: ModuleType) -> None:
    timestamp = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    with pytest.raises(SystemExit) as exc:
        download_osm.main(["--snapshot-at", timestamp])
    assert exc.value.code == 2
    fake_osmnx.graph_from_polygon.assert_not_called()


def test_cli_downloads_with_explicit_snapshot_time(
    tmp_path: Path, fake_osmnx: ModuleType,
) -> None:
    output = tmp_path / "snapshot"
    assert download_osm.main([
        "--routing-area", str(PILOT_SOURCE), "--output-dir", str(output),
        "--snapshot-at", "2020-01-02T10:04:05+07:00",
    ]) == 0
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["snapshot_at"] == "2020-01-02T03:04:05Z"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_transient_http_errors_retry_with_backoff(
    tmp_path: Path, fake_osmnx: ModuleType, monkeypatch: pytest.MonkeyPatch, status: int,
) -> None:
    pause = Mock()
    monkeypatch.setattr(download_osm, "sleep", pause)
    original_download = fake_osmnx.graph_from_polygon.side_effect
    observed_cutoffs: list[str] = []

    def flaky_download(polygon: object, **options: object) -> nx.MultiDiGraph:
        observed_cutoffs.append(fake_osmnx.settings.overpass_settings)
        if len(observed_cutoffs) < 3:
            raise _ResponseStatusCodeError(f"'overpass-api.de' responded: {status} Busy")
        return original_download(polygon, **options)

    fake_osmnx.graph_from_polygon.side_effect = flaky_download
    output = tmp_path / "snapshot"
    download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert fake_osmnx.graph_from_polygon.call_count == 3
    assert [call.args[0] for call in pause.call_args_list] == [10, 20]
    assert len(set(observed_cutoffs)) == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["download_attempts"] == 3
    assert manifest["snapshot_at"] == "2020-01-02T03:04:05Z"


def test_exhausted_http_retries_clean_up_and_restore_settings(
    tmp_path: Path, fake_osmnx: ModuleType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pause = Mock()
    monkeypatch.setattr(download_osm, "sleep", pause)
    previous = vars(fake_osmnx.settings).copy()
    fake_osmnx.graph_from_polygon.side_effect = _ResponseStatusCodeError(
        "'overpass-api.de' responded: 502 Bad Gateway # 502 Gateway Timeout"
    )
    output = tmp_path / "snapshot"
    with pytest.raises(_ResponseStatusCodeError):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert fake_osmnx.graph_from_polygon.call_count == 4
    assert [call.args[0] for call in pause.call_args_list] == [10, 20, 40]
    assert not output.exists()
    assert not list(tmp_path.glob(".osm-download-*"))
    assert vars(fake_osmnx.settings) == previous


@pytest.mark.parametrize("error", [
    _ResponseStatusCodeError("'overpass-api.de' responded: 400 Bad Request"),
    _ResponseStatusCodeError("'overpass-api.de' responded: 403 Forbidden"),
    _ResponseStatusCodeError("unrecognized response format"),
    ValueError("'overpass-api.de' responded: 502 unrelated validation error"),
])
def test_permanent_or_unrelated_errors_are_not_retried(
    tmp_path: Path, fake_osmnx: ModuleType, monkeypatch: pytest.MonkeyPatch, error: ValueError,
) -> None:
    pause = Mock()
    monkeypatch.setattr(download_osm, "sleep", pause)
    fake_osmnx.graph_from_polygon.side_effect = error
    output = tmp_path / "snapshot"
    with pytest.raises(type(error)):
        download_osm.download_snapshot(PILOT_SOURCE, output, SNAPSHOT_AT)
    assert fake_osmnx.graph_from_polygon.call_count == 1
    pause.assert_not_called()
    assert not output.exists()
