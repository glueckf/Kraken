// Renders the side panel: query selector, subquery tray, and the scorecard /
// leaderboard. Pure HTML-string builders; main.ts owns the DOM + delegated events.

import type { AppState } from "./state";
import type { Baselines, Projection, StrategyId } from "./types";
import { eventIconSvg, glyphFor } from "./icons";

const STRAT_ORDER: StrategyId[] = ["all_push", "inev", "prepp", "sequential", "kraken"];

function fmtCost(n: number): string {
  if (n >= 10000) return (n / 1000).toFixed(1) + "k";
  if (n >= 1000) return (n / 1000).toFixed(2) + "k";
  return Math.round(n).toString();
}
function fmtLat(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
function fmtRate(n: number): string {
  return n >= 1000 ? Math.round(n / 100) / 10 + "k" : String(Math.round(n));
}

/**
 * For an operator with 2+ dependencies, let the player pick which one gets
 * pushed (fully transmitted) — the rest are pulled (only matches
 * requested). A dependency is either a raw primitive (rate shown, so the
 * choice is informed — pushing the low-rate stream and pulling the
 * high-rate one is usually cheaper) or an already-placed sub-query (shown
 * with its own sN tag, since its role here was already decided one level
 * down — this operator only chooses between that combined result and its
 * other input(s), not the raw primitives underneath it again).
 * Mandatory: state.readyToScore requires one of these per multi-dep operator.
 */
function renderPushPullRow(state: AppState, name: string, proj: Projection): string {
  if (proj.deps.length < 2) return "";
  const sc = state.scenario!;
  const chosen = state.pushChoice[name];
  const chips = proj.deps
    .map((dep) => {
      const sub = state.subMeta.get(dep);
      const isPush = chosen === dep;
      const isPull = !!chosen && !isPush;
      const role = isPush ? "PUSH" : isPull ? "pull" : "";
      const roleHtml = role ? `<span class="pp-role">${role}</span>` : "";
      if (sub) {
        const depProj = sc.projections.find((p) => p.name === dep);
        const rate = depProj ? fmtRate(depProj.output_rate) + "/s" : "";
        return (
          `<button class="pp-chip${isPush ? " push" : ""}${isPull ? " pull" : ""}" data-pp="${encodeURIComponent(name)}::${encodeURIComponent(dep)}" ` +
          `title="${escapeHtml(dep)}: ${rate || "rate unknown"}">` +
          `<span class="pp-sub-tag" style="background:${sub.color}">${sub.tag}</span>` +
          `<span class="pp-rate">${rate}</span>${roleHtml}` +
          `</button>`
        );
      }
      const rateMap = sc.event_map.local_rate_lookup[dep];
      const rate = rateMap ? Object.values(rateMap)[0] : undefined;
      return (
        `<button class="pp-chip${isPush ? " push" : ""}${isPull ? " pull" : ""}" data-pp="${encodeURIComponent(name)}::${encodeURIComponent(dep)}" ` +
        `title="${dep}: ${rate !== undefined ? rate + "/s" : "rate unknown"}">` +
        eventIconSvg(dep, 12) +
        `<span class="pp-letter">${dep}</span>` +
        `<span class="pp-rate">${rate !== undefined ? fmtRate(rate) + "/s" : ""}</span>${roleHtml}` +
        `</button>`
      );
    })
    .join("");
  return `<div class="pp-row${chosen ? "" : " needed"}"><span class="pp-label">push</span>${chips}</div>`;
}

export function renderTopologyBar(state: AppState): string {
  if (!state.manifest) return "";
  const cur = state.topologyId;
  const items = state.manifest.topologies
    .map((t) => {
      const on = t.id === cur ? "on" : "";
      return (
        `<button class="tcard ${on}" data-topology="${t.id}" title="${escapeHtml(t.label)} — ${t.network_size} nodes" aria-pressed="${t.id === cur}">` +
        `<span class="tname">${escapeHtml(t.label)}</span>` +
        `<span class="tsize">${t.network_size} nodes</span>` +
        `</button>`
      );
    })
    .join("");
  return `<div class="query-label">Pick a reef size</div><div class="tlist">${items}</div>`;
}

export function renderQueryBar(state: AppState): string {
  if (!state.topology) return "";
  const cur = state.scenario?.scenario_id;
  const items = state.topology.scenarios
    .map((s, i) => {
      const on = s.id === cur ? "on" : "";
      return (
        `<button class="qcard ${on}" data-scenario="${s.id}" title="${escapeHtml(s.title)} — ${s.num_subqueries} operators" aria-pressed="${s.id === cur}">` +
        `<span class="qbadge">Q${i + 1}</span>` +
        `<span class="qmeta"><span class="qexpr">${escapeHtml(s.title)}</span>` +
        `<span class="qcount">${s.num_subqueries} operators</span></span>` +
        `</button>`
      );
    })
    .join("");
  return `<div class="query-label">Pick a query</div><div class="qlist">${items}</div>`;
}

export function renderTray(state: AppState): string {
  const sc = state.scenario;
  if (!sc) return "";
  const rows = sc.processing_order
    .map((name) => {
      const m = state.subMeta.get(name)!;
      const node = state.placement[name];
      const placed = node !== undefined;
      const active = state.activeSubquery === name;
      const proj = sc.projections.find((p) => p.name === name)!;
      const inputs = proj.deps
        .map((d) => {
          const dm = state.subMeta.get(d);
          return dm
            ? `<span class="pill mini" style="background:${dm.color}">${dm.tag}</span>`
            : `<span class="pill mini evt" style="background:${glyphFor(d).color}">${eventIconSvg(d, 11)}${d}</span>`;
        })
        .join("");
      const row =
        `<div class="tray-row ${active ? "active" : ""} ${placed ? "placed" : ""}" data-sub="${encodeURIComponent(name)}" tabindex="0" role="button" aria-pressed="${active}">` +
        `<span class="tag" style="background:${m.color}">${m.tag}${m.isRoot ? "★" : ""}</span>` +
        `<span class="tray-body"><span class="tray-name">${escapeHtml(name)}</span>` +
        `<span class="tray-inputs">needs ${inputs}</span></span>` +
        `<span class="tray-loc">${placed ? (node === 0 ? "👑 König Cloud" : "n" + node) : "—"}</span>` +
        `</div>`;
      return row + renderPushPullRow(state, name, proj);
    })
    .join("");

  const pending = state.pendingPushChoices;
  const hint = state.activeSubquery
    ? `<span class="tray-hint">Selected <b>${escapeHtml(state.activeSubquery)}</b> — now tap a node.</span>`
    : !state.complete
      ? `<span class="tray-hint">Tap an operator, then tap a node.</span>`
      : pending.length > 0
        ? `<span class="tray-hint err">Still need a push/pull call for <b>${pending.map(escapeHtml).join(", ")}</b>.</span>`
        : `<span class="tray-hint ok">All operators placed.</span>`;
  const errorHint = state.placementError
    ? `<span class="tray-hint err">${escapeHtml(state.placementError)}</span>`
    : "";

  return (
    `<div class="tray-head"><span>Operators to place</span>` +
    `<span class="progress-txt">${state.placedCount}/${sc.processing_order.length}</span></div>` +
    `<div class="tray-rows">${rows}</div>${errorHint}${hint}`
  );
}

export function renderScorecard(state: AppState): string {
  const sc = state.scenario;
  const bl = state.baselines;
  if (!sc || !bl) return "";

  if (!state.readyToScore || !state.official) {
    const pending = state.pendingPushChoices;
    const pct = Math.round((state.placedCount / sc.processing_order.length) * 100);
    const title =
      state.complete && pending.length > 0
        ? `Choose push or pull for ${pending.length} more operator${pending.length > 1 ? "s" : ""} to score your plan`
        : `Place all ${sc.processing_order.length} operators to score your plan`;
    return (
      `<div class="sc-empty">` +
      `<div class="sc-empty-title">${title}</div>` +
      `<div class="progress"><div class="progress-fill" style="width:${pct}%"></div></div>` +
      `<div class="sc-empty-sub">You choose <b>where</b> each operator runs, and — for push-pull scoring — <b>which stream</b> it pushes. We compute the network cost and latency, then pit it against Kraken and four baselines.</div>` +
      `</div>`
    );
  }

  const o = state.official;
  const krakenScore = bl.kraken.score;
  const beatKraken = o.norm.score <= krakenScore + 1e-9;
  const beaten = STRAT_ORDER.filter((id) => id !== "kraken" && o.norm.score <= bl[id].score + 1e-9).length;

  const verdict = beatKraken
    ? `<span class="v-win">You matched Kraken.</span>`
    : `<span class="v-mid">You beat ${beaten} of 4 baselines — Kraken still wins.</span>`;

  const modeTag = o.pending
    ? `<span class="mode pending">optimising communication…</span>`
    : o.mode === "pushpull"
      ? `<span class="mode pp">push-pull optimised</span>`
      : `<span class="mode est">all-push estimate</span>`;

  // stat tiles vs Kraken
  const dCost = o.cost - bl.kraken.cost;
  const dLat = o.latency - bl.kraken.latency;

  const tiles =
    `<div class="tiles">` +
    tile("Tuples moved", fmtCost(o.cost), deltaLabel(dCost, true), dCost <= 0) +
    tile("Latency (hops)", fmtLat(o.latency), deltaLabel(dLat, false), dLat <= 0) +
    tile("Kraken score", o.norm.score.toFixed(3), `Kraken ${krakenScore.toFixed(3)}`, beatKraken) +
    `</div>`;

  // leaderboard: baselines + You, sorted by score asc
  const rows: { id: string; label: string; score: number; cost: number; latency: number; you?: boolean }[] =
    STRAT_ORDER.map((id) => ({ id, label: sc.strategies[id].label, score: bl[id].score, cost: bl[id].cost, latency: bl[id].latency }));
  rows.push({ id: "you", label: "You", score: o.norm.score, cost: o.cost, latency: o.latency, you: true });
  rows.sort((a, b) => a.score - b.score);
  const maxScore = Math.max(...rows.map((r) => r.score), 0.001);

  const board = rows
    .map((r, i) => {
      const w = Math.max(3, (r.score / maxScore) * 100);
      const cls = r.you ? "you" : r.id === "kraken" ? "kraken" : "";
      return (
        `<div class="lb-row ${cls}">` +
        `<span class="lb-rank">${i + 1}</span>` +
        `<span class="lb-name">${escapeHtml(r.label)}</span>` +
        `<span class="lb-bar"><span class="lb-fill" style="width:${w}%"></span></span>` +
        `<span class="lb-score">${r.score.toFixed(3)}</span>` +
        `<span class="lb-detail">${fmtCost(r.cost)} · ${fmtLat(r.latency)}h</span>` +
        `</div>`
      );
    })
    .join("");

  return (
    `<div class="sc-head">${verdict}${modeTag}</div>` +
    tiles +
    `<div class="lb-title">Leaderboard <span class="lb-hint">lower is better — cost & latency, balanced</span></div>` +
    `<div class="leaderboard">${board}</div>` +
    `<div class="sc-actions">` +
    `<button class="btn ghost" data-action="reveal">${state.reveal ? "Hide" : "Reveal"} Kraken's plan</button>` +
    `<button class="btn" data-action="clear">Try again</button>` +
    `</div>`
  );
}

function tile(label: string, value: string, sub: string, good: boolean): string {
  return (
    `<div class="tile ${good ? "good" : "bad"}">` +
    `<div class="tile-v">${value}</div>` +
    `<div class="tile-l">${label}</div>` +
    `<div class="tile-s">${sub}</div>` +
    `</div>`
  );
}

function deltaLabel(d: number, cost: boolean): string {
  if (Math.abs(d) < 1e-6) return "same as Kraken";
  const s = d > 0 ? "+" : "−";
  const v = cost ? fmtCost(Math.abs(d)) : fmtLat(Math.abs(d));
  return `${s}${v} vs Kraken`;
}

export function verdictOf(state: AppState, bl: Baselines): boolean {
  return !!state.official && state.official.norm.score <= bl.kraken.score + 1e-9;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}
