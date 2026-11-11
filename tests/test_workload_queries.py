"""Multi-query workloads through the full simulation pipeline.

Each query of a workload is split into projections. Equal projections are
generated once and shared, and a query can use projections that come from
other queries. These tests run the real pipeline on one seeded network with
hand-written workloads. They check three things: every query is placed, equal
queries are placed once, and consecutive Simulations in one process (as in a
pool worker) do not see each other's projections.

Kraken is stubbed, so All-Push, INEv, Sequential and PrePP run. INEv's cost
depends on PYTHONHASHSEED, so the tests compare runs within one process
instead of pinning values.
"""

import contextlib
import io
import os
import random
import sys
import tempfile
import types
import unittest
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import simulation_environment as se
from core.tree import AND, SEQ, PrimEvent
from simulator import combigen

CONFIG = dict(
    network_size=12,
    node_event_ratio=0.5,
    num_event_types=6,
    event_skew=0.3,
    max_parents=2,
    parent_factor=1.0,
    query_size=3,
    query_length=5,
)
SEED = 23  # network, rates and selectivities

# AND(D, B, A, C) and AND(B, A, F) are also projections of the first query,
# generated there in another child order
NESTED_WORKLOAD = ["AND(F, D, C, B, A)", "AND(D, B, A, C)", "AND(B, A, F)"]

KRAKEN_MODULE = "src.kraken.run"
_saved_kraken = None
_saved_cwd = None
_tmp_cwd = None


def setUpModule():
    global _saved_kraken, _saved_cwd, _tmp_cwd
    _saved_kraken = sys.modules.get(KRAKEN_MODULE)
    kraken = types.ModuleType(KRAKEN_MODULE)
    kraken.run_kraken_solver = lambda *args, **kwargs: None
    sys.modules[KRAKEN_MODULE] = kraken
    # INEv writes msFilter.txt into the working directory
    _saved_cwd = os.getcwd()
    _tmp_cwd = tempfile.TemporaryDirectory()
    os.chdir(_tmp_cwd.name)


def tearDownModule():
    os.chdir(_saved_cwd)
    _tmp_cwd.cleanup()
    if _saved_kraken is None:
        sys.modules.pop(KRAKEN_MODULE, None)
    else:
        sys.modules[KRAKEN_MODULE] = _saved_kraken


def parse(text):
    """Build a query from its string form, e.g. SEQ(E, AND(D, F, B))."""
    text = text.replace(" ", "")

    def node(i):
        for name, operator in (("AND", AND), ("SEQ", SEQ)):
            if text.startswith(name + "(", i):
                i += len(name) + 1
                children = []
                while text[i] != ")":
                    child, i = node(i)
                    children.append(child)
                    if text[i] == ",":
                        i += 1
                return operator(*children), i + 1
        return PrimEvent(text[i]), i + 1

    return node(0)[0]


def simulate(workload, seed=SEED):
    """Run the pipeline for this workload on the seeded network."""
    random.seed(seed)
    np.random.seed(seed)
    with mock.patch.object(
        se, "generate_workload", lambda *args: [parse(q) for q in workload]
    ), mock.patch.object(se.Simulation, "_write_results"), contextlib.redirect_stdout(
        io.StringIO()
    ):
        sim = se.Simulation(se.SimulationConfig(**CONFIG))
        sim.run()
    return sim


def placements(sim):
    """How many placed projections serve each workload query."""
    return {
        str(q): sum(p == q for p in sim.processing_order) for q in sim.query_workload
    }


def outcome(sim):
    return (
        sorted(str(p) for p in sim.h_projlist),
        [str(p) for p in sim.processing_order],
        sim.inev_results["cost"],
        sim.inev_results["transmission_latency"],
        sim.all_push_results["cost"],
    )


class TestEveryQueryIsPlaced(unittest.TestCase):
    def test_queries_whose_reordered_twin_is_another_querys_projection(self):
        sim = simulate(NESTED_WORKLOAD)
        self.assertEqual(placements(sim), {q: 1 for q in NESTED_WORKLOAD})
        self.assertGreater(sim.inev_results["cost"], 0)


class TestEqualQueriesArePlacedOnce(unittest.TestCase):
    def assert_placed_like_one_query(self, query, twin):
        alone = simulate([query])
        both = simulate([query, twin])
        self.assertEqual(placements(both), {query: 1, twin: 1})
        self.assertEqual(
            [str(p) for p in both.processing_order],
            [str(p) for p in alone.processing_order],
        )
        self.assertEqual(both.inev_results["cost"], alone.inev_results["cost"])

    def test_reordered_and(self):
        self.assert_placed_like_one_query("AND(B, F, D)", "AND(D, B, F)")

    def test_seq_with_reordered_nested_and(self):
        self.assert_placed_like_one_query("SEQ(E, AND(D, F, B))", "SEQ(E, AND(B, D, F))")


class TestQueriesShareProjections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sim = simulate(NESTED_WORKLOAD)

    def test_equal_projections_are_generated_once(self):
        projlist = self.sim.h_projlist
        duplicates = [
            (str(a), str(b))
            for i, a in enumerate(projlist)
            for b in projlist[i + 1 :]
            if a == b
        ]
        self.assertEqual(duplicates, [])

    def test_larger_query_can_use_the_smaller_queries(self):
        # Reordered key: the lookup has to go by equality, not by string
        usable = self.sim.h_projsPerQuery[parse("AND(A, B, C, D, F)")]
        for smaller in ("AND(A, B, C, D)", "AND(A, B, F)"):
            self.assertTrue(any(p == parse(smaller) for p in usable), smaller)

    def test_every_query_has_a_combination(self):
        for query in ("AND(A, B, C, D, F)", "AND(A, B, C, D)", "AND(A, B, F)"):
            self.assertIn(parse(query), self.sim.h_combiDict)
            self.assertIn(parse(query), self.sim.h_mycombi)


class TestConsecutiveSimulationsAreIndependent(unittest.TestCase):
    CONTAINERS = (
        "h_projlist",
        "h_projrates",
        "h_projsPerQuery",
        "h_sharedProjectionsDict",
        "h_sharedProjectionsList",
        "h_combiDict",
        "h_placementTreeDict",
    )

    def test_earlier_runs_do_not_change_later_results(self):
        # Read each outcome right away: shared containers would change later
        first = outcome(simulate(NESTED_WORKLOAD))
        # A run on another network in between, as in a pool worker
        simulate(["AND(D, F, B, A)", "SEQ(E, AND(B, D, F))"], seed=3)
        again = outcome(simulate(NESTED_WORKLOAD))
        self.assertEqual(again, first)

    def test_each_simulation_has_its_own_containers(self):
        a = simulate(["AND(B, F, D)"])
        b = simulate(["AND(B, F, D)"])
        for name in self.CONTAINERS:
            self.assertIsNot(getattr(a, name), getattr(b, name), name)
            self.assertFalse(getattr(se.Simulation, name), name)


class TestDroppedQueryFailsLoudly(unittest.TestCase):
    def test_query_without_combination_raises(self):
        with mock.patch.object(combigen, "get_best_chain_combis"), self.assertLogs(
            se.logger, "ERROR"
        ), self.assertRaisesRegex(ValueError, "missing from the combination"):
            simulate(["AND(B, F, D)"])


if __name__ == "__main__":
    unittest.main()
