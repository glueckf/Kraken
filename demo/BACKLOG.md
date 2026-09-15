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
   **Correction (2026-09-08, see item #10):** that verification only ever
   exercised pushing a raw primitive — pushing an already-placed sub-query
   dependency was silently a no-op (always scored as the optimizer's own
   pick, regardless of the player's actual choice) from when this shipped
   until it was found and fixed today.
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

   **Investigated (2026-09-10), ruled out as the cause — but a real bug
   found anyway.** Suspected the same "already-summed rate × producer
   count" overcounting bug found 3x last week (item #11) might also be in
   combigen's own decompose/don't-decompose decision, which would mean
   large topology's "never worth decomposing" conclusion was itself an
   artifact rather than a real property of random topologies. Found the
   *exact* pattern (`rates[event] * len(nodes[event])`, where
   `rates[event]` is already the summed total across every producer) in
   **6 places**, not 3: `total_rate()`
   ([projections.py:416](../src/simulator/projections.py:416)) plus two
   near-duplicate `optimistic_total_rate`/`optimistic_total_rate_single`
   functions in both
   [projections.py](../src/simulator/projections.py) and
   [combigen.py](../src/simulator/combigen.py) — and confirmed `total_rate()`
   is exactly the function `new_is_partitioning()`
   ([projections.py:253](../src/simulator/projections.py:253), the actual
   accept/reject gate `get_best_chain_combis` calls per-candidate) uses on
   the "cost of not partitioning" side of its decision inequality.
   Tested directly rather than reasoning about it: patched all 6 occurrences
   locally (removed the `* len(nodes[...])`), re-ran combigen on the exact
   large/24-node/seq_abcd case that currently collapses to 1 operator —
   confirmed via a trace print that the patched code path really did run
   (16 calls) — and got the **same result**, still 1 operator, no
   decomposition. Patch was local/uncommitted and has been fully reverted
   (`git status` clean). So: this bug is real and independently confirmed,
   but it is **not** why large topology never decomposes — `new_is_partitioning`'s
   comparison also involves Steiner-tree edge counts and the network's
   longest-path distance (`minimum_subgraph`/`fill_my_dist_matrice` in
   [projections.py](../src/simulator/projections.py)), and those structural
   terms are what's actually driving the "not worth it" outcome for random
   topologies, independent of the rate bug.

   **Follow-up, same day — this is *not* INEv-scoped, and it's bigger than
   "an edge case."** `self.h_mycombi` (the decomposition — which
   sub-queries exist as operators at all) is computed **once** in
   `Simulation.setup()`, shared by all five strategies including Kraken;
   none of them recompute it. Re-ran the same patch-and-compare test on the
   *medium* topology (the demo's actual working 12-node reef, not the
   already-ruled-out large one) across all 4 story queries: the
   decomposition changes on **3 of 4** — `seq_abc` collapses from 2
   operators to 1, `seq_abcd`/`seq_abcde` get entirely different
   intermediate sub-queries (e.g. `SEQ(A, B, D)` replaced by
   `SEQ(B, D)` + `SEQ(A, B, C)`), `and_nested` keeps 5 operators but a
   different set of them. Since Kraken runs on top of whatever `h_mycombi`
   decided, fixing this bug would change Kraken's own placement choices and
   numbers on the demo's primary topology — not just INEv's. Grepped
   `src/kraken/` directly to confirm Kraken never calls any of the 6 buggy
   functions itself (no hits) — it's a shared-upstream-dependency problem,
   not a direct one.

   Wrote this up as a full GitHub issue (title, root cause, all 6
   locations, the empirical before/after tables for both topologies,
   suggested fix) and handed it to the user as text to file themselves —
   `gh` isn't installed in this environment and installing it / hunting for
   credentials wasn't asked for. Scoped as engine work (moved to the
   "Engine (research code, not demo)" section in spirit — this is a
   correctness issue in the shared algorithm, not something the demo layer
   can work around), not something to fix casually inside a demo session.

   **Merged and re-exported (2026-09-15).** The fix landed as
   [glueckf/Kraken#7](https://github.com/glueckf/Kraken/pull/7), merged into
   `master`. Merged `master` into `feat/demo` (clean, no conflicts — this
   branch had never touched `projections.py`/`combigen.py` itself) and
   re-ran `demo/export/export_scenario.py` for all 8 scenarios; the
   exporter's own all-push cross-check against the engine passed with zero
   mismatches. The medium topology's decomposition changed exactly as
   predicted above:

   | query | before | after |
   |---|---|---|
   | `seq_abc` | `SEQ(A, B)`, `SEQ(A, B, C)` (2 ops) | `SEQ(A, B, C)` (1 op) |
   | `seq_abcd` | `SEQ(A, B)`, `SEQ(A, B, D)`, `SEQ(A, B, C, D)` (3 ops) | `SEQ(B, D)`, `SEQ(A, B, C)`, `SEQ(A, B, C, D)` (3 ops) |
   | `seq_abcde` | `SEQ(A, B)`, `SEQ(A, B, D)`, `SEQ(A, B, E)`, `SEQ(A, B, C, D, E)` (4 ops) | `SEQ(B, D)`, `SEQ(A, B, C)`, `SEQ(A, B, C, D, E)` (3 ops) |
   | `and_nested` | `AND(SEQ(A, B), F)`, `AND(SEQ(A, B, C), F)`, `AND(SEQ(A, B), D, F)`, `AND(SEQ(A, B), SEQ(E, F))`, `AND(SEQ(A, B, C), D, SEQ(E, F))` (5 ops) | `AND(SEQ(A, B), F)`, `AND(SEQ(A, B), SEQ(E, F))`, `AND(SEQ(A, B, C), F)`, `AND(SEQ(A, B, C), D, F)`, `AND(SEQ(A, B, C), D, SEQ(E, F))` (5 ops, different set) |

   Large topology's scenarios were untouched by the re-export (byte-for-byte,
   `git status` shows nothing changed there), confirming the earlier "large
   is unaffected" finding held after the real merge, not just the local
   patch test.

   Caught (and fixed) a self-inflicted verification gap along the way: after
   re-exporting, an initial live-UI check against the dev server still
   showed the *old* 2-operator `seq_abc` — turned out `demo/web/serve.mjs`
   serves from `dist/`, and `demo/web/build.mjs` copies `scenarios/` into
   `dist/` at build time, so a re-export alone doesn't reach the running
   server until `npm run build` runs again. Re-built and re-verified: fresh
   `fetch(..., {cache: "no-store"})` confirmed the new JSON was being
   served, then drove the real UI end-to-end for `seq_abc` (1 op, placed,
   scored — Kraken cost 6.39k, matching the export log exactly) and
   `and_nested` (5 ops, all auto-cascaded to König Cloud correctly with the
   new dependency graph, Kraken cost 2.42k matching the export log, reveal
   overlay still rendered 26 edges with the legend intact). No console
   errors either time.

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

6. **Text is often too small, and query expressions read as raw
   programming syntax** — DONE: bumped font sizes across the reef labels,
   query bar, tray, push/pull chips, and scorecard/leaderboard (smallest
   text was 9-10.5px before); `titleWithIcons()` in
   [panel.ts](web/src/panel.ts) swaps each standalone event letter (A-F) in
   query titles/operator names for its icon via a `\b`-bounded regex (leaves
   "SEQ"/"AND" untouched), reusing `eventIconSvg` from
   [icons.ts](web/src/icons.ts) — the reef's leaf nodes already used these
   same glyphs. Query cards now also show their `emblem`
   (crab/turtle/shark/seedling, as emoji) — that field was already exported
   and typed but never rendered anywhere. Had to trim padding/gaps in
   several places afterward to offset the extra height from bigger text —
   the panel scrolls internally when it doesn't fit, but the simplest query
   started overflowing by >100px before the trim, which wasn't true before
   the font bump.
7. **Fog nodes read as "a bomb"** — DONE: after 3 self-critiqued SVG-geometry
   passes (tapered body/roof/window/flag, see git history on
   [reef.ts](web/src/reef.ts)) still didn't feel close enough to the talk's
   own reference art, fog nodes now render the actual reference illustration
   (`/home/aziehn/Dokumente/PhD/ScienceSlam/Icons/tower_2.png`, the
   already-transparent one of the two tower renders provided) as an SVG
   `<image>` (`towerShape` in [reef.ts](web/src/reef.ts)), cropped to its
   opaque bounds and downsized to `demo/web/assets/tower.png` (431×480,
   alpha preserved — checked corner-pixel alpha is 0, not white-baked-in).
   Node's own `.node-dot` circle stays underneath it. `build.mjs` now
   copies `web/assets/` into `dist/`, and `serve.mjs`'s MIME map got
   `.png`/`.jpg` entries (previously only html/js/css/json/wasm/svg were
   mapped — png would've fallen through to `application/octet-stream`,
   which some browsers still render fine as `<img>`/`<image>` but isn't
   correct); the asset is excluded from the root `.gitignore`'s blanket
   `*.png` rule via `git add -f` (that rule is meant for research-output
   plots, not shipped app assets).
9. **King Cloud island + tower placement, follow-up (2026-09-04)** — DONE:
   the hand-drawn island/castle/pool/palm/crown SVG group (`islandPath`,
   `castleGroup`, `poolAndPalm`, `crownGroup` — all removed) is replaced the
   same way item 7 replaced the tower: the cloud node now renders
   `kingcloud_2.png` (the transparent one of the two king-cloud renders,
   cropped to opaque bounds → `demo/web/assets/kingcloud.png`, 640×606) as
   an `<image>` (`cloudImageBox` in [reef.ts](web/src/reef.ts)); the
   "König Cloud" label moved to just below the image instead of overlaid
   on it (the full scene is too busy to write over legibly). Towers also
   nudged down slightly (`bottomY` in `towerShape` moved from `cy + r*0.55`
   to `cy + r*0.85`) per request to sit closer to the source-node row
   below — re-verified no row-to-row overlap on `large` (24 nodes) after
   the shift (still a 20px+ gap on both sides). Also fixed a regression
   from item 7: the tower/cloud `<image>` elements had `pointer-events:
   none` (so only the small foundation dot was actually clickable — before
   the image swap, the *entire* hand-drawn SVG tower shape was part of the
   clickable `<g>`, so this had shrunk the hit area without anyone asking
   for that); removed the rule so the images themselves are click-targets
   again, confirmed via `getScreenCTM`-based coordinate mapping +
   `elementFromPoint` that a click on the tower artwork (not just the dot)
   now resolves to the right `data-node`. The remaining reference images
   (`correls.png`, `correls_2.png`) are still full multi-subject scenes,
   not pre-cropped icons — revisit if a use for them comes up.
13. **Reef letterboxing + selector control sizing (2026-09-09)** — DONE:
    `.reef-wrap` was stretching to the grid row's full height regardless of
    width, so on most real window shapes (including this repo's own dev
    viewport) its box ended up far taller/narrower than the SVG's own
    viewBox (1000×640, a landscape ratio) — `preserveAspectRatio` then
    letterboxed the actual drawing down to fit, wasting up to ~65% of the
    box as empty bars. Gave `.reef-wrap` that same `aspect-ratio` directly
    (`align-self: center` so the grid stops force-stretching it) — the SVG
    now fills its box edge to edge with zero internal waste, verified by
    comparing rendered box dimensions to the SVG's own bounding rect at
    1440px, 1024px, and 700px wide (exact 1.5625 aspect ratio, no overflow
    at any width). Also enlarged the `.tcard`/`.qpill` (topology + query
    selector) padding and font sizes, per direct request that they read
    too small/cramped.
    **Follow-up — DONE (2026-09-10)**: the panel's fixed 352px cap is now
    `minmax(280px, min(640px, 32vw))` — scales with viewport (32vw) between
    a 280px floor and a 640px ceiling, instead of a single fixed value.
    (First landed at a 480px/30vw cap; the user's own screen — a wide
    external monitor — still showed the panel visibly narrow relative to
    the reef, so raised to 640px/32vw the same session.) Checked whether
    the panel's children actually benefit from more width or would just
    look sparse: every child already uses flexible sizing (`flex: 1`,
    `minmax(0, 1fr)` — `.lb-row`'s grid, `.tray-row`, tiles, the alpha
    slider), so widening the container just gives the leaderboard bars and
    text more room rather than leaving awkward gaps — confirmed by placing
    a full scenario and scanning for `scrollWidth > clientWidth` overflow
    at 2560px (none found). Verified panel width resolves to 640px (capped)
    at 2560px viewport and ~614px at 1920px (32vw, just shy of the cap —
    reasonable, since 1920px is not the "wide external monitor" case this
    was raised for), and still respects the 280px floor on small windows.
    The narrow-screen
    override (`@media max-width: 720px`) was left untouched — a different,
    mobile-usability concern, not today's ask.

## Push-pull feature (2026-09-04 → 2026-09-08)

10. **"All-push is valid right now — you have to force one push/pull [choice]."**
    Clarified (2026-09-08): the complaint was about the mandatory-choice hint
    itself — "Still need a push/pull call for SEQ(A, B), SEQ(A, B, D),
    SEQ(A, B, C, D)" kept firing even though all-push is a legitimate
    strategy, because the chip UI only ever let you pick *one specific*
    dependency to push (implicitly pulling the rest) — there was no way to
    explicitly say "push everything" and have that count as a made
    decision. DONE: added `ALL_PUSH` (`"__all_push__"`, [state.ts](web/src/state.ts))
    as a real, selectable third option — a `push all` chip alongside the
    per-dependency ones in `renderPushPullRow` ([panel.ts](web/src/panel.ts)),
    same mandatory toggle mechanics as the existing chips (`setPushChoice`
    needed no changes, it's generic on the string value). When active,
    every per-dependency chip in that row also displays as `PUSH` (true to
    what's actually happening — nothing is pulled), verified via DOM
    inspection.

    **Also found and fixed a real, previously-shipped correctness bug while
    building this** (i.e. item #1's "communication extend," marked DONE
    2026-09-04, was silently broken for one whole class of input since it
    shipped): a player's push/pull choice was only ever actually honored
    when they pushed a **raw primitive** (e.g. "A"). Pushing an
    **already-placed sub-query dependency** (e.g. "SEQ(A, B)") looked
    identical in the UI (chip highlighted, hint cleared, a score came back)
    but the choice was silently discarded and the optimizer's own pick was
    scored instead — confirmed by forcing every variation of a sub-query
    dependency's push (flattened leaves `["A","B"]`, a single leaf `["A"]`)
    across 36+ placement combinations and finding the result *always*
    matched the unforced optimum exactly, while forcing a raw primitive
    (`["D"]`) reliably diverged from it every time. Root cause: PrePP's
    `forced_push_group` matching (`old_copy = query.primitive_operators` in
    `determine_randomized_distribution_push_pull_costs`, [prepp.py](../src/prepp/prepp.py))
    operates on the query's **one-level** dependency tokens — a sub-query
    dependency appears there as its own name string ("SEQ(A, B)"), never
    expanded — but `score_one.py` was flattening the player's sub-query
    choice to its leaf primitives (`dep_obj.leafs()`) before passing it,
    which then matches nothing in that one-level list; the intersection
    silently comes back empty and the code falls through to the regular
    search, with no error or signal that the player's choice was ignored.
    Fixed by passing the chosen dependency's own name through unflattened
    (`forced_push_group=[chosen_dep]`) — re-verified clean (0/20 failures)
    across a systematic placement scan that a forced sub-query choice now
    reliably diverges from the optimizer's own pick exactly like a forced
    primitive choice does. Docstrings on `forced_push_group`
    ([prepp.py](../src/prepp/prepp.py),
    [cost_calculator.py](../src/kraken/components/cost_calculator.py)) were
    themselves wrong in the same way (described flattening as correct) —
    corrected, since that's very likely *why* the original bug happened.

    A **second, separate bug** turned up chasing this: forcing every one of
    a query's dependencies into a *single* group (i.e. "push everything,
    nothing left to pull" — needed for the `push all` chip above) doesn't
    reproduce the true all-push cost either — off by a division-like factor
    in several tested placements (e.g. 609.0 instead of the correct 1827.0).
    Not root-caused (looks like a bug in how PrePP turns a single-group,
    no-`rest` plan into acquisition steps, downstream of the fix above) —
    worked around rather than fixed: `push all` in `score_one.py` doesn't
    go through `forced_push_group` at all, it directly uses
    `cost_calculator.calculate(..., forced_push_group=None)`'s first entry
    (`_compute_all_push_costs`'s result, always present, unaffected by any
    forced-group path) — reliable by construction, verified against known
    all-push numbers. If a real forced-single-group use case ever comes up,
    this second bug still needs a proper root-cause pass.

    Re-investigated the earlier "identical cost regardless of which
    dependency is forced" finding from the first pass at this item in light
    of the above — that specific case (both dependencies co-located at the
    same node, distance 0 either way) is still a genuine coincidence and
    not an instance of either bug, confirmed by re-running it after the fix
    and getting the same result.

    End-to-end tested through the real UI (topology → query → place all
    three operators at König Cloud → force a sub-query dependency's push
    directly, and separately toggle `push all` per operator → mandatory-
    choice hint clears both ways → backend round-trip returns a correctly
    differentiated `push-pull optimised` score), including the toggle-off
    path restoring the pending state.

    **Follow-up — DONE.** `state.ts`'s `rescore()` used to show the
    client's instant all-push `Engine.score()` estimate as the *official*
    score immediately, then silently swap it for the real push-pull number
    once the backend replied (or leave the wrong estimate sitting there
    forever if the backend was unreachable). Demonstrated the actual
    impact live rather than just describing it: for one real placement,
    read the scorecard tile in the same synchronous tick as the triggering
    click (before the backend could possibly have responded) — it showed
    "11.2k" (mode: "optimising communication…"); ~2s later, once the
    backend replied, the *same* tile showed "1.78k" (mode: "push-pull
    optimised") — a ~6x difference, for the identical placement and push
    choices, because the first number ignores every push/pull decision
    the player made and just assumes everything is pushed. Once that
    landed, the fix requested was the "block" option from the original
    two: `rescore()` now sets `official = null` and `scoring = true`
    while a backend request is in flight, instead of populating `official`
    with the estimate first — the scorecard shows a loading state (🐙
    wiggle animation + "Kraken is crunching the numbers…") the whole
    time, only ever showing *one* number once it's the real one. If the
    backend is unreachable (or was never configured), it falls back to
    the estimate rather than hanging forever, now labeled plainly ("all-push
    estimate — no live scoring available") instead of a badge that could
    be mistaken for a neutral status indicator. Removed the now-dead
    `OfficialScore.pending` field (`official` is either null-while-scoring
    or a fully-resolved result — there's no in-between state to track
    anymore) and the matching dead `.mode.pending` CSS rule. Verified all
    three paths live: the loading state (read synchronously, same tick,
    so no race with the backend could have produced it by luck), the
    success transition (correct number + label), and the failure fallback
    (killed the backend mid-session, confirmed it degrades to the labeled
    estimate instead of hanging) — then restarted the backend and
    confirmed the success path still works.
11. **"All-Push" leaderboard baseline was ~2–7x inflated — fixed
    2026-09-09.** Found by the user manually placing every operator of
    SEQ(A,B,C,D) at König Cloud with `push all` chosen throughout and
    getting 11.2k, while the leaderboard's "All-Push" row showed 33.7k for
    the same query — a discrepancy that shouldn't exist, since that's
    literally the placement+strategy the "All-Push" baseline is supposed to
    represent. Root cause, in `compute_all_push()`
    ([simulation_environment.py:302](../src/simulation_environment.py:302),
    demo-only — confirmed **not** used anywhere in Kraken's own algorithm;
    `kraken/run.py`'s one reference only reads the unaffected latency
    field, and only in an opt-in study mode the demo doesn't use): for an
    event type produced at k nodes, the code multiplied the event type's
    *already-summed* total rate (`h_rates_data`) by the distance of
    whichever single producer was closest to the cloud, once *per producer*
    — so the true cost got multiplied by k instead of computed once. E.g.
    verified directly on seq_abcd/medium: event A (3 producers, rate 1000
    each) contributed 27000 instead of the correct 9000 (1000×3 + 1000×3 +
    1000×3, all three producers being distance 3 from the cloud in that
    topology). Fixed by summing each producer's own rate times its own
    distance directly from `h_local_rate_lookup` (the same per-producer
    data `CostCalculator._compute_all_push_costs` already uses correctly)
    instead of re-deriving a "closest producer" search that was never the
    right model for a strategy where every producer independently
    transmits.

    Re-exported all 8 scenarios and diffed old vs. new: **only**
    `strategies.all_push.cost`/`processing_latency` changed anywhere — every
    other baseline (INEv, Sequential, PrePP, Kraken, including Kraken's full
    `per_placement`) is byte-identical, and the Rust goldens are untouched
    (they were always computed via a separate, independently-correct
    `ref_all_push` in `export_scenario.py`, which is *why* `cargo test`
    never caught this — it was never exercising the buggy function).
    `cargo test --release` (3/3 pass, including the sanity check that
    Kraken's score beats every baseline) and a live browser check both
    confirm the fix: placing everything at the cloud with `push all` now
    matches the "All-Push" leaderboard row exactly (11.2k both ways).

    One real, visible side effect worth knowing about: `norm_anchors.cost_max`
    (used to normalize every strategy's 0–1 "score" — `min(costs)`/`max(costs)`
    across all 5 baselines) was **all_push's inflated cost** in all 4
    *medium*-topology scenarios (it was always the worst/highest number
    there), so fixing all_push shrinks that anchor and every other
    strategy's displayed *normalized score* shifts slightly, even though
    every raw cost/latency number is unchanged. It also flips a ranking:
    "All-Push" moves from dead last to *ahead of INEv* in all 4 medium
    scenarios (e.g. seq_abcd: 11244 vs. INEv's unchanged 15897). Large
    topology is unaffected — there, `cost_max` was already anchored by INEv
    (which, for large's single-operator queries — see item #5 — happens to
    equal the old buggy all_push number by coincidence, not by shared code
    path), so nothing shifts there beyond All-Push's own row.
12. **Kraken-plan reveal, improved toward push/pull edges — DONE.** Was:
    `toggleReveal()`/`view.reveal` in [reef.ts](web/src/reef.ts) only drew
    a ghost ring around whichever node Kraken placed each subquery on — it
    showed *where*, not *how it communicates*.

    The per-subquery `strategy` field (`"all_push"`/`"push_pull"`) already
    exported wasn't enough — it doesn't say *which* dependency was pulled
    when a placement is mixed. That detail lives one level deeper, in
    `PlacementInfo.acquisition_steps` (`src/kraken/data/state.py`), which
    `export_scenario.py` discarded before. Traced the actual semantics
    empirically (a written-out reasoning trap: the field named
    `pull_request.events` is *not* the dep being pulled — it's the
    already-received deps used as a semi-join filter; the dep actually
    being acquired in a step is `step.events_to_pull`, and whether that
    acquisition was push or pull is `step.is_push_based`). Verified on a
    real run before writing any frontend code: for `SEQ(A,B)` (medium
    topology, strategy `push_pull`), step 0 acquires B with no pull
    request (pushed), step 1 acquires A with
    `pull_request.events=['B']` (A pulled, using already-received B as a
    filter) — confirmed by cross-reading
    `determine_costs_for_pull_request`'s own docstring in
    [push_pull_plan_generator.py](../src/prepp/push_pull_plan_generator.py):
    `eventtypes_in_pull_request` empty ⇒ push step.

    `export_scenario.py` now builds an `edges: Record<dep, "push"|"pull">`
    per Kraken placement from `events_to_pull`/`is_push_based` across all
    of that placement's `acquisition_steps`, threaded through
    `per_placement` (`types.ts`). `main.ts` passes
    `strategies.kraken.per_placement` as the reveal payload (was just
    `.placement`, bare node ids).

    **Revised after first-pass feedback.** The first version drew a new
    bezier straight from each dependency's source node to the consumer's
    node — a line that often didn't correspond to any real link in the
    topology (e.g. skipping over intermediate fog towers). Feedback: don't
    invent edges, highlight the *existing* ones; and the accent-blue/muted
    grey pairing didn't read as clearly push-vs-pull as it should.
    `reef.ts` now builds an adjacency graph from the same
    `node.parents`/`children` the base topology edges are drawn from, BFS's
    the real hop-by-hop path from each dependency's source to the
    consumer's node (a primitive dep can have several producers —
    `event_map.producers[dep]` — each gets its own path; a subquery dep
    resolves to wherever *its own* reveal entry placed it), and accumulates
    push/pull roles per physical hop. Overlays are drawn only on `d` strings
    that are exact matches (verified) of the base `.edge` paths — solid push
    first, dashed pull on top, so a hop carrying both reads as push showing
    through the pull dashes' gaps rather than needing a third "mixed" style.
    Colors moved off `--accent`/`--ink-soft` to two new dedicated tokens:
    `--push` (aliases `--warm`, the same orange already used for the ghost
    ring — both mark "this is Kraken's own choice") and `--pull` (a fresh
    teal, `#0f9b8e`/`#2dd4bf` light/dark, picked distinct from the `--sea-*`
    backdrop colors so it doesn't blend into the reef). Per-edge text labels
    were dropped (they'd stack illegibly on shared trunk hops near the
    cloud, where most paths converge) in favor of one small
    `push ▬ / pull ┄` legend next to the reveal button, shown only while
    revealed.

    **Revised again — color now identifies the event type, not push/pull.**
    Feedback: even with push/pull legible, it was still unclear *which*
    event type was being pushed or pulled on a given edge — a real gap,
    since a hop can carry several different event types at once (e.g. one
    physical link both pulling `A` for one placement and pushing `B` for
    another). Color now comes from the dependency's own identity — the same
    per-letter glyph colors already used for event pods/chips
    (`glyphFor(dep).color` from [icons.ts](web/src/icons.ts)) for
    primitives, or the subquery's own chip color (`subMeta.get(dep).color`)
    for a subquery dep — set inline per `<path>` rather than via a CSS
    class, since it now varies per dependency instead of just per role.
    Push/pull moved from color to line style alone (solid vs. dashed),
    matching a small `edge color = event type · push / pull` legend. Where
    several event types share one physical hop, each now fans out as its
    own parallel offset stroke (computed via the true perpendicular to that
    hop, ~5px apart) instead of collapsing into one line — confirmed this
    actually happens in practice, not just in theory: the medium reef's
    `n4↔n10` hop carries both `A` (pulled, into `SEQ(A,B)`) and `B` (pushed,
    same placement) simultaneously, and now renders as two adjacent
    differently-colored strokes rather than one merged line. Removed the
    now-unused `--push`/`--pull` CSS tokens (color is no longer role-based).

    Verified end-to-end all three times (not just typecheck): pass 1 drove
    the real UI for medium `seq_abcd`, all 3 operators placed, revealed —
    12 edges, 3 `pull` (A's 3 producers) / 9 `push`, matching the exported
    `SEQ(A,B).edges = {A: pull, B: push}` exactly. Pass 2 (existing-edges
    rework) redrove the same scenario and asserted in the live DOM that
    every rendered `.plan-edge`'s endpoints exactly match an existing
    `.edge`'s endpoints (0 mismatches). Pass 3 (per-event color) redrove it
    again and read the actual `stroke` inline style + `d` of every rendered
    edge: 5 distinct colors present, one per non-colocated dependency (`A`,
    `B`, `C`, `D`, and `SEQ(A,B)`'s own chip color) — the 6th dependency,
    `SEQ(A,B,D)` feeding `SEQ(A,B,C,D)`, correctly produced *no* edge since
    both are placed at the same node (König Cloud), confirming the
    already-colocated skip still holds — and the shared `n4↔n10` hop showed
    up as two separate offset strokes (`A` pull + `B` push) exactly as
    intended. No console errors, `tsc --noEmit` clean all three times. Full
    scenario re-export re-ran the exporter's own all-push cross-check
    (`ref_all_push` vs. the engine) with zero mismatches across all 8
    scenarios, so nothing else moved.
14. **Alpha default + forced-cloud auto-placement — DONE.** Two small,
    unrelated asks from the same session:
    - Default `cost_weight` (the "alpha" slider) changed from 0.5 to 0.6
      ([state.ts](web/src/state.ts)) — 0.6 is the paper's own reported best
      cost/latency balance, and at 0.5 Kraken doesn't clearly beat every
      baseline on medium topology (see item #11's normalization note). The
      exported scenario JSON still bakes in 0.5 as its own fallback, but
      that's harmless: `loadScenario()` always overwrites the engine's
      weight with `state.costWeight` right after construction, so the
      JSON's value is never actually used once the page has loaded.
    - Placing an operator whose sub-query dependency already sits at König
      Cloud (node 0) is now automatic instead of requiring a click.
      Mathematically, node 0 is the *only* valid placement in that case —
      `computeDescendants()` builds each node's reachable set by walking
      *down* through `children`, so node 0 (the tree's root) is nobody's
      descendant but its own; `placementIssue()`'s reachability check can
      therefore only pass at node 0 itself once a dependency is parked
      there. `reconcileForcedCloudPlacements()` in state.ts runs after
      every placement change, auto-placing (and, symmetrically,
      auto-*un*placing on pick-up) anything newly forced, looping to catch
      cascades — placing one operator at the cloud can force the next one,
      which can force the one after that. Each auto-placement records a
      reason (`state.autoPlacedReason`) shown as a small "auto" badge +
      tooltip on the location, plus a one-line note under the row
      ([panel.ts](web/src/panel.ts)) so it doesn't look like the game
      placed something on its own for no reason. Verified end-to-end:
      placing just the first (deepest-dependency) operator of a 3-operator
      query at the cloud correctly cascades both remaining operators there
      automatically with correct per-row reasons; picking the first one
      back up correctly un-places both cascaded ones too; placing at a
      *non*-cloud node correctly does **not** trigger anything.
15. **"Try again" after revealing Kraken's plan should surface a new
    topology — DONE.** Was: `clear()` (`data-action="clear"`) only reset
    placement/push-choice/score for the *same* scenario — after revealing
    the answer, "Try again" just replayed the identical puzzle you'd
    already seen solved. `clear()` in [state.ts](web/src/state.ts) now
    checks whether `this.reveal` was true before resetting; if so, it picks
    a random topology other than the current one from the manifest and
    calls the existing `selectTopology()` (which already keeps the same
    query selected where it exists there, and does its own full reset via
    `loadScenario()`). A plain "Try again" without having revealed is
    untouched — same topology, same query, as before.

    Verified live: drove the real UI for medium `seq_abcd`, confirmed (a) a
    plain place-all → Try again keeps `Reef 12n` selected, and (b)
    place-all → Reveal → Try again jumps to `Grand Reef 24n`. No console
    errors, `tsc --noEmit` clean.
16. **Regression from the combigen merge (item #5): placing the first
    operator of `seq_abcde` froze the tab — DONE, fixed.** Found while
    confirming "the use cases have updated results" after merging PR #7 —
    every case scored correctly *except* medium `seq_abcde`, where placing
    `SEQ(B, D)` (the query's first leaf operator) at König Cloud hung the
    page completely: no console error, no exception, page unresponsive to
    any further input, reproduced identically across two different browser
    tools (one reported a dead renderer, the other a bare CDP
    "Internal error" with nothing catchable by `try/catch` — consistent
    with the JS main thread never yielding back to the event loop, not a
    normal thrown error).

    Bisected with temporary `console.log` instrumentation in
    `placeActiveAt()` (`state.ts`) rather than guessing — logs showed
    execution reaching `reconcileForcedCloudPlacements()` and never
    returning, an infinite loop, not a slow WASM call (confirmed separately
    that `engine.score()` isn't even invoked yet at this point — the query
    isn't `complete` until all 3 operators are placed). Root cause: the
    "undo" half of `reconcileForcedCloudPlacements()`'s fixed-point loop
    used the full `placementIssue()` check, which requires *every* subquery
    dependency to already be placed somewhere — but the "force" half only
    ever required *one* forcing dependency to be at node 0. For
    `SEQ(A, B, C, D, E)` (deps `[E, SEQ(B, D), SEQ(A, B, C)]`), placing
    `SEQ(B, D)` at the cloud force-placed it (one forcing dep present) —
    then the undo check immediately reversed that, because its *other*
    subquery dependency (`SEQ(A, B, C)`, which has no subquery dependency of
    its own and can therefore never auto-force) wasn't placed yet and never
    would be until the player did it manually — then the force check
    immediately re-triggered, forever. `and_nested` has the same
    two-subquery-dependency join shape (e.g. `s5` needs `s2, s4`) but never
    hit this, because by the time its forcing check runs, a single earlier
    pass has already force-cascaded *both* of its subquery deps — the
    oscillation only shows up when one side of a join can never
    auto-resolve. This shape didn't exist in any scenario before today's
    re-export; the combigen fix's revised decomposition is what introduced
    it for `seq_abcde` specifically.

    Fix: the undo check in `state.ts` now re-evaluates the *same* forcing
    predicate used to place it (does this operator still have at least one
    subquery dependency sitting at node 0?), instead of demanding full
    validity of every dependency. Verified: re-tested the exact failing
    click (now cascades `SEQ(B, D)` + `SEQ(A, B, C, D, E)` correctly,
    leaves `SEQ(A, B, C)` for the player, scores 3.51k matching the export
    log), then re-verified `seq_abc`, `seq_abcd`, and `and_nested` all still
    score correctly (6.39k / 1.62k / 2.42k, all matching), plus reveal and
    try-again still work. No console errors, `tsc --noEmit` clean.
17. **Alpha slider replaced with named Kraken stages — DONE.** The raw 0-1
    "cost/latency balance" slider was too abstract for a lay audience.
    Replaced with named buttons.

    **Revised down to 3 stages, non-evenly-spaced (same day).** First pass
    shipped 5 evenly-spaced stages (Fastest/Fast/Balanced/Efficient/Cheapest
    at 0.0/0.25/0.5/0.75/1.0) — simplified further to 3: **Fast** (0.2),
    **Balanced** (0.6 — the paper's own reported best cost/latency balance,
    same value the old continuous slider defaulted to, see item #14),
    **Cheap** (0.9). `KRAKEN_STAGES` in `export_scenario.py` and
    `state.ts`'s default `stageIndex` (now 1, the middle of 3) updated
    accordingly; re-exported all 8 scenarios (2.8s vs. 5.8s for 5 stages —
    3 fresh Kraken runs per scenario instead of 4). Re-verified live for
    medium `seq_abc`: Balanced (0.6) shows Kraken at cost 283 — matching
    exactly what the original 0.05-step sweep recorded at alpha=0.60 — and
    correctly re-ranks the other four baselines for that alpha (Sequential
    ties Kraken at 0.268, both beating All-Push's 0.600). No console errors,
    `tsc --noEmit` clean.

    The subtlety this surfaced: of the 5 strategies, only Kraken's own
    placement actually depends on cost_weight. Checked each of the other
    four directly rather than assuming — `compute_all_push`
    (`simulation_environment.py`) takes no weight parameter at all;
    `compute_single_sink_placement` (INEv, `src/inev/placement_aug.py:827`)
    picks a node by a single scalar `mycosts < costs` comparison, no latency
    term or weight anywhere nearby; `generate_prePP`
    (`src/prepp/prepp.py:928`)'s signature has no such parameter either. So
    for those four, only the *displayed score* needed to react to the chosen
    stage (already true today — `engine.baselines()` re-normalizes their
    fixed (cost, latency) live for whatever `cost_weight` is set). Kraken's
    greedy search, though, explicitly reads `cost_weight`/`latency_weight`
    out of the placement problem's context and uses it to rank candidates
    during `expand()` — so its chosen node per operator, not just its score,
    genuinely changes with alpha.

    Confirmed this before writing any UI: swept Kraken's own greedy search
    in 0.05 steps (21 values, 0.00-1.00) across all 8 scenarios via a
    throwaway script calling `run_kraken_solver` directly (reusing the
    already-set-up `Simulation` object, not re-running the whole pipeline
    each time) — cost/latency step cleanly between a small number of
    plateaus per scenario (e.g. medium `seq_abcd`: 7736/3h for alpha<0.45,
    1622/9h for alpha in [0.45,0.60], 1281/9h for alpha>=0.65), confirming
    5 evenly-spaced stages give real, distinguishable placements without
    needing per-scenario-tuned breakpoints.

    `demo/export/export_scenario.py` now runs Kraken's greedy search once
    more per stage (4 extra runs per scenario — the 0.5/"Balanced" stage
    reuses the already-computed default run) and exports a new
    `kraken_stages` array, each entry the same shape as `strategies.kraken`
    (own `placement`/`per_placement`/`cost`/`latency`) plus `alpha`/`label`.
    `norm_anchors` now spans every stage's cost/latency too, not just the 5
    baseline rows — the Rust normalizer's `norm()` only clamps the low side,
    so an un-anchored high value from a pure-cost or pure-latency stage
    would've displayed as an out-of-range score instead of a merely-good one
    (caught by inspecting the exported anchors before wiring up the
    frontend, not discovered live).

    Frontend: `state.ts` replaced `costWeight: number` with `stageIndex`
    (default 2 = Balanced) and added `effectiveBaselines` — `state.baselines`
    with just the `kraken` entry swapped for the selected stage's own
    (cost, latency) re-normalized via the existing `engine.normalizePoint()`;
    the other four rows pass through untouched. No Rust/WASM changes needed
    at all — `normalizePoint` was already generic over any (cost, latency)
    pair. `panel.ts`'s slider became `renderStagePicker()` (5 buttons);
    `main.ts`'s reveal payload now reads `state.currentStage.per_placement`
    instead of the scenario's single fixed `strategies.kraken.per_placement`.

    Verified live end-to-end, re-export included: re-ran the full exporter
    (all defaults byte-identical to before — 6.39k/1.62k/3.51k/2.42k medium
    Kraken costs unchanged), then drove the real UI for `seq_abc` — default
    (Balanced) shows 6.39k matching the export; switching to Cheapest shows
    258 (matching that stage's export exactly) and correctly re-ranks every
    other baseline's score for alpha=1.0 (All-Push jumps to the worst score,
    as expected for a pure-cost weighting); the reveal overlay's ghost ring
    moves from node 1 (Fastest) to node 0 (Cheapest) — Kraken's real,
    different placement at each stage, not just a re-colored number. Also
    re-checked `and_nested` at its default stage (2.42k, matching). No
    console errors, `tsc --noEmit` clean.

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
