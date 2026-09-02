# Kraken Demo

Interactive single-page demo for the Kraken cloud-fog operator placement engine.
You place operators on network nodes yourself, and the app scores your plan
against Kraken and four baselines. Scoring runs client-side via a Rust engine
compiled to WebAssembly.

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

## Push-pull scoring backend (optional)

Without a backend, the demo scores your placement with the instant
client-side all-push estimate only. To also show the real push-pull-optimized
number (labelled "push-pull optimised" instead of "all-push estimate" in the
scorecard), run the local backend alongside the frontend:

```bash
uv run python demo/backend/server.py   # http://localhost:8787
```

`web/index.html` already points `window.KRAKEN_BACKEND` at that address for
local development. The backend reuses Kraken's own `CostCalculator` (via
`export/score_one.py`, run in its own subprocess per request for the same
RNG-isolation reason as above) to pick the cheapest push/push-pull strategy
per operator for whatever placement you chose — the same model the
"Sequential" baseline already uses for INEv's placement, generalized to any
placement. If the backend isn't running, `backend.ts` degrades gracefully
back to the all-push estimate.
