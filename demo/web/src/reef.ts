// SVG "reef" renderer: the fog-cloud topology. Cloud at the top (a cloud), fog
// towers in the middle layers, event-source pods on the seabed. Nodes are placement
// targets; placed subqueries appear as small colored chips. Data-driven + full
// re-render on each state change (12 nodes is cheap); clicks handled by delegation.

import type { Scenario } from "./types";
import { eventIconGroup } from "./icons";

export interface SubMeta {
  idx: number;
  tag: string;
  color: string;
  isRoot: boolean;
}

export interface ReefView {
  placement: Record<string, number>;
  activeSubquery: string | null;
  sourceNodes: Set<number>; // leaves/deps feeding the active subquery
  reveal: Record<string, number> | null; // Kraken plan overlay, or null
}

const VB_W = 1000;
const VB_H = 640;
const TOP_Y = 86; // leaves room for König Cloud's crown above the topmost row
const BOTTOM_MARGIN = 60;

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

function coralPetals(cx: number, cy: number, r: number): string {
  // A ring of little petals around the source pods, standing in for coral/anemones.
  let out = "";
  const n = 5;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const px = cx + Math.cos(a) * r * 0.94;
    const py = cy + Math.sin(a) * r * 0.94;
    out += `<circle class="coral-petal" cx="${px}" cy="${py}" r="${r * 0.32}"/>`;
  }
  return out;
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

    const label = n.is_cloud ? "König Cloud" : `n${n.id}`;
    const ariaPlaced = (atNode.get(n.id) || []).length
      ? `, holds ${(atNode.get(n.id) || []).length} operator(s)`
      : "";
    const aria = `${n.is_cloud ? "König Cloud, the sink" : n.is_leaf ? "Reef source node " + n.id : "Watchtower " + n.id}${ariaPlaced}`;

    let shape: string;
    let cloudBox: CloudBox | null = null;
    if (n.is_cloud) {
      cloudBox = cloudImageBox(x, y);
      shape =
        `<image class="cloud-img" href="assets/kingcloud.png" x="${cloudBox.x}" y="${cloudBox.y}" ` +
        `width="${cloudBox.w}" height="${cloudBox.h}" preserveAspectRatio="xMidYMax meet"/>`;
    } else if (n.is_leaf) {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>` + coralPetals(x, y, r);
    } else {
      // A small foundation, not the tower itself — the old full-size circle
      // read as "the shape", with the tower as decoration on top of a ball.
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r * 0.62}"/>` + towerShape(x, y, r);
    }

    // event pods for leaves (which message types they emit)
    let events = "";
    if (n.is_leaf) {
      const letters = Object.keys(n.events);
      const step = 20;
      letters.forEach((L, i) => {
        const ex = x + (i - (letters.length - 1) / 2) * step;
        const ey = y + r + 14;
        events +=
          eventIconGroup(L, ex, ey, 15) +
          `<text class="evt-lbl" x="${ex}" y="${ey + 15}">${L}</text>`;
      });
    }

    // placed-subquery chips near the node
    const placed = atNode.get(n.id) || [];
    let chips = "";
    placed.forEach((sub, i) => {
      const m = subMeta.get(sub)!;
      const cw = 26;
      const cx = x - ((placed.length - 1) * (cw + 4)) / 2 + i * (cw + 4);
      const cy = y - r - 14;
      chips +=
        `<g class="chip" data-sub="${encodeURIComponent(sub)}" tabindex="0" role="button" aria-label="Operator ${m.tag} on node ${n.id}, click to move">` +
        `<rect x="${cx - cw / 2}" y="${cy - 11}" rx="6" width="${cw}" height="22" fill="${m.color}"/>` +
        `<text class="chip-tx" x="${cx}" y="${cy + 4}">${m.tag}${m.isRoot ? "★" : ""}</text>` +
        `</g>`;
    });

    // reveal overlay (Kraken plan): draw a ghost ring where kraken places each sub
    let ghost = "";
    if (view.reveal) {
      const here = Object.entries(view.reveal).filter(([, nn]) => nn === n.id);
      if (here.length) {
        ghost = `<circle class="ghost" cx="${x}" cy="${y}" r="${r + 8}"/>`;
      }
    }

    g +=
      `<g class="${cls}" data-node="${n.id}" tabindex="0" role="button" aria-label="${aria}">` +
      ghost +
      shape +
      `<text class="node-lbl${n.is_cloud ? " on-isle" : ""}" x="${x}" y="${cloudBox ? cloudBox.y + cloudBox.h + 13 : y + 5}">${label}</text>` +
      events +
      chips +
      `</g>`;
  }

  return (
    `<svg viewBox="0 0 ${VB_W} ${VB_H}" class="reef-svg" preserveAspectRatio="xMidYMid meet" role="group" aria-label="Fog-cloud topology; tap a node to place the selected operator">` +
    background() +
    `<g class="edges">${edges}</g>` +
    `<g class="nodes">${g}</g>` +
    `</svg>`
  );
}
