// SVG "reef" renderer: the fog-cloud topology. Cloud at the top (a cloud), fog
// towers in the middle layers, event-source pods on the seabed. Nodes are placement
// targets; placed subqueries appear as small colored chips. Data-driven + full
// re-render on each state change (12 nodes is cheap); clicks handled by delegation.

import type { Scenario } from "./types";
import { eventIconGroup, glyphFor } from "./icons";
import { t } from "./i18n";

export interface SubMeta {
  idx: number;
  tag: string;
  color: string;
  isRoot: boolean;
}

export interface RevealEntry {
  node: number;
  edges?: Record<string, "push" | "pull">; // dep name -> how it's acquired
}

export interface ReefView {
  placement: Record<string, number>;
  activeSubquery: string | null;
  sourceNodes: Set<number>; // leaves/deps feeding the active subquery
  reveal: Record<string, RevealEntry> | null; // Kraken plan overlay, or null
}

const VB_W = 1000;
const VB_H = 640;
const TOP_Y = 86; // leaves room for König Cloud's crown above the topmost row
const BOTTOM_Y = VB_H - 92; // leaf-row petals (up to r*0.95+petalR below center) + the event legend strip
const SIDE = 56; // horizontal margin to the outermost node centers

const CLOUD_R = 40;
const FOG_R = 30;
const LEAF_R = 24;

interface Pt {
  x: number;
  y: number;
}

export interface Layout {
  nodes: Map<number, { x: number; y: number; r: number }>;
  /** Topology edge child>parent -> the points it is drawn through, child
   * first. Two points for an edge between adjacent rows; one more per row it
   * skips, so a long edge is routed around the nodes in between instead of
   * straight through them. */
  routes: Map<string, Pt[]>;
}

// Half the width each node takes up in its row: the scenery, not just the
// dot -- a watchtower image is far wider than its foundation.
const towerHalf = (r: number) => (r * 3.3 * TOWER_IMG_ASPECT) / 2;
const leafHalf = (r: number) => r * 0.95 + r * 0.34; // petal ring

interface Item {
  node: number | null; // null = routing point of a long edge
  row: number;
  half: number;
  up: Item[];
  down: Item[];
  ord: number;
  x: number;
}

/** Positions that keep `gaps[i]` between items i-1 and i, within [lo, hi],
 * as close as possible (least squares) to `desired`: isotonic regression on
 * desired - cumulative gap (pool adjacent violators). */
function fitRow(desired: number[], gaps: number[], lo: number, hi: number): number[] {
  const n = desired.length;
  const c = [0];
  for (let i = 1; i < n; i++) c.push(c[i - 1] + gaps[i]);
  const total = c[n - 1];
  if (total >= hi - lo) {
    const s = n > 1 ? (hi - lo) / total : 0;
    return c.map((ci) => (n > 1 ? lo + ci * s : (lo + hi) / 2));
  }
  const blocks: { sum: number; cnt: number }[] = [];
  for (let i = 0; i < n; i++) {
    blocks.push({ sum: desired[i] - c[i], cnt: 1 });
    while (blocks.length > 1) {
      const b = blocks[blocks.length - 1];
      const a = blocks[blocks.length - 2];
      if (a.sum / a.cnt <= b.sum / b.cnt) break;
      a.sum += b.sum;
      a.cnt += b.cnt;
      blocks.pop();
    }
  }
  const out: number[] = [];
  for (const b of blocks) for (let k = 0; k < b.cnt; k++) out.push(b.sum / b.cnt);
  return out.map((y, i) => Math.min(Math.max(y + c[i], lo + c[i]), hi - (total - c[i])));
}

/**
 * Layered layout (Sugiyama-style). Rows are the longest path from the cloud,
 * so every edge points at least one row up; an edge that skips rows gets a
 * routing point in each skipped row, which takes a slot like a node does.
 * That is what keeps edges visible: in the old layout every source sat on
 * the bottom row, and an edge from a source to a parent several rows up ran
 * straight through the nodes in between (dunes n7->n3 behind n4, large_b
 * n6->n3 behind n5), so visitors read the wrong parent.
 */
