"""Tests for multi-node placement (components/multi_node.py).

A multi-node placement splits one input X of a projection over several
instances: every instance receives all senders of the other inputs, and each
sender of X sends to exactly one instance, so every combination of one
sender per input meets exactly once.

Most tests use this tree (events flow towards the cloud 0, the sink):

            0 (cloud)
          /   \\
        1       2
       / \\     / \\
      3   4   5   6

A (10/s) is produced at 3 and B (1000/s) at 4 and 6, SEQ(A, B) has
selectivity 0.0001, i.e. output rate 0.0001 x 10 x 2000 = 2. Only the cloud
receives A, B@4 and B@6, so a single-node placement sits there:
A 10 x 2 hops + B 1000 x 2 + B 1000 x 2 = 4020. Splitting B, an instance on
node 1 gets A and B@4 (10 + 1000, plus its output 1 x 1 hop to the sink) and
one on the cloud gets A and B@6 (20 + 2000): 3031.
"""

import itertools
import os
import random
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import networkx as nx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.all_pairs import create_routing_dict
from core.structures import init_event_nodes
from kraken.components.cost_calculator import CostCalculator
from kraken.components.multi_node import choose_instances, splittable_inputs
from kraken.problem import PlacementProblem
from kraken.search.greedy import GreedySearch

TREE = {1: [0], 2: [0], 3: [1], 4: [1], 5: [2], 6: [2]}  # child: parents
SOURCES = {"A": {3: 10.0}, "B": {4: 1000.0, 6: 1000.0}}
Q = "SEQ(A, B)"
Q_RATES = (0.0001, 2.0)  # (selectivity, output rate)
# A query on top of Q, for nested placements: C (1/s) is produced at 5.
Q2 = "SEQ(A, B, C)"
Q2_RATES = (0.01, 0.04)


def _graph(parents):
    graph = nx.DiGraph()
    graph.add_nodes_from(range(max(parents) + 1))
    for child, ps in parents.items():
        graph.add_edges_from((child, p) for p in ps)
    return graph


def _distances(graph):
    undirected = graph.to_undirected()
    nodes = sorted(graph.nodes)
    return [[nx.shortest_path_length(undirected, a, b) for b in nodes] for a in nodes]


def _reaches(graph):
    """reaches(u, h): u's events can flow up to h."""
    return lambda u, h: u == h or nx.has_path(graph, u, h)


def _context(sources=SOURCES, workload=(Q,), deps=None, rates=None,
             parents=TREE, multi=True, push_pull=False, xi=0.0):
    """A Kraken problem context like run._gather_problem_parameters builds."""
    deps = deps or {Q: ["A", "B"]}
    rates = rates or {Q: Q_RATES}
    graph = _graph(parents)
    distances = _distances(graph)
    nodes = sorted(graph.nodes)
    network_data = {n: [e for e, s in sources.items() if n in s] for n in nodes}
    nodes_per_event = {e: sorted(s) for e, s in sources.items()}
    event_nodes, index_event_nodes = init_event_nodes(nodes_per_event, network_data)
    primitives = {}
    for projection in deps:
        primitives[projection] = sorted(e for e in sources if e in projection)
    return {
        "query_workload": list(workload),
        "dependencies_per_projection": deps,
        "pairwise_distance_matrix": distances,
        "all_pairs": distances,
        "graph": graph,
        "routing_dict": create_routing_dict(graph),
        "network_data": network_data,
        "event_nodes": event_nodes,
        "event_distribution_matrix": event_nodes,
        "index_event_nodes": index_event_nodes,
        "global_event_rates": {e: max(s.values()) for e, s in sources.items()},
        "projection_rates_selectivity": rates,
        "pairwise_selectivities": {},
        "primitive_events_per_projection": primitives,
        "nodes_per_primitive_event": nodes_per_event,
        "sink_nodes": [0],
        "local_rate_lookup": sources,
        "simulation_mode": SimpleNamespace(value="deterministic"),
        "latency_weighting_factor": xi,
        "cost_weight": 1.0,
        "latency_weight": 0.0,
        "multi_node_placement": multi,
        "push_pull": push_pull,
    }


def _solve(order=(Q,), **kwargs):
    problem = PlacementProblem(list(order), _context(**kwargs), False)
    return GreedySearch().solve(problem), problem


def _senders(sources):
    return {e: sorted(s.items()) for e, s in sources.items()}


