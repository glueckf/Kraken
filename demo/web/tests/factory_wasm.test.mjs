// Checks the shipped Rust/WASM scorer (vendor/engine) against the exported
// paper-example round, without a browser or a Rust toolchain:
//   1. its all-push model reproduces every all-push cell of the decision
//      table (the goldens the exporter cross-checked against the engine), and
//   2. its normalised score equals the paper's F(s) (Sec. 4.3.2, min-max over
//      the candidate pool) for every cell at every stage alpha, so the
//      on-screen ranking is the same function the enumeration minimises.
// Run from demo/web:  npm test   (= node --test tests/factory_wasm.test.mjs)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, "..");
const mod = await import(path.join(web, "vendor/engine/kraken_engine.js"));
await mod.default({ module_or_path: await readFile(path.join(web, "vendor/engine/kraken_engine_bg.wasm")) });
const scenario = JSON.parse(await readFile(path.join(web, "scenarios/factory/factory_join.json"), "utf8"));
const table = scenario.paper_round.decision_table;
const sub = scenario.processing_order[0];

function paperF(d, alpha) {
  const cs = table.map((x) => x.cost), ls = table.map((x) => x.latency);
  const [vmin, vmax, lmin, lmax] = [Math.min(...cs), Math.max(...cs), Math.min(...ls), Math.max(...ls)];
  const vn = vmax === vmin ? 0 : (d.cost - vmin) / (vmax - vmin);
  const ln = lmax === lmin ? 0 : (d.latency - lmin) / (lmax - lmin);
  return alpha * vn + (1 - alpha) * ln;
}

test("WASM all-push scorer reproduces every all-push cell", () => {
  const scorer = new mod.Scorer(JSON.stringify(scenario));
  const cells = table.filter((d) => d.scheme === "all_push");
  assert.equal(cells.length, 3);
  for (const d of cells) {
    const r = JSON.parse(scorer.score(JSON.stringify({ [sub]: d.node })));
    assert.ok(Math.abs(r.total_cost - d.cost) < 1e-6, `node ${d.node}: ${r.total_cost} != ${d.cost}`);
    assert.ok(Math.abs(r.total_latency - d.latency) < 1e-6, `node ${d.node}: latency`);
  }
  scorer.free();
});

test("displayed score is the paper's F for every cell and stage", () => {
  const scorer = new mod.Scorer(JSON.stringify(scenario));
  for (const stage of scenario.kraken_stages) {
    scorer.setCostWeight(stage.alpha);
    for (const d of table) {
      const np = JSON.parse(scorer.normalizePoint(d.cost, d.latency));
      assert.ok(Math.abs(np.score - paperF(d, stage.alpha)) < 1e-9, `alpha ${stage.alpha} ${d.node}/${d.scheme}`);
    }
    const best = Math.min(...table.map((d) => paperF(d, stage.alpha)));
    const k = JSON.parse(scorer.normalizePoint(stage.cost, stage.latency));
    assert.ok(Math.abs(k.score - best) < 1e-9, `Kraken at alpha ${stage.alpha} is not the enumeration minimum`);
  }
  scorer.free();
});

test("existing reef rounds still load in the scorer", async () => {
  const manifest = JSON.parse(await readFile(path.join(web, "scenarios/manifest.json"), "utf8"));
  // Not a fixed id list: topologies.py adds variant networks (different
  // seed/size) per family over time, so only the families themselves --
  // the ones the topology bar actually shows a button for -- are pinned.
  const families = new Set(manifest.topologies.map((t) => t.family));
  assert.deepEqual(families, new Set(["medium", "large", "factory"]));
  for (const topo of manifest.topologies) {
    for (const s of topo.scenarios) {
      const sc = JSON.parse(await readFile(path.join(web, "scenarios", s.file), "utf8"));
      const scorer = new mod.Scorer(JSON.stringify(sc));
      const bl = JSON.parse(scorer.baselines());
      assert.ok("kraken" in bl && "all_push" in bl && "sequential" in bl, s.file);
      scorer.free();
    }
  }
});
