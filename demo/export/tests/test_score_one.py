"""Regression tests for score_one.py's push/pull choice handling.

Two bugs were found and fixed here (2026-09-08/09), both in how a player's
push/pull choice gets turned into forced_push_group:

1. Choosing to push an already-placed sub-query dependency (as opposed to a
   raw primitive) was a silent no-op: score_one.py flattened the choice to
   its leaf primitives before passing it as forced_push_group, but PrePP's
   own forced-group matching (prepp.py's `old_copy = query.
   primitive_operators`) is one-level -- a sub-query dependency appears
   there as its own name string, never expanded -- so the flattened group
   never matched anything and the optimizer's own pick was silently scored
   instead, regardless of what the player chose. Fixed by passing the
   chosen dependency's name through unflattened.
2. The explicit "push everything" (ALL_PUSH) choice used to go through the
   same forced_push_group path with every dependency flattened together --
   which hits a *different*, separately-confirmed bug where a single-group
   ("nothing left to pull") forced plan doesn't reproduce the true all-push
   cost. Fixed by bypassing forced_push_group entirely for ALL_PUSH and
   using the independently-computed all-push strategy result directly.

These run score_one.py as a real subprocess, the same way server.py
invokes it -- the RNG-isolation subprocess boundary is part of what's being
tested, not just the cost formula.

The medium/seq_abcd decomposition (and its operator names) changed after the
combigen rate-overcounting fix; this file's PLACEMENT and expected values
were recomputed on 2026-09-15 to match. The decomposition is now:
SEQ(B, D) (deps B, D), SEQ(A, B, C) (deps A, B, C), and the root
SEQ(A, B, C, D) (deps SEQ(B, D), SEQ(A, B, C)). PLACEMENT puts the two
non-root projections at node 1 and the root at node 0 (the cloud) rather
than colocating everything at node 0 -- colocated dependencies cost 0
either way, which would make the sub-query-forcing test pass even if
forcing were silently ignored.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.abspath(os.path.join(HERE, ".."))
SCORE_ONE = os.path.join(EXPORT_DIR, "score_one.py")

PLACEMENT = {"SEQ(B, D)": 1, "SEQ(A, B, C)": 1, "SEQ(A, B, C, D)": 0}


def run_score_one(push_choice):
    result = subprocess.run(
        [sys.executable, SCORE_ONE, "medium", "seq_abcd",
         json.dumps(PLACEMENT), json.dumps(push_choice)],
        capture_output=True, text=True, check=True, cwd=EXPORT_DIR,
    )
    return json.loads(result.stdout)


class TestScoreOnePushChoice(unittest.TestCase):
    def test_no_choice_uses_optimizer_pick(self):
        out = run_score_one({})
        pp = out["per_placement"]["SEQ(B, D)"]
        self.assertEqual(pp["strategy"], "push_pull")
        self.assertAlmostEqual(pp["cost"], 884.5999999999999)

    def test_forcing_primitive_dependency_is_honored(self):
        # 'D' is a bad choice here (pushing the higher-rate side) -- forcing
        # it should cost more than the optimizer's own pick, not silently
        # revert to it.
        out = run_score_one({"SEQ(B, D)": "D"})
        pp = out["per_placement"]["SEQ(B, D)"]
        self.assertAlmostEqual(pp["cost"], 1226.0)

    def test_forcing_sub_query_dependency_is_honored(self):
        # This is exactly the case that was silently ignored before the
        # fix: 'SEQ(A, B, C)' is a sub-query dependency, not a raw
        # primitive. The optimizer's own natural pick for the root is
        # all_push (cost 323.6436174148544, see
        # test_all_push_reproduces_true_all_push_cost below) -- forcing
        # this sub-query dependency pushed should cost *more* than that and
        # switch the reported strategy to push_pull, not silently fall back
        # to the optimizer's all_push pick.
        out = run_score_one({"SEQ(A, B, C, D)": "SEQ(A, B, C)"})
        pp = out["per_placement"]["SEQ(A, B, C, D)"]
        self.assertEqual(pp["strategy"], "push_pull")
        self.assertAlmostEqual(pp["cost"], 326.04081493818165)

    def test_all_push_reproduces_true_all_push_cost(self):
        out = run_score_one({"SEQ(B, D)": "__all_push__"})
        pp = out["per_placement"]["SEQ(B, D)"]
        self.assertEqual(pp["strategy"], "all_push")
        self.assertAlmostEqual(pp["cost"], 1226.0)


if __name__ == "__main__":
    unittest.main()
