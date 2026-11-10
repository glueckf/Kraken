"""Regression tests for SolutionCandidate.get_critical_path_latency.

The old recursion added a projection's own transmission latency -- the max
hops over ALL its inputs, raw primitive events included -- on top of the
full end-to-end latency of its upstream subqueries. Inputs that travel in
parallel were therefore summed: on the demo's medium_c Reef, Q1
SEQ(A, B, C) = SEQ(SEQ(A, B), C) with everything pushed to the cloud scored
3 (A to the cloud) + 3 (C to the cloud) = 6 hops, although no event travels
more than 3. Each input w now arrives at ready(w) + hops(w -> node); only
push-pull steps are sequential.

The network is medium_c's tree: cloud 0 (the sink) <- 5 <- 6 <- {1, 2},
A produced at node 1, B and C at node 2. Events only flow towards the cloud,
so a projection can only sit on a common ancestor of its sources that
produces no events itself (node 6, 5 or the cloud), as Kraken's optimizer
enforces; every test uses such placements. Node 7 below 5 is not part of
medium_c: it produces D, for the queries S3, FLAT and A_D that can therefore only
sit on 5 or the cloud, and a second copy of C in TestSeveralSources.
"""

import itertools
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kraken.data.acquisition_step import (
    AcquisitionSet,
    AcquisitionStep,
    PullRequest,
    PullResponse,
)
from kraken.data.state import PlacementInfo, SolutionCandidate
from simulation_environment import calculate_sequential_max_latency

CLOUD = 0
PARENT = {5: 0, 6: 5, 1: 6, 2: 6, 7: 5}
SOURCES = {"A": [1], "B": [2], "C": [2], "D": [7]}
S1 = "SEQ(A, B)"
S2 = "SEQ(A, B, C)"
S3 = "SEQ(A, B, C, D)"  # a third level on top of S2
FLAT = "AND(A, B, D)"  # three primitive inputs, no subquery
# Two more workload queries that only bring primitives to a node (see
# TestPushPullSteps): A_C has its sources below 6, A_D below 5.
A_C = "AND(A, C)"
A_D = "AND(A, D)"
DEPS = {S1: ["A", "B"], S2: [S1, "C"], S3: [S2, "D"], FLAT: ["A", "B", "D"],
        A_C: ["A", "C"], A_D: ["A", "D"]}
# processing order: every projection, inputs first
ORDER = [S1, A_C, A_D, S2, S3, FLAT]


def _path_to_root(n):
    path = [n]
    while path[-1] in PARENT:
        path.append(PARENT[path[-1]])
    return path


def _hops(a, b):
    pa, pb = _path_to_root(a), _path_to_root(b)
    common = next(x for x in pa if x in pb)
    return pa.index(common) + pb.index(common)


NODES = [CLOUD, *PARENT]
DIST = {a: {b: _hops(a, b) for b in NODES} for a in NODES}


def _response(events, node, placed):
    """pull_response.detailed_costs as CostCalculator / PrePP build them."""
    details = {}
    for event in events:
        sources = [placed[event]] if event in placed else SOURCES[event]
        details[event] = {
            "latency": max(DIST[s][node] for s in sources),
            "sources": [{"source_node": s, "distance": DIST[s][node]} for s in sources],
        }
    return PullResponse(cost=0.0, latency=max(d["latency"] for d in details.values()),
                        detailed_costs=details)


def _plan(node, steps, placed, already_at_node=()):
    """steps: list of (events the pull request is sent with, events
    acquired). The request is sent with events of earlier steps; an empty
    first element is a push step, and one step pushing everything is
    all-push. already_at_node: (step index, primitives of the step that
    already reach the node), as CostCalculator derives it from the
    event stack."""
    acquisition = AcquisitionSet()
    for i, (pull_with, acquire) in enumerate(steps):
        response = _response(acquire, node, placed)
        request = None
        if pull_with:
            request = PullRequest(cost=0.0, latency=response.latency, events=list(pull_with))
        step = AcquisitionStep(pull_request=request, pull_response=response,
                               events_to_pull=list(acquire))
        if i in dict(already_at_node):
            step.already_at_node = dict(already_at_node)[i]
        acquisition.steps.append(step)
    return acquisition


