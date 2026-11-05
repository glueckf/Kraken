// Central application state + scoring orchestration. Framework-free: subscribers
// are notified on every change and re-render. Scoring waits for the real
// push-pull number from the backend instead of flashing the client-side
// all-push model first (it ignores the player's own push/pull choices
// entirely, sometimes wildly — see BACKLOG.md item #10): `official` stays
// null and `scoring` stays true until the backend replies. If the backend is
// unreachable, only a pure all-push plan is scored (mode "allpush_local");
// a plan that pulls is marked `unscorable` instead of being mis-scored. The
// paper-example round is scored from its exported decision table (mode
// "table") and never needs the backend. See ScoreMode.

import { Engine } from "./engine";
import { refinePushPull, backendConfigured, checkBackend, type PushPullResult } from "./backend";
import type {
  Baselines, CommScheme, Decision, KrakenStage, Manifest, PaperRound, Placement, Scenario, ScoreResult, NormPoint, TopologyEntry,
} from "./types";
import type { SubMeta } from "./reef";
import { t } from "./i18n";

// Same verified colorblind-safe set as icons.ts's GLYPHS (reordered to this
// array's own existing slot order) -- this used to be a separately-drifted
// near-duplicate palette with its own, worse collisions (orange/gold and
// purple/blue both sat below any acceptable simulated separation). See
// icons.ts's GLYPHS comment and BACKLOG.md for the full check.
const PALETTE = ["#d9542f", "#2f9e8f", "#3d2c96", "#a58312", "#c0497e", "#2d7fd2"];

/** Sentinel `pushChoice` value meaning "push every dependency, pull nothing" —
 * a deliberate, explicit choice distinct from picking one specific dep to
 * push (which pulls the rest). Without this, the only way to satisfy the
 * mandatory push/pull call was to force a split; all-push is a legitimate
 * strategy in its own right and needed its own selectable option. */
export const ALL_PUSH = "__all_push__";

/** How a score was obtained — shown on the scorecard, never mixed up:
 * - "pushpull": the backend costed the player's exact placement + push/pull calls.
 * - "table": paper-example round; looked up in the exported decision table,
 *   which is Kraken's own CostCalculator on every (node, scheme) cell —
 *   exact, and needs no backend.
 * - "allpush_local": backend unavailable, but the player's plan is pure
 *   all-push, so the in-browser all-push model is the right model for it.
 * A plan that pulls anything is never scored by the all-push model; see
 * `unscorable`. */
export type ScoreMode = "pushpull" | "table" | "allpush_local";

export interface OfficialScore {
  cost: number;
  latency: number;
  norm: NormPoint;
  mode: ScoreMode;
}

/** off = no backend configured; unknown = not probed yet. */
export type BackendStatus = "off" | "unknown" | "up" | "down";

const BACKEND_POLL_MS = 15000;

export class AppState {
  manifest: Manifest | null = null;
  topologyId: string | null = null;
  scenario: Scenario | null = null;
  engine: Engine | null = null;
  baselines: Baselines | null = null;
  subMeta: Map<string, SubMeta> = new Map();
  /** Index into scenario.kraken_stages — the player's choice of cost/latency
   * balance, simplified from a raw 0-1 "alpha" number (too abstract for a lay
   * audience) into 3 named presets ("Fast" / "Balanced" / "Cheap", at alpha
   * 0.2/0.6/0.9 — see KRAKEN_STAGES in export_scenario.py). Persists across
   * topology/query switches, same as the old continuous weight did (each
   * freshly-created Engine gets this stage's alpha explicitly reapplied in
   * loadScenario). Default 1 = "Balanced" (alpha 0.6). */
  stageIndex = 1;