export function computeLayout(scenario: Scenario): Layout {
  const topo = scenario.topology.nodes;
  const byId = new Map(topo.map((n) => [n.id, n]));

  const rowOf = new Map<number, number>();
  const visiting = new Set<number>();
  const rowFor = (id: number): number => {
    const known = rowOf.get(id);
    if (known !== undefined) return known;
    const n = byId.get(id)!;
    if (n.is_cloud || !n.parents.length || visiting.has(id)) return n.layer;
    visiting.add(id);
    const r = 1 + Math.max(...n.parents.map(rowFor));
    visiting.delete(id);
    rowOf.set(id, r);
    return r;
  };
  for (const n of topo) rowOf.set(n.id, rowFor(n.id));
  const maxRow = Math.max(...rowOf.values());
  const step = maxRow > 0 ? (BOTTOM_Y - TOP_Y) / maxRow : 0;
  // A tower reaches up toward the row above. In the deep (5-6 row) Barrier
  // Reefs it reached the parent's foundation, so a child right below its
  // parent hid the edge between them. Smaller fog nodes there keep a gap;
  // the 4-row networks keep the full size.
  const fogR = Math.min(FOG_R, (step - 13) / 3.3);

  const items = new Map<number, Item>();
  const rows: Item[][] = Array.from({ length: maxRow + 1 }, () => []);
  const add = (it: Item) => {
    rows[it.row].push(it);
    return it;
  };
  for (const n of [...topo].sort((a, b) => a.id - b.id)) {
    const half = n.is_cloud ? cloudImageBox(0, 0).w / 2 : n.is_leaf ? leafHalf(LEAF_R) : towerHalf(fogR);
    items.set(n.id, add({ node: n.id, row: rowOf.get(n.id)!, half, up: [], down: [], ord: 0, x: 0 }));
  }
  const chains = new Map<string, Item[]>();
  for (const n of topo) {
    for (const p of n.parents) {
      const chain = [items.get(n.id)!];
      for (let r = rowOf.get(n.id)! - 1; r > rowOf.get(p)!; r--) {
        chain.push(add({ node: null, row: r, half: 3, up: [], down: [], ord: 0, x: 0 }));
      }
      chain.push(items.get(p)!);
      for (let i = 0; i < chain.length - 1; i++) {
        chain[i].up.push(chain[i + 1]);
        chain[i + 1].down.push(chain[i]);
      }
      chains.set(`${n.id}>${p}`, chain);
    }
  }

  // --- order within rows: barycenter sweeps, keeping the fewest crossings ---
  const renumber = (row: Item[]) => row.forEach((it, i) => (it.ord = i));
  const sortRow = (row: Item[], dir: "up" | "down") => {
    const key = new Map(
      row.map((it) => {
        const nb = it[dir];
        return [it, nb.length ? nb.reduce((s, o) => s + o.ord, 0) / nb.length : it.ord] as const;
      }),
    );
    row.sort((a, b) => key.get(a)! - key.get(b)! || a.ord - b.ord);
    renumber(row);
  };
  const crossings = () => {
    let k = 0;
    for (let r = 1; r <= maxRow; r++) {
      const es: [number, number][] = [];
      for (const it of rows[r]) for (const u of it.up) if (u.row === r - 1) es.push([u.ord, it.ord]);
      for (let i = 0; i < es.length; i++)
        for (let j = i + 1; j < es.length; j++)
          if ((es[i][0] - es[j][0]) * (es[i][1] - es[j][1]) < 0) k++;
    }
    return k;
  };
  rows.forEach(renumber);
  for (let r = 1; r <= maxRow; r++) sortRow(rows[r], "up");
  let best = rows.map((row) => row.slice());
  let bestK = crossings();
  for (let sweep = 0; sweep < 12 && bestK > 0; sweep++) {
    if (sweep % 2) for (let r = 1; r <= maxRow; r++) sortRow(rows[r], "up");
    else for (let r = maxRow - 1; r >= 0; r--) sortRow(rows[r], "down");
    const k = crossings();
    if (k < bestK) {
      bestK = k;
      best = rows.map((row) => row.slice());
    }
  }
  best.forEach((row, r) => {
    rows[r] = row;
    renumber(row);
  });

  // --- x: as close to the neighbors as the spacing allows ---
  const lo = SIDE;
  const hi = VB_W - SIDE;
  // One padding for the whole figure, as wide as the fullest row allows, so
  // sparse rows don't huddle while the canvas sits empty.
  let pad = 110;
  for (const row of rows) {
    if (row.length < 2) continue;
    const widths = row.reduce((s, it) => s + it.half * 2, 0) - row[0].half - row[row.length - 1].half;
    pad = Math.min(pad, (hi - lo - widths) / (row.length - 1));
  }
  pad = Math.max(pad, 10);
  const gapsOf = (row: Item[]) => row.map((it, i) => (i ? row[i - 1].half + it.half + pad : 0));
  for (const row of rows) {
    const g = gapsOf(row);
    const total = g.reduce((s, v) => s + v, 0);
    let x = VB_W / 2 - total / 2;
    row.forEach((it, i) => {
      x += g[i];
      it.x = x;
    });
  }
  const place = (row: Item[], nbrs: (it: Item) => Item[]) => {
    const desired = row.map((it) => {
      const nb = nbrs(it);
      return nb.length ? nb.reduce((s, o) => s + o.x, 0) / nb.length : it.x;
    });
    fitRow(desired, gapsOf(row), lo, hi).forEach((x, i) => (row[i].x = x));
  };
  for (let pass = 0; pass < 16; pass++) {
    if (pass % 2) for (let r = maxRow; r >= 0; r--) place(rows[r], (it) => it.down);
    else for (let r = 0; r <= maxRow; r++) place(rows[r], (it) => it.up);
  }
  for (let pass = 0; pass < 4; pass++) for (const row of rows) place(row, (it) => [...it.up, ...it.down]);

  // The passes above only keep the spacing; nothing anchors the drawing, so
  // it can drift to one side. Stretch it to the full width, centered --
  // stretching only widens gaps, so order and spacing stay valid.
  const all = rows.flat();
  const cl = Math.min(...all.map((it) => it.x));
  const cr = Math.max(...all.map((it) => it.x));
  const maxHalf = Math.max(...all.map((it) => it.half));
  if (cr > cl) {
    const s = Math.min(2.5, Math.max(1, (VB_W - 2 * 16 - 2 * maxHalf) / (cr - cl)));
    const mid = (cl + cr) / 2;
    for (const it of all) it.x = VB_W / 2 + (it.x - mid) * s;
  }

  const yOf = (r: number) => TOP_Y + r * step;
  const nodes = new Map<number, { x: number; y: number; r: number }>();
  for (const [id, it] of items) {
    const n = byId.get(id)!;
    nodes.set(id, { x: it.x, y: yOf(it.row), r: n.is_cloud ? CLOUD_R : n.is_leaf ? LEAF_R : fogR });
  }
  // Edges into the cloud end at the bottom of König Cloud's island, which
  // is drawn under the edges (see renderReef).
  const anchor = (it: Item): Pt => {
    const y = yOf(it.row);
    if (it.node === null || !byId.get(it.node)!.is_cloud) return { x: it.x, y };
    const box = cloudImageBox(it.x, y);
    return { x: it.x, y: box.y + box.h };
  };
  const routes = new Map<string, Pt[]>();
  for (const [key, chain] of chains) routes.set(key, chain.map(anchor));
  return { nodes, routes };
}

