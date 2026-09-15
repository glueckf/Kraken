# Known Issues

Lightweight tracker for issues that don't have a home elsewhere (GitHub
Issues is disabled on this repo). One entry per issue, newest first.

---

## Kraken's own reported push-pull cost is sometimes higher than the identical plan actually costs — confirmed via direct reproduction, not yet fixed

**Status:** confirmed and precisely isolated 2026-09-16, root cause narrowed
to a specific function, not yet fixed (needs careful reconciliation of two
cost formulas across a non-trivial combinatorial search — bigger than a
one-line patch, see "Why this is deeper than a quick fix" below).

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

### Root cause, as far as traced

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

Not yet traced: which of the two formulas is "correct" (matches the
system's intended cost semantics), or whether `determine_exact_push_pull_plan`
also fails to *enumerate* the winning plan at all (a completeness gap) vs.
enumerating it but mis-costing it during search (a formula gap only).

### Why this is deeper than a quick fix

Two non-trivial, independent cost functions
(`determine_costs_of_push_pull_plan` vs.
`determine_costs_for_pull_request`/`determine_costs_for_pull_response`)
would need to be reconciled — either by making the search rank candidates
using the same formula that reports the final number, or by understanding
why they were built to differ in the first place (there may be a reason
that isn't obvious from a first read, e.g. one accounts for something the
other deliberately omits during search for performance). This needs
careful, dedicated attention, not a rushed patch — and touches the same
exact-plan search several other call sites rely on
(`operator_placement.py`'s INEv path, PrePP's own baseline), so a fix here
should be re-verified against those too, not just the demo's Kraken path.

### Impact

- Every "Reveal Kraken's plan" comparison in the demo where the player
  replicates Kraken's plan by hand is potentially affected — the player's
  identical replication can legitimately show a better score than Kraken's
  own row, which reads (incorrectly) like the player outsmarted the
  algorithm, when actually it's the same decision costed two different
  ways.
- This is upstream of the demo entirely — it's a correctness question
  about the shared push-pull cost model itself, so it also affects
  Kraken's own *placement choices* (its search ranks candidate
  placements using these same reported costs) and INEv's baseline, not
  just what the demo displays.
