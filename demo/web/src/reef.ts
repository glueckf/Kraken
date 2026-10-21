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
const BOTTOM_MARGIN = 92; // leaf-row petals (up to r*0.95+petalR below center) + the event legend strip

export type Layout = Map<number, { x: number; y: number; r: number }>;

export function computeLayout(scenario: Scenario): Layout {
  const layout: Layout = new Map();
  const byLayer = new Map<number, number[]>();
  const nodeById = new Map(scenario.topology.nodes.map((n) => [n.id, n]));
  for (const n of scenario.topology.nodes) {
    if (!byLayer.has(n.layer)) byLayer.set(n.layer, []);
    byLayer.get(n.layer)!.push(n.id);
  }
  // Rows are spaced evenly across the whole canvas height, based on however
  // many layers THIS scenario actually has — different network sizes have
  // different depths (levels ≈ log2(node count)), so a fixed 4-row table
  // would overflow (or waste space) for other sizes.
  const maxLayer = Math.max(...byLayer.keys());
  const step = maxLayer > 0 ? (VB_H - BOTTOM_MARGIN - TOP_Y) / maxLayer : 0;
  for (const [layer, ids] of byLayer) {
    ids.sort((a, b) => a - b);
    const y = TOP_Y + layer * step;
    const count = ids.length;
    const margin = 96;
    const span = VB_W - margin * 2;
    ids.forEach((id, i) => {
      const x = count === 1 ? VB_W / 2 : margin + (span * i) / (count - 1);
      const r = layer === 0 ? 40 : nodeById.get(id)!.is_leaf ? 24 : 30;
      layout.set(id, { x, y, r });
    });
  }
  return layout;
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const my = (a.y + b.y) / 2;
  return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
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

function towerShape(cx: number, cy: number, r: number): string {
  // The reference tower illustration, standing on the node's round base.
  // Replaces the old hand-drawn SVG silhouette (tapered body/roof/window/flag),
  // which still read as too abstract next to the talk's own reference art.
  const h = r * 3.3;
  const w = h * TOWER_IMG_ASPECT;
  const bottomY = cy + r * 0.85; // nudged down toward the source-node row below, still clears row-to-row spacing
  const x = cx - w / 2;
  const y = bottomY - h;
  return (
    `<image class="tower-img" href="assets/tower.png" x="${x}" y="${y}" ` +
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

export function renderReef(scenario: Scenario, layout: Layout, subMeta: Map<string, SubMeta>, view: ReefView): string {
  const nodes = scenario.topology.nodes;
  const pos = (id: number) => layout.get(id)!;

  // placement map: node -> subqueries there
  const atNode = new Map<number, string[]>();
  for (const [sub, node] of Object.entries(view.placement)) {
    if (!atNode.has(node)) atNode.set(node, []);
    atNode.get(node)!.push(sub);
  }

  // --- edges (behind nodes) ---
  let edges = "";
  for (const n of nodes) {
    for (const p of n.parents) {
      const a = pos(n.id);
      const b = pos(p);
      edges += `<path class="edge" d="${edgePath(a, b)}" />`;
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
      const a = pos(u);
      const b = pos(v);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const len = Math.hypot(dx, dy) || 1;
      const perp = { x: -dy / len, y: dx / len };
      const entries = [...deps.entries()];
      entries.forEach(([dep, role], i) => {
        const offset = (i - (entries.length - 1) / 2) * FAN_GAP;
        const oa = { x: a.x + perp.x * offset, y: a.y + perp.y * offset };
        const ob = { x: b.x + perp.x * offset, y: b.y + perp.y * offset };
        const d = edgePath(oa, ob);
        const color = depColor(dep);
        const stroke = `<path class="plan-edge ${role}" d="${d}" style="stroke:${color}"/>`;
        if (role === "pull") pullOverlay += stroke;
        else pushOverlay += stroke;
      });
    }
    planEdges = pullOverlay + pushOverlay;
  }

  // --- nodes ---
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

    const label = n.is_cloud ? t().cloudName : `n${n.id}`;
    const ariaPlaced = (atNode.get(n.id) || []).length ? t().holdsSubqueries((atNode.get(n.id) || []).length) : "";
    const leafLetters = n.is_leaf ? Object.keys(n.events) : [];
    const ariaEvents = leafLetters.length ? t().producesEvents(leafLetters.join(", ")) : "";
    const aria = `${n.is_cloud ? t().cloudSink : n.is_leaf ? t().sourceNode(n.id) : t().watchtower(n.id)}${ariaPlaced}${ariaEvents}`;

    let shape: string;
    let cloudBox: CloudBox | null = null;
    if (n.is_cloud) {
      cloudBox = cloudImageBox(x, y);
      shape =
        `<image class="cloud-img" href="assets/kingcloud.png" x="${cloudBox.x}" y="${cloudBox.y}" ` +
        `width="${cloudBox.w}" height="${cloudBox.h}" preserveAspectRatio="xMidYMax meet"/>`;
    } else if (n.is_leaf) {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>` + eventPetals(x, y, r, leafLetters);
    } else {
      // A small foundation, not the tower itself — the old full-size circle
      // read as "the shape", with the tower as decoration on top of a ball.
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r * 0.62}"/>` + towerShape(x, y, r);
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

  return (
    `<svg viewBox="0 0 ${VB_W} ${VB_H}" class="reef-svg" preserveAspectRatio="xMidYMid meet" role="group" aria-label="${t().topologyAria}">` +
    background() +
    `<g class="edges">${edges}</g>` +
    `<g class="plan-edges">${planEdges}</g>` +
    `<g class="nodes">${g}</g>` +
    eventLegend(Object.keys(scenario.event_map.producers)) +
    `</svg>`
  );
}
