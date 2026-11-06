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

    # Families go by watchtowers (fog nodes with children). Kraken's Forge
    # has 4 and nothing shown has fewer; Lagoon is the smaller topologies
    # with 4-5 watchtowers, Barrier Reef the bigger ones with 6 or more.
    # design/integrate.py applies the same rule to the designed block below.

    # Reef variants -- the four curated queries (seq_abc/abcd/abcde,
    # and_nested) laid out over the original hand-built tree and two
    # hand-curated siblings (a plain branching chain, and a left/right-wing
    # split with its decision nodes renumbered -- see reef_topologies.py's
    # build_medium_e for why), so edges vary between plays without the query
    # itself changing -- and, unlike a random network, each was actually
    # designed and checked to place the story queries differently from the
    # others, specifically at the *root* query's own node, not just "some
    # node in the plan". medium_e has 6 watchtowers, so it's a Barrier Reef
    # (listed after the Grand Reef variants: a family button opens its first
    # entry).
    dict(id="medium", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hardcoded"),
    dict(id="medium_d", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=9, seed=None, kind="hand_curated"),

    # Grand Reef variants -- same idea, deeper wings. The original Grand
    # Reef ("large") is retired, see RETIRED below; a Barrier Reef family
    # button now opens large_b.
    dict(id="large_b", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),
    dict(id="large_c", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),
    dict(id="large_d", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),
    dict(id="medium_e", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=13, seed=None, kind="hand_curated"),

    # Designed topologies -- see reef_topologies.py. `scenarios` lists only
    # the queries that decompose into 2-5 operators on that network.
    # BEGIN designed (generated)
    dict(id="dunes", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=10, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    dict(id="cliffs", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=10, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    dict(id="reefflat", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    dict(id="abyss", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=12, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="current", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=13, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="seagrass", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=13, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    dict(id="wreck", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=16, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcde', 'and_nested']),
    dict(id="pearl", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=16, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    dict(id="coral", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=18, seed=None, kind="hand_curated",
         scenarios=['seq_abcd', 'seq_abcde', 'and_nested']),
    dict(id="whirlpool", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=18, seed=None, kind="hand_curated",
         scenarios=['seq_abc', 'seq_abcd', 'seq_abcde']),
    # END designed
]

# Not exported or shown, but still reconstructable by score_one.py.
RETIRED = [
    # 3 watchtowers, fewer than Kraken's Forge. The critical-path latency bug
    # was reported on medium_c, and export/tests/test_score_one_latency.py
    # pins it there.
    dict(id="medium_c", family="lagoon", label="Lagoon", label_de="Lagune",
         network_size=9, seed=None, kind="hand_curated"),
    # Retired 2026-11-06. "large" was the family's original random network
    # (seed=1024) pruned to 24 edges, with a redesigned letter assignment
    # (reef_topologies.py's build_large and _LARGE_LEAVES; BACKLOG.md item
    # #30). Even so, every operator of every query had exactly one valid
    # host (the cloud), so the round was only a push/pull quiz, and its Q5
    # had shipped with two operators leaked from Q4 (BACKLOG.md item #32).
    dict(id="large", family="barrier", label="Barrier Reef", label_de="Barriereriff",
         network_size=24, seed=None, kind="hand_curated"),
]
