"""Hand-curated alternative networks for the Reef/Grand Reef families.

Random topology generation (create_sized_deterministic) almost never gives a
story query more than one viable placement node under Kraken's own search --
see demo/BACKLOG.md's "large collapses to 1 operator" item. These builders
replace that randomness with deliberately shaped networks -- a "left wing"
and a "right wing" of sources joined by a shared node -- verified (not
assumed) to actually produce different placements, not just different graphs:
for every one of the four story queries, at least 3 of a family's variants
place it at a genuinely different node (or different number of nodes) under
Kraken's real greedy search at the Balanced stage (alpha=0.6). See
demo/BACKLOG.md for the verification table.

Each `build_*` function has the same (root, network, e_list) contract as
simulation_environment.create_hardcoded_tree -- swapped in for the duration
of one export via `curated_tree()`. `e_list` is unused dead data in the
engine itself (simulation_environment.py only ever assigns `self.eList`,
nothing reads it back), so every builder here returns `{}` for it, same as
factory_example.py's own tree builder does.

Event rates are NOT overridden -- every builder uses the engine's own
`generate_hardcoded_primitive_events()` default (A=1000, B=2, C=45, D=203,
E=800, F=5), read at build time so a change there is picked up automatically.
Only the network *shape* differs between variants; the placement diversity
below comes entirely from that, not from retuned rates.
"""
from __future__ import annotations

import contextlib
import math
from typing import Dict, List


def _build(edges: Dict[int, List[int]], leaf_letters: Dict[int, List[int]],
           compute_power: Dict[int, float]):
    """edges: {parent_id: [child_id, ...]}. leaf_letters: {leaf_id: [letter
    index, ...]} (0=A, 1=B, ..., 5=F). Node ids must be a dense 0..N-1 range
    (the engine's distance code indexes by id), 0 = cloud. A child listed
    under more than one parent gets a real multi-parent `Node.Parent` list
    (accumulated, not overwritten) -- `core.graph.create_fog_graph` builds
    the actual distance graph from `Parent` alone, so a node that appears
    under two parent keys must keep both, or one route silently vanishes
    from every cost/latency computation. Returns a zero-arg builder function
    with the create_hardcoded_tree() contract."""
    n = max(max(edges, default=0), *(max(c) for c in edges.values())) + 1

    def build():
        import simulation_environment as se
        from core.node import Node

        rates = se.generate_hardcoded_primitive_events()
        nodes = {i: Node(id=i, compute_power=compute_power.get(i, 15), memory=15) for i in range(n)}
        for nid in nodes:
            nodes[nid].eventrates = [0] * len(rates)
            nodes[nid].Parent = []
        for parent, children in edges.items():
            nodes[parent].Child = [nodes[c] for c in children]
            for c in children:
                nodes[c].Parent.append(nodes[parent])
        for leaf, idxs in leaf_letters.items():
            for i in idxs:
                nodes[leaf].eventrates[i] = rates[i]
        network = [nodes[i] for i in range(n)]
        return nodes[0], network, {}

    return build


# --------------------------------------------------------------------------
# Reef family (small: ~9 nodes). "medium" itself keeps the engine's own
# original hand-built tree (create_hardcoded_tree, unchanged) -- these three
# are its siblings in the rotation.
# --------------------------------------------------------------------------

# medium_b: left wing (A, B, C) / bridge (D) / right wing (E, F).
#   0 cloud -> 1 bridge -> {2 left hub, 3 right hub, 8 D-leaf}
#   2 -> {4 A-leaf, 5 BC-leaf}; 3 -> {6 E-leaf, 7 F-leaf}
_MEDIUM_B_EDGES = {0: [1], 1: [2, 3, 8], 2: [4, 5], 3: [6, 7]}
_MEDIUM_B_LEAVES = {4: [0], 5: [1, 2], 8: [3], 6: [4], 7: [5]}
_MEDIUM_B_CP = {0: math.inf, 1: 25, 2: 20, 3: 20, 4: 10, 5: 10, 6: 10, 7: 10, 8: 10}
build_medium_b = _build(_MEDIUM_B_EDGES, _MEDIUM_B_LEAVES, _MEDIUM_B_CP)

