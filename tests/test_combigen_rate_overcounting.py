"""Regression tests for the rate-overcounting bug in query decomposition.

h_rates_data[event_type] already holds the *summed* rate across every node
that produces that event type. Several functions used to multiply that
already-summed value by the producer count again
(rates[event] * len(nodes[event])), inflating the true per-source
contribution by that producer count. These tests pin down the fixed
behaviour for three of those locations: two in projections.py and the
near-duplicate in combigen.py.
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.tree import PrimEvent
from simulator import projections
from simulator import combigen

EVENT = "A"
PER_PRODUCER_RATE = 1000
NUM_PRODUCERS = 3
SUMMED_RATE = PER_PRODUCER_RATE * NUM_PRODUCERS  # 3000, as stored in h_rates_data


class TestProjectionsOptimisticTotalRate(unittest.TestCase):
    """optimistic_total_rate()'s primitive-event branch in projections.py."""

    def test_does_not_multiply_already_summed_rate_by_producer_count(self):
        projection = PrimEvent(EVENT)
        sim = SimpleNamespace(
            h_rates_data={EVENT: SUMMED_RATE},
            h_nodes={EVENT: [f"n{i}" for i in range(NUM_PRODUCERS)]},
            h_projlist=[],
            h_projFilterDict={},
            h_IndexEventNodes={},
        )

        result = projections.optimistic_total_rate(sim, projection)

        self.assertEqual(result, SUMMED_RATE)
        self.assertNotEqual(result, SUMMED_RATE * NUM_PRODUCERS)


class TestProjectionsTotalRate(unittest.TestCase):
    """total_rate()'s primitive-event branch (`elif len(projection) == 1`) --
    what new_is_partitioning() uses on the "cost of not partitioning" side
    of its decompose/don't-decompose gate."""

    def test_does_not_multiply_already_summed_rate_by_producer_count(self):
        projection = PrimEvent(EVENT)
        sim = SimpleNamespace(
            h_rates_data={EVENT: SUMMED_RATE},
            h_nodes={EVENT: [f"n{i}" for i in range(NUM_PRODUCERS)]},
            h_IndexEventNodes={},
        )

        result = projections.total_rate(sim, projection, projrates={})

        self.assertEqual(result, SUMMED_RATE)
        self.assertNotEqual(result, SUMMED_RATE * NUM_PRODUCERS)


class TestCombigenOptimisticTotalRate(unittest.TestCase):
    """combigen.py's own near-duplicate optimistic_total_rate()."""

    def test_does_not_multiply_already_summed_rate_by_producer_count(self):
        projection = PrimEvent(EVENT)
        sim = SimpleNamespace(
            h_rates_data={EVENT: SUMMED_RATE},
            h_nodes={EVENT: [f"n{i}" for i in range(NUM_PRODUCERS)]},
            h_projlist=[],
            h_projFilterDict={},
            h_IndexEventNodes={},
            single_selectivity={},
            h_instances={},
        )

        result = combigen.optimistic_total_rate(sim, projection)

        self.assertEqual(result, SUMMED_RATE)
        self.assertNotEqual(result, SUMMED_RATE * NUM_PRODUCERS)


if __name__ == "__main__":
    unittest.main()