def _latency(placements, workload=(S2,), processing=None, xi=0.0):
    """placements: list of (projection, node, steps[, already_at_node]) in
    processing order; processing: l_p per projection, weighted by xi."""
    candidate, placed = SolutionCandidate(), {}
    for projection, node, steps, *local in placements:
        acquisition = _plan(node, steps, placed, *local)
        # l_t as CostCalculator reports it (steps summed, plus the sink hop):
        # no longer read for the critical path, kept realistic anyway.
        transmission = sum(step.total_latency for step in acquisition.steps)
        if projection in workload and node != CLOUD:
            transmission += DIST[node][CLOUD]
        candidate.placements[projection] = PlacementInfo(
            projection=projection, node=node, strategy="test", individual_cost=0.0,
            individual_transmission_latency=transmission,
            individual_processing_latency=(processing or {}).get(projection, 0.0),
            acquisition_steps=acquisition,
        )
        placed[projection] = node
    problem = SimpleNamespace(
        processing_order=ORDER,
        dependencies_per_projection=DEPS,
        query_workload=list(workload),
        latency_weighting_factor=xi,
        cost_calculator=SimpleNamespace(
            params={"pairwise_distance_matrix": DIST, "sink_nodes": [CLOUD]}),
    )
    return candidate.get_critical_path_latency(problem)


def _sequential_latency(placements):
    """The Sequential baseline's latency of the last projection for the same
    plans. It reports no sink hop, so callers place that one in the cloud."""
    acquisitions, placed = {}, {}
    for projection, node, steps in placements:
        acquisitions[projection] = _plan(node, steps, placed)
        placed[projection] = node
    context = SimpleNamespace(
        config=SimpleNamespace(xi=0.0),
        processing_order=ORDER,
        h_mycombi=DEPS,
        sum_of_input_rates_per_query={},
        h_projrates={},
        allPairs=DIST,
        query_workload=[projection],
    )
    latencies, _ = calculate_sequential_max_latency(
        context, [None] * 6 + [acquisitions])
    return latencies[projection]


ALL_PUSH_S1 = [((), ["A", "B"])]
ALL_PUSH_S2 = [((), [S1, "C"])]
ALL_PUSH_S3 = [((), [S2, "D"])]

# Every placement Kraken can choose: S1 on a host, S2 on the same or a higher
# one (it consumes S1, and events only flow up). Hosts form a chain.
HOSTS = [6, 5, CLOUD]
DEPTH = {CLOUD: 0, 5: 1, 6: 2, 1: 3, 2: 3}
PLACEMENTS = [(n1, n2) for i, n1 in enumerate(HOSTS) for n2 in HOSTS[i:]]
S1_PLANS = {
    "all push": ALL_PUSH_S1,
    "push B, pull A with B": [((), ["B"]), (["B"], ["A"])],
    "push A, pull B with A": [((), ["A"]), (["A"], ["B"])],
}
S2_PLANS = {
    "all push": ALL_PUSH_S2,
    "push S1, pull C with S1": [((), [S1]), ([S1], ["C"])],
    "push C, pull S1 with C": [((), ["C"]), (["C"], [S1])],
}


def _expected(n1, plan1, n2, plan2, workload=(S2,)):
    """The same timings derived by hand for this chain of hosts.

    h1 = hops from A's or B's source up to S1 (both are equally deep),
    h2 = hops from C's source up to S2, d12 = hops from S1 up to S2.

    S1 is ready at
    - all push: h1, A and B travel in parallel;
    - push one, pull the other: 3 * h1, the pushed event comes up, the
      request goes down to the other source and its answer comes back up.
    S2 is ready at
    - all push: max(ready1 + d12, h2), S1's output and C travel in parallel;
    - push S1, pull C with S1: ready1 + d12 + 2 * h2, the request for C
      leaves once S1's output is in;
    - push C, pull S1 with C: max(h2 + d12, ready1) + d12, the request
      reaches S1's node after C is in, but S1 can only answer once it has
      results.
    The latency adds S2's hops to the cloud. A shared S1 adds its own hops
    to the cloud to ready1, which S2 does not inherit.
    """
    h1 = DEPTH[1] - DEPTH[n1]
    h2 = DEPTH[2] - DEPTH[n2]
    d12 = DEPTH[n1] - DEPTH[n2]
    ready1 = h1 if plan1 == "all push" else 3 * h1
    if plan2 == "all push":
        ready2 = max(ready1 + d12, h2)
    elif plan2 == "push S1, pull C with S1":
        ready2 = ready1 + d12 + 2 * h2
    else:
        ready2 = max(h2 + d12, ready1) + d12
    latency = ready2 + DEPTH[n2]
    if S1 in workload:
        latency = max(latency, ready1 + DEPTH[n1])
    return latency