# medium_c: the same wing/bridge idea, but with the bridge's own id moved
# (5, not 1) -- *not* just medium_b's network with letters swapped, which
# verified to tie with medium_b on and_nested (both bridges happened to
# share raw id 1, so a visitor would see "n1 wins" in both even though the
# underlying graphs differ -- a real, not cosmetic, lack of variety). This
# shape also swaps which wing holds A/B/C vs E/F.
#   0 cloud -> 5 bridge -> {6 left hub, 7 right hub, 4 D-leaf}
#   6 -> {1 A-leaf, 2 BC-leaf}; 7 -> {3 E-leaf, 8 F-leaf}
_MEDIUM_C_EDGES = {0: [5], 5: [6, 7, 4], 6: [1, 2], 7: [3, 8]}
_MEDIUM_C_LEAVES = {1: [0], 2: [1, 2], 4: [3], 3: [4], 8: [5]}
_MEDIUM_C_CP = {0: math.inf, 5: 25, 6: 20, 7: 20, 1: 10, 2: 10, 3: 10, 4: 10, 8: 10}
build_medium_c = _build(_MEDIUM_C_EDGES, _MEDIUM_C_LEAVES, _MEDIUM_C_CP)

# medium_d: no wings at all -- one long branching chain.
_MEDIUM_D_EDGES = {0: [1], 1: [2], 2: [3, 4], 3: [5, 6], 4: [7, 8]}
_MEDIUM_D_LEAVES = {5: [0], 6: [1], 7: [2, 3], 8: [4, 5]}
_MEDIUM_D_CP = {0: math.inf, 1: 30, 2: 25, 3: 20, 4: 20, 5: 10, 6: 10, 7: 10, 8: 10}
build_medium_d = _build(_MEDIUM_D_EDGES, _MEDIUM_D_LEAVES, _MEDIUM_D_CP)

# medium_e: medium_b's own wing/bridge shape (A, B, C left; D on the
# bridge; E, F right). Root-cause for why this exists: checked every
# query's *root* placement (not just "which nodes are touched anywhere",
# which masked this) across medium/_b/_c/_d, and two pairs collide on the
# exact same raw id -- medium and medium_b both land Q2-Q4's root on node
# 1, medium_b and medium_d both land Q1's root on node 2 -- so a visitor
# hitting "try again" a few times has better than even odds of seeing a
# repeat. See demo/BACKLOG.md for the full original per-query table.
#
# Redesigned 2026-11-05 (fully renumbered -- roles, not the old ids):
#   0 cloud -> 3 bridge -> {9 left trunk, 1 right hub, 2 D-leaf}
#   9 -> {4 left-A sub-hub, 5 left-C sub-hub}
#   4 -> 6 A-leaf
#   5 -> {7 BC-leaf, 8 left-C-deep sub-hub} ; 8 -> 10 C-leaf (second producer)
#   1 -> {11 E-leaf, 12 F-leaf}
# Two asks: "let C travel on the left side" -- C used to live on exactly
# one leaf (alongside B); it now has a second producer (10) three hops
# further down the same left branch, through two more watchtowers (5, 8)
# that exist only to carry it there, so C's valid hosts become {5, 9, 3, 0}
# instead of just that one leaf. And "add at least 3 more watchtowers":
# the old shape had 3 (bridge + 2 hubs); this one has 6 (1, 3, 4, 5, 8, 9)
# -- the left branch alone grew from 1 hub to 4 (trunk + A sub-hub + C
# sub-hub + C-deep sub-hub) to give C somewhere to travel through. Right
# side (bridge -> hub -> E/F) is untouched in shape.
#
# The bridge and left-trunk ids (3, 9) are not arbitrary: the first attempt
# reused 1 and 2 for those two roles (closest to the old shape) and
# re-running the root-collision check this redesign is *for* immediately
# caught a fresh collision it would have reintroduced -- Kraken's root
# landed on node 1 for Q2-Q4, same as medium_b's bridge, and on node 2 for
# Q1, same as both medium_b's and medium_d's hub. 3 and 9 were checked
# against the *actual* exported root placement (not assumed from shape
# alone) for every story query against medium/_b/_c/_d and land on neither
# -- see demo/BACKLOG.md for the table. Every duplicated-letter candidate
# set (C here, and the A/D/F ones from round 4 on Grand Reef) has a real
# non-cloud host too, not just the cloud.
_MEDIUM_E_EDGES = {0: [3], 3: [9, 1, 2], 9: [4, 5], 1: [11, 12], 4: [6], 5: [7, 8], 8: [10]}
_MEDIUM_E_LEAVES = {
    2: [3],        # D
    6: [0],        # A
    7: [1, 2],     # B, C (primary)
    10: [2],       # C (secondary -- travels down the left branch)
    11: [4],       # E
    12: [5],       # F
}
_MEDIUM_E_CP = {0: math.inf, 3: 25, 9: 20, 1: 20, 2: 10,
                4: 16, 5: 16, 8: 12, 6: 10, 7: 10, 10: 10, 11: 10, 12: 10}
