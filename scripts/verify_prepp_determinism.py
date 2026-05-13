"""Verify that PrePP produces identical output for identical inputs.

Sanity check for the seeded-RNG fix in `src/prepp/prepp.py` and
`src/kraken/components/cost_calculator.py`. Run from the repo root:

    python3 scripts/verify_prepp_determinism.py

Exits non-zero if any check fails. CI-friendly.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

# Make the in-tree modules importable when run from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from prepp.prepp import determine_randomized_single_selectivities_within_all_projections


def _call(seed: int) -> tuple:
    """Run PrePP's selectivity sampler once with a seeded local RNG."""
    query = list("ABCD")
    upper_bounds_keys: list = []
    pip = {"A": 0.6, "B": 0.7, "C": 0.8, "D": 0.9,
           "AB": 0.5, "AC": 0.55, "AD": 0.6,
           "BC": 0.65, "BD": 0.7, "CD": 0.75, "ABCD": 0.3}
    sscoe = dict(pip)
    rates = {"A": 100, "B": 50, "C": 25, "D": 12}
    sources = {"A": [1, 2], "B": [3], "C": [4], "D": [5]}

    rng = random.Random(seed)
    # Mutate the global RNG between calls to confirm the local RNG is isolated.
    random.random(); random.random()

    determine_randomized_single_selectivities_within_all_projections(
        query, upper_bounds_keys, pip, rates, sources, sscoe,
        is_deterministic=False, rng=rng,
    )
    return tuple(sorted(sscoe.items()))


def main() -> int:
    a = _call(seed=12345)
    b = _call(seed=12345)
    c = _call(seed=99999)

    same_seed_reproducible = a == b
    different_seeds_differ = a != c

    print(f"  same seed reproducible:        {same_seed_reproducible}")
    print(f"  different seeds differ:        {different_seeds_differ}")

    if not same_seed_reproducible:
        print("FAIL: seeded PrePP is not deterministic")
        return 1
    if not different_seeds_differ:
        print("FAIL: different seeds produced identical output (RNG ignored?)")
        return 1

    print("PASS: seeded PrePP determinism verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