class TestAllPushParallelInputs(unittest.TestCase):
    """The reported case: with everything pushed, no event travels further
    than the longest path in the tree, so latency is at most 3."""

    def test_both_in_cloud(self):
        latency = _latency([(S1, CLOUD, ALL_PUSH_S1), (S2, CLOUD, ALL_PUSH_S2)])
        self.assertEqual(latency, 3)  # was 6: 3 (A for S1) + 3 (C for S2)

    def test_both_on_fog_node_above_the_sources(self):
        latency = _latency([(S1, 6, ALL_PUSH_S1), (S2, 6, ALL_PUSH_S2)])
        self.assertEqual(latency, 3)  # 1 hop in, 2 hops to the sink; was 4

    def test_split_between_fog_and_cloud(self):
        latency = _latency([(S1, 5, ALL_PUSH_S1), (S2, CLOUD, ALL_PUSH_S2)])
        self.assertEqual(latency, 3)  # was 5

    def test_sink_hop_of_a_shared_workload_query_is_not_inherited(self):
        # S1 is itself a workload query (shared subquery): its own result
        # goes to the sink, but S2 consumes it at node 6 without that detour.
        latency = _latency([(S1, 6, ALL_PUSH_S1), (S2, 6, ALL_PUSH_S2)],
                           workload=(S1, S2))
        self.assertEqual(latency, 3)  # was 6

    def test_nothing_placed(self):
        self.assertEqual(_latency([]), 0.0)


class TestAllFeasibleCombinations(unittest.TestCase):
    """Every placement Kraken can choose here with every acquisition plan of
    either projection: 6 placements x 3 x 3 plans, S1 shared or not."""

    def test_against_hand_derived_timings(self):
        for workload in [(S2,), (S1, S2)]:
            for (n1, n2), plan1, plan2 in itertools.product(
                    PLACEMENTS, S1_PLANS, S2_PLANS):
                with self.subTest(S1=(n1, plan1), S2=(n2, plan2), workload=workload):
                    latency = _latency([(S1, n1, S1_PLANS[plan1]),
                                        (S2, n2, S2_PLANS[plan2])], workload)
                    self.assertEqual(
                        latency, _expected(n1, plan1, n2, plan2, workload))

    def test_all_push_never_exceeds_the_deepest_source(self):
        for n1, n2 in PLACEMENTS:
            with self.subTest(S1=n1, S2=n2):
                latency = _latency([(S1, n1, ALL_PUSH_S1), (S2, n2, ALL_PUSH_S2)])
                self.assertEqual(latency, 3)

    def test_pulling_is_never_faster_than_all_push(self):
        for (n1, n2), plan1, plan2 in itertools.product(
                PLACEMENTS, S1_PLANS, S2_PLANS):
            with self.subTest(S1=(n1, plan1), S2=(n2, plan2)):
                latency = _latency([(S1, n1, S1_PLANS[plan1]),
                                    (S2, n2, S2_PLANS[plan2])])
                self.assertGreaterEqual(latency, 3)


class TestSeveralSources(unittest.TestCase):
    def test_pull_waits_for_the_farthest_source(self):
        # C also produced at node 7 (one hop below 5), so S2 can only sit on
        # 5 or the cloud. S1 at 6 is ready at 1 and reaches 5 at 2; the
        # request for C gets to 7 at 3 and its answer back at 4, but node 2
        # is two hops away: back at 6, +1 hop to the sink.
        with mock.patch.dict(SOURCES, {"C": [7, 2]}):
            latency = _latency([
                (S1, 6, ALL_PUSH_S1),
                (S2, 5, S2_PLANS["push S1, pull C with S1"]),
            ])
        self.assertEqual(latency, 7)


class TestProcessingLatency(unittest.TestCase):
    def test_weighted_processing_delays_dependents(self):
        # S1 in the cloud is ready at 3 + 0.5 * 2; S2 waits for it: 4 + 0.5 * 1
        latency = _latency([(S1, CLOUD, ALL_PUSH_S1), (S2, CLOUD, ALL_PUSH_S2)],
                           processing={S1: 2.0, S2: 1.0}, xi=0.5)
        self.assertEqual(latency, 4.5)

    def test_processing_of_a_late_subquery_delays_the_pull_answer(self):
        # As test_pull_waits_for_a_late_subquery, but S1 needs 0.5 * 2 to
        # process its inputs: it has results at 7 instead of 6, so the
        # request waiting at node 5 is answered at 7, back in the cloud at 8.
        latency = _latency([
            (S1, 5, S1_PLANS["push B, pull A with B"]),
            (S2, CLOUD, S2_PLANS["push C, pull S1 with C"]),
        ], processing={S1: 2.0}, xi=0.5)
        self.assertEqual(latency, 8)  # was 12: 7 + (3 + 1 + 1)