build_medium_e = _build(_MEDIUM_E_EDGES, _MEDIUM_E_LEAVES, _MEDIUM_E_CP)


# --------------------------------------------------------------------------
# Grand Reef family (larger: ~13-24 nodes, deeper wings).
# --------------------------------------------------------------------------

# large: the family's original random network (create_sized_deterministic,
# seed=1024), kept as-is but with every edge removed that no query's letter
# reachability actually depends on. A random DAG's extra parent edges (this
# one had 67 for 24 nodes -- most non-leaf nodes had 3-4 parents) are
# almost always redundant in exactly this sense: a second route to a node
# that already reaches the same letters some other way, there purely
# because the generator over-connects, not because any query needs it.
# Verified by brute force (every node's reachable-letter-set recomputed
# before/after, for every node, not just leaves) that this pruned graph
# gives the *identical* set for all 24 nodes -- so every placement
# candidate set, and therefore Kraken's own search result, for all four
# story queries is unaffected; only the drawing gets simpler (24 edges
# instead of 67, down to a near-tree -- one node, 13, still has two parents
# because those two really do reach different letters below them). See
# demo/BACKLOG.md for the pruning method and the before/after edge counts.
#
# Two cross-links, 6->12 and 6->8, were added back on top of the pruning
# above (requested experiment: give node 6 extra reach). Tested every
# requested addition first -- 6->11 on its own, or all three of {6->12,
# 6->8, 2->7} together, collapse and_nested's decomposition from 3
# subqueries down to 1 (the only query on this topology that decomposes at
# all), the same "no real choice" degeneracy the pruning above was meant to
# avoid. Any *two* of {6->12, 6->8, 2->7} leaves and_nested's 3 subqueries
# intact, so this keeps 6->12 and 6->8 (both anchored on node 6, closest to
# the original ask) and drops 6->11 and 2->7.
_LARGE_EDGES = {
    0: [1, 2, 3], 1: [6], 2: [4], 3: [5, 7], 4: [10], 5: [8], 6: [9, 12, 8], 7: [11],
    8: [18, 21], 9: [13, 14, 16, 22], 10: [12, 13, 23], 11: [15, 17, 19, 20],
}

