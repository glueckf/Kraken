// SVG "reef" renderer: the fog-cloud topology. Cloud at the top (a cloud), fog
// towers in the middle layers, event-source pods on the seabed. Nodes are placement
// targets; placed subqueries appear as small colored chips. Data-driven + full
// re-render on each state change (12 nodes is cheap); clicks handled by delegation.

import type { Scenario } from "./types";

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
const ROW_Y: Record<number, number> = { 0: 66, 1: 214, 2: 362, 3: 548 };

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

function cloudPath(cx: number, cy: number, s: number): string {
  // simple stylized cloud made of arcs, centered at (cx, cy)
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

    const label = n.is_cloud ? "Cloud" : `n${n.id}`;
    const ariaPlaced = (atNode.get(n.id) || []).length
      ? `, holds ${(atNode.get(n.id) || []).length} operator(s)`
      : "";
    const aria = `${n.is_cloud ? "Cloud sink node" : n.is_leaf ? "Source node " + n.id : "Fog node " + n.id}${ariaPlaced}`;

    let shape: string;
    if (n.is_cloud) {
      shape = `<path class="cloud-shape" d="${cloudPath(x, y, 34)}"/>`;
    } else {
      shape = `<circle class="node-dot" cx="${x}" cy="${y}" r="${r}"/>`;
    }

    // event pods for leaves (which streams they emit)
    let events = "";
    if (n.is_leaf) {
      const letters = Object.keys(n.events);
      letters.forEach((L, i) => {
        events += `<text class="evt" x="${x + (i - (letters.length - 1) / 2) * 16}" y="${y + r + 16}">${L}</text>`;
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
      `<text class="node-lbl" x="${x}" y="${y + (n.is_cloud ? 4 : 5)}">${label}</text>` +
      events +
      chips +
      `</g>`;
  }

  return (
    `<svg viewBox="0 0 ${VB_W} ${VB_H}" class="reef-svg" preserveAspectRatio="xMidYMid meet" role="group" aria-label="Fog-cloud topology; tap a node to place the selected operator">` +
    `<g class="edges">${edges}</g>` +
    `<g class="nodes">${g}</g>` +
    `</svg>`
  );
}
