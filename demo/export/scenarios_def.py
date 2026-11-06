"""Curated demo scenarios: one shared 12-node fog-cloud reef (the engine's
`create_hardcoded_tree`), five queries. The list order is the Q1-Q5 numbering the
UI shows, ordered by how hard each query played in the 2026-11-06 play study
(mean stage rating): seq_abc 1.94, seq_abcde 2.22, seq_abcd 2.46, and_nested 2.61,
seq_and_pairs 2.83. That puts the five-stream chain (shark) before the four-stream
one (turtle), so the order no longer follows the subquery count.
The first four queries' emblems match the reference outreach artwork
(crab/turtle/shark/seedling); the fifth (octopus) has no reference artwork yet --
see demo/BACKLOG.md item #30 for why it was added (more subqueries, more
placement decisions per round, on top of the Grand Reef leaf-assignment fix).

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
        id="seq_abcde",
        title="SEQ(A, B, C, D, E)",
        emblem="shark",
        difficulty=2,
        blurb="Branches that share a common sub-result.",
        build=lambda: SEQ(P("A"), P("B"), P("C"), P("D"), P("E")),
    ),
    dict(
        id="seq_abcd",
        title="SEQ(A, B, C, D)",
        emblem="turtle",
        difficulty=3,
        blurb="A shorter chain than the shark's, but it plays harder.",
        build=lambda: SEQ(P("A"), P("B"), P("C"), P("D")),
    ),
    dict(
        id="and_nested",
        title="AND(SEQ(A,B,C), D, SEQ(E,F))",
        emblem="seedling",
        difficulty=4,
        blurb="A rich nested query touching all six streams.",
        build=lambda: AND(SEQ(P("A"), P("B"), P("C")), P("D"), SEQ(P("E"), P("F"))),
    ),
    dict(
        id="seq_and_pairs",
        title="SEQ(AND(A,B), C, AND(D,E), F)",
        emblem="octopus",
        difficulty=5,
        blurb="Two paired branches, chained together -- the most operators yet.",
        build=lambda: SEQ(AND(P("A"), P("B")), P("C"), AND(P("D"), P("E")), P("F")),
    ),
]