  placement: Placement = {};
  activeSubquery: string | null = null;
  placementError: string | null = null;
  /** subquery name -> the set of its *decidable* deps (see decidableDeps())
   * the player chose to push; any decidable dep not in the array is pulled.
   * An operator only appears here once the player has made at least one
   * push/pull call on it — absence means "let the optimizer decide" (only
   * allowed where there's no real call to make, see needsPushChoice). Deps
   * already at the node are never listed here; refine() adds them to the
   * push group itself (see buildPushSnapshot). Pushing *every* decidable dep is
   * sent to the backend as `ALL_PUSH` rather than the literal full list —
   * see refine() — since forcing a single group covering every dependency
   * hits a separate PrePP bug (cost off by a division-like factor). */
  pushChoice: Record<string, string[]> = {};
  /** subquery name -> why it was placed for the player instead of by
   * clicking a node — see reconcileForcedCloudPlacements(). */
  autoPlacedReason: Record<string, string> = {};
  reveal = false;
  /** True from confirm() until clear() ("try again") — freezes placement and
   * push/pull choices (placeActiveAt/pickUp/setPushChoice/setAllPushChoice
   * all no-op while this is true) and is the only thing that lets rescore()
   * actually score: a complete plan sits idle, not auto-scoring, until the
   * player deliberately locks it in. Without this a player could watch the
   * score update live while still rearranging the plan, which turns scoring
   * into a search tool instead of a one-shot decision. */
  confirmed = false;
  /** Decision-time clock: set on the first successful placement of the
   * round (first call into placeActiveAt that actually places something —
   * not on load, not on an attempt the placement-validity check rejects),
   * and frozen in confirm(). Timing the player against Kraken's own
   * (effectively instant) decision is the point of the stopwatch in the
   * header — see renderTimer() in main.ts. */
  planStartedAt: number | null = null;
  planConfirmedAt: number | null = null;
  private descendants: Map<number, Set<number>> = new Map();

  clientScore: ScoreResult | null = null;
  official: OfficialScore | null = null;
  /** True from the moment the placement is complete until the backend's
   * real push-pull number lands (or fails) — the scorecard shows a
   * "scoring…" state instead of a number while this is true. */
  scoring = false;
  /** Set instead of a score when the plan uses pull somewhere and the
   * push-pull backend is unavailable: an all-push number would ignore those
   * choices, so no score, rank or "you matched Kraken" is shown at all. */
  unscorable: "backend_down" | null = null;
  backendStatus: BackendStatus = backendConfigured() ? "unknown" : "off";
  loading = false;
  error: string | null = null;

  private listeners = new Set<() => void>();
  private refineToken = 0;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  subscribe(fn: () => void): void {
    this.listeners.add(fn);
  }
  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  /** Probe the backend now and every BACKEND_POLL_MS, so the badge recovers
   * by itself once the service is (re)started — no page reload needed. A
   * plan left unscorable while it was down is rescored on recovery. */
  startBackendPolling(): void {
    if (!backendConfigured() || this.pollTimer) return;
    const probe = async () => {
      const up = await checkBackend();
      const next: BackendStatus = up ? "up" : "down";
      if (next === this.backendStatus) return;
      this.backendStatus = next;
      if (up && this.unscorable === "backend_down") this.rescore();
      else this.emit();
    };
    void probe();
    this.pollTimer = setInterval(probe, BACKEND_POLL_MS);
  }

  async init(base = "scenarios/"): Promise<void> {
    this.startBackendPolling();
    this.loading = true;
    this.emit();
    try {
      this.manifest = await fetchJson<Manifest>(`${base}manifest.json`);
      // seq_and_pairs ("Oktopus-Puls", Q5) is hidden: the engine computes a
      // different subquery decomposition at export time than at live-score
      // time for this query, so every confirmed plan fails push-pull
      // scoring with "incomplete placement" regardless of what the player
      // does. Not a demo-layer bug -- see BACKLOG.md item 32. Remove this
      // filter once that's fixed upstream.
      for (const topo of this.manifest.topologies) {
        topo.scenarios = topo.scenarios.filter((s) => s.id !== "seq_and_pairs");
      }
      const defaultTopo = this.manifest.topologies.find((t) => t.id === "medium") ?? this.manifest.topologies[0];
      this.topologyId = defaultTopo.id;
      await this.loadScenario(defaultTopo.scenarios[0].id);
    } catch (e) {
      this.error = t().loadScenariosFailed(String(e));
      this.loading = false;
      this.emit();
    }
  }

