"""Exercise CSR startup from a fixed bundle without offline graph dependencies."""

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy.sparse import csr_matrix, save_npz
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import box, mapping

from app.config.settings import Settings
from app.main import create_app
from app.services.graph_loader import load_csr_graph
from scripts.download_osm import _sha256


@pytest.fixture
def csr_bundle(tmp_path: Path) -> Path:
    versions = {"graph_version": "fixture-v1", "weight_profile_version": "car-v1"}
    (tmp_path / "validation.json").write_text(json.dumps({
        **versions, "status": "passed", "checks": {"csr_weights_and_mappings": "passed"},
    }))
    (tmp_path / "aoi.geojson").write_text(json.dumps(mapping(box(104, 20, 106, 22))))
    (tmp_path / "reverse_edges.json").write_text(json.dumps({
        "pairs": [{"forward": [-3, 7, 0], "reverse": [7, -3, 0]}],
        "unpaired": [{"edge": [-3, 7, 1], "reason": "oneway", "candidates": []}],
    }))
    (tmp_path / "graph.graphml").write_text("""\
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <key id="weight" for="edge" attr.name="travel_time" attr.type="double"/>
  <graph edgedefault="directed">
    <node id="-3"/>
    <node id="7"/>
    <edge source="-3" target="7" id="0"><data key="weight">5</data></edge>
    <edge source="-3" target="7" id="1"><data key="weight">20</data></edge>
    <edge source="7" target="-3" id="0"><data key="weight">11</data></edge>
  </graph>
</graphml>
""")
    save_npz(tmp_path / "csr.npz", csr_matrix([[0.0, 5.0], [11.0, 0.0]]))
    np.savez(
        tmp_path / "mappings.npz",
        node_ids=np.array([-3, 7], dtype=np.int64),
        node_xy=np.array([[500000.0, 2300000], [500020, 2300000]]),
        node_lonlat=np.array([[105.0, 20.8], [105.0002, 20.8]]),
        in_aoi=np.array([True, True]),
        is_candidate=np.array([False, True]),
        edge_ids=np.array([[-3, 7, 0], [-3, 7, 1], [7, -3, 0]], dtype=np.int64),
        arc_edge_indices=np.array([0, 2], dtype=np.int64),
    )
    np.savez(
        tmp_path / "geometry.npz",
        coordinates=np.array([
            [500000.0, 2300000], [500020, 2300000],
            [500000, 2300000], [500010, 2300005], [500020, 2300000],
            [500020, 2300000], [500000, 2300000],
        ]),
        offsets=np.array([0, 2, 5, 7], dtype=np.int64),
    )
    checksums = {f"{file.stem}_sha256": _sha256(file) for file in tmp_path.iterdir()}
    (tmp_path / "metadata.json").write_text(json.dumps({
        **versions, **checksums, "stage": "csr", "crs": "EPSG:32648",
        "geometry_crs": "EPSG:32648", "travel_mode": "car", "source_date": "2026-11-06",
        "node_count": 2, "edge_count": 3, "csr_arc_count": 2, "candidate_node_count": 1,
    }))
    return tmp_path


def test_loads_directed_csr_and_protects_shared_buffers(csr_bundle: Path) -> None:
    graph = load_csr_graph(csr_bundle)
    matrix = graph.csr
    assert graph.node_indices[-3] == 0
    assert graph.node_indices[7] == 1
    assert graph.mappings["edge_ids"][graph.mappings["arc_edge_indices"]].tolist() == [
        [-3, 7, 0], [7, -3, 0],
    ]
    assert graph.geometry["offsets"].tolist() == [0, 2, 5, 7]
    np.testing.assert_array_equal(dijkstra(matrix, directed=True), [[0, 5], [11, 0]])
    assert np.shares_memory(matrix.data, graph.csr.data)
    for array in (matrix.data, matrix.indices, matrix.indptr,
                  *graph.mappings.values(), *graph.geometry.values()):
        with pytest.raises(ValueError, match="WRITEABLE"):
            array.setflags(write=True)

    # Requests get separate wrappers and array views over shared storage.
    matrix.data = np.zeros(matrix.nnz)
    assert graph.csr.data.tolist() == [5, 11]
    assert graph.mappings["node_ids"] is not graph.mappings["node_ids"]


def test_rejects_arc_mapping_with_wrong_endpoints_even_with_updated_checksum(
    csr_bundle: Path,
) -> None:
    mappings = csr_bundle / "mappings.npz"
    with np.load(mappings) as archive:
        arrays = dict(archive)
    arrays["arc_edge_indices"] = arrays["arc_edge_indices"][::-1]
    np.savez(mappings, **arrays)
    metadata_path = csr_bundle / "metadata.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["mappings_sha256"] = _sha256(mappings)
    metadata_path.write_text(json.dumps(metadata))

    with pytest.raises(ValueError, match="arc endpoints"):
        load_csr_graph(csr_bundle)


@pytest.mark.parametrize("corrupt", [False, True])
def test_startup_only_publishes_validated_graph(
    csr_bundle: Path, corrupt: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, graph_dir=csr_bundle)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    if corrupt:
        (csr_bundle / "geometry.npz").write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="checksum mismatch: geometry.npz"):
            load_csr_graph(csr_bundle)

    app = create_app()
    with TestClient(app) as client:
        graph = app.state.csr_graph
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == (503 if corrupt else 200)
        config = client.get("/api/v1/map/config")
        assert config.status_code == (503 if corrupt else 200)
        if corrupt:
            assert config.json()["error_code"] == "GRAPH_UNAVAILABLE"
            assert config.json()["request_id"] == config.headers["X-Request-ID"]
        assert (graph is None) == corrupt
        assert app.state.csr_graph is graph
    assert app.state.csr_graph is None
