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
A produced at node 1, B and C at node 2.
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kraken.data.acquisition_step import (
    AcquisitionSet,
    AcquisitionStep,
    PullRequest,
    PullResponse,
)
from kraken.data.state import PlacementInfo, SolutionCandidate

CLOUD = 0
PARENT = {5: 0, 6: 5, 1: 6, 2: 6}
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


def _latency(placements, workload=(S2,)):
    """placements: list of (projection, node, steps[, already_at_node]) in
    processing order."""
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
            individual_processing_latency=0.0, acquisition_steps=acquisition,
        )
        placed[projection] = node
    problem = SimpleNamespace(
        processing_order=[S1, S2],
        dependencies_per_projection=DEPS,
        query_workload=list(workload),
        latency_weighting_factor=0.0,
        cost_calculator=SimpleNamespace(
            params={"pairwise_distance_matrix": DIST, "sink_nodes": [CLOUD]}),
    )
    return candidate.get_critical_path_latency(problem)


ALL_PUSH_S1 = [((), ["A", "B"])]
ALL_PUSH_S2 = [((), [S1, "C"])]


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

    def test_serial_path_through_a_subquery_still_accumulates(self):
        # B travels 2 hops to S1 at node 1, S1's output 3 more to the cloud:
        # a genuinely sequential path of 5, longer than C's direct 3.
        latency = _latency([(S1, 1, ALL_PUSH_S1), (S2, CLOUD, ALL_PUSH_S2)])
        self.assertEqual(latency, 5)

    def test_sink_hop_of_a_shared_workload_query_is_not_inherited(self):
        # S1 is itself a workload query (shared subquery): its own result
        # goes to the sink, but S2 consumes it at node 6 without that detour.
        latency = _latency([(S1, 6, ALL_PUSH_S1), (S2, 6, ALL_PUSH_S2)],
                           workload=(S1, S2))
        self.assertEqual(latency, 3)  # was 6

    def test_nothing_placed(self):
        self.assertEqual(_latency([]), 0.0)


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
        # S1 at 1: push A (local), pull B from node 2 (2 + 2)   -> ready 4
        # S2 at 6: push C (1); pull S1 from node 1: the request is there at
        # 2 but S1 only has results at 4, back at 5; +2 hops to the sink.
        latency = _latency([
            (S1, 1, [((), ["A"]), (["A"], ["B"])]),
            (S2, 6, [((), ["C"]), (["C"], [S1])]),
        ])
        self.assertEqual(latency, 7)  # was 9: 4 + (1 + 1 + 1) + 2

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
        self.assertEqual(latency, 5)  # S1 at 1, request to 2 and back by 3, +2


if __name__ == "__main__":
    unittest.main()