  get base(): string {
    return "scenarios/";
  }

  get topology(): TopologyEntry | null {
    return this.manifest?.topologies.find((t) => t.id === this.topologyId) ?? null;
  }

  /** Switch topology, keeping the same query selected if it exists there. */
  async selectTopology(topologyId: string): Promise<void> {
    if (topologyId === this.topologyId) return;
    const topo = this.manifest?.topologies.find((t) => t.id === topologyId);
    if (!topo) return;
    const keepId = this.scenario?.scenario_id;
    this.topologyId = topologyId;
    const next = topo.scenarios.find((s) => s.id === keepId) ?? topo.scenarios[0];
    await this.loadScenario(next.id);
  }

  async loadScenario(id: string): Promise<void> {
    this.loading = true;
    this.error = null;
    this.emit();
    try {
      const entry = this.topology!.scenarios.find((s) => s.id === id)!;
      const scenario = await fetchJson<Scenario>(`${this.base}${entry.file}`);
      this.engine?.dispose();
      this.engine = await Engine.create(scenario);
      const stageAlpha = scenario.kraken_stages[this.stageIndex]?.alpha ?? 0.6;
      this.engine.setCostWeight(stageAlpha);
      this.scenario = scenario;
      this.baselines = this.engine.baselines();
      this.descendants = computeDescendants(scenario);

      // subquery display metadata
      this.subMeta = new Map();
      scenario.processing_order.forEach((name, i) => {
        const proj = scenario.projections.find((p) => p.name === name)!;
        this.subMeta.set(name, {
          idx: i + 1,
          tag: `s${i + 1}`,
          color: PALETTE[i % PALETTE.length],
          isRoot: proj.is_workload,
        });
      });

      this.placement = {};
      this.placementError = null;
      this.pushChoice = {};
      this.autoPlacedReason = {};
      this.reveal = false;
      this.confirmed = false;
      this.planStartedAt = null;
      this.planConfirmedAt = null;
      this.clientScore = null;
      this.official = null;
      this.scoring = false;
      this.unscorable = null;
      // auto-select the first (deepest-dependency) subquery to guide the user
      this.activeSubquery = scenario.processing_order[0] ?? null;
    } catch (e) {
      this.error = t().loadScenarioFailed(id, String(e));
    } finally {
      this.loading = false;
      this.emit();
    }
  }

  get subqueries(): string[] {
    return this.scenario?.processing_order ?? [];
  }

  get complete(): boolean {
    return this.subqueries.length > 0 && this.subqueries.every((s) => s in this.placement);
  }

  get placedCount(): number {
    return this.subqueries.filter((s) => s in this.placement).length;
  }

  /** `name`'s dependencies for which push vs. pull genuinely changes cost —
   * excludes ones the current placement already makes free either way: a
   * sub-query dependency placed at the very same node as `name` (distance
   * 0, so push and pull cost the same — literally already there), or a
   * primitive whose only producer(s) already sit at that node. Undefined
   * until `name` itself is placed (no node to compare against yet). */
  decidableDeps(name: string): string[] {
    const sc = this.scenario;
    const proj = sc?.projections.find((p) => p.name === name);
    const here = this.placement[name];
    if (!sc || !proj || here === undefined) return proj?.deps ?? [];
    return proj.deps.filter((dep) => {
      const producers = sc.event_map.producers[dep];
      if (producers) return !producers.every((p) => p === here);
      return this.placement[dep] !== here;
    });
  }

