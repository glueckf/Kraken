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
# bridge; E, F right), but with the bridge and left hub -- the two nodes
# that actually end up holding the root query -- renumbered to ids 8/7
# instead of 1/2. Root-cause for why this exists: checked every query's
# *root* placement (not just "which nodes are touched anywhere", which
# masked this) across medium/_b/_c/_d, and two pairs collide on the exact
# same raw id -- medium and medium_b both land Q2-Q4's root on node 1,
# medium_b and medium_d both land Q1's root on node 2 -- so a visitor
# hitting "try again" a few times has better than even odds of seeing a
# repeat, which is exactly what was reported (stuck on the same node after
# two rounds). Reusing the proven wing shape rather than inventing a new
# one is deliberate: every other shape tried that still resolves Q1 inside
# a single A/B/C hub (required to keep its root off the bridge at all)
# necessarily produces the same kind of bridge/hub split -- the only real
# freedom left is which raw id that hub and bridge get, so this spends it
# on ids neither collision pair uses. Verified empirically, not assumed:
# root 7 for Q1, root 8 for Q2-Q4, colliding with none of medium/_b/_c/_d
# on any query -- see demo/BACKLOG.md for the full per-query table.
_MEDIUM_E_EDGES = {0: [8], 8: [7, 1, 6], 7: [2, 3], 1: [4, 5]}
_MEDIUM_E_LEAVES = {2: [0], 3: [1, 2], 6: [3], 4: [4], 5: [5]}
_MEDIUM_E_CP = {0: math.inf, 8: 25, 7: 20, 1: 20, 2: 10, 3: 10, 4: 10, 5: 10, 6: 10}
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
# the original ask) and drops 6->11 and 2->7. Verified: and_nested still 3
# subqueries at every alpha; seq_abc/seq_abcd/seq_abcde unaffected (still 1
# subquery, still cloud); only cost numbers shift slightly (e.g. seq_abc
# Balanced: 777.5 -> 750.1), the "not much changes" outcome that was hoped
# for -- see demo/BACKLOG.md for the full edge-combination table.
_LARGE_EDGES = {
    0: [1, 2, 3], 1: [6], 2: [4], 3: [5, 7], 4: [10], 5: [8], 6: [9, 12, 8], 7: [11],
    8: [18, 21], 9: [13, 14, 16, 22], 10: [12, 13, 23], 11: [15, 17, 19, 20],
}
_LARGE_LEAVES = {
    12: [2, 3, 5], 13: [1, 3, 5], 14: [3, 4], 15: [0, 2, 5], 16: [0, 2, 3, 5],
    17: [0, 1, 4], 18: [0, 3], 19: [3, 4], 20: [2, 4], 21: [0, 1, 2, 4, 5],
    22: [0, 3], 23: [0, 4],
}
_LARGE_CP = {0: math.inf, 1: 4, 2: 4, 3: 4, 4: 3, 5: 3, 6: 3, 7: 3,
             8: 2, 9: 2, 10: 2, 11: 2,
             12: 1, 13: 1, 14: 1, 15: 1, 16: 1, 17: 1, 18: 1, 19: 1, 20: 1, 21: 1, 22: 1, 23: 1}
build_large = _build(_LARGE_EDGES, _LARGE_LEAVES, _LARGE_CP)

# large_b: deep wings behind two bridges, D split off at the inner bridge.
#   0 -> 1 -> 2 -> {3 left hub, 4 right hub, 10 D-leaf}
#   3 -> {5 mid, 6 C-leaf}; 5 -> {7 A-leaf, 8 B-leaf}
#   4 -> 9 mid -> {11 E-leaf, 12 F-leaf}
_LARGE_B_EDGES = {0: [1], 1: [2], 2: [3, 4, 10], 3: [5, 6], 5: [7, 8], 4: [9], 9: [11, 12]}
_LARGE_B_CP = {0: math.inf, 1: 30, 2: 28, 3: 22, 4: 22, 5: 18, 9: 18,
               6: 15, 7: 15, 8: 15, 10: 15, 11: 15, 12: 15}
_LARGE_B_LEAVES = {7: [0], 8: [1], 6: [2], 10: [3], 11: [4], 12: [5]}  # A,B,C left; D bridge; E,F right
build_large_b = _build(_LARGE_B_EDGES, _LARGE_B_LEAVES, _LARGE_B_CP)

# large_c: same shape, wings swapped.
_LARGE_C_LEAVES = {7: [4], 8: [5], 6: [1], 10: [3], 11: [0], 12: [2]}
build_large_c = _build(_LARGE_B_EDGES, _LARGE_C_LEAVES, _LARGE_B_CP)

# large_d: long branching chain, scaled up.
_LARGE_D_EDGES = {0: [1], 1: [2], 2: [3], 3: [4, 5], 4: [6, 7], 5: [8, 9], 6: [10], 7: [11], 8: [12]}
_LARGE_D_CP = {0: math.inf, 1: 30, 2: 28, 3: 25, 4: 20, 5: 20,
               6: 15, 7: 15, 8: 15, 9: 15, 10: 15, 11: 15, 12: 15}
_LARGE_D_LEAVES = {9: [0], 10: [1], 11: [2, 3], 12: [4, 5]}
build_large_d = _build(_LARGE_D_EDGES, _LARGE_D_LEAVES, _LARGE_D_CP)


BUILDERS = {
    "medium_b": build_medium_b,
    "medium_c": build_medium_c,
    "medium_d": build_medium_d,
    "medium_e": build_medium_e,
    "large": build_large,
    "large_b": build_large_b,
    "large_c": build_large_c,
    "large_d": build_large_d,
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
