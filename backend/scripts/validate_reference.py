"""Export a reproducible offline M2 run with synthetic origins and route evidence."""

import argparse
import hashlib
import json
import pickle
import platform
import subprocess
from datetime import UTC, datetime
from importlib.metadata import version
from itertools import combinations
from math import fsum, hypot
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import Point

from app.config.settings import Settings
from app.models.requests import MeetingRequest
from app.services.coordinate_snapper import CoordinateSnapper
from app.services.graph_loader import load_reference_graph
from app.services.meeting_optimizer import build_meeting_results, rank_candidates
from app.services.shortest_path import route_origins
from scripts.download_osm import _sha256


def validate_reference(bundle_dir: Path, output: Path, seed: int = 20261115) -> Path:
    """Check M2 output on a local bundle; never accept or persist user locations."""
    if output.exists():
        raise FileExistsError(f"Choose a new report path: {output}")
    reference = load_reference_graph(bundle_dir)
    snapper = CoordinateSnapper(reference, Settings(_env_file=None))
    projector = Transformer.from_crs(32648, 4326, always_xy=True)
    edges = [e for e in snapper.edge_ids
             if all(reference.graph.nodes[n]['in_aoi'] for n in e[:2])]
    origins = []
    for index in np.random.default_rng(seed).permutation(len(edges)):
        point = reference.graph.edges[edges[index]]['geometry'].interpolate(.3, normalized=True)
        lon, lat = projector.transform(point.x, point.y, errcheck=True)
        if reference.aoi.covers(Point(lon, lat)):
            origins.append(dict(id='ABCD'[len(origins)], lat=lat, lon=lon))
            if len(origins) == 4:
                break
    if len(origins) != 4:
        raise ValueError("Bundle needs at least four roads inside AOI for the synthetic sample")
    request = MeetingRequest.model_validate(dict(origins=origins, travel_mode='car', optimization={
        'phi': .5, 'max_travel_seconds': 3600, 'top_k': 5, 'min_spacing_meters': 500,
    }))
    routing = route_origins(snapper, request)

    def fingerprint() -> str:
        # Hash graph data, excluding NetworkX's lazily cached view objects.
        graphs = [(g.graph, list(g.nodes(data=True)), list(g.edges(keys=True, data=True)))
                  for g in (reference.graph, routing.overlay.graph)]
        return hashlib.sha256(pickle.dumps((graphs, routing.sources))).hexdigest()

    before = fingerprint()
    scenarios = []
    for phi in (0., .5, 1.):
        ranking = rank_candidates(routing, phi=phi, max_travel_seconds=3600)
        results = build_meeting_results(ranking, top_k=5, min_spacing_meters=500)
        if not results:
            raise ValueError("Synthetic request has no meeting points within 3600 seconds")
        best = ranking.candidates[0].raw_times_seconds
        if any(all(t <= b for t, b in zip(c.raw_times_seconds, best))
               and any(t < b for t, b in zip(c.raw_times_seconds, best))
               for c in ranking.candidates):
            raise ValueError("Top-ranked point is Pareto dominated")
        spacing = [hypot(reference.graph.nodes[a.node_id]['x'] -
                         reference.graph.nodes[b.node_id]['x'],
                         reference.graph.nodes[a.node_id]['y'] -
                         reference.graph.nodes[b.node_id]['y'])
                   for a, b in combinations(results, 2)]
        if any(distance < 500 for distance in spacing):
            raise ValueError("Selected points violate spacing")
        routes = []
        for result in results:
            if set(result.routes) != set('ABCD'):
                raise ValueError("Missing origin routes")
            for source in routing.sources:
                node = result.node_id
                edge_ids = []
                while node != source.source_node:
                    if len(edge_ids) >= len(routing.overlay.graph):
                        raise ValueError("Predecessor chain does not reach source")
                    parent, key = source.paths.predecessors[node]
                    edge_ids.append((parent, node, key))
                    node = parent
                edge_ids.reverse()
                seconds = fsum(routing.overlay.graph.edges[e]['travel_time'] for e in edge_ids)
                raw = source.paths.distances_seconds[result.node_id]
                error = abs(seconds - raw)
                route = result.routes[source.snap.origin_id]
                if (error > 1e-6 * raw + 1e-3
                        or route.duration_seconds != result.travel_times[source.snap.origin_id]
                        or round(10 * route.access_seconds) + round(10 * route.network_seconds)
                        != round(10 * route.duration_seconds)):
                    raise ValueError("Route timing mismatch")
                expected_xy = [source.snap.snapped_xy]
                for edge in edge_ids:
                    expected_xy.extend(list(routing.overlay.graph.edges[edge]['geometry'].coords)[1:])
                if len(expected_xy) == 1:
                    expected_xy.append(expected_xy[0])
                expected_lonlat = [projector.transform(*xy, errcheck=True) for xy in expected_xy]
                length = fsum(routing.overlay.graph.edges[e]['length_m'] for e in edge_ids)
                if (route.geometry.coordinates != expected_lonlat
                        or abs(route.distance_meters - length) > 1e-8):
                    raise ValueError("Route geometry or distance mismatch")
                routes.append(dict(origin_id=source.snap.origin_id, node_id=result.node_id,
                                   edge_ids=edge_ids, network_raw_seconds=raw,
                                   edge_sum_seconds=seconds, error_seconds=error))
        scenarios.append(dict(phi=phi, candidate_count=len(ranking.candidates),
                              min_spacing_meters=min(spacing) if spacing else None,
                              top1_pareto_safe=True, route_checks=routes,
                              results=[result.model_dump(mode='json') for result in results]))
    if fingerprint() != before:
        raise ValueError("Graph data or routing tables changed during selection")
    backend = Path(__file__).resolve().parents[1]
    implementations = ['scripts/validate_reference.py', *[
        f'app/services/{name}.py' for name in ('coordinate_snapper', 'graph_loader',
            'request_overlay', 'shortest_path', 'objective', 'meeting_optimizer', 'route_builder')
    ]]
    report = dict(
        schema_version=1, status='passed', validated_at=datetime.now(UTC).isoformat(), seed=seed,
        scope='M2 reference sample; TC-01–TC-12 unit tests are run separately',
        origin_source='Synthetic road samples, not user locations',
        graph_version=reference.graph_version,
        weight_profile_version=reference.weight_profile_version,
        source_metadata_sha256=_sha256(bundle_dir / 'metadata.json'),
        git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                         cwd=backend, text=True).strip(),
        implementation_sha256={name: _sha256(backend / name) for name in implementations},
        environment=dict(python=platform.python_version(), platform=platform.platform(),
                         libraries={name: version(name) for name in
                                    ('networkx', 'numpy', 'shapely', 'pyproj', 'osmnx')}),
        request=request.model_dump(mode='json'), graph_and_routing_unchanged=True,
        scenarios=scenarios,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return output


def main(argv: list[str] | None = None) -> int:
    """Run the offline reference acceptance sample and export inspectable JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261115)
    args = parser.parse_args(argv)
    try:
        output = validate_reference(args.bundle_dir, args.output, args.seed)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError,
            subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(f'M2 reference report: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
