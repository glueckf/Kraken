"""The paper's motivating example, extended into a playable demo round.

Source: Ziehn et al., "KRAKEN: Joint Optimization of Operator Placement and
Communication for Distributed Stream Processing", extended technical report
(Kraken_DEBS_Long_Version.pdf in the repo root):
  - Example 1 + Figure 1: factory topology, sequential vs. joint plan
  - Example 2: source rates r(A)=1000, r(B)=10
  - Example 3 + Figure 3: one expand step, deployment decisions over
    {all-push, push-pull} at each candidate node
  - Example 4: ingress/egress cost and latency rules
  - Sec. 4.3.2: scalar score F(s) = min-max normalised weighted sum over the
    candidate pool

The rates, selectivity and cost/latency *rules* below are the paper's own
(see the passages above); nothing here encodes a result -- costs, latencies
and the winning plan are computed by Kraken's own engine (src/) and,
independently, by `paper_cost_model()` from those rules. The *topology* is
not Fig. 1, though (see FOG_A/FOG_B below): in the paper's own shape, A and
B both feed straight into one node, so every one of its three real
candidates happens to see both sources, and there was nowhere to show the
rule every Reef round already teaches -- a node that doesn't reach one of a
subquery's sources can't host it. This demo gives A and B their own hub
each, one hop further apart, and only merges them at a third node -- so the
cost/latency *numbers* are this demo's own (still computed and cross-checked
the same rigorous way), not the paper's printed figures. See
FACTORY_ROUND.md for the full derivation and what changed.

How the example is mapped onto the existing engine (and where it has to
deviate from the engine's defaults — see demo/FACTORY_ROUND.md):

  * Topology: sources A and B each feed their own fog hub (FOG_A, FOG_B),
    which both feed FOG_MERGE, then FOG_PRE_CLOUD, then the cloud c. Engine
    node ids: c = 0 (the engine's cloud is always node 0); see the
    constants below for the rest. Hop distances: every edge is 1, as in the
    paper (ℓ(e) = 1, Fig. 1), so e.g. dist(A, FOG_MERGE) = dist(B,
    FOG_MERGE) = 2, dist(FOG_MERGE, c) = 2.
  * Sources do no processing (Sec. 2.1: cpu(n) = 0 for sources); compute
    capacity is not part of the example ("ignoring capacity and latency
    constraints"), so fog/cloud get unbounded capacity.
  * Operator: the paper's binary window operator [A o B]_W with selectivity
    s_AB = 0.1 and r_out = s * r(A) * r(B) (Sec. 2.2) = 1000 — the value
    Example 4 assumes. The engine models a binary operator with exactly that
    rate as SEQ(A, B) (Theta may contain temporal order constraints, Sec.
    2.1). The engine's AND(A, B) is SEQ(A,B) u SEQ(B,A) and would double the
    output rate to 2000, contradicting the paper — so SEQ is used.
  * Pull selectivity: Example 1/4 pull matching A tuples with
    sigma(A | B) = s_AB = 0.1. PrePP's deterministic mode normally reads a
    hardcoded table tuned to the 12-node reef ("A|AB": 0.0013437); for this
    round only, that table is replaced by the paper's value. The paper gives
    no value for sigma(B | A) (pushing A and pulling B is not one of the
    paper's evaluated decisions). It is set from the engine's own invariant
    sigma(A|AB) * sigma(B|AB) = s_AB (simulator/single_selectivities.py),
    i.e. 1.0, and the round does not offer that acquisition order; a test
    checks the reference results do not depend on it.
  * Result forwarding (Sec. 4.3.1, "fixed sinks and explicit result
    forwarding"): the output is shipped to the cloud sink c; the engine's
    CostCalculator adds this egress term.
"""
from __future__ import annotations

import contextlib
import io
import math
from typing import Dict, List

