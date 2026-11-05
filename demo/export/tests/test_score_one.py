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

Target changed 2026-11-05: "medium"'s leaf-letter assignment was redesigned
that day (demo/BACKLOG.md item #33) to the same "3 of 6 letters duplicated"
standard as the demo's other topologies, which changed medium/seq_abcd's
decomposition into a shape (SEQ(A, B) at the root of a 2-dep chain all the
way up) where forcing either root-level dependency ties *exactly* with the
unforced pick and with each other -- not useful for proving a specific
named dependency is actually read rather than silently ignored. Moved to
medium/and_nested instead, whose "AND(SEQ(A, B), SEQ(E, F))" projection has
three deps -- one sub-query (SEQ(A, B)) and two primitives (E, F) -- with
real, independently-confirmed (not assumed) cost differences between
forcing each one: the optimizer's own natural pick is to push F (892.16,
same as forcing F explicitly); forcing the sub-query dependency SEQ(A, B)
instead gives a different, real number (896.19) that would equal the
natural 892.16 if the forcing were being silently dropped back to the
optimizer's own pick -- it doesn't, so it's exercising the actual fix, not
coincidentally matching it. PLACEMENT puts every non-root projection at
node 1 and the root at node 0 (the cloud) rather than colocating everything
at node 0, for the same reason as before: colocated dependencies cost 0
either way, which would make a forcing test pass even if forcing were
silently ignored.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.abspath(os.path.join(HERE, ".."))
SCORE_ONE = os.path.join(EXPORT_DIR, "score_one.py")

PLACEMENT = {
    "SEQ(A, B)": 1,
    "AND(SEQ(A, B), SEQ(E, F))": 1,
    "AND(SEQ(A, B, C), F)": 1,
    "AND(SEQ(A, B, C), D, F)": 1,
    "AND(SEQ(A, B, C), D, SEQ(E, F))": 0,
}
TARGET = "AND(SEQ(A, B), SEQ(E, F))"  # deps: SEQ(A, B) [sub-query], E, F [primitives]


def run_score_one(push_choice):
    result = subprocess.run(
        [sys.executable, SCORE_ONE, "medium", "and_nested",
         json.dumps(PLACEMENT), json.dumps(push_choice)],
        capture_output=True, text=True, check=True, cwd=EXPORT_DIR,
    )
    return json.loads(result.stdout)


class TestScoreOnePushChoice(unittest.TestCase):
    def test_no_choice_uses_optimizer_pick(self):
        out = run_score_one({})
        pp = out["per_placement"][TARGET]
        self.assertEqual(pp["strategy"], "push_pull")
        self.assertAlmostEqual(pp["cost"], 892.1599999999999)

    def test_forcing_primitive_dependency_is_honored(self):
        # 'E' is a bad choice here (pushing the higher-rate side, 800/s vs
        # F's 5/s) -- forcing it should cost more than the optimizer's own
        # pick (which pushes F instead, see test above), not silently
        # revert to it.
        out = run_score_one({TARGET: "E"})
        pp = out["per_placement"][TARGET]
        self.assertAlmostEqual(pp["cost"], 1620.0)

    def test_forcing_sub_query_dependency_is_honored(self):
        # This is exactly the case that was silently ignored before the
        # fix: 'SEQ(A, B)' is a sub-query dependency, not a raw primitive.
        # The optimizer's own natural pick pushes F instead (cost 892.16,
        # see test_no_choice_uses_optimizer_pick) -- forcing this sub-query
        # dependency pushed instead should give a different, real number,
        # not silently fall back to that same 892.16.
        out = run_score_one({TARGET: "SEQ(A, B)"})
        pp = out["per_placement"][TARGET]
        self.assertEqual(pp["strategy"], "push_pull")
        self.assertAlmostEqual(pp["cost"], 896.194744098048)

    def test_all_push_reproduces_true_all_push_cost(self):
        out = run_score_one({TARGET: "__all_push__"})
        pp = out["per_placement"][TARGET]
        self.assertEqual(pp["strategy"], "all_push")
        self.assertAlmostEqual(pp["cost"], 1620.0)


if __name__ == "__main__":
    unittest.main()