# Leaf letters, redesigned (demo/BACKLOG.md item #30, round 3): the edges
# above were never the problem -- the ORIGINAL random leaf-rate assignment
# was. It scattered every letter across 3-7 leaves spread all over the
# tree (e.g. A alone was produced by nodes 15,16,17,18,21,22,23), unlike
# every other hand-curated topology, which single-sources each letter at
# one leaf. A player can only place an operator on a node whose subtree
# reaches *every* producer of its inputs (state.ts's placementIssue()), so
# scattering a letter across unrelated branches collapses that valid set
# to "the cloud, nothing else" -- verified this was happening for every
# one of the 4 story queries on this topology, not just seq_abc/seq_abcd
# (which is why topologies.py used to exclude them here; that's gone now).
#
# This tree has exactly one branch that actually bridges the others:
# node 6 reaches node 1's own leaves (9's children 13/14/16/22, plus 12
# directly) *and*, via the two shared-parent leaves 12 and 13 (parents
# {6,10} and {9,10} respectively) and the shared-parent leaf-group under 8
# (parents {5,6}), node 2's and node 3's leaves too -- so letters placed
# only on {12,13,14,16,18,21,22} always share at least nodes {6,1,0} as
# valid hosts, however they're combined.
#
# Round 4 (2026-11-05): every leaf now gets a letter -- leaving 15,17,19,20
# and 23 without one (the previous round's trade-off) means those five
# source pods render with no letter badge at all, which reads as broken,
# not "deliberately plain". Two more leaf-letter pairings, each picked the
# same way as the B+F pair above -- by finding an actual shared, non-cloud
# ancestor, not just reusing a letter and hoping:
#   - 13 and 23 are both direct children of node 10, so D's second producer
#     goes on 23: D's valid hosts become {10,...} instead of just leaf 13.
#   - 15/17/19/20 (under node 11, itself only reachable via node 7 -> node
#     3) share no ancestor below the cloud with any *other* already-lettered
#     leaf except 18 and 21 -- both under node 8, which has two parents
#     {5,6}, one of which (5) comes down through node 3 too. So node 3 is a
#     real, non-cloud common ancestor of {18,21} and {15,17,19,20} -- A (18's
#     letter, otherwise single-sourced) is the one extended down into all
#     four, rather than C/D/E, whose existing producers (14/13/22) sit in
#     the *other* top-level branch (under node 1) and would collapse to the
#     cloud if paired with anything under node 3.
# Verified directly against the real combigen output (not assumed, same
# method as the B+F round): every leaf-level projection across all five
# story queries (see scenarios_def.py) still has >=2 valid placement
# candidates, several at 3-6, and none of the five collapses to a single
# subquery. A ends up the "rich" letter (5 producers, node 3 as its one
# non-trivial common host); B, D, F stay at 2 producers each; C and E stay
# single-sourced, same as before.
_LARGE_LEAVES = {
    18: [0],        # A (primary)
    15: [0],        # A
    17: [0],        # A
    19: [0],        # A
    20: [0],        # A
    16: [1],        # B (primary)
    12: [1, 5],     # B (secondary) + F (secondary) -- the rarity-pair fix
    14: [2],        # C
    13: [3],        # D (primary)
    23: [3],        # D (secondary)
    22: [4],        # E
    21: [5],        # F (primary)
}
_LARGE_CP = {0: math.inf, 1: 4, 2: 4, 3: 4, 4: 3, 5: 3, 6: 3, 7: 3,
             8: 2, 9: 2, 10: 2, 11: 2,
             12: 1, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1, 19: 1, 20: 1, 21: 1, 22: 1, 23: 1}
build_large = _build(_LARGE_EDGES, _LARGE_LEAVES, _LARGE_CP)

# large_b: deep wings behind two bridges, D split off at the inner bridge.
#   0 -> 1 -> 2 -> {3 left hub, 4 right hub, 10 D-leaf}
#   3 -> {5 mid, 6 C-leaf}; 5 -> {7 A-leaf, 8 B-leaf}
#   4 -> 9 mid -> {11 E-leaf, 12 F-leaf}
# Letters, round 4 (2026-11-05): originally single-sourced -- 6 letters, 6
# leaves, no duplication at all, so every placement was trivially "the leaf
# itself, or anywhere above it" with no real decision in between. Each wing
# gets one letter duplicated onto a sibling leaf that shares a genuine
# non-cloud ancestor with its existing producer:
#   - 6 is a direct sibling of 5 (7+8's parent) under node 3, so it also
#     gets B (8's letter) -- B's hosts become {3, 2, 1, 0} instead of just
#     leaf 8.
#   - 7 is a sibling of 10 under node 2, so it also gets D (10's letter) --
#     D's hosts become {2, 1, 0} instead of just leaf 10.
#   - 11 and 12 are the only two leaves under node 9 (the right wing's own
#     hub), so 12 also gets E (11's letter) -- a smaller, local bridge at
#     node 9 itself.
# A and C stay single-sourced. Verified the same way as the Grand Reef
# redesign above: re-exported, all four story queries still decompose (no
# collapse to one subquery), and every leaf-level projection keeps >=2
# placement candidates where these pairs are actually used together.
_LARGE_B_EDGES = {0: [1], 1: [2], 2: [3, 4, 10], 3: [5, 6], 5: [7, 8], 4: [9], 9: [11, 12]}
_LARGE_B_CP = {0: math.inf, 1: 30, 2: 28, 3: 22, 4: 22, 5: 18, 9: 18,
               6: 15, 7: 15, 8: 15, 10: 15, 11: 15, 12: 15}