# --------------------------------------------------------------------------
# Paper inputs (see module docstring for the exact passages)
# --------------------------------------------------------------------------
CLOUD = 0
# Not the paper's own Fig. 1 (A and B both feed straight into one node) --
# extended so the round can also show the rule every Reef round already
# teaches: a node that doesn't reach one of a subquery's sources can't host
# it. A and B each get their own single-source fog hub; the two only merge
# for the first time at FOG_MERGE, one hop further up; FOG_PRE_CLOUD is a
# plain pass-through so the candidate set is still three nodes deep (same
# shape as the paper's own <1, 2, c>), not two. FOG_A/FOG_B are never
# placement candidates for SEQ(A, B) -- tapping either triggers the same
# generic rejection as in Reef (state.ts placementIssue ->
# t().unreachableSource); verified in
# test_single_source_hubs_are_unreachable_and_never_candidates. This changes
# every hop distance from the paper's own Fig. 1, so the cost/latency
# numbers below are this demo's own (computed and cross-checked the same
# rigorous way, just no longer identical to the paper's printed figures --
# see FACTORY_ROUND.md).
FOG_A = 1          # machine A's own hub -- only A reachable from here
FOG_B = 2          # control panel B's own hub -- only B reachable from here
FOG_MERGE = 3      # first node both A and B are reachable from
FOG_PRE_CLOUD = 4  # one more hop toward the sink, so there are still 3 real candidates
SRC_A = 5          # machine A, vibration measurements
SRC_B = 6          # control panel B, manual fault confirmations

RATES = {"A": 1000, "B": 10}           # Example 2, tuples per window
SELECTIVITY_AB = 0.1                   # Example 1, s_AB
PARENT = {
    SRC_A: FOG_A, SRC_B: FOG_B,
    FOG_A: FOG_MERGE, FOG_B: FOG_MERGE,
    FOG_MERGE: FOG_PRE_CLOUD, FOG_PRE_CLOUD: CLOUD,
}
NODE_LABEL = {CLOUD: "c", FOG_A: "1", FOG_B: "2", FOG_MERGE: "3", FOG_PRE_CLOUD: "4", SRC_A: "A", SRC_B: "B"}

# The two acquisition schemes the paper itself evaluates for every candidate
# node (Sec. 4.2, step 6; Example 3): all-push, and PrePP's tuple-volume-
# greedy push-pull sequence. For [A o B] the latter is <(∅,{B}), ({B},{A})>
# — push B, pull A with B as predicate (Example 4).
SCHEMES = ("all_push", "push_pull")
PUSH_PULL_PUSHED = ["B"]

# The decision space a player can actually build: the demo gives every
# subquery the same free per-dependency push/pull chips as the Reef rounds
# (panel.ts renderPushPullRow), so for SEQ(A, B) that's three of the four
# subsets of {A, B} -- not just the paper's two named schemes, but also not
# the fourth ("pull both", pushing neither). That one isn't offered at all
# (no pull-all quick button in this round's tray, and score_one.py's
# paper_round validation below rejects an empty push group): pulling needs
# an already-pushed tuple to use as the filter/trigger for the request, so
# "pull everything" has nothing to filter with -- not a cheap-but-valid
# choice the way "push A" is, but not a coherent operation at all. "push_a"
# (push A, let the optimizer handle B) *is* real and costed (enumerate_
# decisions below) -- it lands exactly on all-push's cost and latency at
# every candidate node (verified in test_factory_example.py
# test_push_a_is_all_push_in_cost_and_latency): with sigma(B|A) = 1.0,
# pulling B on demand is never cheaper than just publishing it, so the
# search falls back to pushing everything. Pushing B and pulling A is the
# *only* direction that wins, because sigma(A|B) = 0.1 makes pulling the
# expensive stream on demand genuinely cheap. This asymmetry -- not an
# arbitrary restriction -- is why the paper only names two of the three.
PUSH_A = ["A"]
ALL_SCHEMES = SCHEMES + ("push_a",)
FORCED_GROUP = {"push_pull": PUSH_PULL_PUSHED, "push_a": PUSH_A}

# Paper's per-pair conditional selectivities as fed to PrePP (see docstring).
# "B|AB": 1.0 is sigma(B|A) (Engine invariant sigma(A|AB)*sigma(B|AB)=s_AB) --
# the paper never evaluates that direction so it gives no value for it; this
# is the value "push_a"'s live scoring uses.
CONDITIONAL_SELECTIVITIES = {"A": 1.0, "B": 1.0, "A|AB": SELECTIVITY_AB, "B|AB": 1.0}

# Weight used for the headline comparison: 0.6 is the demo's default
# "Balanced" stage, and the paper's own discussion of this example
# (Sec. 4.3.2) singles out alpha >= 0.6 as the "intermediate weights" range.
DEFAULT_ALPHA = 0.6

QUERY_TITLE = "[A ∘ B]"


def build_query():
    from core.tree import PrimEvent as P, SEQ
    from core.query_workload import number_children
    return number_children(SEQ(P("A"), P("B")))


