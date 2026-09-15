# Known Issues

Lightweight tracker for issues that don't have a home elsewhere (GitHub
Issues is disabled on this repo). One entry per issue, newest first.

---

## Kraken's own reported push-pull cost is sometimes higher than the identical plan actually costs — fixed

**Status:** fixed 2026-09-15 in `src/prepp/prepp.py`
(`determine_randomized_distribution_push_pull_costs`). The root cause was
narrower than first suspected — see "Root cause, corrected" below, which
supersedes the "two cost formulas disagree" hypothesis this entry originally
described.

### Summary

Reported by the user as "I have exactly Kraken's plan but get a better
ranking." Verified this is real, not user error or an artifact of the
search heuristic being merely *imperfect* (which would be expected and
fine): for the **identical** node placement and the **identical** logical
push/pull split (same events pushed, same events pulled), asking the
engine to *cost that exact split* gives a **different, lower** number than
what Kraken's own unforced search reported when it *discovered* that same
split on its own.

### Reproduction

Scenario: medium topology, `SEQ(A, B, C, D, E)` (medium/`seq_abcde`),
`cost_weight=0.6`. `SEQ(B, D)` already placed at node 1 (all-push, cost
1226.0, matches independently). Then, for `SEQ(A, B, C)` at node 1:

```python
# Kraken's own unforced search (exactly what expand() calls):
problem.cost_calculator.calculate(seqabc, 1, s_current, forced_push_group=None)
# -> push_pull cost = 164.16551315609036

# The identical logical split (push B, pull A and C), forced explicitly
# instead of discovered by the free search:
problem.cost_calculator.calculate(seqabc, 1, s_current, forced_push_group=["B"])
# -> push_pull cost = 48.428819977230134
```

