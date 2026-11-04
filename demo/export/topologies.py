"""Shared topology definitions for the demo: exported once by export_scenario.py
into static JSON, and reconstructed identically (same size + seed) by the
push-pull scoring backend at request time. Keep this the single source of
truth for both so they never drift apart.

Each entry is one concrete network (fixed size + seed, so edges are
reproducible across re-exports). Several entries can share the same
`family`: the frontend shows one button per family (so the topology bar
stays 3 buttons), but rotates which concrete entry is "active" on load and
on every "try again" after a reveal -- so a visitor who plays right after
someone else sees different edges, and sometimes a node more or fewer,
under the same query and the same family label. `kind` controls how
build_scenario()/score_one.py construct the network:
  - "hardcoded":    the original hand-built 12-node tree, no RNG at all.
  - "sized_random": a randomly generated network of `network_size` nodes,
                     reproducible via `seed` (both `random` and
                     `numpy.random` are seeded right before the run).
  - "paper_example": the paper's own fixed topology (factory_example.py).
"""

TOPOLOGIES = [
    # The paper's motivating example (Example 1-4, Fig. 1), extended into a
    # playable topology -- see factory_example.py's module docstring and
    # FACTORY_ROUND.md for what changed and why. Built by factory_example.py
    # instead of scenarios_def.py. Named for the demo's own engine rather
    # than "Factory" -- a visitor taps in to see what Kraken forges out of
    # the paper's fog nodes. Listed first so its topology-bar button sits
    # leftmost, ahead of the two size-variant families below -- it's a
    # different kind of round (one fixed query, no backend needed), not
    # just another size to pick.
    dict(id="factory", family="factory", label="Kraken's Forge", label_de="Krakens Schmiede",
         network_size=7, seed=None, kind="paper_example"),

    # "Reef" family -- the four curated queries (seq_abc/abcd/abcde,
    # and_nested) laid out over four different fog networks: the original
    # hand-built tree plus three random ones, two at 12 nodes and one each
    # at 11 and 13, so edges (and occasionally node count) vary between
    # plays without the query itself changing.
    dict(id="medium", family="medium", label="Reef", label_de="Riff",
         network_size=12, seed=None, kind="hardcoded"),
    dict(id="medium_b", family="medium", label="Reef", label_de="Riff",
         network_size=12, seed=4117, kind="sized_random"),
    dict(id="medium_c", family="medium", label="Reef", label_de="Riff",
         network_size=13, seed=9931, kind="sized_random"),
    dict(id="medium_d", family="medium", label="Reef", label_de="Riff",
         network_size=11, seed=2609, kind="sized_random"),

    # "Grand Reef" family -- same idea at the larger size.
    dict(id="large", family="large", label="Grand Reef", label_de="Großes Riff",
         network_size=24, seed=1024, kind="sized_random"),
    dict(id="large_b", family="large", label="Grand Reef", label_de="Großes Riff",
         network_size=26, seed=8192, kind="sized_random"),
    dict(id="large_c", family="large", label="Grand Reef", label_de="Großes Riff",
         network_size=22, seed=16384, kind="sized_random"),
]