  /** Whether `name` has a real push-vs-pull call to make: 2+ decidable
   * deps (which of them to push), or a single decidable dep next to one
   * that's already at the node — that local dep is what a pull can filter
   * with, so the decidable one can be pulled instead of pushed. Leaving
   * that lone case to the optimizer hid a pull behind an "everything
   * pushed" plan (medium_c Q1, both operators at the cloud: the player
   * pushed all they could and still scored a 9-hop pull of C). Only a lone
   * dep with nothing local beside it — push is the only option — or no
   * decidable dep at all has nothing to choose. */
  needsPushChoice(name: string): boolean {
    const decidable = this.decidableDeps(name);
    if (decidable.length > 1) return true;
    const proj = this.scenario?.projections.find((p) => p.name === name);
    return decidable.length === 1 && !!proj && proj.deps.length > 1;
  }

  /** Subqueries with a real push/pull call (see needsPushChoice) the player
   * hasn't made yet — that choice is required, not just an optional extra,
   * so a placement isn't "done" while one of these is still unset. */
  get pendingPushChoices(): string[] {
    const sc = this.scenario;
    if (!sc) return [];
    return this.subqueries.filter((name) => this.needsPushChoice(name) && !(name in this.pushChoice));
  }

  /** True once every operator is placed AND every push/pull call is made —
   * this, not `complete`, gates scoring. */
  get readyToScore(): boolean {
    return this.complete && this.pendingPushChoices.length === 0;
  }

  get stages(): KrakenStage[] {
    return this.scenario?.kraken_stages ?? [];
  }

  get currentStage(): KrakenStage | null {
    return this.stages[this.stageIndex] ?? null;
  }

  /** state.baselines, but with the "kraken" entry replaced by the currently
   * selected stage's own (real, re-searched) placement instead of the
   * scenario's single default (alpha 0.5) export — the other four strategies
   * don't need this since their placement never depends on alpha, only the
   * score does (already handled by `engine.baselines()` re-normalizing live). */
  get effectiveBaselines(): Baselines | null {
    const bl = this.baselines;
    const stage = this.currentStage;
    if (!bl || !stage || !this.engine) return bl;
    const norm = this.engine.normalizePoint(stage.cost, stage.latency);
    const out: Baselines = { ...bl, kraken: { cost: stage.cost, latency: stage.latency, ...norm } };
    // Paper round: Sequential's step 2 (pick the scheme at its fixed node)
    // also uses alpha, so it is re-derived per stage at export time, from
    // the same decision table and score F as Kraken.
    const seq = stage.analysis?.sequential;
    if (seq) {
      out.sequential = { cost: seq.cost, latency: seq.latency, ...this.engine.normalizePoint(seq.cost, seq.latency) };
    }
    return out;
  }

  /** The paper's motivating example (factory topology), if that is the
   * loaded round — placement is restricted to its three candidate nodes,
   * and it's scored from its exported decision table (all four schemes the
   * free push/pull chips can build, not just the paper's own two — see
   * ALL_SCHEMES in factory_example.py) instead of the backend. */
  get paperRound(): PaperRound | null {
    return this.scenario?.paper_round ?? null;
  }

  /** The player's scheme for `name` in the paper round, if their push/pull
   * chip choice (pushChoice[name], the same field the Reef rounds use)
   * matches one of the four exported comm_options by its exact push set. */
  paperScheme(name: string): CommScheme | undefined {
    const pr = this.paperRound;
    const pushed = this.pushChoice[name];
    if (!pr || !pushed) return undefined;
    const key = [...pushed].sort().join(",");
    return pr.comm_options.find((o) => [...o.push].sort().join(",") === key)?.id;
  }

  /** Decision-table cell for the current placement + scheme (paper round). */
  get paperDecision(): Decision | null {
    const pr = this.paperRound;
    const name = this.subqueries[0];
    if (!pr || name === undefined) return null;
    const node = this.placement[name];
    const scheme = this.paperScheme(name);
    if (node === undefined || !scheme) return null;
    return pr.decision_table.find((d) => d.node === node && d.scheme === scheme) ?? null;
  }

