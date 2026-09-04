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
   Also DONE: the player can now make the push/pull call themselves instead
   of it always being auto-optimized — a chip row per multi-dependency
   operator (`renderPushPullRow` in [panel.ts](web/src/panel.ts)) lets them
   pick which dependency gets pushed (rate shown per chip so the choice is
   informed), or leave it to the optimizer; **mandatory**, not optional —
   `state.readyToScore` blocks scoring until every such operator has a call
   (caught via testing: it was easy to silently skip). Chips are built from
   `proj.deps` (one level, respecting whatever an earlier operator already
   decided), not the fully flattened primitives — also caught via testing,
   the flattened version re-offered already-bundled primitives as if they
   were still independently decidable. Required a small additive change to
   `prepp.py`/`cost_calculator.py` (`forced_push_group`, default `None` —
   re-exported all 8 scenarios and diffed against committed JSON to confirm
   zero behavior change when unused) to cost the player's *specific* choice
   rather than always the cheapest one, so a bad call actually costs what it
   costs (verified: pushing the wrong/high-rate stream costs ~150x more,
   roughly all-push) instead of silently being corrected.
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

## Visual, from Science Slam audience feedback (2026-09-04)

Talk audience reaction to the current look was lukewarm — reference art from
the talk itself (Kraken-as-cartographer, King Cloud's island, watchtowers,
seahorse messengers, icon badges per query) sets a clearer bar than what's
in the demo now. Two concrete asks:

6. **Text is often too small** (general CSS legibility pass — query titles,
   tray operator names, chip labels) — and **replace the raw event letters
   inside query expressions/operator names with icons** (e.g. `SEQ(A, B, C)`
   → icon-for-A, icon-for-B, icon-for-C), not just the reef's leaf-node
   labels, which already use `eventIconSvg`/`glyphFor` from
   [icons.ts](web/src/icons.ts). Complexity: moderate — titles are always
   `OP(letter, letter, ...)` shaped, so a regex splitting out single
   `[A-F]` tokens (won't false-match "SEQ"/"AND") and swapping each for an
   inline icon is enough; needs applying everywhere a title/operator name
   renders (`renderQueryBar`, tray rows, tooltips) in
   [panel.ts](web/src/panel.ts). Font-size bump is a pure CSS tweak, separate
   and much smaller.
   Free bonus noticed while checking: `ManifestEntry.emblem`
   (crab/turtle/shark/seedling — the exact icon set in the reference art) is
   already exported per query and typed in [types.ts](web/src/types.ts), but
   never rendered anywhere — showing it as a badge on the query cards would
   match the reference look with near-zero new plumbing.
7. **Fog nodes read as "a bomb"** — the current watchtower (a plain circle
   with 3 crenellation notches + a flag, see `towerToppers` in
   [reef.ts](web/src/reef.ts)) doesn't read as a tower at all from a
   distance, just a ball with a fuse. Reference art shows a proper narrow
   vertical tower silhouette (tapered/rectangular body, pointed or domed
   roof, a window/lantern glow, flag on top) and circular icon badges for
   message types linked by distinctly colored dotted paths. Complexity:
   moderate-to-substantial — needs new SVG path geometry (not just
   decorating the existing circle), has to still read clearly at small
   sizes across both topology sizes, and is inherently iterative/creative
   (expect a few passes to land the actual "not a bomb" look), unlike the
   icon-swap above which is mechanical once decided.

## Engine (research code, not demo) — flagged, not scoped

8. **Enable Kraken's multi-node ("MS") placement.** Currently explicitly
   left out of the integrated search — per the TODOs in the algorithm:
   `# ComputeMSPlacement` / `# TODO: Currently leave out MS placement for
   integrated approach, as it is not yet implemented` /
   `partType,_,_ = returnPartitioning(self, projection, unfolded[projection],
   projrates, criticalMSTypes)` (commented out). INEv's separate placement
   already uses this partitioning (`return_partitioning`/`get_savings` in
   [combigen.py:290](../src/simulator/combigen.py:290)); Kraken's own joint
   search doesn't yet consider it. This is a real algorithmic gap in the
   core research contribution, not a demo-polish item — needs its own
   scoping pass (where exactly in `kraken/problem.py`'s `expand()` /
   `CostCalculator` this would plug in, what "multi-node" changes about a
   `PlacementInfo`/`SolutionCandidate`) before estimating effort. Not
   touched today.
