"""Regression tests for get_all_query_components on queries with several
nested operands.

The parenthesis counter used to be initialised once per query instead of
once per nested operand. It reached 0 after the first nested operand, so
every later one was cut to "AND(" / "SEQ(" and its letters were dropped
except the last: AND(SEQ(B, C), SEQ(E, F)) parsed as
['SEQ(B,C)', 'SEQ(', 'F']. PrePP's determine_query_output_rate builds a
projection's output rate from these components, so such projections were
priced far too low. The near-duplicate in single_selectivities.py had the
same bug.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from prepp import prepp
from simulator import single_selectivities

CASES = {
    "AND(SEQ(B, C), SEQ(E, F))": ["SEQ(B,C)", "SEQ(E,F)"],
    "AND(SEQ(A, B, C), D, SEQ(E, F))": ["SEQ(A,B,C)", "D", "SEQ(E,F)"],
    "SEQ(AND(A, B), C, AND(D, E), F)": ["AND(A,B)", "C", "AND(D,E)", "F"],
    "AND(B1, SEQ(F, AND(G1, SEQ(G2, AND(I1, I2, B2)))))": ["B", "SEQ(F,AND(G,SEQ(G,AND(I,I,B))))"],
    "AND(SEQ(A, B, C), F)": ["SEQ(A,B,C)", "F"],
    "SEQ(A, B, C)": ["A", "B", "C"],
}


class TestGetAllQueryComponents(unittest.TestCase):
    def test_prepp(self):
        for query, expected in CASES.items():
            with self.subTest(query=query):
                self.assertEqual(prepp.get_all_query_components(query), expected)

    def test_single_selectivities(self):
        for query, expected in CASES.items():
            with self.subTest(query=query):
                self.assertEqual(single_selectivities.get_all_query_components(query), expected)


class TestPreppOutputRateOfNestedOperands(unittest.TestCase):
    def test_second_nested_operand_keeps_its_letters(self):
        rates = {"B": 2, "C": 3, "E": 5, "F": 7}
        sources = {e: ["n0"] for e in rates}
        rate = prepp.determine_query_output_rate("AND(SEQ(B, C), SEQ(E, F))", None, True, rates, sources)
        # 2 operands * SEQ(B,C) (2*3) * SEQ(E,F) (5*7); the bug gave 3 * 6 * 1 * 7 = 126
        self.assertEqual(rate, 2 * 6 * 35)


if __name__ == "__main__":
    unittest.main()
