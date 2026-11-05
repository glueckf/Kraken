"""End-to-end regression for the critical-path latency score_one.py reports.

Reported 2026-11-05: medium_c, Q1 (seq_abc), every projection set to push
everything, scored 6 hops -- impossible, since no event in that tree
travels more than 3. The engine (SolutionCandidate.get_critical_path_latency)
added SEQ(A, B, C)'s own input hops, C's 3 included, on top of SEQ(A, B)'s
full latency, so inputs arriving in parallel were summed. Unit tests for the
latency model itself live in the repo's tests/test_critical_path_latency.py;
these pin the real reconstructed scenario through score_one.py.

medium_c: cloud 0 <- 5 <- 6 <- {1, 2}; A at node 1, B and C at node 2.
"""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.abspath(os.path.join(HERE, ".."))
SCORE_ONE = os.path.join(EXPORT_DIR, "score_one.py")

S1, S2 = "SEQ(A, B)", "SEQ(A, B, C)"
ALL_PUSH = {S1: "__all_push__", S2: "__all_push__"}


def score(placement, push_choice):
    result = subprocess.run(
        [sys.executable, SCORE_ONE, "medium_c", "seq_abc",
         json.dumps(placement), json.dumps(push_choice)],
        capture_output=True, text=True, check=True, cwd=EXPORT_DIR,
    )
    return json.loads(result.stdout)


def latency(placement, push_choice):
    return score(placement, push_choice)["latency"]


class TestAllPushLatencyIsLongestPath(unittest.TestCase):
    def test_both_in_cloud(self):
        self.assertEqual(latency({S1: 0, S2: 0}, ALL_PUSH), 3.0)  # was 6.0

    def test_both_on_fog_node_above_the_sources(self):
        self.assertEqual(latency({S1: 6, S2: 6}, ALL_PUSH), 3.0)  # was 4.0

    def test_split_between_fog_and_cloud(self):
        self.assertEqual(latency({S1: 5, S2: 0}, ALL_PUSH), 3.0)  # was 5.0


class TestPushPullLatencyStaysSequential(unittest.TestCase):
    def test_pull_round_trips_add_up(self):
        # SEQ(A, B) at 6: push B, pull A (1 + 1 + 1 = 3). SEQ(A, B, C) in the
        # cloud: push SEQ(A, B) (3 + 2), then pull C from node 2 (+3 +3).
        self.assertEqual(latency({S1: 6, S2: 0}, {S1: ["B"], S2: [S1]}), 11.0)


class TestPullAgainstALocalInput(unittest.TestCase):
    """Both operators in the cloud: S1 is already at S2's node, so pushing
    or pulling C is S2's only call. The web UI sends a pull of C as S2's
    push group [S1] (state.ts buildPushSnapshot): the group covers every
    dependency, the local one included."""

    BOTH_IN_CLOUD = {S1: 0, S2: 0}

    def test_pushing_c_is_all_push(self):
        pushed = score(self.BOTH_IN_CLOUD, ALL_PUSH)
        self.assertEqual(pushed["latency"], 3.0)
        self.assertEqual(pushed["per_placement"][S2]["strategy"], "all_push")

    def test_pulling_c_filters_with_the_local_subquery(self):
        pulled = score(self.BOTH_IN_CLOUD, {S1: "__all_push__", S2: [S1]})
        pushed = score(self.BOTH_IN_CLOUD, ALL_PUSH)
        # S1 ready at 3, request to C's node and back: 3 + 3 + 3.
        self.assertEqual(pulled["latency"], 9.0)
        self.assertLess(pulled["per_placement"][S2]["cost"], pushed["per_placement"][S2]["cost"])


if __name__ == "__main__":
    unittest.main()
