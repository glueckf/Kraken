// Renders the side panel: query selector, subquery tray, and the scorecard /
// leaderboard. Pure HTML-string builders; main.ts owns the DOM + delegated events.

import type { AppState } from "./state";
import type { Baselines, Projection, StrategyId } from "./types";
import { eventIconSvg, glyphFor } from "./icons";
import { t, getLang } from "./i18n";

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
      const role = isFree ? t().roleHere : isPush ? t().rolePush : isPull ? t().rolePull : "";
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
          `title="${escapeHtml(dep)}${isFree ? " " + t().alreadyHere : `: ${rate || t().rateUnknown}`}">` +
          `<span class="pp-sub-tag" style="background:${sub.color}">${sub.tag}</span>` +
          `<span class="pp-rate">${rate}</span>${roleHtml}` +
          `</${el}>`
        );
      }
      const rateMap = sc.event_map.local_rate_lookup[dep];
      const rate = rateMap ? Object.values(rateMap)[0] : undefined;
      return (
        `<${el} class="pp-chip${cls}"${tag} ` +
        `title="${dep}${isFree ? " " + t().alreadyHere : `: ${rate !== undefined ? rate + "/s" : t().rateUnknown}`}">` +
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
    return `<div class="pp-row done"><span class="pp-label">${t().ppLabel}</span>${chips}</div>`;
  }
  const allPushed = !!chosen && chosen.length === decidable.size;
  const allPulled = !!chosen && chosen.length === 0;
  const pushAllChip =
    `<button class="pp-chip pp-chip-all${allPushed ? " push" : ""}" data-pushall="${encodeURIComponent(name)}" ` +
    `title="${t().pushAllTitle}">` +
    `<span class="pp-all-label">${t().pushAllLabel}</span>${allPushed ? `<span class="pp-role">${t().rolePush}</span>` : ""}` +
    `</button>`;
  const pullAllChip =
    `<button class="pp-chip pp-chip-all${allPulled ? " pull" : ""}" data-pullall="${encodeURIComponent(name)}" ` +
    `title="${t().pullAllTitle}">` +
    `<span class="pp-all-label">${t().pullAllLabel}</span>${allPulled ? `<span class="pp-role">${t().rolePull}</span>` : ""}` +
    `</button>`;
  return `<div class="pp-row${chosen ? "" : " needed"}"><span class="pp-label">${t().ppLabel}</span>${chips}${pushAllChip}${pullAllChip}</div>`;
}

// Compact by design: once you've picked a size/query you mostly just need
// to see (and occasionally switch) it, not re-read four full cards every
// render — the freed vertical space goes to the tray/scorecard instead.

export function renderTopologyBar(state: AppState): string {
  if (!state.manifest) return "";
  const cur = state.topologyId;
  const items = state.manifest.topologies
    .map((topo) => {
      const on = topo.id === cur ? "on" : "";
      return (
        `<button class="tcard ${on}" data-topology="${topo.id}" title="${escapeHtml(t().topologyTitle(topo.label, topo.network_size))}" aria-pressed="${topo.id === cur}">` +
        `<span class="tname">${escapeHtml(topo.label)}</span>` +
        `<span class="tsize">${topo.network_size}n</span>` +
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
        `<button class="qpill ${on}" data-scenario="${s.id}" title="${escapeHtml(t().queryTitle(s.title, t().subqueries(s.num_subqueries)))}" aria-pressed="${s.id === cur}">` +
        `<span class="qpill-badge">Q${i + 1}</span>` +
        (emblem ? `<span class="qpill-emblem" aria-hidden="true">${emblem}</span>` : "") +
        `</button>`
      );
    })
    .join("");
  const active_line = active
    ? `<div class="qactive">` +
      `<div class="qactive-headline">${EMBLEM_EMOJI[active.emblem] ?? ""} ${escapeHtml(queryHeadline(active.id) ?? active.title)}</div>` +
      `<div class="qactive-sub"><span class="qactive-expr">${titleWithIcons(active.title)}</span>` +
      `<span class="qactive-count">${t().subqueries(active.num_subqueries)}</span></div>` +
      `</div>`
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
        `<span class="tray-inputs">${t().needs} ${inputs}</span></span>` +
        `<span class="tray-loc"${autoReason ? ` title="${escapeHtml(autoReason)}"` : ""}>${placed ? (node === 0 ? `👑 ${t().cloudName}` : "n" + node) : "—"}${autoReason ? ` <span class="tray-auto-badge">${t().autoBadge}</span>` : ""}</span>` +
        `</div>` +
        (autoReason ? `<div class="tray-note">${escapeHtml(autoReason)}</div>` : "");
      return row + renderPushPullRow(state, name, proj);
    })
    .join("");

  const pending = state.pendingPushChoices;
  const hint = state.activeSubquery
    ? `<span class="tray-hint">${t().selectedNowTapNode(`<b>${escapeHtml(state.activeSubquery)}</b>`)}</span>`
    : !state.complete
      ? `<span class="tray-hint">${t().tapSubqueryThenNode}</span>`
      : pending.length > 0
        ? `<span class="tray-hint err">${t().stillNeedPushPull(`<b>${pending.map(escapeHtml).join(", ")}</b>`)}</span>`
        : `<span class="tray-hint ok">${t().allSubqueriesPlaced}</span>`;
  const errorHint = state.placementError
    ? `<span class="tray-hint err">${escapeHtml(state.placementError)}</span>`
    : "";

  return (
    `<div class="tray-head"><span>${t().subqueriesToPlace}</span>` +
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
      const label = t().stageLabel(s.label);
      return (
        `<button class="stage-btn${on ? " on" : ""}" data-action="stage" data-stage="${i}" ` +
        `title="${escapeHtml(t().stageTitleFor(label.toLowerCase()))}">${icon ? icon + " " : ""}${escapeHtml(label)}</button>`
      );
    })
    .join("");
  return `<div class="stage-row" title="${escapeHtml(t().stageRowTitle)}">${buttons}</div>`;
}

