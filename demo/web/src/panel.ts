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
 * For an operator with 2+ *decidable* dependencies (see state.decidableDeps
 * — excludes ones the current placement already makes free either way, e.g.
 * a sub-query dependency sitting at the very same node), let the player
 * toggle each one independently between push and pull — pushing 2 of 3
 * streams is just as valid a choice as pushing exactly 1, so this is a
 * multi-select, not a single pick. A dependency is either a raw primitive
 * (rate shown, so the choice is informed — pushing the low-rate stream and
 * pulling the high-rate one is usually cheaper) or an already-placed
 * sub-query (shown with its own sN tag, since its role here was already
 * decided one level down). A non-decidable dep still gets a chip so the row
 * doesn't look incomplete, but it's inert — "already here" says why there's
 * nothing to choose. Trailing "push all"/"pull all" chips are quick-set
 * shortcuts for the two extremes, not the only two options.
 * Mandatory: state.readyToScore requires a call on any operator with 2+
 * decidable deps (state.pendingPushChoices).
 */
function renderPushPullRow(state: AppState, name: string, proj: Projection): string {
  const sc = state.scenario!;
  const decidable = new Set(state.decidableDeps(name));
  if (decidable.size === 0) return ""; // nothing to choose at all -- e.g. a single dep, or every dep already free
  const chosen = state.pushChoice[name];
  const chips = proj.deps
    .map((dep) => {
      const sub = state.subMeta.get(dep);
      const isFree = !decidable.has(dep);
      const isPush = !isFree && (!!chosen ? chosen.includes(dep) : false);
      const isPull = !isFree && !isPush && !!chosen;
      const role = isFree ? "here" : isPush ? "PUSH" : isPull ? "pull" : "";
      const roleHtml = role ? `<span class="pp-role">${role}</span>` : "";
      const cls = isFree ? " free" : isPush ? " push" : isPull ? " pull" : "";
      // Free chips get their own inert marker rather than data-pp: a plain
      // <span> would otherwise let its click bubble past this row to the
      // enclosing tray-row's data-sub (pick-up/select), since it carries no
      // stoppable attribute of its own.
      const tag = isFree
        ? ` data-pp-inert="1"`
        : ` data-pp="${encodeURIComponent(name)}::${encodeURIComponent(dep)}"`;
      const el = isFree ? "span" : "button";
      if (sub) {
        const depProj = sc.projections.find((p) => p.name === dep);
        const rate = depProj ? fmtRate(depProj.output_rate) + "/s" : "";
        return (
          `<${el} class="pp-chip${cls}"${tag} ` +
          `title="${escapeHtml(dep)}${isFree ? " is already at this node" : `: ${rate || "rate unknown"}`}">` +
          `<span class="pp-sub-tag" style="background:${sub.color}">${sub.tag}</span>` +
          `<span class="pp-rate">${rate}</span>${roleHtml}` +
          `</${el}>`
        );
      }
      const rateMap = sc.event_map.local_rate_lookup[dep];
      const rate = rateMap ? Object.values(rateMap)[0] : undefined;
      return (
        `<${el} class="pp-chip${cls}"${tag} ` +
        `title="${dep}${isFree ? " is already at this node" : `: ${rate !== undefined ? rate + "/s" : "rate unknown"}`}">` +
        eventIconSvg(dep, 12) +
        `<span class="pp-letter">${dep}</span>` +
        `<span class="pp-rate">${rate !== undefined ? fmtRate(rate) + "/s" : ""}</span>${roleHtml}` +
        `</${el}>`
      );
    })
    .join("");
  if (decidable.size < 2) {
    // A lone decidable dep (or none) has no real combinatorial choice —
    // show the chips (including any "already here" ones) but no mandatory
    // call, no quick-set buttons.
    return `<div class="pp-row done"><span class="pp-label">push</span>${chips}</div>`;
  }
  const allPushed = !!chosen && chosen.length === decidable.size;
  const allPulled = !!chosen && chosen.length === 0;
  const pushAllChip =
    `<button class="pp-chip pp-chip-all${allPushed ? " push" : ""}" data-pushall="${encodeURIComponent(name)}" ` +
    `title="Push every input, pull nothing">` +
    `<span class="pp-all-label">push all</span>${allPushed ? `<span class="pp-role">PUSH</span>` : ""}` +
    `</button>`;
  const pullAllChip =
    `<button class="pp-chip pp-chip-all${allPulled ? " pull" : ""}" data-pullall="${encodeURIComponent(name)}" ` +
    `title="Pull every input, push nothing">` +
    `<span class="pp-all-label">pull all</span>${allPulled ? `<span class="pp-role">pull</span>` : ""}` +
    `</button>`;
  return `<div class="pp-row${chosen ? "" : " needed"}"><span class="pp-label">push</span>${chips}${pushAllChip}${pullAllChip}</div>`;
}

// Compact by design: once you've picked a size/query you mostly just need
// to see (and occasionally switch) it, not re-read four full cards every
// render — the freed vertical space goes to the tray/scorecard instead.

export function renderTopologyBar(state: AppState): string {
  if (!state.manifest) return "";
  const cur = state.topologyId;
  const items = state.manifest.topologies
    .map((t) => {
      const on = t.id === cur ? "on" : "";
      return (
        `<button class="tcard ${on}" data-topology="${t.id}" title="${escapeHtml(t.label)} — ${t.network_size} nodes" aria-pressed="${t.id === cur}">` +
        `<span class="tname">${escapeHtml(t.label)}</span>` +
        `<span class="tsize">${t.network_size}n</span>` +
        `</button>`
      );
    })
    .join("");
  return `<div class="tlist">${items}</div>`;
}