def _create_tree():
    from core.node import Node
    nodes = {
        CLOUD: Node(id=CLOUD, compute_power=math.inf, memory=math.inf),
        FOG_PRE_CLOUD: Node(id=FOG_PRE_CLOUD, compute_power=math.inf, memory=math.inf),
        FOG_MERGE: Node(id=FOG_MERGE, compute_power=math.inf, memory=math.inf),
        FOG_A: Node(id=FOG_A, compute_power=math.inf, memory=math.inf),
        FOG_B: Node(id=FOG_B, compute_power=math.inf, memory=math.inf),
        SRC_A: Node(id=SRC_A, compute_power=0, memory=0),
        SRC_B: Node(id=SRC_B, compute_power=0, memory=0),
    }
    letters = list(RATES)
    for n in nodes.values():
        n.eventrates = [0] * len(letters)
    nodes[SRC_A].eventrates[letters.index("A")] = RATES["A"]
    nodes[SRC_B].eventrates[letters.index("B")] = RATES["B"]
    for child, parent in PARENT.items():
        nodes[child].Parent = [nodes[parent]]
        nodes[parent].Child.append(nodes[child])
    # eList: every ancestor of each source, as create_hardcoded_tree does
    e_list = {}
    for src in (SRC_A, SRC_B):
        anc, cur = [], src
        while cur in PARENT:
            cur = PARENT[cur]
            anc.append(cur)
        e_list[src] = sorted(anc)
    network = [nodes[i] for i in sorted(nodes)]
    return nodes[CLOUD], network, e_list


@contextlib.contextmanager
def factory_model():
    """Swap the engine's hardcoded (12-node reef) inputs for the paper's
    example for the duration of the block, then restore them. Scoped so the
    reef rounds can never see the factory values or vice versa."""
    import simulation_environment as se
    import prepp.prepp as prepp_mod

    q = build_query()
    patches = {
        (se, "create_hardcoded_tree"): _create_tree,
        (se, "generate_hardcoded_primitive_events"): lambda: [RATES[k] for k in RATES],
        (se, "generate_hardcoded_selectivities"): lambda: (
            {"AB": SELECTIVITY_AB, "BA": SELECTIVITY_AB}, [SELECTIVITY_AB, SELECTIVITY_AB]),
        (se, "generate_hardcoded_workload"): lambda: [q],
        (prepp_mod, "generate_hardcoded_projection_selectivities"): lambda: dict(CONDITIONAL_SELECTIVITIES),
    }
    saved = {k: getattr(*k) for k in patches}
    try:
        for (mod, name), fn in patches.items():
            setattr(mod, name, fn)
        yield q
    finally:
        for (mod, name), fn in saved.items():
            setattr(mod, name, fn)


def make_config(cost_weight: float, output_dataset_name: str):
    import simulation_environment as se
    return se.SimulationConfig.create_deterministic(
        network_size=len(NODE_LABEL), num_event_types=len(RATES), xi=0.0,
        cost_weight=cost_weight, latency_threshold=None,
        output_dataset_name=output_dataset_name,
    )


def fresh_simulation(cost_weight: float = DEFAULT_ALPHA, output_dataset_name: str = "demo_factory"):
    """Set up (but do not run) the engine on the paper example.

    Kraken and the enumeration must start from this *clean* state, not from a
    Simulation after `run()`: `run()` executes INEv first, and INEv's
    placement code writes its own forwarding decisions into the shared
    `h_eventNodes` matrix (core/structures.set_event_nodes). Kraken's
    PlacementOptimizer later reads that same matrix to decide which nodes are
    candidates — on this topology it then only offers the cloud (verified:
    after `run()`, rows for A3/B4 are [1,1,1,1,0]/[1,1,1,0,1] instead of the
    initial [0,0,0,1,0]/[0,0,0,0,1]). Starting from a fresh object gives
    Kraken and Sequential identical inputs."""
    import simulation_environment as se
    with factory_model():
        with contextlib.redirect_stdout(io.StringIO()):
            sim = se.Simulation(make_config(cost_weight, output_dataset_name))
            sim.all_push_results = se.compute_all_push(sim)
    return sim


def run_baselines(output_dataset_name: str = "demo_factory"):
    """The engine's own full pipeline (`Simulation.run()`), used only for the
    cloud-only baselines All-Push and PrePP — both are independent of the
    event-node side effect described in fresh_simulation(), and serve as a
    cross-check of the enumerated (c, all-push) and (c, push-pull) cells."""
    import simulation_environment as se
    with factory_model():
        with contextlib.redirect_stdout(io.StringIO()):
            sim = se.Simulation(make_config(DEFAULT_ALPHA, output_dataset_name))
            sim.run()
    return sim