class TestDeeperQueries(unittest.TestCase):
    """S3 = SEQ(S2, D) adds a third level. D comes from node 7, two hops below
    the cloud. The old recursion added one more transmission latency per
    level, so its error grew with the depth of the query."""

    def test_three_levels_all_push_in_the_cloud(self):
        # S1 and S2 are ready at 3 as in test_both_in_cloud; D arrives at 2.
        # S3 only waits for its latest input, S2 at 3.
        latency = _latency([
            (S1, CLOUD, ALL_PUSH_S1),
            (S2, CLOUD, ALL_PUSH_S2),
            (S3, CLOUD, ALL_PUSH_S3),
        ], workload=(S3,))
        self.assertEqual(latency, 3)  # was 8: 3 + 3 + 2

    def test_three_levels_climbing_towards_the_cloud(self):
        # S1 at 6 is ready at 1; S2 at 5 at 2 (S1 one hop up, C two hops);
        # S3 in the cloud at 3 (S2 one hop up, D two hops). Each level picks
        # up its inputs on the way up, so the deepest source still decides.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (S2, 5, ALL_PUSH_S2),
            (S3, CLOUD, ALL_PUSH_S3),
        ], workload=(S3,))
        self.assertEqual(latency, 3)  # was 5: 1 + 2 + 2

    def test_sink_hop_is_not_inherited_over_two_levels(self):
        # All three are workload queries: S1 at 6 is ready at 1 and sends
        # its matches 2 hops to the cloud (3); S2 at 5 is ready at 2, +1 (3);
        # S3 at 5 gets S2 locally and D after 1 hop, ready at 2, +1 (3).
        # Each adds its own hops to the cloud, none inherits another's.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (S2, 5, ALL_PUSH_S2),
            (S3, 5, ALL_PUSH_S3),
        ], workload=(S1, S2, S3))
        self.assertEqual(latency, 3)  # was 8: (1 + 2) + (2 + 1) + (1 + 1)

    def test_late_subquery_two_levels_down(self):
        # S1 at 5: push B (2), pull A with B (2 + 2 + 2) -> ready 6. S2 at 5
        # gets S1 locally at 6 and C at 2 -> ready 6. S3 in the cloud: push
        # D (2), pull S2 with D: the request is at node 5 at 3, but S2 only
        # has results at 6, back at 7. S1's delay reaches S3 through S2.
        latency = _latency(LATE_TWO_LEVELS, workload=(S3,))
        self.assertEqual(latency, 7)  # was 12: 6 + 2 + (2 + 1 + 1)


LATE_TWO_LEVELS = [
    (S1, 5, S1_PLANS["push B, pull A with B"]),
    (S2, 5, ALL_PUSH_S2),
    (S3, CLOUD, [((), ["D"]), (["D"], [S2])]),
]


class TestLongerAcquisitionPlans(unittest.TestCase):
    """FLAT = AND(A, B, D) takes three primitives directly, so its plan can
    have three steps, or pull two events in one step. D at node 7 is one hop
    closer to the cloud than A and B."""

    def test_each_pull_waits_for_all_earlier_steps(self):
        # FLAT in the cloud: push D (2); pull B with D: the request goes 3
        # down, B 3 up -> 8; pull A with D and B: leaves at 8, back at 14.
        # Summing is right here, every request needs the earlier events.
        latency = _latency([
            (FLAT, CLOUD, [((), ["D"]), (["D"], ["B"]), (["D", "B"], ["A"])]),
        ], workload=(FLAT,))
        self.assertEqual(latency, 14)

    def test_one_pull_of_two_events_waits_for_the_farther(self):
        # FLAT in the cloud: push B (3); pull D and A with B in one step: the
        # request leaves at 3, D is back at 3 + 2 + 2 = 7, A only at
        # 3 + 3 + 3 = 9.
        latency = _latency([
            (FLAT, CLOUD, [((), ["B"]), (["B"], ["D", "A"])]),
        ], workload=(FLAT,))
        self.assertEqual(latency, 9)


class TestPartialCandidates(unittest.TestCase):
    """The search checks the latency after every placement, to prune, while
    later projections are not placed yet."""

    def test_only_the_subquery_placed(self):
        # S1 at 5 pulling A is ready at 6; S2 does not count yet.
        latency = _latency([(S1, 5, S1_PLANS["push B, pull A with B"])])
        self.assertEqual(latency, 6)

    def test_placed_subquery_in_the_workload_adds_its_sink_hop(self):
        # As above, but S1 is a workload query itself: +1 hop to the cloud.
        latency = _latency([(S1, 5, S1_PLANS["push B, pull A with B"])],
                           workload=(S1, S2))
        self.assertEqual(latency, 7)


