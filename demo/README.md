# Kraken Demo

Interactive single-page demo for the Kraken cloud-fog operator placement engine.
You place operators on network nodes yourself, and the app scores your plan
against Kraken and the baselines. All-push scoring runs client-side via a Rust
engine compiled to WebAssembly; push-pull scoring uses the local backend.

Two demos share this code. This branch, `kraken-demo`, is the plain version
for a scientific audience. `kraken-demo-bsw` keeps the underwater theme for
a general audience (shown at BSW 2026) and has three named alpha presets
instead of the slider.

Rounds:

- **Paper example (P)**: the paper's motivating example (Example 1–4), a
  small fixed round where the best node depends on the communication scheme.
  See [FACTORY_ROUND.md](FACTORY_ROUND.md) for its derivation.
- **Small networks (S1–S8, 9–13 nodes)** and **large networks (L1–L10,
  13–26 nodes)**, with three to five queries each. Codes are numbered by
  size within each group (`export/topologies.py`, `display_code`); the
  internal ids (dunes, coral, …) are still the themed ones. `?topo=S2` or
  `?topo=dunes` opens a network directly. "Try again" stays within the
  current size; the topology-bar buttons switch size.

The networks are hand-curated (`export/reef_topologies.py`), not randomly
generated: a random network almost never gives a query more than one real
placement candidate (its valid set is just the ancestor chain up to the
root), so it never showed the placement trade-off this demo is about. See
`BACKLOG.md` item #30 for the history of the original large network.

A slider sets the cost/latency weight α from 0.0 to 1.0 in steps of 0.1.
Kraken has its own real run at every step; the baselines (All-Push, INEv,
Sequential, PrePP) don't depend on α, only their score does.

[BOOTH.md](BOOTH.md) is the start/reset/recovery guide for running the demo.

## Layout

- `engine/` — Rust scorer, compiled to WASM (`kraken_engine`).
- `web/` — TypeScript/esbuild front end that loads the WASM engine.
- `export/` — Python scripts that generate the JSON scenarios under `web/scenarios/`.
- `backend/` — optional local push-pull scoring server (see below).

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain) + `cargo`
- [`wasm-pack`](https://rustwasm.github.io/wasm-pack/) — install with `cargo install wasm-pack`
- Node.js 18+ and `npm`
- Python 3.11+ with the repo's `uv`-managed venv (`uv sync` from the repo root) — only needed for `export/` and `backend/`, not for running the built frontend on its own.

Check what you already have:

```bash
rustc --version && cargo --version && wasm-pack --version
node -v && npm -v
```

If Rust is missing:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
cargo install wasm-pack
```

## Start the demo

All commands run from `demo/web/`:

```bash
cd demo/web

# 1. Build the Rust engine to WASM (only needed once, or after engine/src changes)
npm run build:wasm

# 2. Install JS dependencies
npm install

# 3. Bundle the front end into dist/
npm run build

# 4. Serve dist/ locally
npm run serve
```

Then open **http://localhost:5173**.

Change the port with `PORT=xxxx npm run serve`.

## Development loop

For front-end changes, `npm run dev` rebuilds `dist/` on save (esbuild watch
mode); keep `npm run serve` running in another terminal and just reload the
page. Engine (Rust) changes need a re-run of `npm run build:wasm` followed by
`npm run build`.

## Regenerating scenarios

The JSON files in `web/scenarios/` are generated from `export/scenarios_def.py`
and `export/topologies.py` via `export/export_scenario.py`:

```bash
uv run python demo/export/export_scenario.py
```

Re-run after changing scenario or topology definitions, then rebuild the
front end. Each topology exports in its own subprocess — don't remove that
isolation (see the comment in `export_scenario.py`): sharing one process lets
RNG state from a randomly-sized topology leak into another's reconstruction.

## Push-pull scoring backend

The network rounds (S, L) need it to score any plan that pulls. Without it (not
configured, or not reachable), only pure all-push plans are scored, by the
in-browser all-push model and labelled as such; a plan that pulls anything
shows "can't score this plan right now" instead of an all-push number that
would ignore the pulls. A status line under the scorecard says which mode is
active; the page polls `GET /health` every 15 s and rescores by itself when the
service comes back. The paper example never needs the backend (scored from its
exported, engine-computed decision table). Run the backend alongside the
frontend:

```bash
uv run python demo/backend/server.py   # http://localhost:8787
```

`web/index.html` already points `window.KRAKEN_BACKEND` at that address for
local development. The backend reuses Kraken's own `CostCalculator` (via
`export/score_one.py`, run in its own subprocess per request for the same
RNG-isolation reason as above) to pick the cheapest push/push-pull strategy
per operator for whatever placement you chose — the same model the
"Sequential" baseline already uses for INEv's placement, generalized to any
placement. For the paper example it restricts placement to nodes 1, 2, cloud,
and push/pull to real subsets of {A, B} (so a player's free per-dependency
chips can build any of the four combinations, not just the paper's own two)
— `score_one.py` is also what the exported decision table itself comes from
(via `factory_example.enumerate_decisions`), but the game never calls the
backend for this round: every cell was computed at export time, so it scores
from that table directly, offline.

## Tests

```bash
# Python: paper round (engine vs. paper formulas, enumeration, backend) + push/pull regressions
cd demo/export && uv run python -m unittest tests.test_factory_example tests.test_score_one
# Frontend: types, and the shipped WASM scorer against the paper example
cd demo/web && npm run typecheck && npm test
# Rust scorer goldens (unchanged)
cd demo/engine && cargo test --release
```