def run_kraken(cost_weight: float, output_dataset_name: str = "demo_factory"):
    """Kraken's real greedy search (run_kraken_solver) at one alpha, on clean
    inputs. Returns (simulation, greedy-result dict)."""
    from kraken.run import run_kraken_solver
    sim = fresh_simulation(cost_weight, output_dataset_name)
    with factory_model():
        with contextlib.redirect_stdout(io.StringIO()):
            res = run_kraken_solver(sim, strategies_to_run=[{"name": "greedy"}], compare_within_kraken=False)
    return sim, res["strategies"]["greedy"]


# --------------------------------------------------------------------------
# Full enumeration of the reference search space with Kraken's own cost model
# --------------------------------------------------------------------------
def _problem(sim):
    from inev.process_combination import compute_dependencies
    from kraken.run import _gather_problem_parameters
    from kraken.problem import PlacementProblem
    levels = compute_dependencies(sim, sim.h_mycombi, getattr(sim, "h_criticalMSTypes", None))
    order = sorted(levels, key=lambda x: levels[x])
    problem = PlacementProblem(order, _gather_problem_parameters(sim))
    return problem, order


def enumerate_decisions(sim=None) -> List[Dict]:
    """Every (node, scheme) deployment decision for the single subquery,
    costed by Kraken's CostCalculator exactly as score_one.py costs a
    player's choice -- all four schemes in ALL_SCHEMES, i.e. the full set a
    player can build with the free per-dependency push/pull chips, not just
    the paper's own two. Candidate nodes are the engine's own feasible set
    (the paper's N_cand = <1, 2, c>). `sim` must be a fresh, un-run
    Simulation (see fresh_simulation())."""
    if sim is None:
        sim = fresh_simulation()
    with factory_model():
        problem, order = _problem(sim)
        assert len(order) == 1, f"expected a single subquery, got {order}"
        p = order[0]
        s0 = problem.get_initial_candidate()
        # Same call PlacementProblem.expand() makes for its candidate set.
        nodes = problem.optimizer.get_possible_placement_nodes_optimized(
            p, s0.get_placed_subqueries(p, problem), problem.cost_calculator.params
        )

        def make_entry(scheme, n, r, forced_cost=None):
            s1 = problem._create_next_candidate(s0, p, n, r)
            steps = [
                {"mode": "push" if st.is_push_based else "pull",
                 "events": [str(e) for e in st.events_to_pull]}
                for st in r["acquisition_steps"].steps
            ] if r.get("acquisition_steps") is not None else []
            entry = {
                "node": n,
                "scheme": scheme,
                "cost": float(s1.cumulative_cost),
                "latency": float(s1.get_critical_path_latency(problem)),
                "processing_latency": float(r.get("individual_processing_latency", 0.0)),
                "steps": steps,
            }
            if forced_cost is not None:
                entry["forced_cost"] = float(forced_cost)
            return entry

        out = []
        with contextlib.redirect_stdout(io.StringIO()):
            for n in sorted(int(x) for x in nodes):
                results = problem.cost_calculator.calculate(p, n, s0, forced_push_group=None)
                by_strategy = {r["strategy"]: r for r in results}
                out.append(make_entry("all_push", n, by_strategy["all_push"]))
                for scheme in ("push_pull", "push_a"):
                    forced_group = FORCED_GROUP[scheme]
                    forced = problem.cost_calculator.calculate(
                        p, n, s0, forced_push_group=list(forced_group)
                    )[-1]
                    # For push_pull, this is PrePP's own unforced pick too
                    # (by_strategy["push_pull"]) -- the player's explicit call
                    # must cost the same as the optimizer's free one, since
                    # it's the same plan. push_a has no unforced counterpart
                    # (PrePP's free search never picks it, see the
                    # ALL_SCHEMES comment), so there's nothing separate to
                    # cross-check it against here (paper_cost_model covers
                    # that instead) -- forced_cost is just its own cost,
                    # kept for shape-consistency with push_pull's entry.
                    r = (by_strategy.get("push_pull") if scheme == "push_pull" else None) or forced
                    out.append(make_entry(scheme, n, r, forced["individual_cost"]))
    return out