class TestTwoSteps(unittest.TestCase):
    """Step 1 (is a split possible?) and step 2 (which instances?)."""

    def test_tree_example_splits_b(self):
        graph = _graph(TREE)
        hosts = [0, 1, 2, 5]  # the nodes producing no events
        splittable = splittable_inputs(_senders(SOURCES), hosts, _reaches(graph))
        # A has one sender. Splitting B, the hosts must receive A from 3.
        self.assertEqual(splittable, {"B": [0, 1]})
        options = choose_instances(
            _senders(SOURCES)["B"], _senders(SOURCES)["A"], [0, 1],
            _reaches(graph), _distances(graph),
            output_per_split_rate=Q_RATES[1] / 2000.0,
            sink_distance=lambda host: _distances(graph)[host][0],
        )
        self.assertEqual(options, [((0, (6,)), (1, (4,)))])

    def test_no_option_if_every_input_spans_both_subtrees(self):
        # A at 3 and 5, B at 4 and 6: only the cloud receives every sender of
        # either input, so no split has two instances.
        sources = {"A": {3: 10.0, 5: 10.0}, "B": {4: 1000.0, 6: 1000.0}}
        graph = _graph(TREE)
        splittable = splittable_inputs(_senders(sources), [0, 1, 2], _reaches(graph))
        self.assertEqual(splittable, {"A": [0], "B": [0]})
        for split, hosts in splittable.items():
            complete = [s for e, lst in _senders(sources).items() if e != split for s in lst]
            self.assertEqual(
                choose_instances(_senders(sources)[split], complete, hosts,
                                 _reaches(graph), _distances(graph)),
                [],
            )
        solution, _ = _solve(sources=sources, rates={Q: (0.0001, 4.0)})
        self.assertEqual(solution.placements[Q].location, 0)

    def test_local_search_merges_instances(self):
        # Hosts 10, 11, 12; complete sender 0 costs 10 per instance. Split
        # senders 1 and 2 are 1 hop from "their" host (10 / 11) and 5 hops
        # from the other one; 3 reaches only 12. Widest split: 3 instances,
        # 30 + 3 = 33. Merging 1 and 2 on 11: 20 + 5 + 1 + 1 = 27.
        near = {(1, 10): 1, (1, 11): 5, (2, 11): 1, (2, 10): 5, (3, 12): 1}
        distances = {u: {h: near.get((u, h), 99) for h in (10, 11, 12)} for u in (1, 2, 3)}
        distances[0] = {10: 1, 11: 1, 12: 1}
        options = choose_instances(
            [(1, 1.0), (2, 1.0), (3, 1.0)], [(0, 10.0)], [10, 11, 12],
            lambda u, h: u == 0 or (u, h) in near, distances,
        )
        self.assertEqual(options, [
            ((10, (1,)), (11, (2,)), (12, (3,))),  # widest split
            ((11, (1, 2)), (12, (3,))),  # local optimum
        ])

    def test_every_combination_meets_exactly_once(self):
        """Random DAGs: every option is a valid split of one input."""
        checked = 0
        for seed in range(40):
            rng = random.Random(seed)
            n = rng.randint(8, 16)
            # node i > 0 has 1-3 parents with smaller ids, so 0 is the root
            parents = {i: rng.sample(range(i), min(i, rng.randint(1, 3))) for i in range(1, n)}
            graph = _graph(parents)
            reaches = _reaches(graph)
            leaves = [i for i in range(1, n) if not any(i in ps for ps in parents.values())]
            sources = {
                e: {node: float(rng.choice([1, 10, 100]))
                    for node in rng.sample(leaves, rng.randint(1, min(3, len(leaves))))}
                for e in "ABC"[: rng.randint(2, 3)]
            }
            senders = _senders(sources)
            producing = {node for s in sources.values() for node in s}
            hosts = [h for h in range(n) if h not in producing]
            for split, valid in splittable_inputs(senders, hosts, reaches).items():
                complete = [s for e, lst in senders.items() if e != split for s in lst]
                for option in choose_instances(senders[split], complete, valid,
                                               reaches, _distances(graph)):
                    checked += 1
                    self.assertGreaterEqual(len(option), 2)
                    for host, units in option:
                        self.assertTrue(all(reaches(c, host) for c, _ in complete))
                        self.assertTrue(all(reaches(u, host) for u in units))
                    # one sender per input: count the instances receiving it
                    per_input = [[node for node, _ in senders[e]] for e in senders]
                    for combination in itertools.product(*per_input):
                        meets = [
                            host for host, units in option
                            if all(node in units or e != split
                                   for e, node in zip(senders, combination))
                        ]
                        self.assertEqual(len(meets), 1, (seed, option, combination))
        self.assertGreater(checked, 10)  # the property was exercised