/** Shared with main.ts, which watches for the moment this flips to true on a
 * freshly-arrived official score to fire the win celebration (bubble burst)
 * exactly once per win, not on every unrelated re-render (e.g. toggling
 * reveal) while a win is already showing. */
export function playerBeatsKraken(state: AppState): boolean {
  const bl = state.effectiveBaselines;
  const o = state.official;
  if (!bl || !o) return false;
  return o.norm.score <= bl.kraken.score + 1e-9;
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
        ? t().choosePushPullFor(pending.length)
        : t().placeAllToScore(t().subqueries(sc.processing_order.length));
    return (
      `<div class="sc-empty">` +
      `<div class="sc-empty-title">${title}</div>` +
      `<div class="progress"><div class="progress-fill" style="width:${pct}%"></div></div>` +
      `<div class="sc-empty-sub">${t().scEmptySub}</div>` +
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
      `<div class="sc-scoring-title">${t().scoringTitle}</div>` +
      `<div class="sc-scoring-sub">${t().scoringSub}</div>` +
      stagePicker +
      `</div>`
    );
  }

  const o = state.official;
  const krakenScore = bl.kraken.score;
  const beatKraken = playerBeatsKraken(state);
  const beaten = STRAT_ORDER.filter((id) => id !== "kraken" && o.norm.score <= bl[id].score + 1e-9).length;

  const verdict = beatKraken
    ? `<span class="v-win">${t().verdictMatched}</span>`
    : `<span class="v-mid">${t().verdictMid(beaten)}</span>`;

  const modeTag =
    o.mode === "pushpull"
      ? `<span class="mode pp">${t().modePushPull}</span>`
      : `<span class="mode est">${t().modeEstimate}</span>`;

  // stat tiles vs Kraken
  const dCost = o.cost - bl.kraken.cost;
  const dLat = o.latency - bl.kraken.latency;

  const tiles =
    `<div class="tiles">` +
    tile(t().tupleLabel, fmtCost(o.cost), deltaLabel(dCost, true), dCost <= 0) +
    tile(t().latencyLabel, fmtLat(o.latency), deltaLabel(dLat, false), dLat <= 0) +
    tile(t().krakenScoreLabel, o.norm.score.toFixed(3), `Kraken ${krakenScore.toFixed(3)}`, beatKraken, "krakenScoreTile") +
    `</div>`;

  // leaderboard: baselines + You, sorted by score asc
  const rows: { id: string; label: string; score: number; cost: number; latency: number; you?: boolean }[] =
    STRAT_ORDER.map((id) => ({ id, label: sc.strategies[id].label, score: bl[id].score, cost: bl[id].cost, latency: bl[id].latency }));
  rows.push({ id: "you", label: t().youLabel, score: o.norm.score, cost: o.cost, latency: o.latency, you: true });
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
    `<div class="lb-title">${t().leaderboardTitle} <span class="lb-hint">${t().leaderboardHint}</span></div>` +
    stagePicker +
    `<div class="leaderboard">${board}</div>` +
    (state.reveal
      ? `<div class="plan-legend"><span class="plan-legend-hint">${t().legendHint}</span>` +
        `<span class="plan-swatch push"></span>${t().legendPush}` +
        `<span class="plan-swatch pull"></span>${t().legendPull}</div>`
      : "") +
    `<div class="sc-actions">` +
    `<button class="btn ghost" data-action="reveal">${state.reveal ? t().hidePlan : t().revealPlan}</button>` +
    `<button class="btn" data-action="clear">${t().tryAgain}</button>` +
    `</div>`
  );
}

function tile(label: string, value: string, sub: string, good: boolean, id?: string): string {
  return (
    `<div class="tile ${good ? "good" : "bad"}"${id ? ` id="${id}"` : ""}>` +
    `<div class="tile-v">${value}</div>` +
    `<div class="tile-l">${label}</div>` +
    `<div class="tile-s">${sub}</div>` +
    `</div>`
  );
}

function deltaLabel(d: number, cost: boolean): string {
  if (Math.abs(d) < 1e-6) return t().sameAsKraken;
  const s = d > 0 ? "+" : "−";
  const v = cost ? fmtCost(Math.abs(d)) : fmtLat(Math.abs(d));
  return t().vsKraken(s, v);
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

// Short, story-flavored stand-in for the raw SEQ(...)/AND(...) expression as
// the primary headline — reads as "spot the alarm," not programming syntax.
// The expression itself isn't hidden, just demoted to secondary text below
// (see renderQueryBar) — it still carries real information (operator count,
// which streams feed in) a returning player may want. Keyed by scenario_id
// rather than emblem since that's the stable per-query identity.
const QUERY_HEADLINE_EN: Record<string, string> = {
  seq_abc: "Crab signal",
  seq_abcd: "Turtle trail",
  seq_abcde: "Shark alarm",
  and_nested: "Reef bloom",
};
const QUERY_HEADLINE_DE: Record<string, string> = {
  seq_abc: "Krabben-Signal",
  seq_abcd: "Schildkröten-Spur",
  seq_abcde: "Hai-Alarm",
  and_nested: "Riff-Blüte",
};
function queryHeadline(scenarioId: string): string | undefined {
  return (getLang() === "de" ? QUERY_HEADLINE_DE : QUERY_HEADLINE_EN)[scenarioId];
}
