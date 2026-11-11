"""Equality and hashing of query trees.

AND ignores the order of its children, SEQ and NSEQ do not, and an AND nested
in a SEQ still ignores its own order. The pipeline keys projections and
queries by these trees (projrates, projsPerQuery, combiDict), so equal trees
need equal hashes. With hash(str(tree)), a workload query whose reordered twin
had already been generated as another query's projection was missing from the
combination and never placed.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.tree import AND, NSEQ, SEQ, PrimEvent


def prims(*types):
    return [PrimEvent(t) for t in types]


class TestAndIgnoresChildOrder(unittest.TestCase):
    def test_reordered_and_is_equal_with_equal_hash(self):
        a, b = AND(*prims("B", "F", "D")), AND(*prims("D", "B", "F"))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_reordered_and_finds_the_dict_entry_and_dedups_in_a_set(self):
        rates = {AND(*prims("B", "F", "D")): 42}
        self.assertIn(AND(*prims("D", "B", "F")), rates)
        self.assertEqual(rates[AND(*prims("F", "D", "B"))], 42)
        self.assertEqual(
            len({AND(*prims("B", "F", "D")), AND(*prims("D", "B", "F"))}), 1
        )

    def test_nested_and_is_reordered_at_every_level(self):
        a = AND(PrimEvent("A"), AND(*prims("B", "C")))
        b = AND(AND(*prims("C", "B")), PrimEvent("A"))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_repeated_types_are_counted(self):
        self.assertNotEqual(AND(*prims("A", "A", "B")), AND(*prims("A", "B", "B")))
        a, b = AND(*prims("A", "A", "B")), AND(*prims("B", "A", "A"))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_different_types_differ(self):
        self.assertNotEqual(AND(*prims("A", "B")), AND(*prims("A", "C")))
        self.assertNotEqual(AND(*prims("A", "B")), AND(*prims("A", "B", "C")))


class TestSeqAndNseqKeepChildOrder(unittest.TestCase):
    def test_reordered_seq_differs(self):
        self.assertNotEqual(SEQ(*prims("B", "C")), SEQ(*prims("C", "B")))

    def test_seq_with_reordered_nested_and_is_equal_with_equal_hash(self):
        a = SEQ(PrimEvent("E"), AND(*prims("D", "F", "B")))
        b = SEQ(PrimEvent("E"), AND(*prims("B", "D", "F")))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)

    def test_seq_with_nested_and_still_respects_position(self):
        a = SEQ(PrimEvent("E"), AND(*prims("D", "F")))
        b = SEQ(AND(*prims("F", "D")), PrimEvent("E"))
        self.assertNotEqual(a, b)

    def test_nseq_keeps_child_order(self):
        a, b = NSEQ(*prims("A", "B", "C")), NSEQ(*prims("A", "B", "C"))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(NSEQ(*prims("A", "B", "C")), NSEQ(*prims("C", "B", "A")))


class TestOperatorsAndPrimitiveEvents(unittest.TestCase):
    def test_operator_type_matters(self):
        self.assertNotEqual(AND(*prims("A", "B")), SEQ(*prims("A", "B")))
        self.assertNotEqual(SEQ(*prims("A", "B", "C")), NSEQ(*prims("A", "B", "C")))

    def test_primitive_events_compare_by_type(self):
        self.assertEqual(PrimEvent("A"), PrimEvent("A"))
        self.assertEqual(hash(PrimEvent("A")), hash(PrimEvent("A")))
        self.assertNotEqual(PrimEvent("A"), PrimEvent("B"))


if __name__ == "__main__":
    unittest.main()