export function renderQueryBar(state: AppState): string {
  if (!state.topology) return "";
  const cur = state.scenario?.scenario_id;
  const active = state.topology.scenarios.find((s) => s.id === cur);
  const pills = state.topology.scenarios
    .map((s, i) => {
      const on = s.id === cur ? "on" : "";
      const emblem = EMBLEM_EMOJI[s.emblem] ?? "";
      return (
        `<button class="qpill ${on}" data-scenario="${s.id}" title="${escapeHtml(s.title)} — ${s.num_subqueries} operators" aria-pressed="${s.id === cur}">` +
        `<span class="qpill-badge">Q${i + 1}</span>` +
        (emblem ? `<span class="qpill-emblem" aria-hidden="true">${emblem}</span>` : "") +
        `</button>`
      );
    })
    .join("");
  const active_line = active
    ? `<div class="qactive"><span class="qactive-expr">${titleWithIcons(active.title)}</span>` +
      `<span class="qactive-count">${active.num_subqueries} operators</span></div>`
    : "";
  return `<div class="qpills">${pills}</div>${active_line}`;
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
      const autoReason = state.autoPlacedReason[name];
      const row =
        `<div class="tray-row ${active ? "active" : ""} ${placed ? "placed" : ""}" data-sub="${encodeURIComponent(name)}" tabindex="0" role="button" aria-pressed="${active}">` +
        `<span class="tag" style="background:${m.color}">${m.tag}${m.isRoot ? "★" : ""}</span>` +
        `<span class="tray-body"><span class="tray-name">${titleWithIcons(name)}</span>` +
        `<span class="tray-inputs">needs ${inputs}</span></span>` +
        `<span class="tray-loc"${autoReason ? ` title="${escapeHtml(autoReason)}"` : ""}>${placed ? (node === 0 ? "👑 König Cloud" : "n" + node) : "—"}${autoReason ? ` <span class="tray-auto-badge">auto</span>` : ""}</span>` +
        `</div>` +
        (autoReason ? `<div class="tray-note">${escapeHtml(autoReason)}</div>` : "");
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

/** Replaces the old raw 0-1 "alpha" slider (too abstract for a lay audience)
 * with a small set of named presets. Unlike a re-normalized score, Kraken has a genuinely
 * different real placement at each stage (see KrakenStage / currentStage),
 * computed once at export time — picking a stage is instant, no rescoring or
 * backend round-trip needed. */
// Reef-themed, one per stage rather than a separate legend flanking the
// row — a fitting icon on the button itself reads more directly than an
// icon-plus-word pair sitting outside it. Falls back to no icon for a
// label this map doesn't recognize (e.g. a future 4th/5th stage).
const STAGE_ICON: Record<string, string> = { fast: "🐟", balanced: "🪸", cheap: "🐚" };

function renderStagePicker(state: AppState): string {
  const stages = state.stages;
  const buttons = stages
    .map((s, i) => {
      const on = i === state.stageIndex;
      const icon = STAGE_ICON[s.label.toLowerCase()];
      return (
        `<button class="stage-btn${on ? " on" : ""}" data-action="stage" data-stage="${i}" ` +
        `title="Kraken optimised for ${escapeHtml(s.label.toLowerCase())}">${icon ? icon + " " : ""}${escapeHtml(s.label)}</button>`
      );
    })
    .join("");
  return `<div class="stage-row" title="How Kraken balances cost (fewer messages) vs. latency (speed)">${buttons}</div>`;
}

export function renderScorecard(state: AppState): string {
  const sc = state.scenario;
  const bl = state.effectiveBaselines;
  if (!sc || !bl) return "";
  const stagePicker = renderStagePicker(state);

  if (!state.readyToScore) {
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
      stagePicker +
      `</div>`
    );
  }

  if (state.scoring || !state.official) {
    // Waiting for the backend's real push-pull number rather than showing
    // the client-side all-push estimate first — that estimate ignores
    // every push/pull choice the player just made, sometimes by several
    // times the real cost, so a brief "crunching the numbers" beat reads
    // better than a number that's about to change.
    return (
      `<div class="sc-scoring">` +
      `<div class="sc-scoring-icon" aria-hidden="true">🐙</div>` +
      `<div class="sc-scoring-title">Kraken is crunching the numbers…</div>` +
      `<div class="sc-scoring-sub">Optimising push/pull for your placement.</div>` +
      stagePicker +
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

  const modeTag =
    o.mode === "pushpull"
      ? `<span class="mode pp">push-pull optimised</span>`
      : `<span class="mode est">all-push estimate — no live scoring available</span>`;

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
    stagePicker +
    `<div class="leaderboard">${board}</div>` +
    (state.reveal
      ? `<div class="plan-legend"><span class="plan-legend-hint">edge color = event type ·</span>` +
        `<span class="plan-swatch push"></span>push` +
        `<span class="plan-swatch pull"></span>pull</div>`
      : "") +
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

/** "SEQ(A, B, C)" -> the same text with each standalone event letter (A-F)
 * swapped for its icon — matches the reef's leaf-node icons instead of
 * reading as bare programming syntax. \b keeps "SEQ"/"AND" untouched (no
 * boundary between adjacent letters inside those words). */
function titleWithIcons(title: string): string {
  return escapeHtml(title).replace(
    /\b([A-F])\b/g,
    (_m, letter: string) => `<span class="op-evt">${eventIconSvg(letter, 12)}${letter}</span>`,
  );
}

const EMBLEM_EMOJI: Record<string, string> = { crab: "🦀", turtle: "🐢", shark: "🦈", seedling: "🌱" };