Same operator, same node, same `s_current`, same resulting push/pull
assignment (B pushed, A and C pulled) — **164.17 vs. 48.43**. This is
exactly the number a player sees when they replicate Kraken's revealed
plan by hand via the push/pull chips (which go through `forced_push_group`,
see item #18 in `demo/BACKLOG.md`): the player's identical choice is
costed via the cheaper, correct-for-that-split path, while Kraken's own
displayed number for the same decision came from the other, more expensive
path — so the player's "copy" of Kraken's plan legitimately outscores
Kraken's own reported number, even though nothing about the actual
placement or communication strategy differs.

### Root cause, corrected

The initial trace (below, kept for the record) suspected a fundamental
disagreement between two independent cost formulas. Further isolation
disproved that: `determine_costs_for_projection_on_node` (the function that
actually produces the reported number, via
`determine_costs_for_pull_request`/`determine_costs_for_pull_response`) is
internally *consistent* — given the same plan shape, it costs it the same
way regardless of whether that plan came from the forced or free branch.
Traced with a monkeypatch on `determine_costs_for_projection_on_node`
itself: for the reproduction above, it returns 330.06 for the forced
branch's 2-step joint plan `[["B"], ["A","C"]]` and 168.17 for a 3-step
progressive plan `[["B"], ["A"], ["C"]]` — correctly ranking the joint
shape as worse, using one single formula throughout.

So the actual bug was structural, not a formula disagreement:
`src/prepp/prepp.py`'s `determine_randomized_distribution_push_pull_costs`,
in the **forced** branch (`forced_push_group` given), built the plan
directly as `[forced_group, rest]` — lumping every remaining dependency
into *one* joint pull step. The **free** branch
(`forced_push_group=None`) never produces that shape: it calls
`push_pull_plan_generator.determine_exact_push_pull_plan`
(`src/prepp/push_pull_plan_generator.py:1104`), which enumerates candidate
plans via `weak_ordered_plans_generator` and ranks them with
`determine_costs_of_push_pull_plan` — and that ranking formula already
recognizes the joint-group shape as worse than pulling the rest
progressively (one event at a time, each filtered by everything received
so far), so the free search never picks it. The forced branch's naive
`[forced_group, rest]` construction was the *only* place in the whole
push-pull engine that ever produced this cheaper-but-wrong-shaped plan —
confirmed via a repo-wide grep that `demo/export/score_one.py` is the only
caller anywhere that ever sets `forced_push_group` to a non-`None` value,
so Kraken's own real search (`GreedySearch`/`PlacementProblem.expand()`)
was never affected by this, only the demo's "cost the player's exact
choice" path.

**Fix** (`src/prepp/prepp.py`, in the `forced_group is not None` branch):
instead of building `[forced_group, rest]` directly, decompose `rest` into
individual singleton steps and search permutations of their order (bounded
to `len(rest) <= 6`, falling back to the old naive shape above that
ceiling — 6! = 720 is still cheap, and no demo query comes close to that
many remaining deps), ranking each ordering with the same
`determine_costs_of_push_pull_plan` formula the free search uses,
restricted to plans starting with `forced_group`. This exactly reproduces
what the free search would find if forced to start with that specific push
choice. Verified to give an exact match (to full floating-point precision)
between forcing Kraken's own discovered choice and Kraken's own reported
number, across multiple scenarios (a single operator in isolation, and a
full multi-operator plan replication). Also re-exported all 8 demo
scenarios (2 topologies × 4 queries) and confirmed byte-identical output —
this fix only touches the forced/demo-only path, so Kraken's own numbers
are unaffected, as expected.

### Root cause, as first traced (superseded by the corrected section above)

`src/prepp/prepp.py`'s `determine_randomized_distribution_push_pull_costs`
has two distinct branches for algorithm `"e"`:

- **Forced** (`forced_push_group` given): builds the plan directly as
  `[forced_group, rest]` — exactly 2 acquisition steps — and costs it via
  `determine_costs_for_projection_on_node` →
  `determine_costs_for_pull_request` / `determine_costs_for_pull_response`.
- **Free** (`forced_push_group=None`): calls
  `push_pull_plan_generator.determine_exact_push_pull_plan`
  (`src/prepp/push_pull_plan_generator.py:1104`), which enumerates
  candidate plans via `weak_ordered_plans_generator` and ranks them using a
  **different cost function**, `determine_costs_of_push_pull_plan` — not
  `determine_costs_for_pull_request`/`determine_costs_for_pull_response`.
  Only *after* picking a "best" plan under that first formula does the
  caller (`_process_prepp_output` in `cost_calculator.py`) cost it again
  for the *reported* number — via the same
  `determine_costs_for_projection_on_node` path the forced branch uses.

So the free search optimizes against one cost formula
(`determine_costs_of_push_pull_plan`) but reports a number computed by a
*different* formula. If the two formulas don't agree on which plan is
cheapest — which they evidently don't, at least in the reproduction above
— the "exact" search can settle on a plan that is *not* actually the
cheapest under the formula used for the number the player and Kraken both
see. A plan that's structurally identical to the split found here
(`[["B"], ["A","C"]]`) was not what the free search's chosen best plan
costed out to be under the reporting formula, even though forcing that
exact split directly gives a strictly lower number — i.e. the "exact"
search is missing (or mis-costing) a plan that's demonstrably better under
the formula that actually matters.

This part of the trace was accurate as far as it went (the two functions
really are different formulas), but the conclusion — that they disagree on
ranking and that's the bug — was wrong. Both formulas agree the joint
shape is worse; the bug was that the forced branch was the only code path
that ever constructed the joint shape in the first place.

### Impact

- Was: every "Reveal Kraken's plan" comparison in the demo where the
  player replicates Kraken's plan by hand could show a better score than
  Kraken's own row, which read (incorrectly) like the player outsmarted
  the algorithm, when actually it was the same decision costed via a
  worse-shaped (but not worse-formula) plan. Fixed — replicating Kraken's
  plan now reproduces Kraken's own number exactly.
- Confirmed demo-only: `forced_push_group` is never set to a non-`None`
  value anywhere except `demo/export/score_one.py`, so this never affected
  Kraken's own placement search, INEv's baseline, or PrePP's own baseline —
  even though the defective code lived in the shared `src/prepp/prepp.py`.
