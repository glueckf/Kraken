"""Curated demo scenarios: one shared 12-node fog-cloud reef (the engine's
`create_hardcoded_tree`), four queries forming a 2->3->4->5 subquery difficulty ramp.
Each query's emblem matches the reference outreach artwork (crab/turtle/shark/seedling).

Imported by export_scenario.py *after* sys.path is set up, so importing core.tree here
is safe.
"""
from core.tree import PrimEvent as P, SEQ, AND

SCENARIOS = [
    dict(
        id="seq_abc",
        title="SEQ(A, B, C)",
        emblem="crab",
        difficulty=1,
        blurb="A short sequence over three streams. Warm-up.",
        build=lambda: SEQ(P("A"), P("B"), P("C")),
    ),
    dict(
        id="seq_abcd",
        title="SEQ(A, B, C, D)",
        emblem="turtle",
        difficulty=2,
        blurb="A longer chain — one more operator to place.",
        build=lambda: SEQ(P("A"), P("B"), P("C"), P("D")),
    ),
    dict(
        id="seq_abcde",
        title="SEQ(A, B, C, D, E)",
        emblem="shark",
        difficulty=3,
        blurb="Branches that share a common sub-result.",
        build=lambda: SEQ(P("A"), P("B"), P("C"), P("D"), P("E")),
    ),
    dict(
        id="and_nested",
        title="AND(SEQ(A,B,C), D, SEQ(E,F))",
        emblem="seedling",
        difficulty=4,
        blurb="A rich nested query touching all six streams.",
        build=lambda: AND(SEQ(P("A"), P("B"), P("C")), P("D"), SEQ(P("E"), P("F"))),
    ),
]