  /** True iff nothing in the plan is pulled and nothing is left for the
   * optimizer to decide — the only case the in-browser all-push model
   * scores correctly without the backend. */
  get planIsPureAllPush(): boolean {
    return this.subqueries.every((name) => {
      const decidable = this.decidableDeps(name);
      if (decidable.length === 0) return true;
      const pushed = this.pushChoice[name];
      return !!pushed && decidable.every((d) => pushed.includes(d));
    });
  }

  selectSubquery(name: string): void {
    this.activeSubquery = this.activeSubquery === name ? null : name;
    this.placementError = null;
    this.emit();
  }

  /**
   * Why `node` can't host `subqueryName` right now, or null if it's fine.
   * Events only flow upward (child -> parent) toward the cloud, so a node
   * can only host an operator if every one of its dependencies is fully
   * reachable from that node's own subtree — for a primitive event, that
   * means *every* node producing it (an operator needs the complete stream,
   * not just whichever producer happens to be reachable — the cost model
   * sums over every source of a primitive, so missing even one would mean
   * computing on incomplete data); for a sub-query dependency, wherever the
   * player already placed it (a single materialized output, so just that
   * one node).
   */
  placementIssue(subqueryName: string, node: number): string | null {
    const sc = this.scenario;
    if (!sc) return null;
    const proj = sc.projections.find((p) => p.name === subqueryName);
    if (!proj) return null;
    const reach = this.descendants.get(node);
    if (!reach) return t().unknownNode(node);
    for (const dep of proj.deps) {
      const producers = sc.event_map.producers[dep];
      if (producers) {
        if (!producers.every((p) => reach.has(p))) {
          return t().unreachableSource(node, dep);
        }
      } else {
        const depNode = this.placement[dep];
        if (depNode === undefined || !reach.has(depNode)) {
          return t().noPathFrom(node, dep);
        }
      }
    }
    return null;
  }

  placeActiveAt(node: number): void {
    if (this.confirmed || this.activeSubquery == null) return;
    const issue = this.placementIssue(this.activeSubquery, node);
    if (issue) {
      this.placementError = issue;
      this.emit();
      return;
    }
    this.placementError = null;
    this.placement[this.activeSubquery] = node;
    if (this.planStartedAt == null) this.planStartedAt = Date.now();
    this.reconcileForcedCloudPlacements();
    // auto-advance to the next unplaced subquery (skips anything the
    // reconcile above just placed for the player)
    const next = this.subqueries.find((s) => !(s in this.placement));
    this.activeSubquery = next ?? null;
    this.reveal = false;
    this.rescore();
  }

