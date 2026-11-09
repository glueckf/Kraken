// SVG network renderer: the fog-cloud topology as a plain layered graph.
// Cloud at the top, fog nodes in the middle rows, event sources below their
// deepest parent. Nodes are placement targets; placed subqueries appear as
// small colored chips. Data-driven + full re-render on each state change
// (≤26 nodes is cheap); clicks handled by delegation.

import type { Scenario } from "./types";
import { glyphFor } from "./icons";
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
const TOP_Y = 78; // room for placed-subquery chips above the cloud
const BOTTOM_Y = VB_H - 44;
const SIDE = 44; // horizontal margin to the outermost node centers

const CLOUD_W = 96;
const CLOUD_H = 40;
const FOG_R = 22;
const SRC_H = 52;
const BADGE_R = 9.5;
const BADGE_STEP = 21;

interface Pt {
  x: number;
  y: number;
}

export interface NodeBox extends Pt {
  w: number;
  h: number;
}

export interface Layout {
  nodes: Map<number, NodeBox>;
  /** Topology edge child>parent -> the points it is drawn through, child
   * first. Two points for an edge between adjacent rows; one more per row it
   * skips, so a long edge is routed around the nodes in between instead of
   * straight through them. */
  routes: Map<string, Pt[]>;
}

const sourceWidth = (eventCount: number) => Math.max(48, eventCount * BADGE_STEP + 12);

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

  const items = new Map<number, Item>();
  const rows: Item[][] = Array.from({ length: maxRow + 1 }, () => []);
  const add = (it: Item) => {
    rows[it.row].push(it);
    return it;
  };
  for (const n of [...topo].sort((a, b) => a.id - b.id)) {
    const w = n.is_cloud ? CLOUD_W : n.is_leaf ? sourceWidth(Object.keys(n.events).length) : FOG_R * 2;
    items.set(n.id, add({ node: n.id, row: rowOf.get(n.id)!, half: w / 2, up: [], down: [], ord: 0, x: 0 }));
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

  const step = maxRow > 0 ? (BOTTOM_Y - TOP_Y) / maxRow : 0;
  const yOf = (r: number) => TOP_Y + r * step;
  const nodes = new Map<number, NodeBox>();
  for (const [id, it] of items) {
    const n = byId.get(id)!;
    const w = it.half * 2;
    nodes.set(id, { x: it.x, y: yOf(it.row), w, h: n.is_cloud ? CLOUD_H : n.is_leaf ? SRC_H : FOG_R * 2 });
  }
  const routes = new Map<string, Pt[]>();
  for (const [key, chain] of chains) routes.set(key, chain.map((it) => ({ x: it.x, y: yOf(it.row) })));
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

function eventBadges(cx: number, cy: number, letters: string[]): string {
  let out = "";
  letters.forEach((L, i) => {
    const bx = cx + (i - (letters.length - 1) / 2) * BADGE_STEP;
    out +=
      `<circle class="evt-badge" cx="${bx}" cy="${cy}" r="${BADGE_R}" fill="${glyphFor(L).color}"/>` +
      `<text class="evt-badge-tx" x="${bx}" y="${cy + 4.5}">${L}</text>`;
  });
  return out;
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

  // --- edges (behind nodes) ---
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
  let g = "";
  for (const n of nodes) {
    const { x, y, w, h } = pos(n.id);
    const isSource = view.sourceNodes.has(n.id);
    const kind = n.is_cloud ? "cloud" : n.is_leaf ? "leaf" : "fog";
    const cls = ["node", kind, isSource ? "source" : ""].filter(Boolean).join(" ");

    const label = n.is_cloud ? t().cloudName : `n${n.id}`;
    const ariaPlaced = (atNode.get(n.id) || []).length ? t().holdsSubqueries((atNode.get(n.id) || []).length) : "";
    const leafLetters = n.is_leaf ? Object.keys(n.events) : [];
    const ariaEvents = leafLetters.length ? t().producesEvents(leafLetters.join(", ")) : "";
    const aria = `${n.is_cloud ? t().cloudSink : n.is_leaf ? t().sourceNode(n.id) : t().fogNode(n.id)}${ariaPlaced}${ariaEvents}`;

    let shape: string;
    if (n.is_cloud) {
      shape =
        `<rect class="node-dot" x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="${h / 2}"/>` +
        `<text class="node-lbl" x="${x}" y="${y + 5}">${label}</text>`;
    } else if (n.is_leaf) {
      shape =
        `<rect class="node-dot" x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="7"/>` +
        `<text class="node-lbl" x="${x}" y="${y - 7}">${label}</text>` +
        eventBadges(x, y + 12, leafLetters);
    } else {
      shape =
        `<circle class="node-dot" cx="${x}" cy="${y}" r="${FOG_R}"/>` +
        `<text class="node-lbl" x="${x}" y="${y + 5}">${label}</text>`;
    }

    // placed-subquery chips above the node -- the control a player taps to
    // pick a placed subquery back up. Sized for the booth's touchscreen.
    const placed = atNode.get(n.id) || [];
    let chips = "";
    const chipH = 28;
    placed.forEach((sub, i) => {
      const m = subMeta.get(sub)!;
      const cw = 32;
      const cx = x - ((placed.length - 1) * (cw + 4)) / 2 + i * (cw + 4);
      const cy = y - h / 2 - chipH / 2 - 3;
      chips +=
        `<g class="chip" data-sub="${encodeURIComponent(sub)}" tabindex="0" role="button" aria-label="${t().subqueryChipAria(m.tag, n.id)}">` +
        `<rect x="${cx - cw / 2}" y="${cy - chipH / 2}" rx="7" width="${cw}" height="${chipH}" fill="${m.color}"/>` +
        `<text class="chip-tx" x="${cx}" y="${cy + 4}">${m.tag}${m.isRoot ? "★" : ""}</text>` +
        `</g>`;
    });

    // reveal overlay (Kraken plan): draw a ghost ring where kraken places each sub
    let ghost = "";
    if (view.reveal && Object.values(view.reveal).some((entry) => entry.node === n.id)) {
      ghost = `<rect class="ghost" x="${x - w / 2 - 7}" y="${y - h / 2 - 7}" width="${w + 14}" height="${h + 14}" rx="${Math.min(w, h) / 2 + 7}"/>`;
    }

    g += `<g class="${cls}" data-node="${n.id}" tabindex="0" role="button" aria-label="${aria}">` + ghost + shape + chips + `</g>`;
  }

  // Quiet reference tag, not UI — lets a visitor (or us, in a bug report)
  // name *this exact* concrete network ("large_b") rather than only its
  // family label, which several variants share.
  const idTag = `<text class="topo-id" x="10" y="18">${topologyId}</text>`;

  return (
    `<svg viewBox="0 0 ${VB_W} ${VB_H}" class="reef-svg" preserveAspectRatio="xMidYMid meet" role="group" aria-label="${t().topologyAria}">` +
    `<g class="edges">${edges}</g>` +
    `<g class="plan-edges">${planEdges}</g>` +
    `<g class="nodes">${g}</g>` +
    idTag +
    `</svg>`
  );
}
