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
const ROW_Y: Record<number, number> = { 0: 86, 1: 214, 2: 362, 3: 548 };

export type Layout = Map<number, { x: number; y: number; r: number }>;

export function computeLayout(scenario: Scenario): Layout {
  const layout: Layout = new Map();
  const byLayer = new Map<number, number[]>();
  for (const n of scenario.topology.nodes) {
    if (!byLayer.has(n.layer)) byLayer.set(n.layer, []);
    byLayer.get(n.layer)!.push(n.id);
  }
  for (const [layer, ids] of byLayer) {
    ids.sort((a, b) => a - b);
    const y = ROW_Y[layer] ?? 66 + layer * 150;
    const count = ids.length;
    const margin = 96;
    const span = VB_W - margin * 2;
    ids.forEach((id, i) => {
      const x = count === 1 ? VB_W / 2 : margin + (span * i) / (count - 1);
      const r = layer === 0 ? 40 : layer === 3 ? 24 : 30;
      layout.set(id, { x, y, r });
    });
  }
  return layout;
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): string {
  const my = (a.y + b.y) / 2;
  return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
}

function islandPath(cx: number, cy: number, s: number): string {
  // King Cloud's little island: a rounded silhouette in the same footprint the
  // old cloud shape used, so the layout math around it doesn't have to change.
  const x = cx - s;
  const y = cy - s * 0.35;
  return (
    `M ${x} ${y} ` +
    `a ${s * 0.45} ${s * 0.45} 0 0 1 ${s * 0.55} -${s * 0.5} ` +
    `a ${s * 0.5} ${s * 0.5} 0 0 1 ${s * 0.95} 0 ` +
    `a ${s * 0.42} ${s * 0.42} 0 0 1 ${s * 0.5} ${s * 0.55} ` +
    `a ${s * 0.4} ${s * 0.4} 0 0 1 -${s * 0.2} ${s * 0.75} ` +
    `l -${s * 2.05} 0 ` +
    `a ${s * 0.42} ${s * 0.42} 0 0 1 -${s * 0.25} -${s * 0.75} Z`
  );
}

function crownGroup(cx: number, topY: number, s: number): string {
  // A tiny crown resting just above the castle — the one thing King Cloud never delegates.
  const w = s * 1.3;
  const h = s * 0.56;
  const y = topY - h - s * 0.12;
  const x0 = cx - w / 2;
  return (
    `<g class="crown">` +
    `<path d="M ${x0} ${y + h} L ${x0} ${y + h * 0.32} L ${x0 + w * 0.22} ${y + h * 0.72} L ${x0 + w * 0.5} ${y} L ${x0 + w * 0.78} ${y + h * 0.72} L ${x0 + w} ${y + h * 0.32} L ${x0 + w} ${y + h} Z"/>` +
    `<circle cx="${x0 + w * 0.5}" cy="${y - 1}" r="${s * 0.09}"/>` +
    `</g>`
  );
}

function castleGroup(cx: number, cy: number, s: number): { markup: string; topY: number } {
  // A small keep for King Cloud to actually live in, under the crown.
  const w = s * 0.95;
  const h = s * 0.8;
  const x0 = cx - w / 2;
  const y0 = cy - h;
  const notchW = w * 0.2;
  const notches = [0, 1, 2, 3]
    .map((i) => {
      const nx = x0 + i * (w / 3) - notchW / 2;
      return `<rect class="castle-notch" x="${nx}" y="${y0 - notchW * 0.85}" width="${notchW}" height="${notchW}"/>`;
    })
    .join("");
  const doorW = w * 0.26;
  return {
    markup:
      `<g class="castle">` +
      `<rect class="castle-body" x="${x0}" y="${y0}" width="${w}" height="${h}" rx="1.5"/>` +
      `<rect class="castle-door" x="${cx - doorW / 2}" y="${y0 + h * 0.5}" width="${doorW}" height="${h * 0.5}" rx="1.5"/>` +
      notches +
      `</g>`,
    topY: y0 - notchW * 0.85,
  };
}

function poolAndPalm(cx: number, cy: number, s: number): string {
  // The pool he moved to the island for, plus a palm for lounging in its shade.
  // Offsets are pulled well inside the island's own footprint (it's wider than
  // it is tall) so nothing pokes past the coastline.
  const px = cx + s * 0.58;
  const py = cy + s * 0.2;
  const tx = cx - s * 0.56;
  const ty = cy + s * 0.05;
  return (
    `<g class="king-pool">` +
    `<ellipse class="pool-rim" cx="${px}" cy="${py}" rx="${s * 0.32}" ry="${s * 0.14}"/>` +
    `<ellipse class="pool-water" cx="${px}" cy="${py}" rx="${s * 0.25}" ry="${s * 0.1}"/>` +
    `</g>` +
    `<g class="palm" transform="translate(${tx} ${ty})">` +
    `<path class="palm-trunk" d="M0 ${s * 0.3} Q ${s * 0.09} ${s * 0.03} 0 -${s * 0.08}"/>` +
    `<path class="palm-leaf" d="M0 -${s * 0.08} q -${s * 0.26} -${s * 0.03} -${s * 0.35} ${s * 0.1}"/>` +
    `<path class="palm-leaf" d="M0 -${s * 0.08} q ${s * 0.26} -${s * 0.03} ${s * 0.35} ${s * 0.1}"/>` +
    `<path class="palm-leaf" d="M0 -${s * 0.08} q -${s * 0.06} -${s * 0.2} -${s * 0.17} -${s * 0.25}"/>` +
    `<path class="palm-leaf" d="M0 -${s * 0.08} q ${s * 0.06} -${s * 0.2} ${s * 0.17} -${s * 0.25}"/>` +
    `</g>`
  );
}

function towerToppers(cx: number, cy: number, r: number): string {
  // Crenellations + a small pennant, turning the plain fog circle into a watchtower.
  const topY = cy - r;
  const notchW = r * 0.3;
  const notches = [-1.05, 0, 1.05]
    .map(
      (k) =>
        `<rect class="tower-notch" x="${cx + k * notchW - notchW / 2.4}" y="${topY - notchW * 0.85}" width="${notchW / 1.2}" height="${notchW}" rx="1"/>`,
    )
    .join("");
  const poleX = cx + r * 0.18;
  const poleTopY = topY - r * 0.9;
  return (
    `<line class="tower-pole" x1="${poleX}" y1="${topY}" x2="${poleX}" y2="${poleTopY}"/>` +
    `<path class="tower-flag" d="M ${poleX} ${poleTopY} l ${r * 0.5} ${r * 0.17} l -${r * 0.5} ${r * 0.17} Z"/>` +
    notches
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
    if (n.is_cloud) {
      const S = 44; // bigger island — enough room for the castle, pool, and palm to sit inside its coastline
      const castle = castleGroup(x, y, S);
      shape =
        `<path class="cloud-shape" d="${islandPath(x, y, S)}"/>` +
        poolAndPalm(x, y, S) +
        castle.markup +
        crownGroup(x, castle.topY, S * 0.88);
    } else if (n.is_leaf) {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>` + coralPetals(x, y, r);
    } else {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>` + towerToppers(x, y, r);
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
      `<text class="node-lbl${n.is_cloud ? " below" : ""}" x="${x}" y="${y + (n.is_cloud ? 44 * 0.45 + 15 : 5)}">${label}</text>` +
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
