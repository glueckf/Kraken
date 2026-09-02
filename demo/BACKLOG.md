# Kraken Demo — Backlog

Internal working list, not a public issue tracker. Functional pieces first —
gamification is a polish pass once the demo actually demonstrates what Kraken
does.

## Functional (current priority)

1. **Extend communication** — DONE: a local push-pull scoring backend
   ([backend/server.py](backend/server.py)) reuses Kraken's own
   `CostCalculator`/`PlacementProblem` ([cost_calculator.py](../src/kraken/components/cost_calculator.py),
   [problem.py](../src/kraken/problem.py)) to pick the cheapest push/push-pull
   strategy per operator for whatever placement the user chose — the same
   model "Sequential" already uses for INEv's placement, generalized to any
   placement. Each request scores in its own subprocess
   ([export/score_one.py](export/score_one.py)), for the same RNG-isolation
   reason export_scenario.py isolates its own exports. `window.KRAKEN_BACKEND`
   in [index.html](web/index.html) points at it for local dev; not deployed
   anywhere yet.
2. **Simplify the query representation** for a non-technical audience.
   Currently queries are shown as raw expressions (`SEQ(A, B, C)`), which
   reads as programming syntax rather than "spot the shark alarm."
3. **Let the user choose the network size** — DONE: 2 topologies export
   (`medium`=12 — the original hand-built reef, unchanged — `large`=24
   nodes), same 4 story queries on each, via `SimulationMode.SIZED_TOPOLOGY`
   in [simulation_environment.py](../src/simulation_environment.py) +
   subprocess-isolated export in
   [export_scenario.py](export/export_scenario.py) (isolation matters:
   sharing one process leaked RNG state from the sized-random topology into
   the untouched hardcoded one and shifted its numbers). Frontend has a
   topology selector alongside the query picker (`renderTopologyBar` in
   [panel.ts](web/src/panel.ts)); switching topology keeps the same query
   selected when it exists there. (A third, 8-node "small" topology was
   tried and dropped — not worth the extra scenario set for this pass.)
4. **Test the visualization at different network sizes** — DONE for
   12 vs. 24 nodes: the reef layout now spaces rows evenly across however
   many layers a topology actually has (`computeLayout` in
   [reef.ts](web/src/reef.ts)) instead of a fixed 4-row table, so large's
   5 layers no longer overflow the canvas. Found and fixed a real bug along
   the way: the layout cache was keyed by `scenario_id`, which isn't unique
   across topologies (every size has its own "seq_abc"), and a race where
   `loadScenario`'s loading-state emit fired with `topologyId` already
   switched but `state.scenario` still the old data — now keyed by the
   scenario object's identity instead of a derived string.
5. **Known limitation from #3: large collapses to 1 operator per query.**
   The hand-built 12-node reef is a deliberately hand-tuned multi-parent DAG
   with overlapping event placement (see `create_hardcoded_tree` in
   [simulation_environment.py:715](../src/simulation_environment.py:715)) —
   that's *why* combigen finds shared sub-results worth materializing there.
   Randomly generated topologies almost never do (tried ~120 seed/parameter
   combinations — node_event_ratio, max_parents, event_skew — virtually all
   collapse every query to a single placeable operator, since
   `get_best_chain_combis`/`return_partitioning` in
   [combigen.py:290](../src/simulator/combigen.py:290) make the
   split/materialize decision from real distances + rates, and random trees
   rarely produce the kind of overlapping-producer structure that makes it
   worthwhile). Getting a good 2–5-operator ramp at other sizes needs the
   same kind of hand-curated topology design that produced the 12-node reef,
   not a quick parameter tweak — worth a dedicated pass, not a side task.

## Gamification (later — once the above works)

- Weave the "Hai-Alarm" fairy-tale framing into the actual UI copy (query
  picker, task description, info modal), not just the spoken talk — e.g.
  frame query selection as "which alarm are you hunting" rather than an
  abstract `SEQ(...)` expression.
- Add a tangible reward moment (short animation/sound) for beating Kraken —
  a bare score delta (0.342 vs 0.298) doesn't land emotionally for a lay
  audience.
- Open question: accessibility for a diverse audience — German vs English UI
  copy, colorblind-safe palette check, mobile usability for a slam/QR-code
  crowd.
