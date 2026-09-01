# Kraken Demo

Interactive single-page demo for the Kraken cloud-fog operator placement engine.
You place operators on network nodes yourself, and the app scores your plan
against Kraken and four baselines. Scoring runs client-side via a Rust engine
compiled to WebAssembly.

## Layout

- `engine/` — Rust scorer, compiled to WASM (`kraken_engine`).
- `web/` — TypeScript/esbuild front end that loads the WASM engine.
- `export/` — Python scripts that generate the JSON scenarios under `web/scenarios/`.

## Prerequisites

- [Rust](https://rustup.rs/) (stable toolchain) + `cargo`
- [`wasm-pack`](https://rustwasm.github.io/wasm-pack/) — install with `cargo install wasm-pack`
- Node.js 18+ and `npm`

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
via `export/export_scenario.py` (Python 3). Re-run that script after changing
scenario definitions, then rebuild the front end.