_LARGE_B_LEAVES = {
    7: [0, 3],      # A (primary) + D (secondary, bridges at node 2 with 10)
    8: [1],         # B (primary)
    6: [2, 1],      # C (primary) + B (secondary, bridges at node 3 with 8)
    10: [3],        # D (primary)
    11: [4],        # E (primary)
    12: [5, 4],      # F (primary) + E (secondary, bridges at node 9 with 11)
}
build_large_b = _build(_LARGE_B_EDGES, _LARGE_B_LEAVES, _LARGE_B_CP)

# large_c: same shape, wings swapped -- same duplication pattern, carried
# over letter-for-letter (6 pairs with 8's letter, 7 pairs with 10's
# letter, 12 pairs with 11's letter), since the edges (and therefore every
# ancestor relationship the pairing depends on) are identical to large_b.
_LARGE_C_LEAVES = {
    7: [4, 3],      # E (primary) + D (secondary, bridges at node 2 with 10)
    8: [5],         # F (primary)
    6: [1, 5],      # B (primary) + F (secondary, bridges at node 3 with 8)
    10: [3],        # D (primary)
    11: [0],        # A (primary)
    12: [2, 0],      # C (primary) + A (secondary, bridges at node 9 with 11)
}
build_large_c = _build(_LARGE_B_EDGES, _LARGE_C_LEAVES, _LARGE_B_CP)

# large_d: long branching chain, scaled up. Only 4 leaves for 6 letters, so
# C+D and E+F were always doubled up *within* one leaf each -- but every
# letter still had exactly one producer. Round 4 (2026-11-05): 10 and 11
# share node 4 as a real common ancestor (10 under node 6, 11 under node 7,
# both children of 4), and 9 and 12 share node 5 the same way -- so C and D
# each also get a second producer on 10 (bridging at node 4), and E gets a
# second producer on 9 (bridging at node 5). B and A stay single-sourced.
# Verified the same way as the rest of this round's redesign: re-exported,
# all four story queries still decompose, no collapse to one subquery.
_LARGE_D_EDGES = {0: [1], 1: [2], 2: [3], 3: [4, 5], 4: [6, 7], 5: [8, 9], 6: [10], 7: [11], 8: [12]}
_LARGE_D_CP = {0: math.inf, 1: 30, 2: 28, 3: 25, 4: 20, 5: 20,
               6: 15, 7: 15, 8: 15, 9: 15, 10: 15, 11: 15, 12: 15}
_LARGE_D_LEAVES = {9: [0, 4], 10: [1, 2, 3], 11: [2, 3], 12: [4, 5]}
build_large_d = _build(_LARGE_D_EDGES, _LARGE_D_LEAVES, _LARGE_D_CP)


# --------------------------------------------------------------------------
# Designed topologies (one family each, their own topology-bar button).
# Found by a quality-diversity search (MAP-Elites over what each network
# *teaches*, then farthest-point sampling) and checked with topology_lab.py:
# sources are dual-homed -- a fast direct uplink plus a slower local
# aggregation route -- so Fast, Balanced and Cheap genuinely place operators
# differently, not only push vs pull. See demo/BACKLOG.md item 35.
# --------------------------------------------------------------------------

# BEGIN designed (generated -- regenerate, don't hand-edit)
_DUNES_EDGES = {0: [1, 2], 1: [3, 5], 2: [8, 9], 3: [4, 7], 4: [6, 8, 9]}
_DUNES_LEAVES = {8: [3], 5: [2], 6: [4, 5], 9: [2, 5], 7: [0, 1, 4]}
_DUNES_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 10, 6: 10, 7: 10, 8: 10, 9: 10}
build_dunes = _build(_DUNES_EDGES, _DUNES_LEAVES, _DUNES_CP)

_CLIFFS_EDGES = {0: [1, 2], 1: [3, 5], 2: [8, 9], 3: [4, 7], 4: [6, 8, 9]}
_CLIFFS_LEAVES = {8: [0, 2, 3], 5: [4], 6: [3, 5], 9: [4, 5], 7: [1]}
_CLIFFS_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 10, 6: 10, 7: 10, 8: 10, 9: 10}
build_cliffs = _build(_CLIFFS_EDGES, _CLIFFS_LEAVES, _CLIFFS_CP)

