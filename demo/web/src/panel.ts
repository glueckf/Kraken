// Renders the side panel: query selector, subquery tray, and the scorecard /
// leaderboard. Pure HTML-string builders; main.ts owns the DOM + delegated events.

import type { AppState } from "./state";
import type { Baselines, CommScheme, Projection, StrategyId, TopologyEntry } from "./types";
import { eventIconSvg, glyphFor } from "./icons";
import { t, getLang } from "./i18n";

const STRAT_ORDER: StrategyId[] = ["all_push", "inev", "prepp", "sequential", "kraken"];

/** The baselines this round actually exports (the paper round has no INEv). */
function strategyIds(state: AppState, bl: Baselines): StrategyId[] {
  const sc = state.scenario!;
  return STRAT_ORDER.filter((id) => sc.strategies[id] && bl[id]);
}

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
  const pushAllChip =
    `<button class="pp-chip pp-chip-all${allPushed ? " push" : ""}" data-pushall="${encodeURIComponent(name)}" ` +
    `title="${t().pushAllTitle}">` +
    `<span class="pp-all-label">${t().pushAllLabel}</span>${allPushed ? `<span class="pp-role">${t().rolePush}</span>` : ""}` +
    `</button>`;
  // "Pull all" (force every decidable dep to be pulled) only makes sense
  // when at least one of this subquery's OTHER dependencies is already free
  // -- already at this node for free, with nothing to decide (see the
  // "isFree" chips above) -- since that's the one local tuple a pull can
  // actually filter/trigger against. With zero free deps (e.g. Kraken's
  // Forge, where neither of SEQ(A, B)'s two raw deps is ever collocated
  // with a candidate node) there is nothing anywhere to filter with, so
  // "pull everything" isn't a cheap-but-valid choice, just incoherent --
  // see score_one.py's validation, which rejects an empty push group for
  // exactly those subqueries.
  const hasFreeAnchor = proj.deps.length > decidable.size;
  const allPulled = !!chosen && chosen.length === 0;
  const pullAllChip = !hasFreeAnchor
    ? ""
    : `<button class="pp-chip pp-chip-all${allPulled ? " pull" : ""}" data-pullall="${encodeURIComponent(name)}" ` +
      `title="${t().pullAllTitle}">` +
      `<span class="pp-all-label">${t().pullAllLabel}</span>${allPulled ? `<span class="pp-role">${t().rolePull}</span>` : ""}` +
      `</button>`;
  return `<div class="pp-row${chosen ? "" : " needed"}"><span class="pp-label">${t().ppLabel}</span>${chips}${pushAllChip}${pullAllChip}</div>`;
}

// Compact by design: once you've picked a size/query you mostly just need
// to see (and occasionally switch) it, not re-read four full cards every
// render — the freed vertical space goes to the tray/scorecard instead.

