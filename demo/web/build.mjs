// Build the demo: bundle the TS app with esbuild and copy static assets into dist/.
// The wasm package (vendor/engine) is copied verbatim and loaded at runtime, so the
// bundler never rewrites the wasm URL.
import * as esbuild from "esbuild";
import { cp, mkdir, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(fileURLToPath(import.meta.url));
const dist = path.join(root, "dist");
const watch = process.argv.includes("--watch");

async function copyStatics() {
  await mkdir(dist, { recursive: true });
  for (const f of ["index.html", "styles.css"]) {
    await cp(path.join(root, f), path.join(dist, f));
  }
  await cp(path.join(root, "scenarios"), path.join(dist, "scenarios"), { recursive: true });
  const engine = path.join(root, "vendor", "engine");
  if (!existsSync(path.join(engine, "kraken_engine.js"))) {
    console.error("\n[build] missing vendor/engine — run `npm run build:wasm` first.\n");
    process.exit(1);
  }
  await cp(engine, path.join(dist, "vendor", "engine"), {
    recursive: true,
    filter: (src) => !src.endsWith(".gitignore"),
  });
}

const options = {
  entryPoints: [path.join(root, "src", "main.ts")],
  bundle: true,
  format: "esm",
  outfile: path.join(dist, "app.js"),
  minify: !watch,
  sourcemap: true,
  target: ["es2020"],
  logLevel: "info",
};

await rm(dist, { recursive: true, force: true });
await copyStatics();

if (watch) {
  const ctx = await esbuild.context(options);
  await ctx.watch();
  console.log("[build] watching… (statics copied once; re-run for asset changes)");
} else {
  await esbuild.build(options);
  console.log("[build] done -> dist/");
}
