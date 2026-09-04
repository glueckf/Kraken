// Minimal zero-dependency static server for dist/. Serves .wasm as application/wasm
// (required for WebAssembly streaming instantiation). For local preview only.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "dist");
const port = Number(process.env.PORT || 5173);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".wasm": "application/wasm",
  ".map": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://localhost:${port}`);
    let rel = decodeURIComponent(url.pathname);
    if (rel.endsWith("/")) rel += "index.html";
    let file = path.join(root, rel);
    if (!file.startsWith(root)) {
      res.writeHead(403).end("forbidden");
      return;
    }
    let body;
    try {
      const s = await stat(file);
      if (s.isDirectory()) file = path.join(file, "index.html");
      body = await readFile(file);
    } catch {
      file = path.join(root, "index.html"); // SPA fallback
      body = await readFile(file);
    }
    res.writeHead(200, {
      "Content-Type": MIME[path.extname(file)] || "application/octet-stream",
      "Cache-Control": "no-cache",
    });
    res.end(body);
  } catch (e) {
    res.writeHead(500).end(String(e));
  }
});

server.listen(port, () => console.log(`[serve] http://localhost:${port}`));
