# Kraken Demo — Backlog

Internal working list, not a public issue tracker. Functional pieces first —
gamification is a polish pass once the demo actually demonstrates what Kraken
does.

## Functional (current priority)

1. **Extend communication.** The demo only scores the client-side all-push
   estimate today (`window.KRAKEN_BACKEND` is empty in
   [index.html](web/index.html), see `backendConfigured()` in
   [state.ts](web/src/state.ts)). No push-pull backend is wired up, so the
   demo can't show Kraken's actual communication-strategy co-optimization —
   only placement.
2. **Simplify the query representation** for a non-technical audience.
   Currently queries are shown as raw expressions (`SEQ(A, B, C)`), which
   reads as programming syntax rather than "spot the shark alarm."
3. **Let the user choose the network size** — DONE (in progress): 3 topologies
   now export (`small`=8, `medium`=12 — the original hand-built reef,
   unchanged — `large`=24 nodes), same 4 story queries on each, via
   `SimulationMode.SIZED_TOPOLOGY` in
   [simulation_environment.py](../src/simulation_environment.py) +
   subprocess-isolated export in
   [export_scenario.py](export/export_scenario.py) (isolation matters:
   sharing one process leaked RNG state from the sized-random topologies into
   the untouched hardcoded one and shifted its numbers). Frontend selector
   still to build.
4. **Test the visualization at different network sizes** — in progress via
   the above; still need to check the reef layout at 24 nodes / 5 layers
   (`ROW_Y` in [reef.ts](web/src/reef.ts) only defines rows 0–3).
5. **Known limitation from #3: small/large collapse to 1 operator per
   query.** The hand-built 12-node reef is a deliberately hand-tuned
   multi-parent DAG with overlapping event placement (see
   `create_hardcoded_tree` in
   [simulation_environment.py:715](../src/simulation_environment.py:715)) —
   that's *why* combigen finds shared sub-results worth materializing there.
   Randomly generated topologies of other sizes almost never do (tried ~120
   seed/parameter combinations — node_event_ratio, max_parents, event_skew —
   virtually all collapse every query to a single placeable operator, since
   `get_best_chain_combis`/`return_partitioning` in
   [combigen.py:290](../src/simulator/combigen.py:290) make the
   split/materialize decision from real distances + rates, and random trees
   rarely produce the kind of overlapping-producer structure that makes it
   worthwhile). Getting a good 2–5-operator ramp at other sizes needs the same
   kind of hand-curated topology design that produced the 12-node reef, not a
   quick parameter tweak — worth a dedicated pass, not a side task.

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