# --------------------------------------------------------------------------
# Paper scoring (Sec. 4.3.2) and the two planners compared in Example 1
# --------------------------------------------------------------------------
def score_F(cost: float, latency: float, pool: List[Dict], alpha: float) -> float:
    vmin, vmax = min(d["cost"] for d in pool), max(d["cost"] for d in pool)
    lmin, lmax = min(d["latency"] for d in pool), max(d["latency"] for d in pool)
    vn = 0.0 if vmax == vmin else (cost - vmin) / (vmax - vmin)
    ln = 0.0 if lmax == lmin else (latency - lmin) / (lmax - lmin)
    return alpha * vn + (1.0 - alpha) * ln


def _argmin(cands: List[Dict], pool: List[Dict], alpha: float) -> Dict:
    # ties: lower cost, then lower latency, then node id — deterministic
    return min(cands, key=lambda d: (round(score_F(d["cost"], d["latency"], pool, alpha), 12),
                                     d["cost"], d["latency"], d["node"]))


def reference_optimum(pool: List[Dict], alpha: float) -> Dict:
    """Exhaustive: the best decision in the whole enumerated pool."""
    return _argmin(pool, pool, alpha)


def all_push_best(pool: List[Dict], alpha: float) -> Dict:
    return _argmin([d for d in pool if d["scheme"] == "all_push"], pool, alpha)


def sequential_plan(pool: List[Dict], alpha: float) -> Dict:
    """Example 1's sequential planner, with the same inputs and the same F as
    Kraken: (1) fix the placement that is best under all-push, (2) then pick
    the best acquisition scheme for that fixed node."""
    node = all_push_best(pool, alpha)["node"]
    return _argmin([d for d in pool if d["node"] == node], pool, alpha)


# --------------------------------------------------------------------------
# Independent re-derivation from the paper's formulas (no engine involved)
# --------------------------------------------------------------------------
def _dist(x: int, y: int) -> int:
    def path_up(n):
        p = [n]
        while n in PARENT:
            n = PARENT[n]
            p.append(n)
        return p
    px, py = path_up(x), path_up(y)
    common = next(n for n in px if n in py)
    return px.index(common) + py.index(common)


def paper_cost_model(node: int, scheme: str) -> Dict:
    """Sec. 4.3.1 ingress-egress formulation for p = [A o B] at `node`,
    initial state s0 (only sources hold streams), xi = 0.

    all-push:  one push step (∅,{A,B})
    push-pull: <(∅,{B}), ({B},{A})>
      V_req(a2) = r(B) * dist(node, A)           (predicate tuples to A)
      V_res(a2) = r(A) * sigma(A|B) * dist(A, node)
    push_a: the ALL_SCHEMES comment explains why it is always plain
      all-push (sigma(B|A) = 1.0 makes pulling B never cheaper than
      publishing it). The exact-plan search realizes it as two push steps
      -- <(∅,{A}),({},{B})> -- but neither waits for a request, so both
      streams arrive in parallel: max(dist(node,A), dist(node,B)), the same
      latency as all-push's single step.
    egress:    r_out * dist(node, c), r_out = s_AB * r(A) * r(B)
    latency:   pushed streams arrive in parallel (max provider dist); a pull
               leg starts once its pushed trigger has arrived (+ request
               + response), then + dist(node, c)
    """
    rA, rB, s = RATES["A"], RATES["B"], SELECTIVITY_AB
    dA, dB, dC = _dist(SRC_A, node), _dist(SRC_B, node), _dist(node, CLOUD)
    r_out = s * rA * rB
    if scheme == "all_push":
        ingress = rA * dA + rB * dB
        lat_ing = max(dA, dB)
    elif scheme == "push_a":
        ingress = rA * dA + rB * dB            # same volume as all-push
        lat_ing = max(dA, dB)                  # both pushed, in parallel
    elif scheme == "push_pull":
        a1 = rB * dB                         # push B
        a2_req = rB * 1.0 * dA               # sigma(Psi) = 1 for the raw B stream
        a2_res = rA * s * dA                 # sigma(A | B) = s_AB
        ingress = a1 + a2_req + a2_res
        lat_ing = dB + (dA + dA)             # push leg, then request + response
    else:
        raise ValueError(scheme)
    egress = r_out * dC if node != CLOUD else 0.0
    return {"node": node, "scheme": scheme, "cost": ingress + egress,
            "latency": float(lat_ing + dC), "ingress": ingress, "egress": egress}