  /**
   * Auto-place (and, symmetrically, auto-unplace) operators for which
   * König Cloud is mathematically the *only* valid node: once any
   * sub-query dependency of an operator sits at the cloud (node 0, the
   * tree's root), no other node can ever host that operator — node 0 is
   * nobody's descendant but its own (see computeDescendants below), so
   * placementIssue() can only ever pass at node 0 itself for that
   * dependency. Rather than making the player click the one node that was
   * already the only option, place it for them and record why (rendered
   * in the tray). Runs after every placement change and loops to catch
   * cascades — placing (or picking up) one operator at the cloud can force
   * (or unforce) the next one too.
   */
  private reconcileForcedCloudPlacements(): void {
    const sc = this.scenario;
    if (!sc) return;
    let changed = true;
    while (changed) {
      changed = false;
      // undo anything auto-placed that no longer needs to be (its forcing
      // dependency was picked up or moved elsewhere). Must re-check the same
      // *forcing* predicate used to place it below, not the fuller
      // placementIssue() — that also demands every OTHER subquery dependency
      // already be placed somewhere, which isn't this operator's concern and
      // isn't guaranteed yet (a still-unplaced, never-auto-forceable sibling
      // dependency, e.g. one with only primitive deps, would otherwise make
      // this check permanently disagree with the forcing check below and
      // force/undo the same operator forever).
      for (const name of Object.keys(this.autoPlacedReason)) {
        if (!(name in this.placement)) {
          delete this.autoPlacedReason[name];
          continue;
        }
        const proj = sc.projections.find((p) => p.name === name);
        const stillForced = !!proj?.deps.some(
          (dep) => !sc.event_map.producers[dep] && this.placement[dep] === 0
        );
        if (!stillForced) {
          delete this.placement[name];
          delete this.autoPlacedReason[name];
          changed = true;
        }
      }
      // place anything newly forced
      for (const name of this.subqueries) {
        if (name in this.placement) continue;
        const proj = sc.projections.find((p) => p.name === name);
        if (!proj) continue;
        const forcingDep = proj.deps.find(
          (dep) => !sc.event_map.producers[dep] && this.placement[dep] === 0
        );
        if (forcingDep) {
          this.placement[name] = 0;
          this.autoPlacedReason[name] = t().autoPlacedAtCloud(forcingDep);
          changed = true;
        }
      }
    }
  }

  pickUp(name: string): void {
    if (this.confirmed) return;
    delete this.placement[name];
    delete this.autoPlacedReason[name];
    this.activeSubquery = name;
    this.placementError = null;
    this.reveal = false;
    this.reconcileForcedCloudPlacements();
    this.rescore();
  }

  clear(): void {
    // If the plan was revealed OR confirmed (confirming already shows a
    // real score, even without the separate "show Kraken's plan" reveal --
    // the player has seen their own outcome either way), retrying the
    // identical topology/query is a non-challenge -- jump to a sibling
    // topology instead (same query where it exists there, via
    // selectTopology) so "try again" is a fresh puzzle, not a replay of the
    // one whose answer was just shown. Gating on reveal alone (the original
    // condition, from before the confirm/freeze mechanic existed) left a
    // gap: confirm, see the score, hit "try again" without ever touching
    // reveal, and you'd get the exact same topology every time -- reported
    // 2026-11-05 ("try again gave me 3 times the same topology"). The pool
    // is restricted to the *same family* as the current topology
    // (topologies.py has several per family, each a different hand-curated
    // or random shape) -- Reef stays Reef, Grand Reef stays Grand Reef, so
    // "try again" never surprises a visitor mid-round with a totally
    // different node count or label; the family buttons already offer the
    // cross-family jump explicitly. The paper's fixed "Kraken's Forge"
    // example is excluded regardless: it's a deliberate separate round a
    // visitor taps into on purpose, not something "try again" should pick.
    const jumpToOtherTopology = (this.reveal || this.confirmed) && this.manifest && this.topology
      ? this.manifest.topologies.filter((t) => t.id !== this.topologyId && t.family === this.topology!.family)
      : [];

    this.placement = {};
    this.pushChoice = {};
    this.autoPlacedReason = {};
    this.activeSubquery = this.subqueries[0] ?? null;
    this.reveal = false;
    this.confirmed = false;
    this.planStartedAt = null;
    this.planConfirmedAt = null;
    this.clientScore = null;
    this.official = null;
    this.scoring = false;
    this.unscorable = null;
    this.emit();

    if (jumpToOtherTopology.length) {
      const next = jumpToOtherTopology[Math.floor(Math.random() * jumpToOtherTopology.length)];
      void this.selectTopology(next.id);
    }
  }

