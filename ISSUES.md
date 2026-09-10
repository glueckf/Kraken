# Known Issues

Lightweight tracker for issues that don't have a home elsewhere (GitHub
Issues is disabled on this repo and the reporter doesn't have permission
to enable it). One entry per issue, newest first.

---

## Query decomposition (`combigen`) overcounts primitive rates by producer count — affects all 5 placement strategies, not just INEv

**Status:** PR open, awaiting review. Found and scoped 2026-09-10; fix applied
on branch `az1_fix_combigen_rate_overcounting` (based on `master`), opened as
[glueckf/Kraken#7](https://github.com/glueckf/Kraken/pull/7) with @glueckf
requested as reviewer.

### Summary

`combigen`'s decompose/don't-decompose decision (`new_is_partitioning()` in
`src/simulator/projections.py`, called from `get_best_chain_combis()` in
`src/simulator/combigen.py`) uses a primitive event type's transmission cost
estimate that is inflated by a factor equal to that event type's own
producer count. This is the *same* bug pattern already found and fixed in
three other places this week (`compute_all_push()` in
`simulation_environment.py`, `new_compute_central_costs()` and
`compute_single_sink_placement()` in `src/inev/placement_aug.py` — fixed on
the `feat/demo` branch of the demo worktree, see its `demo/BACKLOG.md`
items #10/#11 for that fix and its verification) — but **five more live
occurrences** (plus a sixth inside already-dead code) of the identical
pattern exist in the query-decomposition step itself, and this one is not
INEv-specific: it changes the operator set
(`h_mycombi`) that **every** strategy — All-Push, INEv, Sequential, PrePP,
and Kraken — is built on top of.

### Root cause

`h_rates_data[event_type]` already holds the *summed* rate across every
node that produces that event type (confirmed directly: for a demo scenario
where `A` is produced at 3 nodes at rate 1000 each,
`h_rates_data['A'] == 3000`). **Five live places** multiply that
already-summed value by the producer count *again*
(`rates[event] * len(nodes[event])`), effectively cubing the true
per-source contribution for primitives with multiple producers instead of
using the sum once — plus a sixth occurrence that turned out to be inside
already-dead code (a whole function, `new_is_partitioning_custom_rates`,
wrapped in a `"""..."""` block, `projections.py:157`–`204` — noted here
so nobody re-discovers and re-reports it, but not touched by the fix):

- `src/simulator/projections.py:416` — `total_rate()`, `elif len(projection) == 1:` branch
- `src/simulator/projections.py:46` — `optimistic_total_rate()`, primitive-else branch
- `src/simulator/projections.py:68` — `optimistic_total_rate_single()`, primitive-else branch
- `src/simulator/projections.py:304` — same pattern inline in `new_is_partitioning()` itself (`additional = rates[i] * len(nodes[i])`)
- `src/simulator/combigen.py:58` — combigen's own (near-duplicate) `optimistic_total_rate()`
- *(not fixed, dead code)* `src/simulator/projections.py:189` — same pattern, but inside the commented-out `new_is_partitioning_custom_rates`

`total_rate()` specifically is what `new_is_partitioning()`
(`src/simulator/projections.py:253`) uses on the "cost of *not*
partitioning" side of its accept/reject inequality
(`total_rate(element) * longestPath > (mysum * costs) + myproj * longestPath`,
lines 310–313) — i.e. it directly feeds the decision of whether a given
sub-query is worth materializing as its own operator.

### Why this isn't scoped to INEv

`self.h_mycombi` (the chosen decomposition — which sub-queries exist as
separately placeable operators at all) is computed exactly once, in
`Simulation.setup()` (`simulation_environment.py`, `generate_combigen(self)`
call around line 1334–1341), **before** any of the five strategies run.
All five — including Kraken's own joint search — consume this same
`h_mycombi` / `processing_order`; none of them recompute or override the
decomposition. Kraken's own code never calls any of the buggy functions
directly (`grep -rln "total_rate\|optimistic_total_rate" src/kraken/`
returns nothing) — but it inherits whatever decomposition this shared,
upstream setup step decided on.

### Empirical verification

Rather than reasoning about this abstractly, patched all five live
occurrences locally (removed the `* len(nodes[...])` multiplier, matching
the already-fixed sibling functions) and re-ran `Simulation.setup()` for
each of the demo's four story queries, comparing `h_mycombi`'s resulting
operator list before and after.

**large topology (24 nodes, randomly generated) — unaffected.** The
query that currently collapses to a single un-decomposable operator
(`SEQ(A, B, C, D)` on the `large`/seed-1024 topology) produced the exact
same single-operator result both before and after the patch (confirmed via
a temporary trace print that the patched code path actually executed — 16
calls). So this bug is **not** the reason large/randomly-generated
topologies fail to decompose (that appears to be a genuinely structural
property — `new_is_partitioning()`'s comparison also involves Steiner-tree
edge counts and the network's longest-path distance, which dominate for
this topology regardless of the rate term).

**medium topology (the demo's hand-built 12-node reef) — decomposition
changes on 3 of 4 story queries:**

| query | before (buggy) | after (patched) |
|---|---|---|
| `seq_abc` | `SEQ(A, B)`, `SEQ(A, B, C)` (2 ops) | `SEQ(A, B, C)` (1 op — decomposition disappears) |
| `seq_abcd` | `SEQ(A, B)`, `SEQ(A, B, D)`, `SEQ(A, B, C, D)` (3 ops) | `SEQ(B, D)`, `SEQ(A, B, C)`, `SEQ(A, B, C, D)` (3 ops, different intermediates) |
| `seq_abcde` | `SEQ(A, B)`, `SEQ(A, B, D)`, `SEQ(A, B, E)`, `SEQ(A, B, C, D, E)` (4 ops) | `SEQ(B, D)`, `SEQ(A, B, C)`, `SEQ(A, B, C, D, E)` (3 ops) |
| `and_nested` | `AND(SEQ(A, B), F)`, `AND(SEQ(A, B, C), F)`, `AND(SEQ(A, B), D, F)`, `AND(SEQ(A, B), SEQ(E, F))`, `AND(SEQ(A, B, C), D, SEQ(E, F))` (5 ops) | `AND(SEQ(A, B), F)`, `AND(SEQ(A, B), SEQ(E, F))`, `AND(SEQ(A, B, C), F)`, `AND(SEQ(A, B, C), D, F)`, `AND(SEQ(A, B, C), D, SEQ(E, F))` (5 ops, different set) |

Since Kraken (and every other strategy) runs on top of `h_mycombi`, fixing
this bug changes the operator set — and therefore the placement choices and
reported numbers — for Kraken too, on the demo's primary working topology,
not only for the INEv baseline.

### Fix

Same shape as the already-applied fix for the three sibling functions this
week: replaced `rates[event] * len(nodes[event])` with `rates[event]`
(the value is already the summed total across every producer) in all five
live locations listed above, on branch `az1_fix_combigen_rate_overcounting`
(based on `master`). Re-verified on that fresh branch, independently of
the earlier demo-worktree investigation: patched, ran the `SEQ(A,B,C,D)`
query through `Simulation.setup()`, got the identical result to the demo
investigation above (`SEQ(A, B)`, `SEQ(A, B, D)`, `SEQ(A, B, C, D)` before
→ `SEQ(B, D)`, `SEQ(A, B, C)`, `SEQ(A, B, C, D)` after, confirmed via
`git stash`/`git stash pop` to toggle the patch on the same branch). No
test suite exists on `master` to run against.

`total_rate()`/`optimistic_total_rate()` are called pervasively throughout
`combigen.py`'s MS-placement and chain-combination search, not just in the
one gate traced in detail here — the fix has only been verified against
the decomposition *outcome* (`h_mycombi`), not against every individual
code path that calls these functions, so a careful review of the diff is
still warranted, not just a rubber stamp on the outcome match.

### Impact

- This sat upstream of every placement strategy's results on any topology
  where it actually changed `h_mycombi` (confirmed: the medium/12-node
  topology, at least 3 of its 4 story queries). Any previously-reported
  numbers — demo or otherwise — that depended on this topology's
  decomposition should be treated as provisional until re-verified against
  this fix.
- The three sibling occurrences of the same underlying bug pattern were
  already fixed this week on the demo worktree (`feat/demo` branch), which
  is what led to finding these five (plus the one dead one).
