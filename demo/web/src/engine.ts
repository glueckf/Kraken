// Thin wrapper over the Rust/WASM scorer. The wasm glue is loaded via a runtime
// dynamic import with a non-literal specifier so the bundler leaves the wasm URL
// alone (it resolves relative to app.js -> ./vendor/engine/).

import type { Scenario, ScoreResult, Baselines, NormPoint, Placement } from "./types";

interface WasmModule {
  default: (input?: unknown) => Promise<unknown>;
  Scorer: new (json: string) => {
    score(json: string): string;
    baselines(): string;
    normalizePoint(cost: number, latency: number): string;
    free(): void;
  };
}

let modPromise: Promise<WasmModule> | null = null;

function loadModule(): Promise<WasmModule> {
  if (!modPromise) {
    // non-literal specifier keeps esbuild from bundling / rewriting the wasm path
    const rel = "vendor/engine/" + "kraken_engine.js";
    const url = new URL(rel, import.meta.url).href;
    modPromise = import(/* @vite-ignore */ url).then(async (mod: WasmModule) => {
      await mod.default();
      return mod;
    });
  }
  return modPromise;
}

export class Engine {
  private scorer: WasmModule["Scorer"]["prototype"];

  private constructor(scorer: WasmModule["Scorer"]["prototype"]) {
    this.scorer = scorer;
  }

  static async create(scenario: Scenario): Promise<Engine> {
    const mod = await loadModule();
    return new Engine(new mod.Scorer(JSON.stringify(scenario)));
  }

  /** Instant all-push cost + latency + normalized score for a placement. */
  score(placement: Placement): ScoreResult {
    return JSON.parse(this.scorer.score(JSON.stringify(placement)));
  }

  /** The five baselines with normalized scores (single source of truth = Rust). */
  baselines(): Baselines {
    return JSON.parse(this.scorer.baselines());
  }

  /** Normalize an externally computed (cost, latency), e.g. the backend push-pull number. */
  normalizePoint(cost: number, latency: number): NormPoint {
    return JSON.parse(this.scorer.normalizePoint(cost, latency));
  }

  dispose(): void {
    this.scorer.free();
  }
}
