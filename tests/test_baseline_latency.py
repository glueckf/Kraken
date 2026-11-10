"""Regression tests for the All-Push and INEv baseline latencies.

All-Push used to report the hop distance of the node farthest from the cloud,
whether or not it produces any event of the workload, and INEv reported that
same central number instead of the latency of its own plan. Both now follow
the events that are actually sent, with inputs arriving in parallel (the
model of Kraken's critical path).
"""

import os
import sys
import unittest
from types import SimpleNamespace

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from simulation_environment import compute_all_push
from simulator.evaluation_plan import Instance
from simulator.operator_placement import inputs_arrival


class _Query:
    def __init__(self, name, leafs):
        self.name = name
        self._leafs = leafs

    def leafs(self):
        return self._leafs

    def __str__(self):
        return self.name


class TestAllPushLatency(unittest.TestCase):
    def test_counts_only_nodes_that_send_events(self):
        # 0 (cloud) - 1 - 2 - 3, and 1 - 4. A is produced at 2, B at 4, both
        # two hops from the cloud; node 3 is three hops away but sends nothing.
        graph = nx.Graph([(0, 1), (1, 2), (2, 3), (1, 4)])
        all_pairs = [
            [nx.shortest_path_length(graph, i, j) for j in range(5)]
            for i in range(5)
        ]
        query = _Query("SEQ(A, B)", ["A", "B"])
        context = SimpleNamespace(
            query_workload=[query],
            allPairs=all_pairs,
            graph=graph,
            h_rates_data={"A": 10, "B": 1},
            h_IndexEventNodes={"A": ["A1"], "B": ["B1"], "A1": 0, "B1": 1},
            h_eventNodes=[[0, 0, 1, 0, 0], [0, 0, 0, 0, 1]],
            h_local_rate_lookup={"A": {2: 10}, "B": {4: 1}},
            h_projrates={query: (0.1, 1.0)},
            sum_of_input_rates_per_query={query: 11},
        )

        result = compute_all_push(context)

        self.assertEqual(result["cost"], 22)
        self.assertEqual(result["transmission_latency"], 2)


class TestInputsArrival(unittest.TestCase):
    def test_parallel_inputs_take_the_latest_not_the_sum(self):
        ready, available_at = {"AB": 2}, {}
        instances = [
            Instance("AB", "AB1", [5], {"ABC": [5, 6]}),
            Instance("C", "C1", [9], {"ABC": [9, 8, 7, 6]}),
        ]

        # AB is ready after 2 hops and travels 1 more; C travels 3 meanwhile.
        self.assertEqual(inputs_arrival(instances, "ABC", ready, available_at), 3)

    def test_event_picked_up_at_a_relay_keeps_its_travel_time(self):
        ready, available_at = {}, {}
        inputs_arrival(
            [Instance("A", "A1", [3], {"AB": [3, 2, 1]})], "AB", ready, available_at
        )
        # A later placement takes A at node 2, which it reached after 1 hop.
        arrival = inputs_arrival(
            [Instance("A", "A1", [2], {"AC": [2, 7]})], "AC", ready, available_at
        )

        self.assertEqual(available_at[("A1", 2)], 1)
        self.assertEqual(arrival, 2)


if __name__ == "__main__":
    unittest.main()
