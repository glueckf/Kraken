"""Regression tests: Kraken's host candidates must not depend on INEv's plan.

Simulation.run() runs INEv before Kraken. INEv mutates h_eventNodes /
h_IndexEventNodes in place: for every ETB it routes, each stop on the path
(often ending at the cloud, node 0) is marked as holding that ETB
(placement_aug.py, ``for stop in shortestPath: set_event_nodes(...)``).
Kraken used to read that mutated table as "where each primitive event is
produced", so relay nodes became required sources, and every host that is
not an ancestor of those relays dropped out. With INEv routing to the cloud,
Kraken was forced to the cloud.

Topology used below (edges point child -> parent, as in INES trees):

        0   cloud
        |
        1   fog
       / \\
      2   3      2 produces A, 3 produces B

Both 0 and 1 are ancestors of both producers, so both can host AND(A, B).
INEv's routing of A2 to the cloud marks stops 2, 1, 0 as holding A2.
"""

import os
import sys
import unittest
from types import SimpleNamespace

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.all_pairs import create_routing_dict
from core.structures import init_event_nodes, set_event_nodes
from kraken.components.optimizer import PlacementOptimizer
from kraken.run import _gather_problem_parameters

PROJECTION = "AND(A, B)"
H_NODES = {"A": [2], "B": [3]}
NETWORK_DATA = {0: [], 1: [], 2: ["A"], 3: ["B"]}
INEV_ROUTE_A2_TO_CLOUD = [2, 1, 0]
EXPECTED_CANDIDATES = [0, 1]

# init_event_nodes(H_NODES, NETWORK_DATA), written out
PRISTINE_EVENT_NODES = [[0, 0, 1, 0], [0, 0, 0, 1]]
PRISTINE_INDEX_EVENT_NODES = {"A2": 0, "A": ["A2"], "B3": 1, "B": ["B3"]}


def build_graph():
    graph = nx.DiGraph()
    graph.add_edges_from([(1, 0), (2, 1), (3, 1)])
    return graph


def event_tables_after_inev():
    """Event tables as INEv leaves them after routing A2 to the cloud."""
    event_nodes, index_event_nodes = init_event_nodes(H_NODES, NETWORK_DATA)
    for stop in INEV_ROUTE_A2_TO_CLOUD:
        set_event_nodes(stop, "A2", event_nodes, index_event_nodes)
    return event_nodes, index_event_nodes


class TestAncestorCandidatesUseProducers(unittest.TestCase):
    """PlacementOptimizer._get_ancestor_based_candidates()."""

    def test_inev_routing_stops_are_not_required_sources(self):
        graph = build_graph()
        event_nodes, index_event_nodes = event_tables_after_inev()
        params = {
            "network_data": NETWORK_DATA,
            "nodes_per_primitive_event": H_NODES,
            "primitive_events_per_projection": {PROJECTION: ["A", "B"]},
            "event_nodes": event_nodes,
            "index_event_nodes": index_event_nodes,
        }
        optimizer = PlacementOptimizer(graph, create_routing_dict(graph))

        candidates = optimizer._get_ancestor_based_candidates(PROJECTION, params)

        self.assertEqual(sorted(candidates), EXPECTED_CANDIDATES)


class TestGatherProblemParametersEventTables(unittest.TestCase):
    """kraken.run._gather_problem_parameters() on a post-INEv context."""

    def setUp(self):
        self.graph = build_graph()
        event_nodes, index_event_nodes = event_tables_after_inev()
        self.sim = SimpleNamespace(
            query_workload=[PROJECTION],
            h_mycombi={PROJECTION: ["A", "B"]},
            allPairs=[],
            graph=self.graph,
            h_network_data=NETWORK_DATA,
            h_eventNodes=event_nodes,
            h_IndexEventNodes=index_event_nodes,
            h_rates_data={"A": 1.0, "B": 1.0},
            h_projrates={},
            selectivities={},
            h_projFilterDict={},
            network=[None] * len(NETWORK_DATA),
            h_primitive_events={PROJECTION: ["A", "B"]},
            h_nodes=H_NODES,
            h_local_rate_lookup={"A": {2: 1.0}, "B": {3: 1.0}},
            sum_of_input_rates_per_query={},
            config=SimpleNamespace(mode=None, xi=0.0),
            latency_threshold=None,
        )

    def test_event_tables_are_init_time_not_inev_state(self):
        params = _gather_problem_parameters(self.sim)

        self.assertEqual(params["event_nodes"], PRISTINE_EVENT_NODES)
        self.assertEqual(params["event_distribution_matrix"], PRISTINE_EVENT_NODES)
        self.assertEqual(params["index_event_nodes"], PRISTINE_INDEX_EVENT_NODES)
        self.assertIsNot(params["event_nodes"], self.sim.h_eventNodes)

    def test_candidates_include_fog_host_after_inev(self):
        params = _gather_problem_parameters(self.sim)
        optimizer = PlacementOptimizer(params["graph"], params["routing_dict"])

        candidates = optimizer._get_ancestor_based_candidates(PROJECTION, params)

        self.assertEqual(sorted(candidates), EXPECTED_CANDIDATES)


if __name__ == "__main__":
    unittest.main()
