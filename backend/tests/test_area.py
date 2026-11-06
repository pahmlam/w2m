"""Offline area tests use only versioned configuration and temporary local files."""

import json
from pathlib import Path

import pytest
from pyproj import Transformer
from shapely.geometry import Point, Polygon

from app.services.area import covers_location, load_aoi, prepare_area
from scripts.prepare_aoi import main

PILOT_SOURCE = (
    Path(__file__).resolve().parents[1] / "app/config/areas/hanoi-pilot-v1.geojson"
)


def _write_polygon(tmp_path: Path, coordinates: list) -> Path:
    path = tmp_path / "test.geojson"
    path.write_text(json.dumps({"type": "Polygon", "coordinates": coordinates}), encoding="utf-8")
    return path


def test_pilot_is_valid_small_wgs84_polygon() -> None:
    polygon = load_aoi(PILOT_SOURCE)
    assert polygon.is_valid
    assert polygon.exterior.is_ccw
    assert polygon.bounds == (105.84, 21.02, 105.86, 21.04)
    area = prepare_area(polygon, 3000)
    assert 4_000_000 < area.aoi_meters.area < 5_000_000


def test_coverage_accepts_boundary_and_preserves_coordinate_order() -> None:
    polygon = load_aoi(PILOT_SOURCE)
    assert covers_location(polygon, latitude=21.03, longitude=105.85)
    assert covers_location(polygon, latitude=21.02, longitude=105.85)
    assert covers_location(polygon, latitude=21.02, longitude=105.84)
    assert not covers_location(polygon, latitude=21.019, longitude=105.85)
    with pytest.raises(ValueError):
        covers_location(polygon, latitude=105.85, longitude=21.03)


def test_buffer_is_three_kilometers_in_projected_units() -> None:
    area = prepare_area(load_aoi(PILOT_SOURCE), 3000)
    assert area.routing_area_meters.covers(area.aoi_meters)
    # Polygonal arcs slightly underestimate a circle between sampled vertices.
    assert area.routing_area_meters.boundary.distance(area.aoi_meters) == pytest.approx(
        3000, abs=0.5
    )
    assert area.routing_area_meters.area > area.aoi_meters.area
    assert area.routing_area_wgs84.exterior.is_ccw
    converter = Transformer.from_crs("EPSG:4326", "EPSG:32648", always_xy=True)
    first_lon, first_lat = area.routing_area_wgs84.exterior.coords[0]
    first_projected = Point(*converter.transform(first_lon, first_lat))
    assert first_projected.distance(area.aoi_meters) == pytest.approx(3000, abs=0.01)
    # Routing may leave the AOI, but this does not expand input coverage.
    x, y = area.routing_area_wgs84.exterior.coords[0]
    assert not covers_location(area.aoi_wgs84, latitude=y, longitude=x)


@pytest.mark.parametrize("distance", [0, -1, float("nan"), float("inf"), True])
def test_invalid_buffer_is_rejected(distance: float) -> None:
    with pytest.raises(ValueError, match="buffer"):
        prepare_area(load_aoi(PILOT_SOURCE), distance)


def test_buffer_configuration_changes_extent_without_mutating_aoi() -> None:
    aoi = load_aoi(PILOT_SOURCE)
    original = aoi.wkb
    small = prepare_area(aoi, 1000)
    large = prepare_area(aoi, 3000)
    assert large.routing_area_meters.covers(small.routing_area_meters)
    assert aoi.wkb == original


@pytest.mark.parametrize("coordinates", [
    [],
    [[[105.84, 21.02], [105.86, 21.02], [105.86, 21.04], [105.84, 21.04]]],
    [[[105.84, 21.02], [105.86, 21.04], [105.86, 21.02], [105.84, 21.04], [105.84, 21.02]]],
    [[[105.84, 21.02], [105.85, 21.02], [105.86, 21.02], [105.84, 21.02]]],
    [[[105.84, 95], [105.86, 95], [105.86, 96], [105.84, 95]]],
    [[[True, 21.02], [105.86, 21.02], [105.86, 21.04], [True, 21.02]]],
    [[[105.84, 21.02, 0], [105.86, 21.02, 0], [105.86, 21.04, 0], [105.84, 21.02, 0]]],
])
def test_invalid_polygons_are_rejected(tmp_path: Path, coordinates: list) -> None:
    with pytest.raises(ValueError):
        load_aoi(_write_polygon(tmp_path, coordinates))


@pytest.mark.parametrize("text", [
    "not JSON",
    "[]",
    '{"type":"MultiPolygon","coordinates":[]}',
    '{"type":"Feature","geometry":null}',
    '{"type":"Polygon","coordinates":[[[NaN,21],[105,21],[105,22],[NaN,21]]]}',
])
def test_invalid_documents_are_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "invalid.geojson"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_aoi(path)


def test_hole_interior_is_outside_coverage(tmp_path: Path) -> None:
    exterior = list(load_aoi(PILOT_SOURCE).exterior.coords)
    hole = [(105.845, 21.025), (105.855, 21.025), (105.855, 21.035),
            (105.845, 21.035), (105.845, 21.025)]
    polygon = load_aoi(_write_polygon(tmp_path, [exterior, hole]))
    assert not covers_location(polygon, latitude=21.03, longitude=105.85)
    assert covers_location(polygon, latitude=21.025, longitude=105.845)


def test_cli_writes_reloadable_artifacts_and_metadata(tmp_path: Path) -> None:
    aoi_path = tmp_path / "aoi.geojson"
    routing_path = tmp_path / "routing.geojson"
    assert main([
        "--source", str(PILOT_SOURCE),
        "--aoi-output", str(aoi_path),
        "--routing-output", str(routing_path),
        "--buffer-m", "3000",
    ]) == 0
    aoi = load_aoi(aoi_path)
    routing = load_aoi(routing_path)
    metadata = json.loads(aoi_path.with_suffix(".metadata.json").read_text())
    assert aoi.equals(load_aoi(PILOT_SOURCE))
    assert routing.is_valid and routing.covers(aoi)
    assert metadata["buffer_m"] == 3000
    assert metadata["measurement_crs"] == "EPSG:32648"
    assert metadata["boundary_rule"] == "covers"
    assert metadata["area_id"] == "hanoi-pilot-v1"
    assert len(metadata["source_sha256"]) == 64


def test_cli_invalid_input_writes_nothing(tmp_path: Path) -> None:
    source = tmp_path / "invalid.geojson"
    source.write_text('{"type":"Polygon","coordinates":[]}', encoding="utf-8")
    aoi_path = tmp_path / "aoi.geojson"
    routing_path = tmp_path / "routing.geojson"
    with pytest.raises(SystemExit) as exc:
        main(["--source", str(source), "--aoi-output", str(aoi_path),
              "--routing-output", str(routing_path)])
    assert exc.value.code == 2
    assert not aoi_path.exists()
    assert not routing_path.exists()


def test_cli_refuses_to_overwrite_source(tmp_path: Path) -> None:
    source = _write_polygon(tmp_path, list(Polygon([
        (105.84, 21.02), (105.86, 21.02), (105.86, 21.04), (105.84, 21.02),
    ]).__geo_interface__["coordinates"]))
    original = source.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["--source", str(source), "--aoi-output", str(source)])
    assert exc.value.code == 2
    assert source.read_bytes() == original
