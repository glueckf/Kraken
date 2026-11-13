"""Tests for multi-node placement (components/multi_node.py).

TestTwoSteps covers the two steps on their own, TestPrePPInput what PrePP
sees of a multi-node placement. The Kraken scenarios run twice, with
multi-node placement off (TestMultiNodeOff) and on (TestMultiNodeOn), so
every change is checked in both modes.

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
from kraken.data.acquisition_step import AcquisitionSet
from kraken.data.state import PlacementInfo, PlacementInstance, SolutionCandidate
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


class TestPrePPInput(unittest.TestCase):
    """What PrePP sees of a multi-node placement (CostCalculator's buffer).

    PrePP models one rate per source of an event. An instance of a
    multi-node subquery sends only its share of the matches; the muse graph
    lists the instances as the subquery's sources with sourceShare= f, each
    sending f times the subquery's output rate.
    """

    def test_source_share_token(self):
        from prepp.prepp import extract_muse_graph_source_share

        line = ("SELECT SEQ(A, B) FROM A; B ON {0, 1} WITH selectionRate= 0.0001"
                " sourceShare= 0.25")
        self.assertEqual(extract_muse_graph_source_share(line), 0.25)
        self.assertIsNone(extract_muse_graph_source_share(line.split(" sourceShare")[0]))

    def _prepp_steps(self, on, source_share):
        """PrePP's plan for Q2 on the cloud, reading Q from the nodes in on."""
        import contextlib
        import io

        from prepp.prepp import generate_prePP

        sources = NESTED["sources"]
        lines = ["network"]
        for node in range(7):
            rates = [sources.get(e, {}).get(node, 0) for e in "ABCDEF"]
            children = [c for c, ps in TREE.items() if node in ps] or None
            lines += [f"Node {node} Node {node}", "Computational Power: inf",
                      "Memory: inf", f"Eventrates: {rates}",
                      f"Parents: {TREE.get(node)}", f"Child: {children}",
                      "Siblings: None", ""]
        share = "" if source_share is None else f" sourceShare= {source_share}"
        lines += [
            "selectivities",
            str({"AB": 0.0001, "BA": 0.0001, "AC": 0.01, "CA": 0.01, "BC": 1, "CB": 1}),
            "", "queries", Q2, "", "muse graph",
            f"SELECT {Q} FROM A; B ON {{{on}}} WITH selectionRate= 0.0001{share}",
            f"SELECT {Q2} FROM {Q}; C ON {{0}} WITH selectionRate= 0.01",
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            output = generate_prePP(io.StringIO("\n".join(lines)), "ppmuse", "e",
                                    0, 0, 1, True, allPairs=_distances(_graph(TREE)),
                                    is_deterministic=True)
        return {str(step.events_to_pull): step for step in output[6][Q2].steps}

    def test_prepp_scales_the_instance_rates(self):
        # Q's rate is 0.0001 x 10 x 2000 = 2. Listed on nodes 0 and 1, each
        # node sends all of it by default (INEv's multi-sink), so getting Q
        # from node 1 costs 2 x 1 hop; with sourceShare 0.5 it costs 1.
        key = str([Q])
        self.assertAlmostEqual(self._prepp_steps("0, 1", None)[key].total_cost, 2.0)
        self.assertAlmostEqual(self._prepp_steps("0, 1", 0.5)[key].total_cost, 1.0)

    def _nested_state(self, rates):
        """Q placed on nodes 0 and 1 with these instance output rates."""
        candidate = SolutionCandidate()
        candidate.placements[Q] = PlacementInfo(
            projection=Q, node=None, strategy="all_push", individual_cost=0.0,
            individual_transmission_latency=0.0, individual_processing_latency=0.0,
            acquisition_steps=AcquisitionSet(), split_input="B",
            instances=[PlacementInstance(node, [unit], rate, 0.0, 0.0, 0.0,
                                         AcquisitionSet())
                       for node, unit, rate in zip((0, 1), (6, 4), rates)],
        )
        return candidate

    def test_muse_graph_lists_the_instances(self):
        calculator = CostCalculator(_context(**{k: v for k, v in NESTED.items()
                                                 if k != "order"}))
        state = self._nested_state((1.5, 0.5))
        lines = []
        calculator._add_muse_graph_entries(lines, Q2, 0, {Q: (0, 1)}, state)
        # Two sources, 2.0 / 2 each on average.
        self.assertEqual(lines[0], "SELECT SEQ(A, B) FROM A; B ON {0, 1} WITH "
                                   "selectionRate= 0.0001 sourceShare= 0.5")
        # An instance of Q2 that receives Q from node 0 only: 1.5 of 2.0.
        lines = []
        calculator._add_muse_graph_entries(lines, Q2, 0, {Q: (0, 1)}, state,
                                           split=(Q, [0]))
        self.assertEqual(lines[0], "SELECT SEQ(A, B) FROM A; B ON {0} WITH "
                                   "selectionRate= 0.0001 sourceShare= 0.75")

    def test_instance_network_drops_the_other_sources(self):
        # A primitive split input: the instance's network keeps the event
        # only at the sources it receives; nothing else changes.
        import ast

        from kraken.run import _gather_problem_parameters

        simulation = _ines_simulation(*SIMULATIONS[-1])
        calculator = CostCalculator(_gather_problem_parameters(simulation))
        lookup = calculator.params["local_rate_lookup"]
        p, event = next(
            (p, dep)
            for p, deps in calculator.params["dependencies_per_projection"].items()
            for dep in deps
            if dep in lookup and len(lookup[dep]) >= 3
        )
        keep = sorted(lookup[event])[:1]
        dropped = set(lookup[event]) - set(keep)
        full = calculator._build_prepp_input_buffer(p, 0, SolutionCandidate())
        instance = calculator._build_prepp_input_buffer(
            p, 0, SolutionCandidate(), split=(event, keep))
        full, instance = full.getvalue().splitlines(), instance.getvalue().splitlines()
        self.assertEqual(len(full), len(instance))
        index = ord(event) - ord("A")
        node = None
        changed = set()
        for before, after in zip(full, instance):
            if before.startswith("Node "):
                node = int(before.split()[1])
            if before != after:
                self.assertTrue(before.startswith("Eventrates: "))
                rates_before = ast.literal_eval(before[len("Eventrates: "):])
                rates_after = ast.literal_eval(after[len("Eventrates: "):])
                self.assertEqual(rates_after[index], 0)
                self.assertGreater(rates_before[index], 0)
                rates_before[index] = 0
                self.assertEqual(rates_before, rates_after)
                changed.add(node)
        self.assertEqual(changed, dropped)


# Every scenario below runs twice, through TestMultiNodeOff and
# TestMultiNodeOn, so each change to Kraken is checked in both modes: off,
# Kraken must place every projection on one node exactly as it did before
# multi-node placement existed; on, it may split, and every split must be
# valid. EXPECTED holds the hand-derived results per mode.

NESTED = dict(sources=dict(SOURCES, C={5: 1.0}), workload=(Q2,), order=(Q, Q2),
              deps={Q: ["A", "B"], Q2: [Q, "C"]}, rates={Q: Q_RATES, Q2: Q2_RATES})

EXPECTED = {
    False: {
        # Q at the cloud: A 10 x 2 hops + B 1000 x 2 + B 1000 x 2.
        "single_query": (0, 4020.0, []),
        "event_stack": {0: {"A", "B"}},
        # 2 + 2 hops to the cloud
        "latency": 4.0,
        # Q at the cloud for 4020 (no sink: only Q2 reads it), Q2 gets C: 2
        "nested": (0, 4020.0, 0, 2.0),
        "nested_senders": {Q: [(0, 2.0)], "C": [(5, 1.0)]},
        "push_pull_guard": (0, 0),
    },
    True: {
        # Split B: the cloud gets A and B@6 (20 + 2000), node 1 gets A and
        # B@4 (10 + 1000) plus its output 1 x 1 hop to the sink.
        "single_query": ((0, 1), 3031.0,
                         [(0, [6], 1.0, 2020.0), (1, [4], 1.0, 1011.0)]),
        # Each instance has all A's, but only part of the B's.
        "event_stack": {0: {"A"}, 1: {"A"}},
        # Node 1 needs 1 + 1 hop + 1 hop to the sink, the cloud 1 + 2 hops.
        "latency": 3.0,
        # Q on (0, 1) only feeds Q2, so its instances send nothing to the
        # sink: 1010 + 2020. Q2 needs a host every instance and C reach: the
        # cloud, receiving Q from node 1 (1/s, 1 hop) and C (1/s, 2 hops).
        "nested": ((0, 1), 3030.0, 0, 3.0),
        "nested_senders": {Q: [(0, 1.0), (1, 1.0)], "C": [(5, 1.0)]},
        # With push-pull on, only projections nobody reads may be split.
        "push_pull_guard": (0, (0, 1)),
    },
}

# Random INES simulations (network size, max_parents, seed), event skew
# 2.0. With multi-node placement on, all-push Kraken splits at least one
# projection in each of them (checked for several PYTHONHASHSEED values).
SIMULATIONS = [(12, 2, 0), (12, 2, 1), (12, 2, 6), (12, 2, 7), (20, 3, 4)]


def _ines_simulation(network_size, max_parents, seed):
    """A random INES simulation, run up to INEv (Kraken's input)."""
    import contextlib
    import io

    import numpy as np

    import simulation_environment as se
    from simulator.operator_placement import calculate_operator_placement

    random.seed(seed)
    np.random.seed(seed)
    config = se.SimulationConfig(
        network_size=network_size, node_event_ratio=0.5, num_event_types=6,
        event_skew=2.0, max_parents=max_parents, parent_factor=1.0,
        query_size=3, query_length=5,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        simulation = se.Simulation(config)
        calculate_operator_placement(simulation, "test", 0)
    return simulation


def _run_kraken(simulation, multi, push_pull, drop_switch=False, guard=True):
    """Kraken greedy as run_kraken_solver runs it, without writing results.

    drop_switch leaves multi_node_placement out of the context, i.e. Kraken
    as it was before the switch existed. guard=False lets Kraken split
    projections that other projections read, also with push-pull on
    (PlacementProblem.consumed_projections). PrePP draws random
    selectivities, so the RNG is reset for every run.
    """
    import contextlib
    import io

    from inev.process_combination import compute_dependencies
    from kraken.run import _calculate_solution_metrics, _gather_problem_parameters

    simulation.config.multi_node_placement = multi
    simulation.config.push_pull = push_pull
    context = _gather_problem_parameters(simulation)
    if drop_switch:
        del context["multi_node_placement"]
    dependencies = compute_dependencies(
        simulation, simulation.h_mycombi, simulation.h_criticalMSTypes
    )
    order = sorted(dependencies, key=lambda x: dependencies[x])
    problem = PlacementProblem(order, context, False)
    if not guard:
        problem.consumed_projections = set()
    random.seed(0)
    with contextlib.redirect_stdout(io.StringIO()):
        solution = GreedySearch().solve(problem)
    metrics = _calculate_solution_metrics(solution, problem, simulation)
    return solution, problem, metrics


def _plan(solution):
    return [(str(p), info.location, info.strategy, round(info.individual_cost, 6))
            for p, info in solution.placements.items()]


class _OffAndOn:
    """Scenarios shared by TestMultiNodeOff and TestMultiNodeOn."""

    MULTI = None  # set by the subclasses

    def _solve(self, **kwargs):
        return _solve(multi=self.MULTI, **kwargs)

    def _expected(self, key):
        return EXPECTED[self.MULTI][key]

    def assert_valid(self, solution, problem, metrics=None):
        """Checks that hold for every solution, in both modes."""
        params = problem.cost_calculator.params
        rates = params["projection_rates_selectivity"]
        self.assertEqual(set(solution.placements), set(problem.processing_order))
        total = sum(info.individual_cost for info in solution.placements.values())
        self.assertAlmostEqual(solution.cumulative_cost, total,
                               delta=1e-6 * max(1.0, total))
        latency = solution.get_critical_path_latency(problem)
        self.assertGreaterEqual(latency, 0.0)
        self.assertLess(latency, float("inf"))
        split = [p for p, info in solution.placements.items() if info.instances]
        if metrics is not None:
            self.assertEqual(metrics["multi_node_placements"], len(split))
            self.assertEqual(metrics["total_cost"], solution.cumulative_cost)
        if not self.MULTI:
            self.assertEqual(split, [])
        for p, info in solution.placements.items():
            if not info.instances:
                self.assertIsInstance(info.node, int)
                self.assertIsNone(info.split_input)
                continue
            # A valid split: two or more instances on distinct nodes, every
            # sender of the split input at exactly one of them, every sender
            # of the other inputs at all of them.
            self.assertIsNone(info.node)
            self.assertGreaterEqual(len(info.instances), 2)
            self.assertEqual(len(set(info.nodes)), len(info.nodes))
            senders = problem.cost_calculator.get_input_senders(p, solution)
            self.assertIn(info.split_input, senders)
            self.assertEqual(
                sorted(u for i in info.instances for u in i.split_senders),
                sorted(node for node, _ in senders[info.split_input]),
            )
            reaches = problem.optimizer._reaches
            for instance in info.instances:
                for dep, lst in senders.items():
                    nodes = instance.split_senders if dep == info.split_input else [
                        node for node, _ in lst]
                    for node in nodes:
                        self.assertTrue(reaches(node, instance.node), (p, dep, node))
            # Each instance pushes all, or uses PrePP's plan if push-pull is
            # on; the placement is push-pull if any instance is.
            strategies = {i.strategy for i in info.instances}
            if params.get("push_pull", True):
                self.assertLessEqual(strategies, {"all_push", "push_pull"})
            else:
                self.assertEqual(strategies, {"all_push"})
            self.assertEqual(info.strategy,
                             "push_pull" if "push_pull" in strategies else "all_push")
            # The instances add up to the placement.
            self.assertAlmostEqual(info.individual_cost,
                                   sum(i.individual_cost for i in info.instances))
            self.assertAlmostEqual(sum(i.output_rate for i in info.instances),
                                   rates[p][1], delta=1e-9 * max(1.0, rates[p][1]))

    # --- the tree ---------------------------------------------------------

    def test_single_query(self):
        solution, problem = self._solve()
        placement = solution.placements[Q]
        location, cost, instances = self._expected("single_query")
        self.assertEqual((placement.location, placement.individual_cost),
                         (location, cost))
        self.assertEqual(
            [(i.node, i.split_senders, i.output_rate, i.individual_cost)
             for i in placement.instances],
            instances,
        )
        self.assertEqual(solution.cumulative_cost, cost)
        self.assert_valid(solution, problem)

    def test_event_stack(self):
        solution, _ = self._solve()
        self.assertEqual({n: set(events) for n, events in solution.event_stack.items()},
                         self._expected("event_stack"))

    def test_latency(self):
        # l_p = output rate, weighted by xi = 1.
        solution, problem = self._solve(xi=1.0)
        self.assertEqual(solution.get_critical_path_latency(problem),
                         self._expected("latency"))

    def test_nested(self):
        solution, problem = self._solve(**NESTED)
        q_location, q_cost, q2_location, q2_cost = self._expected("nested")
        self.assertEqual(solution.placements[Q].location, q_location)
        self.assertEqual(solution.placements[Q].individual_cost, q_cost)
        self.assertEqual(solution.placements[Q2].location, q2_location)
        self.assertEqual(solution.placements[Q2].individual_cost, q2_cost)
        self.assertEqual(problem.cost_calculator.get_input_senders(Q2, solution),
                         self._expected("nested_senders"))
        self.assert_valid(solution, problem)

    def test_no_split_possible(self):
        # A at 3 and 5, B at 4 and 6: only the cloud receives every sender of
        # either input, so both modes place Q there.
        sources = {"A": {3: 10.0, 5: 10.0}, "B": {4: 1000.0, 6: 1000.0}}
        solution, problem = self._solve(sources=sources, rates={Q: (0.0001, 4.0)})
        self.assertEqual(solution.placements[Q].location, 0)
        self.assert_valid(solution, problem)

    def test_push_pull_guard(self):
        # PrePP is stubbed out (no buffer), which leaves all-push for every
        # node, but push-pull is switched on.
        nested_q, single_q = self._expected("push_pull_guard")
        with mock.patch.object(CostCalculator, "_build_prepp_input_buffer",
                               return_value=None):
            solution, _ = self._solve(push_pull=True, **NESTED)
            self.assertEqual(solution.placements[Q].location, nested_q)
            solution, _ = self._solve(push_pull=True)
            self.assertEqual(solution.placements[Q].location, single_q)

    # --- random INES simulations -----------------------------------------

    @classmethod
    def setUpClass(cls):
        cls.simulations = [_ines_simulation(*s) for s in SIMULATIONS]

    def _check_simulations(self, push_pull, guard=True):
        split, solutions = 0, []
        for spec, simulation in zip(SIMULATIONS, self.simulations):
            with self.subTest(simulation=spec, push_pull=push_pull, guard=guard):
                solution, problem, metrics = _run_kraken(simulation, self.MULTI,
                                                         push_pull, guard=guard)
                self.assert_valid(solution, problem, metrics)
                split += metrics["multi_node_placements"]
                solutions.append((solution, problem))
                if not self.MULTI:
                    # Off is the default: the same plan as without the switch.
                    default, _, _ = _run_kraken(simulation, False, push_pull,
                                                drop_switch=True)
                    self.assertEqual(_plan(solution), _plan(default))
                    self.assertEqual(solution.cumulative_cost, default.cumulative_cost)
        self.solutions = solutions
        return split

    def test_ines_simulations_all_push(self):
        split = self._check_simulations(push_pull=False)
        if self.MULTI:
            self.assertGreater(split, 0)  # the splits were exercised

    def test_ines_simulations_push_pull(self):
        self._check_simulations(push_pull=True)

    def test_ines_simulations_push_pull_unguarded(self):
        # Projections other projections read may be split too: instances use
        # PrePP's plans, and consumers pull from the instances.
        self._check_simulations(push_pull=True, guard=False)
        if not self.MULTI:
            return
        instance_push_pull = pulls_from_instances = False
        for solution, problem in self.solutions:
            for p, info in solution.placements.items():
                instance_push_pull |= any(i.strategy == "push_pull" for i in info.instances)
                reads_multi_node = any(
                    isinstance(solution.placements[d].location, tuple)
                    for d in problem.dependencies_per_projection.get(p, [])
                    if d in solution.placements
                )
                pulls_from_instances |= reads_multi_node and info.strategy == "push_pull"
        self.assertTrue(instance_push_pull)
        self.assertTrue(pulls_from_instances)


class TestMultiNodeOff(_OffAndOn, unittest.TestCase):
    MULTI = False


class TestMultiNodeOn(_OffAndOn, unittest.TestCase):
    MULTI = True


if __name__ == "__main__":
    unittest.main()
