// Central application state + scoring orchestration. Framework-free: subscribers
// are notified on every change and re-render. Scoring waits for the real
// push-pull number from the backend instead of flashing the client-side
// all-push estimate first (that estimate ignores the player's own push/pull
// choices entirely, sometimes wildly — see BACKLOG.md item #10): `official`
// stays null and `scoring` stays true until the backend replies, at which
// point either the real number (mode "pushpull") or, only if the backend is
// unreachable, the estimate (mode "estimate", clearly labeled) fills it in.

import { Engine } from "./engine";
import { refinePushPull, backendConfigured, type PushPullResult } from "./backend";
import type { Baselines, KrakenStage, Manifest, Placement, Scenario, ScoreResult, NormPoint, TopologyEntry } from "./types";
import type { SubMeta } from "./reef";

const PALETTE = ["#e8613c", "#2f9e8f", "#6f5bd1", "#d99a1e", "#c0497e", "#3b7dd8"];

/** Sentinel `pushChoice` value meaning "push every dependency, pull nothing" —
 * a deliberate, explicit choice distinct from picking one specific dep to
 * push (which pulls the rest). Without this, the only way to satisfy the
 * mandatory push/pull call was to force a split; all-push is a legitimate
 * strategy in its own right and needed its own selectable option. */
export const ALL_PUSH = "__all_push__";

export interface OfficialScore {
  cost: number;
  latency: number;
  norm: NormPoint;
  mode: "estimate" | "pushpull"; // estimate = client all-push (only when there's no real number to wait for); pushpull = backend-refined
}

export class AppState {
  manifest: Manifest | null = null;
  topologyId: string | null = null;
  scenario: Scenario | null = null;
  engine: Engine | null = null;
  baselines: Baselines | null = null;
  subMeta: Map<string, SubMeta> = new Map();
  /** Index into scenario.kraken_stages — the player's choice of cost/latency
   * balance, simplified from a raw 0-1 "alpha" number (too abstract for a lay
   * audience) into 5 named presets ("Fastest" .. "Cheapest"). Persists across
   * topology/query switches, same as the old continuous weight did (each
   * freshly-created Engine gets this stage's alpha explicitly reapplied in
   * loadScenario). Default 2 = "Balanced" (alpha 0.5). */
  stageIndex = 2;

  placement: Placement = {};
  activeSubquery: string | null = null;
  placementError: string | null = null;
  /** subquery name -> the dep the player chose to push (rest pulled), or
   * `ALL_PUSH` for an explicit "push everything" choice. */
  pushChoice: Record<string, string> = {};
  /** subquery name -> why it was placed for the player instead of by
   * clicking a node — see reconcileForcedCloudPlacements(). */
  autoPlacedReason: Record<string, string> = {};
  reveal = false;
  private descendants: Map<number, Set<number>> = new Map();

  clientScore: ScoreResult | null = null;
  official: OfficialScore | null = null;
  /** True from the moment the placement is complete until the backend's
   * real push-pull number lands (or fails) — the scorecard shows a
   * "scoring…" state instead of a number while this is true. */
  scoring = false;
  loading = false;
  error: string | null = null;

  private listeners = new Set<() => void>();
  private refineToken = 0;

  subscribe(fn: () => void): void {
    this.listeners.add(fn);
  }
  private emit(): void {
    for (const fn of this.listeners) fn();
  }