class TestKrakenTree(unittest.TestCase):
    """The whole Kraken pipeline on the tree, all-push only."""

    def test_single_node_without_multi_node_placement(self):
        solution, _ = _solve(multi=False)
        placement = solution.placements[Q]
        self.assertEqual((placement.location, placement.individual_cost), (0, 4020.0))
        self.assertEqual(placement.instances, [])

    def test_multi_node_placement(self):
        solution, _ = _solve()
        placement = solution.placements[Q]
        self.assertEqual(placement.location, (0, 1))
        self.assertIsNone(placement.node)
        self.assertEqual(placement.split_input, "B")
        self.assertEqual(
            [(i.node, i.split_senders, i.output_rate, i.individual_cost)
             for i in placement.instances],
            [(0, [6], 1.0, 2020.0), (1, [4], 1.0, 1011.0)],
        )
        self.assertEqual(solution.cumulative_cost, 3031.0)

    def test_event_stack_holds_only_complete_inputs(self):
        # Each instance has all A's, but only part of the B's.
        solution, _ = _solve()
        for node in (0, 1):
            self.assertEqual(set(solution.event_stack[node]), {"A"})

    def test_latency_takes_the_slowest_instance(self):
        # l_p = output rate, weighted by xi = 1. Single node at the cloud:
        # 2 + 2 hops = 4. Multi-node: node 1 needs 1 + 1 hop + 1 hop to the
        # sink, the cloud instance 1 + 2 hops: max 3.
        single, problem = _solve(multi=False, xi=1.0)
        self.assertEqual(single.get_critical_path_latency(problem), 4.0)
        multi, problem = _solve(xi=1.0)
        self.assertEqual(multi.placements[Q].location, (0, 1))
        self.assertEqual(multi.get_critical_path_latency(problem), 3.0)

    def test_parent_reads_the_instances(self):
        # Q2 = SEQ(Q, C), C at 5. Q is placed on (0, 1) and only feeds Q2, so
        # its instances send nothing to the sink: 1010 + 2020. Q2 then needs
        # a host every instance and C reach: the cloud, receiving Q from
        # node 1 (1/s, 1 hop) and C (1/s, 2 hops): 3.
        sources = dict(SOURCES, C={5: 1.0})
        kwargs = dict(sources=sources, workload=(Q2,), order=(Q, Q2),
                      deps={Q: ["A", "B"], Q2: [Q, "C"]},
                      rates={Q: Q_RATES, Q2: Q2_RATES})
        solution, problem = _solve(**kwargs)
        self.assertEqual(solution.placements[Q].location, (0, 1))
        self.assertEqual(solution.placements[Q].individual_cost, 3030.0)
        self.assertEqual(solution.placements[Q2].location, 0)
        self.assertEqual(solution.placements[Q2].individual_cost, 3.0)
        senders = problem.cost_calculator.get_input_senders(Q2, solution)
        self.assertEqual(senders, {Q: [(0, 1.0), (1, 1.0)], "C": [(5, 1.0)]})
        # Single-node: Q at the cloud for 4020, Q2 gets C for 2.
        single, _ = _solve(multi=False, **kwargs)
        self.assertEqual(single.cumulative_cost, 4022.0)

    def test_push_pull_keeps_consumed_projections_single_node(self):
        # With push-pull on, a multi-node input would cost its consumers
        # push-pull, so only projections nobody reads may be split. PrePP is
        # stubbed out (no buffer), which leaves all-push for every node.
        sources = dict(SOURCES, C={5: 1.0})
        nested = dict(sources=sources, workload=(Q2,), order=(Q, Q2),
                      deps={Q: ["A", "B"], Q2: [Q, "C"]},
                      rates={Q: Q_RATES, Q2: Q2_RATES})
        with mock.patch.object(CostCalculator, "_build_prepp_input_buffer",
                               return_value=None):
            solution, _ = _solve(push_pull=True, **nested)
            self.assertEqual(solution.placements[Q].location, 0)
            solution, _ = _solve(push_pull=True)
            self.assertEqual(solution.placements[Q].location, (0, 1))


if __name__ == "__main__":
    unittest.main()