/** A smooth curve through the route points; vertical tangents at every point
 * keep the joins at routing points seamless. */
function routePath(pts: Pt[]): string {
  let d = `M ${pts[0].x} ${pts[0].y}`;
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1];
    const b = pts[i];
    const my = (a.y + b.y) / 2;
    d += ` C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
  }
  return d;
}

/** The route shifted sideways by `off` (perpendicular to its chords). */
function offsetRoute(pts: Pt[], off: number): Pt[] {
  if (!off) return pts;
  const normals = pts.slice(1).map((b, i) => {
    const a = pts[i];
    const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    return { x: -(b.y - a.y) / len, y: (b.x - a.x) / len };
  });
  return pts.map((p, i) => {
    const ns = [normals[i - 1], normals[i]].filter(Boolean);
    const nx = ns.reduce((s, n) => s + n.x, 0);
    const ny = ns.reduce((s, n) => s + n.y, 0);
    const len = Math.hypot(nx, ny) || 1;
    return { x: p.x + (nx / len) * off, y: p.y + (ny / len) * off };
  });
}

// Aspect ratio of assets/kingcloud.png (the reference island scene — cloud,
// crown, castle, pool, palms, cliff and coral all in one), cropped to its
// opaque bounds. Replaces the old hand-drawn island/castle/pool/palm SVG
// group entirely, same reasoning as the tower image swap: the talk's own
// reference art read better than iterating on SVG geometry.
const CLOUD_IMG_ASPECT = 640 / 606;

interface CloudBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

function cloudImageBox(cx: number, cy: number): CloudBox {
  const h = 105;
  const w = h * CLOUD_IMG_ASPECT;
  const bottomY = cy + 30; // clears the row-1 fog towers even on the tightest (24-node) layout
  const y = bottomY - h;
  return { x: cx - w / 2, y, w, h };
}

// Aspect ratio of assets/tower.png (a hand-picked reef-watchtower illustration,
// cropped to its opaque bounds) — needed to size the <image> without distortion.
const TOWER_IMG_ASPECT = 431 / 480;

function towerShape(cx: number, cy: number, r: number, node: number): string {
  // The reference tower illustration, standing on the node's round base.
  // Replaces the old hand-drawn SVG silhouette (tapered body/roof/window/flag),
  // which still read as too abstract next to the talk's own reference art.
  const h = r * 3.3;
  const w = h * TOWER_IMG_ASPECT;
  const bottomY = cy + r * 0.85; // nudged down toward the source-node row below, still clears row-to-row spacing
  const x = cx - w / 2;
  const y = bottomY - h;
  return (
    `<image class="tower-img" data-node="${node}" href="assets/tower.png" x="${x}" y="${y}" ` +
    `width="${w}" height="${h}" preserveAspectRatio="xMidYMax meet"/>`
  );
}

function eventPetals(cx: number, cy: number, r: number, letters: string[]): string {
  // One petal per event type the source actually produces — each a small
  // disc in that event's own color with its glyph in white on top (same
  // "colored chip, white icon" language as the dependency pills elsewhere),
  // arranged in a ring around the node so a source producing several event
  // types (the common case — most leaves emit 2-4, not 1) shows all of them
  // at a glance instead of one average/arbitrary color. Replaces the old
  // fixed-count, uncolored decorative "coral" ring.
  let out = "";
  const n = letters.length;
  const petalR = r * 0.34;
  letters.forEach((L, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const px = cx + Math.cos(a) * r * 0.95;
    const py = cy + Math.sin(a) * r * 0.95;
    out +=
      `<circle class="evt-petal" cx="${px}" cy="${py}" r="${petalR}" fill="${glyphFor(L).color}"/>` +
      eventIconGroup(L, px, py, petalR * 1.5, "#fff");
  });
  return out;
}

function eventLegend(letters: string[]): string {
  // One static key for the whole figure — same colored-dot-plus-white-icon
  // language as eventPetals, just once instead of repeated on every node —
  // so the petals' colors stay readable without crowding a letter onto each
  // small petal individually (tight already at up to 5 petals per node).
  const sorted = [...letters].sort();
  const dot = 11;
  const gap = 58;
  const totalW = (sorted.length - 1) * gap;
  const startX = VB_W / 2 - totalW / 2;
  const cy = VB_H - 24;
  let out = "";
  sorted.forEach((L, i) => {
    const cx = startX + i * gap;
    out +=
      `<circle class="legend-dot" cx="${cx}" cy="${cy}" r="${dot}" fill="${glyphFor(L).color}"/>` +
      eventIconGroup(L, cx, cy, dot * 1.5, "#fff") +
      `<text class="legend-lbl" x="${cx + dot + 6}" y="${cy + 5}">${L}</text>`;
  });
  return `<g class="event-legend" aria-hidden="true">${out}</g>`;
}

function background(): string {
  return (
    `<defs>` +
    `<linearGradient id="seaGrad" x1="0" y1="0" x2="0" y2="1">` +
    `<stop offset="0%" style="stop-color:var(--sea-light)"/>` +
    `<stop offset="55%" style="stop-color:var(--sea-mid)"/>` +
    `<stop offset="100%" style="stop-color:var(--sea-deep)"/>` +
    `</linearGradient>` +
    `<radialGradient id="sunGlow" cx="50%" cy="4%" r="65%">` +
    `<stop offset="0%" style="stop-color:var(--sun);stop-opacity:0.4"/>` +
    `<stop offset="100%" style="stop-color:var(--sun);stop-opacity:0"/>` +
    `</radialGradient>` +
    `</defs>` +
    `<rect x="0" y="0" width="${VB_W}" height="${VB_H}" fill="url(#seaGrad)"/>` +
    `<rect x="0" y="0" width="${VB_W}" height="${VB_H}" fill="url(#sunGlow)"/>` +
    `<g class="coral-decor" aria-hidden="true">` +
    `<path d="M0 ${VB_H} v-52 q42 -32 84 -6 q32 -22 64 4 q54 -36 106 -2 v56 z"/>` +
    `<path d="M${VB_W} ${VB_H} v-46 q-48 -28 -96 -4 q-28 -20 -60 2 q-58 -30 -110 0 v48 z"/>` +
    `</g>`
  );
}

export function renderReef(scenario: Scenario, layout: Layout, subMeta: Map<string, SubMeta>, view: ReefView, topologyId: string): string {
  const nodes = scenario.topology.nodes;
  const pos = (id: number) => layout.nodes.get(id)!;
  const routeBetween = (u: number, v: number): Pt[] => {
    const fwd = layout.routes.get(`${u}>${v}`);
    if (fwd) return fwd;
    const back = layout.routes.get(`${v}>${u}`);
    return back ? [...back].reverse() : [pos(u), pos(v)];
  };

  // placement map: node -> subqueries there
  const atNode = new Map<number, string[]>();
  for (const [sub, node] of Object.entries(view.placement)) {
    if (!atNode.has(node)) atNode.set(node, []);
    atNode.get(node)!.push(sub);
  }

  // --- edges (behind nodes, above the scenery) ---
  // data-from/data-to name both ends of this one link, so hovering a node
  // can highlight every link it has.
  let edges = "";
  for (const n of nodes) {
    for (const p of n.parents) {
      edges += `<path class="edge" data-from="${n.id}" data-to="${p}" d="${routePath(routeBetween(n.id, p))}" />`;
    }
  }

  // --- Kraken plan overlay: highlight *existing* topology edges push/pull,
  // rather than drawing new point-to-point lines that don't correspond to
  // any real link. A dependency's data travels along the actual tree path
  // (possibly several hops) between its source and where Kraken placed the
  // consumer, so each hop on that path gets colored, not just the endpoints.
  let planEdges = "";
  if (view.reveal) {
    const reveal = view.reveal;
    const adjacency = new Map<number, number[]>();
    const link = (u: number, v: number) => {
      if (!adjacency.has(u)) adjacency.set(u, []);
      adjacency.get(u)!.push(v);
    };
    for (const n of nodes) for (const p of n.parents) { link(n.id, p); link(p, n.id); }

    const pathBetween = (start: number, goal: number): number[] | null => {
      if (start === goal) return [start];
      const prev = new Map<number, number>();
      const queue = [start];
      const seen = new Set([start]);
      for (let i = 0; i < queue.length; i++) {
        const u = queue[i];
        if (u === goal) break;
        for (const v of adjacency.get(u) ?? []) {
          if (seen.has(v)) continue;
          seen.add(v);
          prev.set(v, u);
          queue.push(v);
        }
      }
      if (!seen.has(goal)) return null;
      const path = [goal];
      while (path[path.length - 1] !== start) path.push(prev.get(path[path.length - 1])!);
      return path.reverse();
    };

    const depColor = (dep: string) => subMeta.get(dep)?.color ?? glyphFor(dep).color;

    // hop key -> dep name -> role, across every dependency edge. Keyed by
    // dep (not just role) so two different event types crossing the same
    // physical link each keep their own identity/color instead of
    // collapsing into one push/pull line.
    const hopDeps = new Map<string, Map<string, "push" | "pull">>();
    for (const proj of scenario.projections) {
      const here = reveal[proj.name];
      if (!here) continue;
      for (const dep of proj.deps) {
        const role = here.edges?.[dep] ?? "push";
        const sources = reveal[dep] ? [reveal[dep].node] : scenario.event_map.producers[dep] ?? [];
        for (const srcId of sources) {
          const path = pathBetween(srcId, here.node);
          if (!path) continue;
          for (let i = 0; i < path.length - 1; i++) {
            const key = `${Math.min(path[i], path[i + 1])}-${Math.max(path[i], path[i + 1])}`;
            if (!hopDeps.has(key)) hopDeps.set(key, new Map());
            hopDeps.get(key)!.set(dep, role);
          }
        }
      }
    }

    // A hop shared by several event types fans them out as parallel offset
    // strokes (each keeping its own event-type color) rather than
    // collapsing to one line, so which event is pushed/pulled stays legible
    // even where paths converge (e.g. trunk hops near the cloud). Solid
    // pushes are grouped after dashed pulls only so a push's opaque stroke
    // isn't hidden under an adjacent pull's dash gaps at the fan's edges.
    const FAN_GAP = 5;
    let pullOverlay = "";
    let pushOverlay = "";
    for (const [key, deps] of hopDeps) {
      const [u, v] = key.split("-").map(Number);
      const route = routeBetween(u, v);
      const entries = [...deps.entries()];
      entries.forEach(([dep, role], i) => {
        const offset = (i - (entries.length - 1) / 2) * FAN_GAP;
        const d = routePath(offsetRoute(route, offset));
        const stroke = `<path class="plan-edge ${role}" d="${d}" style="stroke:${depColor(dep)}"/>`;
        if (role === "pull") pullOverlay += stroke;
        else pushOverlay += stroke;
      });
    }
    planEdges = pullOverlay + pushOverlay;
  }

  // --- nodes ---
  // The tower and König Cloud images go in their own layer under the edges:
  // they are much bigger than the node itself, and on top they hid any edge
  // passing behind them. data-node keeps them tappable like the node.
  let scenery = "";
  let g = "";
  for (const n of nodes) {
    const { x, y, r } = pos(n.id);
    const isSource = view.sourceNodes.has(n.id);
    const cls = [
      "node",
      n.is_cloud ? "cloud" : n.is_leaf ? "leaf" : "fog",
      isSource ? "source" : "",
    ]
      .filter(Boolean)
      .join(" ");

    // Paper round sources used to carry special names ("Machine A", "Panel
    // B") -- dropped so every source node reads the same way across every
    // round: just its letter, like the Reef rounds. Fog nodes already keep
    // n1/n2, which happen to match the paper's own node numbers 1 and 2.
    const label = n.is_cloud ? t().cloudName : `n${n.id}`;
    const ariaPlaced = (atNode.get(n.id) || []).length ? t().holdsSubqueries((atNode.get(n.id) || []).length) : "";
    const leafLetters = n.is_leaf ? Object.keys(n.events) : [];
    const ariaEvents = leafLetters.length ? t().producesEvents(leafLetters.join(", ")) : "";
    const aria = `${n.is_cloud ? t().cloudSink : n.is_leaf ? t().sourceNode(n.id) : t().watchtower(n.id)}${ariaPlaced}${ariaEvents}`;

    let shape = "";
    let cloudBox: CloudBox | null = null;
    if (n.is_cloud) {
      cloudBox = cloudImageBox(x, y);
      scenery +=
        `<image class="cloud-img" data-node="${n.id}" href="assets/kingcloud.png" x="${cloudBox.x}" y="${cloudBox.y}" ` +
        `width="${cloudBox.w}" height="${cloudBox.h}" preserveAspectRatio="xMidYMax meet"/>`;
    } else if (n.is_leaf) {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>` + eventPetals(x, y, r, leafLetters);
    } else {
      // A small foundation, not the tower itself — the old full-size circle
      // read as "the shape", with the tower as decoration on top of a ball.
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r * 0.62}"/>`;
      scenery += towerShape(x, y, r, n.id);
    }

    // placed-subquery chips near the node -- the control a player taps to
    // pick a placed subquery back up. Sized up from the original 26x22 for
    // the booth's touchscreen, same reasoning as the push/pull chips.
    const placed = atNode.get(n.id) || [];
    let chips = "";
    const chipH = 28;
    placed.forEach((sub, i) => {
      const m = subMeta.get(sub)!;
      const cw = 32;
      const cx = x - ((placed.length - 1) * (cw + 4)) / 2 + i * (cw + 4);
      const cy = y - r - chipH / 2 - 3;
      chips +=
        `<g class="chip" data-sub="${encodeURIComponent(sub)}" tabindex="0" role="button" aria-label="${t().subqueryChipAria(m.tag, n.id)}">` +
        `<rect x="${cx - cw / 2}" y="${cy - chipH / 2}" rx="7" width="${cw}" height="${chipH}" fill="${m.color}"/>` +
        `<text class="chip-tx" x="${cx}" y="${cy + 4}">${m.tag}${m.isRoot ? "★" : ""}</text>` +
        `</g>`;
    });

    // reveal overlay (Kraken plan): draw a ghost ring where kraken places each sub
    let ghost = "";
    if (view.reveal) {
      const here = Object.values(view.reveal).filter((entry) => entry.node === n.id);
      if (here.length) {
        ghost = `<circle class="ghost" cx="${x}" cy="${y}" r="${r + 8}"/>`;
      }
    }

    g +=
      `<g class="${cls}" data-node="${n.id}" tabindex="0" role="button" aria-label="${aria}">` +
      ghost +
      shape +
      `<text class="node-lbl${n.is_cloud ? " on-isle" : ""}" x="${x}" y="${cloudBox ? cloudBox.y + cloudBox.h + 13 : y + 5}">${label}</text>` +
      chips +
      `</g>`;
  }

  // Quiet reference tag, not UI — lets a visitor (or us, in a bug report)
  // name *this exact* concrete network ("id large_b") rather than only its
  // family label ("Grand Reef"), which several variants share.
  const idTag = `<text class="topo-id" x="${VB_W - 10}" y="${VB_H - 10}" text-anchor="end">${topologyId}</text>`;

  return (
    `<svg viewBox="0 0 ${VB_W} ${VB_H}" class="reef-svg" preserveAspectRatio="xMidYMid meet" role="group" aria-label="${t().topologyAria}">` +
    background() +
    `<g class="scenery">${scenery}</g>` +
    `<g class="edges">${edges}</g>` +
    `<g class="plan-edges">${planEdges}</g>` +
    `<g class="nodes">${g}</g>` +
    eventLegend(Object.keys(scenario.event_map.producers)) +
    idTag +
    `</svg>`
  );
}
