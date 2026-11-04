"""Tests for the paper-example round (factory_example.py, FACTORY_ROUND.md).

What is checked, and against what:
  * Engine vs. independent formula: every cell of the decision table computed
    by Kraken's CostCalculator equals the independent re-derivation from the
    paper's cost/latency rules (paper_cost_model), applied to this round's
    own topology -- not the paper's Fig. 1 (see factory_example.py's module
    docstring for why it's extended, and FACTORY_ROUND.md for the full
    derivation). EXTENDED_EXAMPLE_GOLDENS pins specific numbers as a
    regression lock, computed and cross-checked the same rigorous way the
    original six paper cells were, just no longer identical to the paper's
    own printed figures.
  * Full enumeration: the reference optimum is found by scanning the whole
    space, and Kraken's greedy result is compared to it per stage instead of
    being assumed optimal.
  * Coupling (acceptance criterion 2): the placement preferred under
    all-push differs from the best placement+communication combination.
  * Sequential and Kraken see the same table and the same score F.
  * The unquantified sigma(B|A) does not influence any reachable result.
  * Pushing A instead of B -- a real combination the free per-dependency
    chips let a player build, not just the paper's own two named schemes --
    is scored live, and costs exactly the same as all-push everywhere.
  * Pulling everything (pushing nothing) is rejected outright, not silently
    scored as some other plan: there's no pushed tuple to filter against.
  * FOG_A/FOG_B (each reaches only one of the two sources) are never
    placement candidates, same as the sources themselves.
  * The backend worker (score_one.py) scores the round identically and
    rejects a placement, dependency or empty push group outside the paper
    example.
  * The exported JSON is current, and the scoped engine patch is undone.

Run from demo/export:  python -m unittest tests.test_factory_example
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(EXPORT_DIR, "..", ".."))
SCENARIO_JSON = os.path.join(REPO, "demo", "web", "scenarios", "factory", "factory_join.json")
for p in (EXPORT_DIR, REPO, os.path.join(REPO, "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import factory_example as fx  # noqa: E402

# This demo's own cells (not the paper's printed figures -- see the module
# docstring and factory_example.py's docstring on FOG_A/FOG_B): computed by
# the engine and independently cross-checked against paper_cost_model, with
# this round's own extended topology's distances.
EXTENDED_EXAMPLE_GOLDENS = {
    (fx.FOG_MERGE, "all_push"): (4020, 4),
    (fx.FOG_MERGE, "push_pull"): (2240, 8),
    (fx.FOG_PRE_CLOUD, "push_pull"): (1360, 10),
    (fx.CLOUD, "all_push"): (4040, 4),
    (fx.CLOUD, "push_pull"): (480, 12),
}


def key(d):
    return (d["node"], d["scheme"])


class TestFactoryExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = fx.enumerate_decisions(fx.fresh_simulation())
        cls.table = {key(d): d for d in cls.pool}

    # --- inputs ---------------------------------------------------------
    def test_output_rate_follows_paper_rate_model(self):
        sim = fx.fresh_simulation()
        rates = {str(k): v for k, v in sim.h_projrates.items()}
        # r_out = s_AB * r(A) * r(B) (Sec. 2.2) = the 1000 Example 4 assumes
        self.assertEqual(list(rates), ["SEQ(A, B)"])
        self.assertAlmostEqual(rates["SEQ(A, B)"][1],
                               fx.SELECTIVITY_AB * fx.RATES["A"] * fx.RATES["B"])
        self.assertAlmostEqual(rates["SEQ(A, B)"][1], 1000.0)

    def test_hop_distances_match_the_extended_topology(self):
        # Every edge is 1 hop (ℓ(e) = 1, as in Fig. 1), but the shape is this
        # round's own (see factory_example.py docstring on FOG_A/FOG_B): A
        # and B each reach their own hub in 1 hop, the merge point in 2, and
        # the cloud in 4.
        sim = fx.fresh_simulation()
        d = sim.allPairs
        self.assertEqual(d[fx.SRC_A][fx.FOG_A], 1)
        self.assertEqual(d[fx.SRC_B][fx.FOG_B], 1)
        self.assertEqual(d[fx.SRC_A][fx.FOG_MERGE], 2)
        self.assertEqual(d[fx.SRC_B][fx.FOG_MERGE], 2)
        self.assertEqual(d[fx.FOG_MERGE][fx.CLOUD], 2)
        self.assertEqual(d[fx.SRC_A][fx.CLOUD], 4)
        self.assertEqual(d[fx.SRC_B][fx.CLOUD], 4)

    # --- enumeration ----------------------------------------------------
    def test_search_space_is_all_three_schemes_at_all_three_candidates(self):
        # 3 real candidates (FOG_MERGE, FOG_PRE_CLOUD, CLOUD) x 3 schemes --
        # see the ALL_SCHEMES comment in factory_example.py. Not a fourth
        # "pull everything": no pull-all quick button in this round, and
        # score_one.py's paper_round validation rejects an empty push group
        # outright -- pulling needs an already-pushed tuple to filter
        # against, so "pull everything" has nothing to filter with.
        self.assertEqual(sorted(self.table), sorted(
            (n, s) for n in (fx.CLOUD, fx.FOG_MERGE, fx.FOG_PRE_CLOUD) for s in fx.ALL_SCHEMES))
        self.assertNotIn(fx.SRC_A, {d["node"] for d in self.pool})
        self.assertNotIn(fx.SRC_B, {d["node"] for d in self.pool})

    def test_single_source_hubs_are_unreachable_and_never_candidates(self):
        # FOG_A only reaches A, FOG_B only reaches B (see their docstring) --
        # neither can host SEQ(A, B), so neither should ever appear in the
        # enumerated pool, same as the sources themselves.
        nodes = {d["node"] for d in self.pool}
        self.assertNotIn(fx.FOG_A, nodes)
        self.assertNotIn(fx.FOG_B, nodes)

    def test_engine_matches_independent_paper_formulas(self):
        for d in self.pool:
            ref = fx.paper_cost_model(d["node"], d["scheme"])
            self.assertAlmostEqual(d["cost"], ref["cost"], msg=key(d))
            self.assertAlmostEqual(d["latency"], ref["latency"], msg=key(d))

    def test_engine_reproduces_this_rounds_own_goldens(self):
        for k, (v, lat) in EXTENDED_EXAMPLE_GOLDENS.items():
            self.assertAlmostEqual(self.table[k]["cost"], v, msg=k)
            self.assertAlmostEqual(self.table[k]["latency"], lat, msg=k)

    def test_push_pull_is_push_B_pull_A(self):
        for n in (fx.CLOUD, fx.FOG_MERGE, fx.FOG_PRE_CLOUD):
            d = self.table[(n, "push_pull")]
            self.assertEqual(d["steps"], [{"mode": "push", "events": ["B"]},
                                          {"mode": "pull", "events": ["A"]}])
            # the player's explicit choice costs the same as PrePP's own pick
            self.assertAlmostEqual(d["forced_cost"], d["cost"])

    def test_push_a_costs_like_all_push_but_adds_latency(self):
        # The player's free per-dependency push/pull chips (panel.ts
        # renderPushPullRow, same component the Reef rounds use) let them try
        # pushing A instead of B for SEQ(A, B) -- not just the paper's named
        # all_push/push_pull. It's a real, legal choice a visitor can make
        # and see scored, live, via the same engine path as Reef
        # (score_one.py) -- this confirms what they'll see: the *volume* is
        # identical to all-push at every node (with sigma(B|A)=1.0 there's
        # nothing to request B's low native rate against, so the search
        # falls back to publishing it outright), but the *latency* is worse
        # -- realized as two sequential push steps instead of all-push's one
        # parallel step. Pushing B and pulling A is the only direction where
        # pulling genuinely saves cost (sigma(A|B)=0.1) -- see the
        # ALL_SCHEMES comment.
        for n in (fx.CLOUD, fx.FOG_MERGE, fx.FOG_PRE_CLOUD):
            all_push = self.table[(n, "all_push")]
            d = self.table[(n, "push_a")]
            self.assertAlmostEqual(d["cost"], all_push["cost"], msg=n)
            self.assertGreater(d["latency"], all_push["latency"], msg=n)

    # --- coupling + planners -------------------------------------------
    def test_all_push_preference_differs_from_joint_optimum(self):
        a = fx.DEFAULT_ALPHA
        apb = fx.all_push_best(self.pool, a)
        opt = fx.reference_optimum(self.pool, a)
        self.assertNotEqual(apb["node"], opt["node"])
        self.assertEqual((apb["node"], opt["node"], opt["scheme"]),
                         (fx.FOG_MERGE, fx.CLOUD, "push_pull"))

    def test_reference_optimum_is_exhaustive_minimum(self):
        for a in (0.0, 0.2, 0.6, 0.9, 1.0):
            opt = fx.reference_optimum(self.pool, a)
            best = min(fx.score_F(d["cost"], d["latency"], self.pool, a) for d in self.pool)
            self.assertAlmostEqual(fx.score_F(opt["cost"], opt["latency"], self.pool, a), best)

    def test_extreme_weights_pick_cost_vs_latency_winners(self):
        # alpha = 1 (pure cost): the lowest-volume cell, (cloud, push-pull).
        # alpha = 0 (pure latency): all-push ties at the same latency
        # (max(dA,dB)+dC is the constant source-to-sink path length) at every
        # candidate, so the tie-break (lowest cost) picks FOG_MERGE, the
        # cheapest of the three under all-push.
        self.assertEqual(key(fx.reference_optimum(self.pool, 1.0)), (fx.CLOUD, "push_pull"))
        self.assertEqual(key(fx.reference_optimum(self.pool, 0.0)), (fx.FOG_MERGE, "all_push"))

    def test_sequential_uses_same_table_and_score(self):
        a = fx.DEFAULT_ALPHA
        seq = fx.sequential_plan(self.pool, a)
        self.assertIn(key(seq), self.table)
        self.assertEqual(seq["node"], fx.all_push_best(self.pool, a)["node"])
        same_node = [d for d in self.pool if d["node"] == seq["node"]]
        self.assertAlmostEqual(
            fx.score_F(seq["cost"], seq["latency"], self.pool, a),
            min(fx.score_F(d["cost"], d["latency"], self.pool, a) for d in same_node))
        self.assertEqual(key(seq), (fx.FOG_MERGE, "push_pull"))

    def test_kraken_compared_with_enumeration_per_stage(self):
        # Not assumed: Kraken's real greedy run, checked against the scan.
        for a in (0.2, 0.6, 0.9):
            _, g = fx.run_kraken(a)
            (pi,) = g["solution"].placements.values()
            opt = fx.reference_optimum(self.pool, a)
            self.assertEqual((int(pi.node), pi.strategy), key(opt), msg=f"alpha={a}")
            self.assertAlmostEqual(float(g["metrics"]["total_cost"]), opt["cost"])
            self.assertAlmostEqual(float(g["metrics"]["max_latency"]), opt["latency"])

    def test_unquantified_sigma_B_given_A_does_not_matter(self):
        saved = dict(fx.CONDITIONAL_SELECTIVITIES)
        try:
            for value in (fx.SELECTIVITY_AB, 0.5):
                fx.CONDITIONAL_SELECTIVITIES["B|AB"] = value
                pool = fx.enumerate_decisions(fx.fresh_simulation())
                for d in pool:
                    self.assertAlmostEqual(d["cost"], self.table[key(d)]["cost"], msg=(value, key(d)))
                    self.assertAlmostEqual(d["latency"], self.table[key(d)]["latency"])
        finally:
            fx.CONDITIONAL_SELECTIVITIES.clear()
            fx.CONDITIONAL_SELECTIVITIES.update(saved)

    def test_patch_is_scoped(self):
        import simulation_environment as se
        import prepp.prepp as pp
        before = (se.create_hardcoded_tree, pp.generate_hardcoded_projection_selectivities)
        with fx.factory_model():
            self.assertIsNot(se.create_hardcoded_tree, before[0])
        self.assertIs(se.create_hardcoded_tree, before[0])
        self.assertIs(pp.generate_hardcoded_projection_selectivities, before[1])
        self.assertEqual(pp.generate_hardcoded_projection_selectivities()["A|AB"], 0.0013437)

    # --- exported artefacts --------------------------------------------
    def test_exported_json_is_current(self):
        with open(SCENARIO_JSON, encoding="utf-8") as f:
            sc = json.load(f)
        exported = {key(d): d for d in sc["paper_round"]["decision_table"]}
        self.assertEqual(sorted(exported), sorted(self.table))
        for k, d in self.table.items():
            self.assertAlmostEqual(exported[k]["cost"], d["cost"])
            self.assertAlmostEqual(exported[k]["latency"], d["latency"])
        a = sc["paper_round"]["default_alpha"]
        self.assertEqual(sc["config"]["cost_weight"], a)
        seq = fx.sequential_plan(self.pool, a)
        self.assertEqual(sc["strategies"]["sequential"]["decision"],
                         {"node": seq["node"], "scheme": seq["scheme"]})
        anchors = sc["norm_anchors"]
        self.assertEqual((anchors["cost_min"], anchors["cost_max"]),
                         (min(d["cost"] for d in self.pool), max(d["cost"] for d in self.pool)))
        for st in sc["kraken_stages"]:
            self.assertTrue(st["matches_reference"], st["alpha"])


def run_score_one(placement, push_choice):
    r = subprocess.run(
        [sys.executable, os.path.join(EXPORT_DIR, "score_one.py"), "factory", "factory_join",
         json.dumps(placement), json.dumps(push_choice)],
        capture_output=True, text=True, cwd=EXPORT_DIR,
    )
    return r.returncode, json.loads(r.stdout.strip().splitlines()[-1])


class TestFactoryBackend(unittest.TestCase):
    def test_backend_scores_every_cell_like_the_table(self):
        # Not restricted to the paper's two named schemes: the free
        # per-dependency push/pull chips (same component as Reef) let a
        # player force pushing A instead of B too, scored live via the same
        # generic path as Reef.
        table = {key(d): d for d in fx.enumerate_decisions(fx.fresh_simulation())}
        choice = {"all_push": "__all_push__", "push_pull": list(fx.PUSH_PULL_PUSHED),
                  "push_a": list(fx.PUSH_A)}
        for (node, scheme), d in table.items():
            code, out = run_score_one({"SEQ(A, B)": node}, {"SEQ(A, B)": choice[scheme]})
            self.assertEqual(code, 0, out)
            self.assertAlmostEqual(out["cost"], d["cost"], msg=(node, scheme))
            self.assertAlmostEqual(out["latency"], d["latency"], msg=(node, scheme))

    def test_backend_rejects_pulling_everything(self):
        # No pushed tuple anywhere to use as a pull trigger -- rejected
        # outright, not silently scored as some other plan.
        code, out = run_score_one({"SEQ(A, B)": fx.FOG_MERGE}, {"SEQ(A, B)": []})
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)

    def test_backend_rejects_invalid_node_or_dependency(self):
        code, out = run_score_one({"SEQ(A, B)": fx.SRC_A}, {})
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)
        # FOG_A only reaches A -- not a valid execution node either.
        code, out = run_score_one({"SEQ(A, B)": fx.FOG_A}, {})
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)
        # Forcing *every* dependency as a raw group (as opposed to the
        # ALL_PUSH sentinel) hits a separate PrePP bug (see score_one.py) --
        # still rejected, unlike a genuine non-empty proper subset such as
        # ["A"].
        code, out = run_score_one({"SEQ(A, B)": fx.FOG_MERGE}, {"SEQ(A, B)": ["A", "B"]})
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)
        # A dependency this projection doesn't even have.
        code, out = run_score_one({"SEQ(A, B)": fx.FOG_MERGE}, {"SEQ(A, B)": ["C"]})
        self.assertNotEqual(code, 0)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