_REEFFLAT_EDGES = {0: [1, 2], 1: [3, 5, 6], 2: [8, 9, 10, 11], 3: [4, 10, 11], 4: [5, 6, 7, 8, 9]}
_REEFFLAT_LEAVES = {8: [3, 4], 7: [4], 9: [1, 2], 5: [4], 10: [1], 6: [0, 3], 11: [5]}
_REEFFLAT_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 10, 6: 10, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10}
build_reefflat = _build(_REEFFLAT_EDGES, _REEFFLAT_LEAVES, _REEFFLAT_CP)

_ABYSS_EDGES = {0: [1, 2], 1: [5, 6], 2: [3, 11], 3: [4, 9, 10], 4: [5, 6, 7, 8, 11]}
_ABYSS_LEAVES = {5: [3, 5], 7: [5], 6: [1, 2], 8: [5], 9: [1], 11: [0, 3], 10: [4]}
_ABYSS_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 10, 6: 10, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10}
build_abyss = _build(_ABYSS_EDGES, _ABYSS_LEAVES, _ABYSS_CP)

_CURRENT_EDGES = {0: [1, 2], 1: [6, 7], 2: [3, 8, 11], 3: [4, 5, 9, 10], 4: [6, 8], 5: [7, 9, 10, 11, 12]}
_CURRENT_LEAVES = {6: [3, 4], 9: [2], 7: [5], 8: [1, 3], 10: [1], 11: [0, 1], 12: [5]}
_CURRENT_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 14, 6: 10, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10}
build_current = _build(_CURRENT_EDGES, _CURRENT_LEAVES, _CURRENT_CP)

_SEAGRASS_EDGES = {0: [1, 2], 1: [6, 8], 2: [3, 9, 11], 3: [4, 5, 7, 10], 4: [6, 9], 5: [8, 10, 11, 12]}
_SEAGRASS_LEAVES = {6: [0], 7: [3], 8: [3], 9: [0, 1], 10: [1], 11: [1, 4], 12: [2, 5]}
_SEAGRASS_CP = {0: math.inf, 1: 26, 2: 26, 3: 20, 4: 14, 5: 14, 6: 10, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10}
build_seagrass = _build(_SEAGRASS_EDGES, _SEAGRASS_LEAVES, _SEAGRASS_CP)

_WRECK_EDGES = {0: [1, 2, 3], 1: [4, 5], 2: [5, 8], 3: [13, 14, 15], 4: [6, 7, 8, 9], 5: [6, 12, 14, 15], 6: [7, 9, 10, 11, 12, 13]}
_WRECK_LEAVES = {7: [0, 1], 10: [4], 8: [3], 12: [5], 11: [0, 1], 14: [0], 13: [3], 9: [2, 3], 15: [1, 3]}
_WRECK_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 20, 5: 20, 6: 14, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10}
build_wreck = _build(_WRECK_EDGES, _WRECK_LEAVES, _WRECK_CP)

_PEARL_EDGES = {0: [1, 2, 3], 1: [4], 2: [4, 5, 8], 3: [13, 14, 15], 4: [6, 7, 8, 9, 10], 5: [6, 14, 15], 6: [7, 9, 10, 11, 12, 13]}
_PEARL_LEAVES = {7: [2], 11: [4], 8: [3], 12: [5], 9: [1, 2], 14: [0, 3], 13: [3], 10: [1, 2], 15: [1, 3]}
_PEARL_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 20, 5: 20, 6: 14, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10}
build_pearl = _build(_PEARL_EDGES, _PEARL_LEAVES, _PEARL_CP)

_CORAL_EDGES = {0: [1, 2, 3], 1: [7], 2: [10, 15], 3: [4, 13], 4: [5, 6, 11, 12, 14, 16], 5: [7, 8, 9, 10, 11, 13], 6: [14, 15, 16, 17]}
_CORAL_LEAVES = {10: [0], 7: [0], 8: [5], 14: [0], 9: [5], 11: [2], 17: [2, 5], 15: [1, 3], 12: [0, 5], 16: [2], 13: [0, 4]}
_CORAL_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 20, 5: 14, 6: 14, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10, 16: 10, 17: 10}
build_coral = _build(_CORAL_EDGES, _CORAL_LEAVES, _CORAL_CP)

