"""All-push costs skip inputs another placement already brings to the node.

CostCalculator._adjust_for_local_events subtracts the cost of events that are
already at the node (the event stack). For push-pull this worked; for
all-push _compute_all_push_adjustment looked for
step["detailed_cost_contribution"]["pull_response"], a key the all-push step
never has, so all-push always paid for every input again.

The tree (events flow towards the cloud 0, the sink):

            0 (cloud)
          /   \\
        1       2
       / \\     / \\
      3   4   5   6

A (10/s) is produced at 3, B (100/s) and C (1000/s) at 4. Q1 = AND(A, B) on
node 1 brings A and B there; Q2 = AND(A, C) on node 1 then only needs C.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.all_pairs import create_routing_dict
from core.structures import init_event_nodes
from kraken.components.cost_calculator import CostCalculator
from kraken.components.event_stack_manager import update_event_stack
from kraken.data.acquisition_step import AcquisitionSet
from kraken.data.state import PlacementInfo, SolutionCandidate
from kraken.problem import PlacementProblem
from kraken.search.greedy import GreedySearch

TREE = {1: [0], 2: [0], 3: [1], 4: [1], 5: [2], 6: [2]}  # child: parents
SOURCES = {"A": {3: 10.0}, "B": {4: 100.0}, "C": {4: 1000.0}}
Q1, Q2, Q3 = "AND(A, B)", "AND(A, C)", "SEQ(B, A)"
DEPS = {Q1: ["A", "B"], Q2: ["A", "C"], Q3: ["B", "A"]}
RATES = {Q1: (0.001, 1.0), Q2: (0.0001, 2.0), Q3: (0.001, 1.0)}


def _context(workload):
    graph = nx.DiGraph()
    graph.add_nodes_from(range(7))
    for child, parents in TREE.items():
        graph.add_edges_from((child, p) for p in parents)
    undirected = graph.to_undirected()
    distances = [[nx.shortest_path_length(undirected, a, b) for b in range(7)]
                 for a in range(7)]
    network_data = {n: [e for e, s in SOURCES.items() if n in s] for n in range(7)}
    nodes_per_event = {e: sorted(s) for e, s in SOURCES.items()}
    event_nodes, index_event_nodes = init_event_nodes(nodes_per_event, network_data)
    return {
        "query_workload": list(workload),
        "dependencies_per_projection": DEPS,
        "pairwise_distance_matrix": distances,
        "all_pairs": distances,
        "graph": graph,
        "routing_dict": create_routing_dict(graph),
        "network_data": network_data,
        "event_nodes": event_nodes,
        "event_distribution_matrix": event_nodes,
        "index_event_nodes": index_event_nodes,
        "global_event_rates": {e: max(s.values()) for e, s in SOURCES.items()},
        "projection_rates_selectivity": RATES,
        "pairwise_selectivities": {},
        "primitive_events_per_projection": {q: sorted(set(d)) for q, d in DEPS.items()},
        "nodes_per_primitive_event": nodes_per_event,
        "sink_nodes": [0],
        "local_rate_lookup": SOURCES,
        "simulation_mode": SimpleNamespace(value="deterministic"),
        "latency_weighting_factor": 0.0,
        "cost_weight": 1.0,
        "latency_weight": 0.0,
    }


def _all_push_only():
    """No PrePP buffer: Kraken falls back to all-push for every node."""
    return mock.patch.object(CostCalculator, "_build_prepp_input_buffer",
                             return_value=None)


def _with_q1_on(node):
    """A state with Q1 placed (all-push) on the node."""
    candidate = SolutionCandidate()
    info = PlacementInfo(projection=Q1, node=node, strategy="all_push",
                         individual_cost=0.0, individual_transmission_latency=0.0,
                         individual_processing_latency=0.0,
                         acquisition_steps=AcquisitionSet())
    candidate.placements[Q1] = info
    update_event_stack(candidate.event_stack, node, Q1, info)
    return candidate


class TestAllPushLocalEvents(unittest.TestCase):
    def _all_push(self, projection, node, state):
        with _all_push_only():
            results = CostCalculator(_context(workload=())).calculate(
                projection, node, state)
        self.assertEqual([r["strategy"] for r in results], ["all_push"])
        return results[0]

    def test_input_already_at_the_node_is_not_pushed_again(self):
        # A is at node 1 for Q1: Q2 pays only for C (1000 x 1 hop), not for
        # A (10 x 1 hop). C still travels a hop, so the latency stays.
        result = self._all_push(Q2, 1, _with_q1_on(1))
        self.assertEqual(result["individual_cost"], 1000.0)
        self.assertEqual(result["transmission_latency"], 1)
        step = result["acquisition_steps"].steps[0]
        self.assertEqual(step.already_at_node, ["A"])
        self.assertEqual(step.acquired_by_query, {"A": Q1})

    def test_all_inputs_at_the_node(self):
        # Q3 needs A and B, both already at node 1: nothing travels.
        result = self._all_push(Q3, 1, _with_q1_on(1))
        self.assertEqual(result["individual_cost"], 0.0)
        self.assertEqual(result["transmission_latency"], 0)

    def test_inputs_at_another_node_still_count(self):
        # Q1 sits on the cloud: on node 1, Q2 pays for A and C.
        result = self._all_push(Q2, 1, _with_q1_on(0))
        self.assertEqual(result["individual_cost"], 1010.0)
        self.assertIsNone(result["acquisition_steps"].steps[0].already_at_node)

    def test_greedy_shares_the_input(self):
        # Q1 on node 1: 10 + 100 + its output 1 x 1 hop to the sink = 111.
        # Q2 on node 1: C 1000 + output 2 x 1 hop = 1002 (was 1012 with A
        # pushed again). On the cloud it would cost 20 + 2000.
        with _all_push_only():
            problem = PlacementProblem([Q1, Q2], _context(workload=(Q1, Q2)), False)
            solution = GreedySearch().solve(problem)
        self.assertEqual(solution.placements[Q1].node, 1)
        self.assertEqual(solution.placements[Q1].individual_cost, 111.0)
        self.assertEqual(solution.placements[Q2].node, 1)
        self.assertEqual(solution.placements[Q2].individual_cost, 1002.0)


if __name__ == "__main__":
    unittest.main()