  /** Toggle whether `dep` (one of subqueryName's own *decidable* deps — see
   * decidableDeps()) is pushed — independent per dep, so any subset can be
   * pushed at once (pushing 2 of 3 streams is just as valid as pushing 1).
   * First click on an undecided operator starts from "push nothing" and
   * pushes just that dep; toggling off the last pushed dep clears the whole
   * entry back to undecided (pending again — see pendingPushChoices)
   * instead of leaving an empty array around; "push nothing" is the
   * explicit pull-all chip. */
  setPushChoice(subqueryName: string, dep: string): void {
    if (this.confirmed) return;
    const current = this.pushChoice[subqueryName] ?? [];
    const next = current.includes(dep) ? current.filter((d) => d !== dep) : [...current, dep];
    if (next.length === 0) delete this.pushChoice[subqueryName];
    else this.pushChoice[subqueryName] = next;
    this.reveal = false;
    this.rescore();
  }

  /** Quick-set every decidable dep of `subqueryName` to push (or, if
   * `push` is false, to pull) in one call, instead of clicking each chip. */
  setAllPushChoice(subqueryName: string, push: boolean): void {
    if (this.confirmed) return;
    this.pushChoice[subqueryName] = push ? this.decidableDeps(subqueryName) : [];
    this.reveal = false;
    this.rescore();
  }

  toggleReveal(): void {
    this.reveal = !this.reveal;
    this.emit();
  }

  /** Locks in the plan (placement + every push/pull call) and is the one
   * thing that starts real scoring — see `confirmed`. No-ops if the plan
   * isn't complete yet or is already confirmed. */
  confirm(): void {
    if (!this.readyToScore || this.confirmed) return;
    this.confirmed = true;
    this.planConfirmedAt = Date.now();
    this.rescore();
  }

  /** Re-normalize every already-known cost/latency (baselines + the
   * player's own official score) under a new stage's alpha — no rescoring or
   * backend round-trip needed, since normalize_point is a pure function of
   * (cost, latency, anchors, weight) and both are already known. */
  setStage(index: number): void {
    if (index < 0 || index >= this.stages.length) return;
    this.stageIndex = index;
    if (!this.engine) {
      this.emit();
      return;
    }
    this.engine.setCostWeight(this.stages[index].alpha);
    this.baselines = this.engine.baselines();
    if (this.official) {
      const norm = this.engine.normalizePoint(this.official.cost, this.official.latency);
      this.official = { ...this.official, norm };
    }
    this.emit();
  }

  /** Set of node ids that feed the active subquery (its sources / placed deps). */
  get activeSourceNodes(): Set<number> {
    const out = new Set<number>();
    const s = this.activeSubquery;
    if (!s || !this.scenario) return out;
    const proj = this.scenario.projections.find((p) => p.name === s);
    if (!proj) return out;
    for (const dep of proj.deps) {
      const producers = this.scenario.event_map.producers[dep];
      if (producers) producers.forEach((n) => out.add(n));
      else if (dep in this.placement) out.add(this.placement[dep]); // subquery dep
    }
    return out;
  }

  private rescore(): void {
    this.unscorable = null;
    // A complete-but-not-yet-confirmed plan sits idle instead of auto-scoring
    // — see `confirmed` and `confirm()` — so this only ever actually scores
    // once the player has locked the plan in.
    if (!this.engine || !this.readyToScore || !this.confirmed) {
      this.clientScore = null;
      this.official = null;
      this.scoring = false;
      this.emit();
      return;
    }
    // Paper round: every reachable (node, scheme) cell was costed by the
    // engine at export time, so the exact number is a lookup — no backend,
    // no estimate.
    if (this.paperRound) {
      this.clientScore = null;
      this.scoring = false;
      const d = this.paperDecision;
      this.official = d
        ? { cost: d.cost, latency: d.latency, norm: this.engine.normalizePoint(d.cost, d.latency), mode: "table" }
        : null;
      this.emit();
      return;
    }
    // The instant client-side model is all-push only: it ignores every pull
    // the player chose, so it is never shown for a plan that pulls.
    this.clientScore = this.engine.score(this.placement);
    if (this.backendStatus === "off" || this.backendStatus === "down") {
      this.applyFallback();
      return;
    }
    // Wait for the real push-pull number rather than flashing the (often
    // very wrong — sometimes off by several times) all-push estimate first.
    this.official = null;
    this.scoring = true;
    this.emit();
    this.refine();
  }

