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
medium_c: it produces a second copy of C in TestSeveralSources only.
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
SOURCES = {"A": [1], "B": [2], "C": [2]}
S1 = "SEQ(A, B)"
S2 = "SEQ(A, B, C)"
DEPS = {S1: ["A", "B"], S2: [S1, "C"]}


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
    """steps: list of (events pulled with, events acquired). An empty first
    element is a push step; one step pushing everything is all-push."""
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
        processing_order=[S1, S2],
        dependencies_per_projection=DEPS,
        query_workload=list(workload),
        latency_weighting_factor=xi,
        cost_calculator=SimpleNamespace(
            params={"pairwise_distance_matrix": DIST, "sink_nodes": [CLOUD]}),
    )
    return candidate.get_critical_path_latency(problem)


def _sequential_latency(placements):
    """The Sequential baseline's latency of S2 for the same plans. It reports
    no sink hop, so callers place S2 in the cloud."""
    acquisitions, placed = {}, {}
    for projection, node, steps in placements:
        acquisitions[projection] = _plan(node, steps, placed)
        placed[projection] = node
    context = SimpleNamespace(
        config=SimpleNamespace(xi=0.0),
        processing_order=[S1, S2],
        h_mycombi=DEPS,
        sum_of_input_rates_per_query={},
        h_projrates={},
        allPairs=DIST,
        query_workload=[S2],
    )
    latencies, _ = calculate_sequential_max_latency(
        context, [None] * 6 + [acquisitions])
    return latencies[S2]


ALL_PUSH_S1 = [((), ["A", "B"])]
ALL_PUSH_S2 = [((), [S1, "C"])]

# Every placement Kraken can choose: S1 on a host, S2 on the same or a higher
# one (it consumes S1, and events only flow up). Hosts form a chain.
HOSTS = [6, 5, CLOUD]
DEPTH = {CLOUD: 0, 5: 1, 6: 2, 1: 3, 2: 3}
PLACEMENTS = [(n1, n2) for i, n1 in enumerate(HOSTS) for n2 in HOSTS[i:]]
S1_PLANS = {
    "all push": ALL_PUSH_S1,
    "push B, pull A": [((), ["B"]), (["B"], ["A"])],
    "push A, pull B": [((), ["A"]), (["A"], ["B"])],
}
S2_PLANS = {
    "all push": ALL_PUSH_S2,
    "push S1, pull C": [((), [S1]), (["A"], ["C"])],
    "push C, pull S1": [((), ["C"]), (["C"], [S1])],
}


def _expected(n1, plan1, n2, plan2, workload=(S2,)):
    """The same timings derived by hand for this chain of hosts."""
    h1 = DEPTH[1] - DEPTH[n1]  # hops from A's or B's source up to S1
    h2 = DEPTH[2] - DEPTH[n2]  # hops from C's source up to S2
    d12 = DEPTH[n1] - DEPTH[n2]  # hops from S1 up to S2
    # pull: the first event comes up, the request goes down, the other back up
    ready1 = h1 if plan1 == "all push" else 3 * h1
    if plan2 == "all push":
        ready2 = max(ready1 + d12, h2)
    elif plan2 == "push S1, pull C":
        ready2 = ready1 + d12 + 2 * h2
    else:  # the request waits at S1's node until S1 has results
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
                (S2, 5, S2_PLANS["push S1, pull C"]),
            ])
        self.assertEqual(latency, 7)


class TestProcessingLatency(unittest.TestCase):
    def test_weighted_processing_delays_dependents(self):
        # S1 in the cloud is ready at 3 + 0.5 * 2; S2 waits for it: 4 + 0.5 * 1
        latency = _latency([(S1, CLOUD, ALL_PUSH_S1), (S2, CLOUD, ALL_PUSH_S2)],
                           processing={S1: 2.0, S2: 1.0}, xi=0.5)
        self.assertEqual(latency, 4.5)


class TestSequentialBaseline(unittest.TestCase):
    """calculate_sequential_max_latency uses the same model for its plans."""

    def test_matches_the_hand_derived_timings(self):
        for n1, plan1, plan2 in itertools.product(HOSTS, S1_PLANS, S2_PLANS):
            with self.subTest(S1=(n1, plan1), S2=plan2):
                latency = _sequential_latency([(S1, n1, S1_PLANS[plan1]),
                                               (S2, CLOUD, S2_PLANS[plan2])])
                self.assertEqual(latency, _expected(n1, plan1, CLOUD, plan2))


class TestPushPullSteps(unittest.TestCase):
    """Pull steps are a real sequence: each request waits for the events it
    filters with, and a source cannot answer before its event exists."""

    def test_pull_round_trips_stay_sequential(self):
        # S1 at 6: push B (1), pull A with B (1 + 1)        -> ready 3
        # S2 at cloud: push S1 (3 + 2 = 5), pull C (5 + 3 + 3) -> 11
        latency = _latency([
            (S1, 6, [((), ["B"]), (["B"], ["A"])]),
            (S2, CLOUD, [((), [S1]), (["A"], ["C"])]),
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

    def test_step_already_at_the_node_needs_no_round_trip(self):
        # C already reaches node 6 for another placement there, so the pull
        # step for it costs only its 1-hop push, not a request round trip.
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (S2, 6, [((), [S1]), (["A"], ["C"])], [(1, ["C"])]),
        ])
        self.assertEqual(latency, 3)

    def test_without_local_events_the_round_trip_counts(self):
        latency = _latency([
            (S1, 6, ALL_PUSH_S1),
            (S2, 6, [((), [S1]), (["A"], ["C"])]),
        ])
        self.assertEqual(latency, 5)  # S1 ready at 1, request to 2 and back by 3, +2


if __name__ == "__main__":
    unittest.main()