_WHIRLPOOL_EDGES = {0: [1, 2, 3], 1: [7, 10], 2: [4, 8, 16], 3: [10, 14], 4: [5, 6, 9, 11, 12, 13, 14, 15], 5: [7, 8, 9, 13, 14], 6: [13, 15, 16, 17]}
_WHIRLPOOL_LEAVES = {8: [2], 7: [5], 10: [3], 15: [2, 4], 11: [3, 4], 9: [2], 17: [4], 16: [3], 12: [2, 3], 13: [1], 14: [0, 2]}
_WHIRLPOOL_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 20, 5: 14, 6: 14, 7: 10, 8: 10, 9: 10, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10, 16: 10, 17: 10}
build_whirlpool = _build(_WHIRLPOOL_EDGES, _WHIRLPOOL_LEAVES, _WHIRLPOOL_CP)

_SKERRIES_EDGES = {0: [1, 2, 3, 4], 1: [5, 10, 11], 2: [5, 6, 11, 12, 15], 3: [18, 19], 4: [23], 5: [7, 8, 13, 15, 17], 6: [9, 17, 22], 7: [10, 12, 14], 8: [13, 14, 16], 9: [15, 18, 19, 20, 21, 23]}
_SKERRIES_LEAVES = {10: [0, 1], 13: [1, 2], 11: [0, 1], 12: [0], 15: [0], 14: [1], 16: [1], 18: [4, 5], 20: [4], 19: [4], 21: [4], 22: [4], 23: [3, 4], 17: [4]}
_SKERRIES_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 26, 5: 20, 6: 20, 7: 14, 8: 14, 9: 14, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10, 16: 10, 17: 10, 18: 10, 19: 10, 20: 10, 21: 10, 22: 10, 23: 10}
build_skerries = _build(_SKERRIES_EDGES, _SKERRIES_LEAVES, _SKERRIES_CP)

_INLET_EDGES = {0: [1, 2, 3, 4], 1: [5], 2: [5, 14, 15, 16, 17], 3: [5, 6, 18, 19, 20], 4: [6], 5: [7, 10, 13, 15], 6: [8, 22, 25], 7: [9, 11, 12, 14, 16, 17], 8: [18, 19, 20, 21, 23, 24]}
_INLET_LEAVES = {16: [2], 9: [2], 13: [2], 14: [0, 2], 11: [1, 2], 15: [0, 2], 17: [0, 2], 12: [0], 10: [0, 2], 19: [5], 18: [5], 22: [4, 5], 21: [5], 23: [5], 24: [3], 20: [5], 25: [5]}
_INLET_CP = {0: math.inf, 1: 26, 2: 26, 3: 26, 4: 26, 5: 20, 6: 20, 7: 14, 8: 14, 9: 10, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10, 16: 10, 17: 10, 18: 10, 19: 10, 20: 10, 21: 10, 22: 10, 23: 10, 24: 10, 25: 10}
build_inlet = _build(_INLET_EDGES, _INLET_LEAVES, _INLET_CP)

_DESIGNED = {
    "dunes": build_dunes,
    "cliffs": build_cliffs,
    "reefflat": build_reefflat,
    "abyss": build_abyss,
    "current": build_current,
    "seagrass": build_seagrass,
    "wreck": build_wreck,
    "pearl": build_pearl,
    "coral": build_coral,
    "whirlpool": build_whirlpool,
    "skerries": build_skerries,
    "inlet": build_inlet,
}
# END designed


BUILDERS = {
    "medium_b": build_medium_b,
    "medium_c": build_medium_c,
    "medium_d": build_medium_d,
    "medium_e": build_medium_e,
    "large": build_large,
    "large_b": build_large_b,
    "large_c": build_large_c,
    "large_d": build_large_d,
    **_DESIGNED,
}


@contextlib.contextmanager
def curated_tree(topology_id: str):
    """Swap the engine's hardcoded-tree builder for `topology_id`'s curated
    one for the duration of the block, then restore it -- same pattern as
    factory_example.py's factory_model()."""
    import simulation_environment as se

    saved = se.create_hardcoded_tree
    se.create_hardcoded_tree = BUILDERS[topology_id]
    try:
        yield
    finally:
        se.create_hardcoded_tree = saved
