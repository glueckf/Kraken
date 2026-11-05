"""Shared topology definitions for the demo: exported once by export_scenario.py
into static JSON, and reconstructed identically (same size + seed) by the
push-pull scoring backend at request time. Keep this the single source of
truth for both so they never drift apart.

Each entry is one concrete network. Several entries can share the same
`family`: the frontend shows one button per family (so the topology bar
stays 3 buttons), but rotates which concrete entry is "active" on load and
on every "try again" after a reveal -- so a visitor who plays right after
someone else sees different edges, and sometimes a node more or fewer,
under the same query and the same family label. `kind` controls how
build_scenario()/score_one.py construct the network:
  - "hardcoded":     the original hand-built 12-node tree, no RNG at all.
  - "hand_curated":  a different hand-built tree from reef_topologies.py
                      (`id` doubles as the key into its BUILDERS dict), also
                      no RNG. Random generation (below) almost never gives a
                      story query more than one viable placement node under
                      Kraken's own search (demo/BACKLOG.md's "large
                      collapses to 1 operator" item); these were designed
                      and verified instead -- for every one of the four
                      story queries, at least 3 of a family's variants place
                      it at a genuinely different node (or different number
                      of nodes) under Kraken's real search at the Balanced
                      stage. See demo/BACKLOG.md for the verification table.
  - "sized_random":  a randomly generated network of `network_size` nodes,
                      reproducible via `seed` (both `random` and
                      `numpy.random` are seeded right before the run). Kept
                      as one variant per family for the node-count/shape
                      variety it still brings, even though it doesn't give
                      the story queries real placement choice.
  - "paper_example": the paper's own fixed topology (factory_example.py).
"""

TOPOLOGIES = [
    # The paper's motivating example (Example 1-4, Fig. 1), extended into a
    # playable topology -- see factory_example.py's module docstring and
    # FACTORY_ROUND.md for what changed and why. Built by factory_example.py
    # instead of scenarios_def.py. The topology id/family is "forge" (the
    # underlying module stays factory_example.py/factory_model -- only the
    # player-facing id changed) to match the label a visitor actually taps:
    # Kraken's Forge, what Kraken forges out of the paper's fog nodes.
    # Listed first so its topology-bar button sits leftmost, ahead of the
    # two size-variant families below -- it's a different kind of round
    # (one fixed query, no backend needed), not just another size to pick.
    dict(id="forge", family="forge", label="Kraken's Forge", label_de="Krakens Schmiede",
         network_size=7, seed=None, kind="paper_example"),

    # Reef variants (Lagoon family, with the simpler designed ones) -- the four curated queries (seq_abc/abcd/abcde,
    # and_nested) laid out over five different fog networks: the original
    # hand-built tree plus four hand-curated siblings (a left/right-wing
    # split, the same split mirrored, a plain branching chain, and the first
    # split again with its decision nodes renumbered -- see
    # reef_topologies.py's build_medium_e for why), so edges vary between
    # plays without the query itself changing -- and, unlike a random
    # network, each of these four was actually designed and checked to place
    # the story queries differently from the others, specifically at the
    # *root* query's own node, not just "some node in the plan".
    dict(id="medium", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hardcoded"),
    dict(id="medium_b", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=9, seed=None, kind="hand_curated"),
    dict(id="medium_c", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=9, seed=None, kind="hand_curated"),
    dict(id="medium_d", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=9, seed=None, kind="hand_curated"),
    dict(id="medium_e", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=13, seed=None, kind="hand_curated"),

    # Grand Reef variants (Barrier Reef family, with the larger designed ones) -- same idea, deeper wings. "large" is the
    # family's original random network (same shape, same seed=1024) but
    # pruned to the edges its letter reachability actually needs -- 24
    # instead of 67 -- so it reads as a bigger variant in the rotation
    # instead of an illegible tangle; see reef_topologies.py's build_large
    # for the pruning method. Its leaf *letter* assignment (not the edges)
    # used to scatter every letter across several unrelated branches,
    # which collapsed every query's placement choice down to "the cloud,
    # nothing else" -- that's why seq_abc/seq_abcd were excluded below.
    # Fixed by redesigning the letter assignment instead (see
    # reef_topologies.py's _LARGE_LEAVES); all five story queries now have
    # real decomposition and real placement choice here, so the exclusion
    # is gone. See demo/BACKLOG.md item #30 follow-up.
    dict(id="large", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=24, seed=None, kind="hand_curated"),
    dict(id="large_b", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),
    dict(id="large_c", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),
    dict(id="large_d", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),

    # Designed topologies -- see reef_topologies.py. `scenarios` lists only
    # the queries that decompose into 2-5 operators on that network.
    # BEGIN designed (generated)
    dict(id="trench", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=10, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="shoal", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=10, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="cape", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="isle", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="strait", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="harbor", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="gulf", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=16, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="sound", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=16, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    # END designed
]