  async init(base = "scenarios/"): Promise<void> {
    this.loading = true;
    this.emit();
    try {
      this.manifest = await fetchJson<Manifest>(`${base}manifest.json`);
      const defaultTopo = this.manifest.topologies.find((t) => t.id === "medium") ?? this.manifest.topologies[0];
      this.topologyId = defaultTopo.id;
      await this.loadScenario(defaultTopo.scenarios[0].id);
    } catch (e) {
      this.error = `Failed to load scenarios: ${String(e)}`;
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
      const stageAlpha = scenario.kraken_stages[this.stageIndex]?.alpha ?? 0.5;
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
      this.clientScore = null;
      this.official = null;
      this.scoring = false;
      // auto-select the first (deepest-dependency) subquery to guide the user
      this.activeSubquery = scenario.processing_order[0] ?? null;
    } catch (e) {
      this.error = `Failed to load scenario ${id}: ${String(e)}`;
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

  /** Subqueries with 2+ dependencies where the player hasn't made a push/pull
   * call yet — that choice is required, not just an optional extra, so a
   * placement isn't "done" while one of these is still unset. */
  get pendingPushChoices(): string[] {
    const sc = this.scenario;
    if (!sc) return [];
    return this.subqueries.filter((name) => {
      const proj = sc.projections.find((p) => p.name === name);
      return !!proj && proj.deps.length > 1 && !(name in this.pushChoice);
    });
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
    return { ...bl, kraken: { cost: stage.cost, latency: stage.latency, ...norm } };
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
    if (!reach) return `Unknown node n${node}.`;
    for (const dep of proj.deps) {
      const producers = sc.event_map.producers[dep];
      if (producers) {
        if (!producers.every((p) => reach.has(p))) {
          return `n${node} doesn't reach every source of ${dep} — an operator needs the complete stream, and events only flow upward from where they're produced. Check which nodes sit downstream of n${node}.`;
        }
      } else {
        const depNode = this.placement[dep];
        if (depNode === undefined || !reach.has(depNode)) {
          return `n${node} has no path from ${dep} — an operator needs to sit above (or at) all of its inputs in the network.`;
        }
      }
    }
    return null;
  }

  placeActiveAt(node: number): void {
    if (this.activeSubquery == null) return;
    const issue = this.placementIssue(this.activeSubquery, node);
    if (issue) {
      this.placementError = issue;
      this.emit();
      return;
    }
    this.placementError = null;
    this.placement[this.activeSubquery] = node;
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
          this.autoPlacedReason[name] =
            `Placed at König Cloud automatically — its input ${forcingDep} is already there, and no other node can reach it.`;
          changed = true;
        }
      }
    }
  }

  pickUp(name: string): void {
    delete this.placement[name];
    delete this.autoPlacedReason[name];
    this.activeSubquery = name;
    this.placementError = null;
    this.reveal = false;
    this.reconcileForcedCloudPlacements();
    this.rescore();
  }

  clear(): void {
    // If the plan was revealed, retrying the identical topology/query is a
    // non-challenge -- jump to a different topology instead (same query
    // where it exists there, via selectTopology) so "try again" is a fresh
    // puzzle, not a replay of the one whose answer was just shown.
    const jumpToOtherTopology = this.reveal && this.manifest
      ? this.manifest.topologies.filter((t) => t.id !== this.topologyId)
      : [];

    this.placement = {};
    this.pushChoice = {};
    this.autoPlacedReason = {};
    this.activeSubquery = this.subqueries[0] ?? null;
    this.reveal = false;
    this.clientScore = null;
    this.official = null;
    this.scoring = false;
    this.emit();

    if (jumpToOtherTopology.length) {
      const next = jumpToOtherTopology[Math.floor(Math.random() * jumpToOtherTopology.length)];
      void this.selectTopology(next.id);
    }
  }

  /** Toggle whether `dep` (one of subqueryName's own `deps` — a primitive
   * letter or an already-placed sub-query) is the one the player pushes
   * (the rest are pulled) — clicking the already-chosen one clears back to
   * "let the optimizer decide". */
  setPushChoice(subqueryName: string, dep: string): void {
    if (this.pushChoice[subqueryName] === dep) {
      delete this.pushChoice[subqueryName];
    } else {
      this.pushChoice[subqueryName] = dep;
    }
    this.reveal = false;
    this.rescore();
  }

  toggleReveal(): void {
    this.reveal = !this.reveal;
    this.emit();
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
    if (!this.engine || !this.readyToScore) {
      this.clientScore = null;
      this.official = null;
      this.scoring = false;
      this.emit();
      return;
    }
    // Always compute the instant client-side estimate (cheap — pure WASM,
    // no network) — but it ignores every push/pull choice the player made
    // (it can only model all-push), so it's kept internal, not shown as
    // "official", unless there's no backend to eventually give a real
    // number instead.
    this.clientScore = this.engine.score(this.placement);
    if (!backendConfigured()) {
      this.official = this.estimateAsOfficial();
      this.scoring = false;
      this.emit();
      return;
    }
    // Wait for the real push-pull number rather than flashing the (often
    // very wrong — sometimes off by several times) all-push estimate first.
    this.official = null;
    this.scoring = true;
    this.emit();
    this.refine();
  }

  private estimateAsOfficial(): OfficialScore {
    const c = this.clientScore!;
    return {
      cost: c.total_cost,
      latency: c.total_latency,
      norm: { cost_norm: c.cost_norm, latency_norm: c.latency_norm, score: c.score },
      mode: "estimate",
    };
  }

  private async refine(): Promise<void> {
    const token = ++this.refineToken;
    const snapshot: Placement = { ...this.placement };
    const pushSnapshot = { ...this.pushChoice };
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
      const norm = this.engine.normalizePoint(result.cost, result.latency);
      this.official = { cost: result.cost, latency: result.latency, norm, mode: "pushpull" };
    } else {
      // backend unreachable — fall back to the estimate rather than leaving
      // the player with nothing; still clearly labeled "estimate", not silently
      // presented as the real number.
      this.official = this.estimateAsOfficial();
    }
    this.emit();
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