class TestSequentialBaseline(unittest.TestCase):
    """calculate_sequential_max_latency uses the same model for its plans."""

    def test_matches_the_hand_derived_timings(self):
        for n1, plan1, plan2 in itertools.product(HOSTS, S1_PLANS, S2_PLANS):
            with self.subTest(S1=(n1, plan1), S2=plan2):
                latency = _sequential_latency([(S1, n1, S1_PLANS[plan1]),
                                               (S2, CLOUD, S2_PLANS[plan2])])
                self.assertEqual(latency, _expected(n1, plan1, CLOUD, plan2))

    def test_late_subquery_two_levels_down(self):
        # As TestDeeperQueries.test_late_subquery_two_levels_down: 7.
        self.assertEqual(_sequential_latency(LATE_TWO_LEVELS), 7)


class TestPushPullSteps(unittest.TestCase):
    """Pull steps are a real sequence: each request waits for the events it
    filters with, and a source cannot answer before its event exists."""

    def test_pull_round_trips_stay_sequential(self):
        # S1 at 6: push B (1), pull A with B (1 + 1)        -> ready 3
        # S2 at cloud: push S1 (3 + 2 = 5), pull C with S1 (5 + 3 + 3) -> 11
        latency = _latency([
            (S1, 6, [((), ["B"]), (["B"], ["A"])]),
            (S2, CLOUD, [((), [S1]), ([S1], ["C"])]),
        ])
        self.assertEqual(latency, 11)

    def test_pull_waits_for_a_late_subquery(self):
        # S1 at 5: push B (2), pull A with B (2 + 2 + 2)       -> ready 6
        # S2 at cloud: push C (3); pull S1 with C: the request leaves once C
        # is in (3) and is at node 5 at 4, but S1 only has results at 6,
        # back at 7. The old recursion added S2's steps (3 + 1 + 1) on top of
        # S1's 6, although C travels while S1 is still being computed.
        latency = _latency([
            (S1, 5, [((), ["B"]), (["B"], ["A"])]),
            (S2, CLOUD, [((), ["C"]), (["C"], [S1])]),
        ])
        self.assertEqual(latency, 7)  # was 11: 6 + (3 + 1 + 1)

    # S2's own plan only ever gets C by pushing it or by pulling it with S1.
    # Kraken also counts an event as at the node when another query placed
    # there earlier already has it pushed: placing a projection adds its
    # primitives to the node's event stack, and CostCalculator then charges
    # a pull step whose primitives are all on that stack no round trip. The
    # two tests below place such a query explicitly.

    def test_without_local_events_the_round_trip_counts(self):
        # S1 at 6: A and B pushed, ready at 1; node 6's stack has A, B.
        # S2 at 6: push S1 (0 hops, 1), pull C with S1: the request goes
        # down to node 2 (2), C is back at 3; +2 hops to the sink.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (S2, 6, S2_PLANS["push S1, pull C with S1"]),
        ])
        self.assertEqual(latency, 5)

    def test_step_already_at_the_node_needs_no_round_trip(self):
        # As above, but the workload also has A_C = AND(A, C) at node 6,
        # placed before S2 with A and C pushed (1 hop, ready at 1, +2 to the
        # sink = 3). C now reaches node 6 anyway, so S2's step "pull C with
        # S1" is local: C is in at 1, not 3, and S2 is ready at 1, +2 = 3.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (A_C, 6, [((), ["A", "C"])]),
            (S2, 6, S2_PLANS["push S1, pull C with S1"], [(1, ["C"])]),
        ], workload=(A_C, S2))
        self.assertEqual(latency, 3)

    def test_partly_local_step_still_needs_the_round_trip(self):
        # The workload also has A_D = AND(A, D) at node 5 with A and D pushed
        # (ready at 2, +1 to the sink = 3), so node 5's stack has A and D.
        # S1 at 6 is ready at 1. S2 at 5: push C (2), pull S1 with C. Of
        # S1's primitives only A is on node 5's stack, B is not, so S1 cannot
        # be had locally: the request goes down to node 6 (3), S1 answers at
        # once and is back at 4; +1 hop to the sink.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (A_D, 5, [((), ["A", "D"])]),
            (S2, 5, S2_PLANS["push C, pull S1 with C"], [(1, ["A"])]),
        ], workload=(A_D, S2))
        self.assertEqual(latency, 5)  # was 6: 1 + (2 + 1 + 1) + 1


if __name__ == "__main__":
    unittest.main()
