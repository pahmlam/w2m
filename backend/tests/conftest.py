import networkx as nx
import pytest


@pytest.fixture
def road_graph():
    """Directed fixture: parallel arcs, asymmetric return, one-way tail, isolated node."""
    graph = nx.MultiDiGraph()
    for node, x in [(1, 0), (2, 100), (3, 200), (4, 300)]:
        graph.add_node(node, x=x, y=0, in_aoi=True)
    graph.add_edge(1, 2, key=0, travel_time=100.0, length_m=100.0)
    graph.add_edge(1, 2, key=1, travel_time=80.0, length_m=100.0)
    graph.add_edge(1, 2, key=2, travel_time=80.0, length_m=100.0)
    graph.add_edge(2, 1, key=0, travel_time=120.0, length_m=100.0)
    graph.add_edge(2, 3, key=0, travel_time=50.0, length_m=100.0)
    return graph


@pytest.fixture
def meeting_payload():
    # Synthetic contract coordinates; coincident origins are intentionally allowed.
    return {"origins": [{"id": label, "lat": 21.03, "lon": 105.84} for label in "ABCD"]}
