"""Exercise exported M2 evidence on fixed synthetic roads, without OSM access."""

import json
from pathlib import Path

import pytest
from shapely.geometry import LineString
from test_coordinate_snapper import TO_WGS84
from test_route_builder import prepare_snapper

from app.models.responses import MeetingResult
from app.services.meeting_optimizer import CandidateRanking
from scripts import validate_reference as validator


@pytest.fixture
def reference_bundle(tmp_path: Path, monkeypatch) -> Path:
    snapper = prepare_snapper(reverse=True)
    graph = snapper.reference.graph
    for node, x, y in [(3, 500100., 2300100.), (4, 500000., 2300100.)]:
        lon, lat = TO_WGS84.transform(x, y)
        graph.add_node(node, x=x, y=y, lon=lon, lat=lat, in_aoi=True, is_candidate=True)
    for u, v in [(2, 3), (3, 4), (4, 1)]:
        line = LineString([(graph.nodes[u]['x'], graph.nodes[u]['y']),
                           (graph.nodes[v]['x'], graph.nodes[v]['y'])])
        graph.add_edge(u, v, key=0, geometry=line, length_m=line.length,
                       travel_time=100., oneway=True)
    monkeypatch.setattr(validator, 'load_reference_graph', lambda path: snapper.reference)
    (tmp_path / 'metadata.json').write_text('{}')
    return tmp_path


def test_report_reproducible_serializable_and_preserves_existing_output(
    reference_bundle: Path, tmp_path: Path,
) -> None:
    output = tmp_path / 'report.json'
    assert validator.main(['--bundle-dir', str(reference_bundle), '--output', str(output)]) == 0
    report = json.loads(output.read_text())
    assert report['status'] == 'passed'
    assert report['graph_and_routing_unchanged']
    assert report['seed'] == 20261115
    assert set(report['environment']['libraries']) == {'networkx', 'numpy', 'shapely',
                                                       'pyproj', 'osmnx'}
    for scenario in report['scenarios']:
        assert scenario['top1_pareto_safe']
        assert len(scenario['route_checks']) == 4 * len(scenario['results'])
        assert all(check['error_seconds'] < 1e-10 for check in scenario['route_checks'])
    second = validator.validate_reference(reference_bundle, tmp_path / 'second.json')
    assert json.loads(second.read_text())['scenarios'] == report['scenarios']
    original_bytes = output.read_bytes()
    with pytest.raises(FileExistsError):
        validator.validate_reference(reference_bundle, output)
    assert output.read_bytes() == original_bytes


def test_invalid_timing_fails_without_publishing_report(
    reference_bundle: Path, tmp_path: Path, monkeypatch,
) -> None:
    build_results = validator.build_meeting_results

    def broken_results(
        ranking: CandidateRanking, *, top_k: int, min_spacing_meters: float,
    ) -> list[MeetingResult]:
        results = build_results(ranking, top_k=top_k, min_spacing_meters=min_spacing_meters)
        results[0].routes['A'].network_seconds += 1
        return results

    monkeypatch.setattr(validator, 'build_meeting_results', broken_results)
    output = tmp_path / 'invalid.json'
    with pytest.raises(ValueError, match='timing'):
        validator.validate_reference(reference_bundle, output)
    assert not output.exists()


def test_cli_invalid_bundle_fails_without_report(tmp_path: Path) -> None:
    output = tmp_path / 'report.json'
    with pytest.raises(SystemExit) as exc:
        validator.main(['--bundle-dir', str(tmp_path / 'missing'), '--output', str(output)])
    assert exc.value.code == 2
    assert not output.exists()