// Several concrete networks share one `family` (see topologies.py) so that
// repeat visitors see different edges -- and sometimes a node more or fewer
// -- under the same query, without the topology bar growing a button per
// variant. One button per family; it shows (and, on click, re-selects) the
// family's currently-active variant.
export function renderTopologyBar(state: AppState): string {
  if (!state.manifest) return "";
  const cur = state.topologyId;
  const families = new Map<string, TopologyEntry[]>();
  for (const topo of state.manifest.topologies) {
    (families.get(topo.family) ?? families.set(topo.family, []).get(topo.family)!).push(topo);
  }
  const items = [...families.values()]
    .map((variants) => {
      const active = variants.find((v) => v.id === cur) ?? variants[0];
      const on = active.id === cur ? "on" : "";
      const label = getLang() === "de" ? active.label_de : active.label;
      return (
        `<button class="tcard ${on}" data-topology="${active.id}" title="${escapeHtml(t().topologyTitle(label, active.network_size))}" aria-pressed="${active.id === cur}">` +
        `<span class="tname">${escapeHtml(label)}</span>` +
        `<span class="tsize">${active.network_size}n</span>` +
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

  // Paper round only: a standing nudge toward the rate-driven intuition the
  // chips above now show directly (same "⚡ letter rate" shape as Reef) --
  // shown regardless of placement/choice state, not just on first visit,
  // since re-reading it costs nothing and a later visitor restarting the
  // round benefits just as much as the first.
  const paperHint = state.paperRound
    ? `<div class="tray-note paper-hint">${escapeHtml(t().paperRatesHint)}</div>`
    : "";

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
    `${paperHint}<div class="tray-rows">${rows}</div>${errorHint}${hint}`
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

/** Always-visible line saying how this round is scored right now, so a
 * visitor (and the booth staff) can tell a real push-pull result from a
 * fallback before reading any number. */
export function renderServiceBadge(state: AppState): string {
  if (state.paperRound) {
    return `<div class="svc svc-table" role="status">${t().svcTable}</div>`;
  }
  const s = state.backendStatus;
  const cls = s === "up" ? "svc-up" : s === "unknown" ? "svc-unknown" : "svc-down";
  const text = s === "up" ? t().svcUp : s === "unknown" ? t().svcUnknown : s === "off" ? t().svcOff : t().svcDown;
  return `<div class="svc ${cls}" role="status">${text}</div>`;
}

function renderUnscorable(stagePicker: string): string {
  // The plan is confirmed (frozen) by the time this can ever show -- without
  // its own Try Again, a visitor stuck here (pull chosen, backend down)
  // would have no way back into an editable plan.
  return (
    `<div class="sc-unscorable" role="alert">` +
    `<div class="sc-unscorable-title">${t().unscorableTitle}</div>` +
    `<div class="sc-unscorable-sub">${t().unscorableBody}</div>` +
    stagePicker +
    `<div class="sc-actions">` +
    `<button class="btn" data-action="clear">${t().tryAgain}</button>` +
    `</div>` +
    `</div>`
  );
}

/** Paper round, after "reveal": the complete enumeration (all three schemes
 * per node, see ALL_SCHEMES in factory_example.py) with tuple volume,
 * critical-path latency and the score F at the current stage — the evidence
 * behind the ranking, readable at the booth. Deliberately not just the
 * paper's own two: seeing push_a tie all-push's volume but still lose on
 * latency is itself the "I tried it, here's why it doesn't help" answer to
 * the hint above the chips. */
const SCHEME_ORDER: CommScheme[] = ["all_push", "push_pull", "push_a"];
// The two schemes the paper actually names vs. the one that only ever ties
// all-push's volume and loses on latency (see factory_example.py's
// ALL_SCHEMES comment) -- muted in the table so the one real win (push_pull)
// reads clearly against the two ways of not winning, instead of all three
// schemes competing for attention equally.
const SCHEME_DOMINATED: Partial<Record<CommScheme, boolean>> = { push_a: true };
function renderDecisionTable(state: AppState): string {
  const pr = state.paperRound;
  const stage = state.currentStage;
  const a = stage?.analysis;
  if (!pr || !stage || !a) return "";
  const name = state.subqueries[0];
  const mine = state.paperDecision;
  const seq = a.sequential.decision;
  const opt = a.reference_optimum;
  const kNode = stage.placement[name];
  const kScheme = stage.per_placement?.[name]?.strategy as CommScheme | undefined;
  const label = (n: number) => (n === 0 ? `👑 ${t().cloudName}` : `n${n}`);
  const byNode = new Map<number, typeof pr.decision_table>();
  for (const d of pr.decision_table) {
    if (!byNode.has(d.node)) byNode.set(d.node, []);
    byNode.get(d.node)!.push(d);
  }
  const nodeOrder = [...byNode.keys()].sort((x, y) => (x === 0 ? 9 : x) - (y === 0 ? 9 : y));
  const rows = nodeOrder
    .map((node) => {
      const group = [...byNode.get(node)!].sort(
        (x, y) => SCHEME_ORDER.indexOf(x.scheme) - SCHEME_ORDER.indexOf(y.scheme)
      );
      return group
        .map((d, i) => {
          const score = a.scores.find((s) => s.node === d.node && s.scheme === d.scheme)?.score ?? NaN;
          const isBest = d.node === opt.node && d.scheme === opt.scheme;
          const marks = [
            isBest ? `<span class="dt-mark opt" title="${escapeHtml(t().dtOptTitle)}">★</span>` : "",
            d.node === kNode && d.scheme === kScheme ? `<span class="dt-mark k" title="Kraken">K</span>` : "",
            d.node === seq.node && d.scheme === seq.scheme ? `<span class="dt-mark s" title="Sequential">S</span>` : "",
            mine && d.node === mine.node && d.scheme === mine.scheme ? `<span class="dt-mark you" title="${escapeHtml(t().youLabel)}">${escapeHtml(t().youLabel)}</span>` : "",
          ].join("");
          const cls = [
            i === 0 ? "group-start" : "",
            isBest ? "best" : "",
            SCHEME_DOMINATED[d.scheme] ? "dominated" : "",
          ].filter(Boolean).join(" ");
          const nodeCell = i === 0 ? `<td class="dt-node" rowspan="${group.length}">${label(node)}</td>` : "";
          // F is already 0 (best) to 1 (worst) -- bar fullness is "how close
          // to optimal", not the raw score, so a longer bar reads as
          // "better" (matching every other bar in the app) instead of
          // "more F", which would be backwards.
          const barPct = Math.max(2, Math.round((1 - score) * 100));
          return (
            `<tr${cls ? ` class="${cls}"` : ""}>` +
            nodeCell +
            `<td>${escapeHtml(t().paperCommTitle(d.scheme))}</td>` +
            `<td class="num">${fmtCost(d.cost)}</td><td class="num">${fmtLat(d.latency)}</td>` +
            `<td class="num dt-score"><span class="dt-bar" style="width:${barPct}%"></span><span class="dt-score-tx">${score.toFixed(3)}</span></td>` +
            `<td class="marks">${marks}</td></tr>`
          );
        })
        .join("");
    })
    .join("");
  const verdict = stage.matches_reference ? t().dtKrakenMatches : t().dtKrakenDiffers;
  return (
    `<div class="dtable-wrap">` +
    `<div class="dtable-title">${t().dtTitle(pr.decision_table.length, stage.alpha)}</div>` +
    `<table class="dtable"><thead><tr><th>${t().dtNode}</th><th>${t().dtComm}</th>` +
    `<th class="num">${t().tupleLabel}</th><th class="num">${t().latencyLabel}</th><th class="num">F</th><th></th></tr></thead>` +
    `<tbody>${rows}</tbody></table>` +
    `<div class="dtable-note">${verdict} ${t().dtNote}</div>` +
    `</div>`
  );
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

  // Plan complete but not yet locked in: nothing has been scored yet, and
  // placement/push-pull stay fully editable (see AppState.confirmed) --
  // Confirm is the one action that starts scoring and freezes the plan.
  if (!state.confirmed) {
    return (
      `<div class="sc-empty">` +
      `<div class="sc-empty-title">${t().confirmTitle}</div>` +
      `<div class="sc-empty-sub">${t().confirmSub}</div>` +
      stagePicker +
      `<div class="sc-actions">` +
      `<button class="btn" data-action="confirm">${t().confirmBtn}</button>` +
      `</div>` +
      `</div>`
    );
  }

  if (state.unscorable) {
    return renderUnscorable(stagePicker);
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
  const ids = strategyIds(state, bl);
  const others = ids.filter((id) => id !== "kraken");
  const beaten = others.filter((id) => o.norm.score <= bl[id]!.score + 1e-9).length;

  const verdict = beatKraken
    ? `<span class="v-win">${t().verdictMatched}</span>`
    : `<span class="v-mid">${t().verdictMid(beaten, others.length)}</span>`;

  const modeTag =
    o.mode === "pushpull"
      ? `<span class="mode pp">${t().modePushPull}</span>`
      : o.mode === "table"
        ? `<span class="mode pp">${t().modeTable}</span>`
        : `<span class="mode est">${t().modeAllPushLocal}</span>`;

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
    ids.map((id) => ({ id, label: sc.strategies[id]!.label, score: bl[id]!.score, cost: bl[id]!.cost, latency: bl[id]!.latency }));
  rows.push({ id: "you", label: t().youLabel, score: o.norm.score, cost: o.cost, latency: o.latency, you: true });
  // Equal scores: You first (a tie counts as matching), then Kraken, then the
  // export order — so a baseline that ties Kraken (e.g. PrePP in the paper
  // round, where the joint optimum happens to be "cloud + push-pull") is not
  // listed above it by accident of array order.
  const tieRank = (r: { id: string; you?: boolean }) => (r.you ? 0 : r.id === "kraken" ? 1 : 2);
  rows.sort((a, b) => (Math.abs(a.score - b.score) > 1e-9 ? a.score - b.score : tieRank(a) - tieRank(b)));
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
        `<span class="plan-swatch pull"></span>${t().legendPull}</div>` +
        renderDecisionTable(state)
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

const EMBLEM_EMOJI: Record<string, string> = { crab: "🦀", turtle: "🐢", shark: "🦈", seedling: "🌱", factory: "⚒️" };

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
  factory_join: "Forge alarm (paper example)",
};
const QUERY_HEADLINE_DE: Record<string, string> = {
  seq_abc: "Krabben-Signal",
  seq_abcd: "Schildkröten-Spur",
  seq_abcde: "Hai-Alarm",
  and_nested: "Riff-Blüte",
  factory_join: "Schmiede-Alarm (Paper-Beispiel)",
};
function queryHeadline(scenarioId: string): string | undefined {
  return (getLang() === "de" ? QUERY_HEADLINE_DE : QUERY_HEADLINE_EN)[scenarioId];
}
