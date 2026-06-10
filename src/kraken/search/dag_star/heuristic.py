"""Admissible heuristic for DAG* placement search.

Lower-bounds the cost of placing every projection that has not yet been
assigned. Each unplaced projection contributes:

  - ingress from primitive event streams: rate(X) * s_min(P, X) * min_dist
  - ingress from sub-query inputs: producer_rate * min_dist
  - egress (final-workload projections only): output_rate * min_dist_to_sink

Each distance term is minimised independently across admissible nodes; the
per-term minimisers may correspond to mutually-exclusive placements, but the
sum still under-bounds any feasible plan, which is what admissibility needs.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from kraken.problem import PlacementProblem
    from kraken.data.state import SolutionCandidate


class DagStarHeuristic:
    """Pre-computes lower-bound tables and evaluates h(state) in O(remaining)."""

    def __init__(self, problem: "PlacementProblem"):
        self._problem = problem
        params = problem.cost_calculator.params

        self._distances: Any = params["pairwise_distance_matrix"]
        self._selectivities: Dict[str, float] = params["pairwise_selectivities"]
        self._global_event_rates: Any = params["global_event_rates"]
        self._proj_rates: Any = params["projection_rates_selectivity"]
        self._primitives_per_proj: Dict[str, List[str]] = params[
            "primitive_events_per_projection"
        ]
        self._nodes_per_primitive: Dict[str, List[int]] = params[
            "nodes_per_primitive_event"
        ]
        self._sink_nodes: List[int] = params["sink_nodes"]
        self._dependencies = problem.dependencies_per_projection
        self._workload = problem.query_workload

        self._candidates: Dict[Any, List[int]] = {}
        self._s_min: Dict[Any, Dict[str, float]] = {}
        self._min_primitive_dist: Dict[Any, Dict[str, float]] = {}
        self._min_subquery_dist: Dict[Tuple[Any, Any], float] = {}
        self._min_egress_dist: Dict[Any, float] = {}
        self._output_rate: Dict[Any, float] = {}
        self._primitive_rate: Dict[str, float] = {}

        self._precompute()

    def _precompute(self) -> None:
        """Build all per-projection lookup tables once."""
        self._build_candidate_sets()
        self._build_primitive_rates()
        self._build_output_rates()
        self._build_s_min()
        self._build_min_primitive_dist()
        self._build_min_subquery_dist()
        self._build_min_egress_dist()

    def _build_candidate_sets(self) -> None:
        """Per-projection super-set of viable placement nodes (no placed deps)."""
        params = self._problem.cost_calculator.params
        for p in self._problem.processing_order:
            self._candidates[p] = (
                self._problem.optimizer.get_possible_placement_nodes_optimized(
                    p, {}, params
                )
            )

    def _build_primitive_rates(self) -> None:
        """Map primitive event type -> total source rate across all hosts."""
        rates = self._global_event_rates
        for event_type, hosts in self._nodes_per_primitive.items():
            self._primitive_rate[event_type] = self._lookup_primitive_rate(
                rates, event_type, hosts
            )

    @staticmethod
    def _lookup_primitive_rate(
        rates: Any, event_type: str, hosts: List[int]
    ) -> float:
        """Return total ingestion rate of a primitive event across its sources.

        Tries multiple shapes for `rates` because the simulation context exposes
        rates either as a flat dict, a per-event dict-of-nodes, or a list keyed
        by event index (A=0, B=1, ...).
        """
        if isinstance(rates, dict):
            value = rates.get(event_type)
            if isinstance(value, dict):
                return float(sum(value.get(h, 0.0) for h in hosts))
            if value is not None:
                return float(value)
        try:
            idx = ord(event_type) - ord("A")
            return float(rates[idx])
        except (TypeError, IndexError, KeyError):
            return 0.0

    def _build_output_rates(self) -> None:
        """Per-projection output rate (placement-independent)."""
        for p in self._problem.processing_order:
            self._output_rate[p] = self._lookup_output_rate(p)

    def _lookup_output_rate(self, p: Any) -> float:
        """Resolve output rate; mirrors cost_calculator's `(0, 1)[1]` pattern."""
        rates = self._proj_rates
        if not isinstance(rates, dict):
            return 0.0
        for key in (p, str(p)):
            tup = rates.get(key)
            if tup is None:
                continue
            if isinstance(tup, (list, tuple)) and len(tup) > 1:
                try:
                    return float(tup[1])
                except (TypeError, ValueError):
                    return 0.0
            try:
                return float(tup)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def _projection_key(self, p: Any) -> Optional[str]:
        """Resolve the string key used by primitives_per_projection."""
        if str(p) in self._primitives_per_proj:
            return str(p)
        try:
            stripped = p.strip_kl_simple()
            if str(stripped) in self._primitives_per_proj:
                return str(stripped)
        except AttributeError:
            pass
        return None

    def _primitives_for(self, p: Any) -> List[str]:
        key = self._projection_key(p)
        return list(self._primitives_per_proj.get(key, [])) if key else []

    def _build_s_min(self) -> None:
        """For each (P, X), min selectivity over (X, Y) with Y ∈ events(P)."""
        for p in self._problem.processing_order:
            primitives = self._primitives_for(p)
            self._s_min[p] = {}
            for x in primitives:
                best = 1.0
                for y in primitives:
                    if y == x:
                        continue
                    s = self._lookup_selectivity(x, y)
                    if s is not None and s < best:
                        best = s
                self._s_min[p][x] = best

    def _lookup_selectivity(self, x: str, y: str) -> Optional[float]:
        """Look up pairwise selectivity, trying both orderings."""
        for key in (x + y, y + x):
            if key in self._selectivities:
                return float(self._selectivities[key])
        return None

    def _min_dist_between(self, sources: List[int], targets: List[int]) -> float:
        """Minimum pairwise distance between two node sets (0.0 if shared)."""
        if not sources or not targets:
            return 0.0
        target_set = set(targets)
        if any(s in target_set for s in sources):
            return 0.0
        best = float("inf")
        for s in sources:
            row = self._distances[s]
            for t in targets:
                d = row[t]
                if d < best:
                    best = d
        return best if best != float("inf") else 0.0

    def _build_min_primitive_dist(self) -> None:
        """For each (P, X), min distance from any X-source to any candidate(P)."""
        for p in self._problem.processing_order:
            self._min_primitive_dist[p] = {}
            cands = self._candidates.get(p, [])
            for x in self._primitives_for(p):
                hosts = self._nodes_per_primitive.get(x, [])
                self._min_primitive_dist[p][x] = self._min_dist_between(hosts, cands)

    def _build_min_subquery_dist(self) -> None:
        """Min distance over (producer-cand, consumer-cand) when producer unplaced."""
        for consumer in self._problem.processing_order:
            consumer_cands = self._candidates.get(consumer, [])
            for producer in self._dependencies.get(consumer, []):
                producer_cands = self._candidates.get(producer, [])
                self._min_subquery_dist[(producer, consumer)] = self._min_dist_between(
                    producer_cands, consumer_cands
                )

    def _build_min_egress_dist(self) -> None:
        """Min distance from any candidate(P) to any sink, for workload projections."""
        for p in self._problem.processing_order:
            if p not in self._workload:
                self._min_egress_dist[p] = 0.0
                continue
            cands = self._candidates.get(p, [])
            self._min_egress_dist[p] = self._min_dist_between(cands, self._sink_nodes)

    def estimate(self, state: "SolutionCandidate") -> float:
        """Lower bound on remaining cost for unplaced projections."""
        placed_count = len(state.placements)
        order = self._problem.processing_order
        total = 0.0

        for p in order[placed_count:]:
            total += self._estimate_one(p, state)
        return total

    def _estimate_one(self, p: Any, state: "SolutionCandidate") -> float:
        cost = 0.0
        cost += self._primitive_ingress_lb(p)
        cost += self._subquery_ingress_lb(p, state)
        if p in self._workload:
            cost += self._output_rate.get(p, 0.0) * self._min_egress_dist.get(p, 0.0)
        return cost

    def _primitive_ingress_lb(self, p: Any) -> float:
        s_min = self._s_min.get(p, {})
        dist = self._min_primitive_dist.get(p, {})
        total = 0.0
        for x in self._primitives_for(p):
            rate = self._primitive_rate.get(x, 0.0)
            total += rate * s_min.get(x, 1.0) * dist.get(x, 0.0)
        return total

    def _subquery_ingress_lb(self, p: Any, state: "SolutionCandidate") -> float:
        total = 0.0
        consumer_cands = self._candidates.get(p, [])
        for producer in self._dependencies.get(p, []):
            rate = self._output_rate.get(producer, 0.0)
            if rate <= 0.0:
                continue
            placement = state.placements.get(producer)
            if placement is not None:
                d = self._min_dist_between([placement.node], consumer_cands)
            else:
                d = self._min_subquery_dist.get((producer, p), 0.0)
            total += rate * d
        return total