  /** No push-pull service: score only what the all-push model can score
   * correctly (a pure all-push plan); otherwise show no score at all. */
  private applyFallback(): void {
    this.scoring = false;
    if (this.planIsPureAllPush && this.clientScore) {
      const c = this.clientScore;
      this.official = {
        cost: c.total_cost,
        latency: c.total_latency,
        norm: { cost_norm: c.cost_norm, latency_norm: c.latency_norm, score: c.score },
        mode: "allpush_local",
      };
    } else {
      this.official = null;
      this.unscorable = "backend_down";
    }
    this.emit();
  }

  /** Wire format for the backend: an operator whose *entire* decidable set
   * is pushed goes over as `ALL_PUSH` rather than the literal full array —
   * forcing a single PrePP group covering every dependency hits a separate,
   * documented bug (cost off by a division-like factor); the explicit
   * all-push strategy is costed directly instead. Every other decided
   * operator (including an explicit, deliberate "push nothing") goes over
   * as its pushed deps plus every dep already at the node: those are there
   * from the start and are what the pulls filter with. The backend's group
   * covers all deps, so leaving them out pulled them too, and with nothing
   * left to filter with the plan fell back to the all-push cost ("pull all"
   * on large/seq_abcd, both operators at the cloud, scored 1804 instead of
   * 1254.8). */
  private buildPushSnapshot(): Record<string, string | string[]> {
    const out: Record<string, string | string[]> = {};
    for (const [name, pushed] of Object.entries(this.pushChoice)) {
      const decidable = this.decidableDeps(name);
      if (pushed.length > 0 && pushed.length === decidable.length) {
        out[name] = ALL_PUSH;
        continue;
      }
      const deps = this.scenario?.projections.find((p) => p.name === name)?.deps ?? [];
      out[name] = [...deps.filter((dep) => !decidable.includes(dep)), ...pushed];
    }
    return out;
  }

  private async refine(): Promise<void> {
    const token = ++this.refineToken;
    const snapshot: Placement = { ...this.placement };
    const pushSnapshot = this.buildPushSnapshot();
    let result: PushPullResult | null = null;
    try {
      // "<topology>/<query>" — query ids alone aren't unique across topologies,
      // and the backend needs to know which one to reconstruct.
      result = await refinePushPull(`${this.topologyId}/${this.scenario!.scenario_id}`, snapshot, pushSnapshot);
    } catch {
      result = null;
    }
    if (token !== this.refineToken || !this.readyToScore) return; // stale / placement or push choice changed
    this.scoring = false;
    if (result && this.engine) {
      this.backendStatus = "up";
      const norm = this.engine.normalizePoint(result.cost, result.latency);
      this.official = { cost: result.cost, latency: result.latency, norm, mode: "pushpull" };
      this.emit();
    } else {
      // Backend unreachable (or it rejected the request): never pass the
      // all-push number off as a push-pull result — see applyFallback().
      // The poller flips the badge back and rescores once it answers again.
      this.backendStatus = "down";
      this.applyFallback();
    }
  }
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return (await res.json()) as T;
}

/** For every node, the set of nodes reachable by following `children`
 * (itself included) — i.e. "can an operator here receive events from X".
 */
function computeDescendants(scenario: Scenario): Map<number, Set<number>> {
  const nodes = scenario.topology.nodes;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const result = new Map<number, Set<number>>();
  for (const n of nodes) {
    const seen = new Set<number>([n.id]);
    const stack = [...n.children];
    while (stack.length) {
      const c = stack.pop()!;
      if (seen.has(c)) continue;
      seen.add(c);
      const cn = byId.get(c);
      if (cn) stack.push(...cn.children);
    }
    result.set(n.id, seen);
  }
  return result;
}
