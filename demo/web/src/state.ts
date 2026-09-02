// Central application state + scoring orchestration. Framework-free: subscribers
// are notified on every change and re-render. Scoring is two-stage: an instant
// client-side all-push estimate, then (if a backend is configured) an async
// push-pull refinement that becomes the "official" number.

import { Engine } from "./engine";
import { refinePushPull, backendConfigured, type PushPullResult } from "./backend";
import type { Baselines, Manifest, Placement, Scenario, ScoreResult, NormPoint, TopologyEntry } from "./types";
import type { SubMeta } from "./reef";

const PALETTE = ["#e8613c", "#2f9e8f", "#6f5bd1", "#d99a1e", "#c0497e", "#3b7dd8"];

export interface OfficialScore {
  cost: number;
  latency: number;
  norm: NormPoint;
  mode: "estimate" | "pushpull"; // estimate = client all-push; pushpull = backend-refined
  pending: boolean; // a refinement request is in flight
}

export class AppState {
  manifest: Manifest | null = null;
  topologyId: string | null = null;
  scenario: Scenario | null = null;
  engine: Engine | null = null;
  baselines: Baselines | null = null;
  subMeta: Map<string, SubMeta> = new Map();

  placement: Placement = {};
  activeSubquery: string | null = null;
  placementError: string | null = null;
  /** subquery name -> primitive letter the player chose to push (rest pulled). */
  pushChoice: Record<string, string> = {};
  reveal = false;
  private descendants: Map<number, Set<number>> = new Map();

  clientScore: ScoreResult | null = null;
  official: OfficialScore | null = null;
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
      this.reveal = false;
      this.clientScore = null;
      this.official = null;
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
    // auto-advance to the next unplaced subquery
    const next = this.subqueries.find((s) => !(s in this.placement));
    this.activeSubquery = next ?? null;
    this.reveal = false;
    this.rescore();
  }

  pickUp(name: string): void {
    delete this.placement[name];
    this.activeSubquery = name;
    this.placementError = null;
    this.reveal = false;
    this.rescore();
  }

  clear(): void {
    this.placement = {};
    this.pushChoice = {};
    this.activeSubquery = this.subqueries[0] ?? null;
    this.reveal = false;
    this.clientScore = null;
    this.official = null;
    this.emit();
  }

  /** Toggle whether `primitive` is the one the player pushes for `subqueryName`
   * (the rest are pulled) — clicking the already-chosen one clears back to
   * "let the optimizer decide". */
  setPushPrimitive(subqueryName: string, primitive: string): void {
    if (this.pushChoice[subqueryName] === primitive) {
      delete this.pushChoice[subqueryName];
    } else {
      this.pushChoice[subqueryName] = primitive;
    }
    this.reveal = false;
    this.rescore();
  }

  toggleReveal(): void {
    this.reveal = !this.reveal;
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
    if (!this.engine || !this.complete) {
      this.clientScore = null;
      this.official = null;
      this.emit();
      return;
    }
    this.clientScore = this.engine.score(this.placement);
    // instant estimate becomes the official number until (if) push-pull refines it
    this.official = {
      cost: this.clientScore.total_cost,
      latency: this.clientScore.total_latency,
      norm: {
        cost_norm: this.clientScore.cost_norm,
        latency_norm: this.clientScore.latency_norm,
        score: this.clientScore.score,
      },
      mode: "estimate",
      pending: backendConfigured(),
    };
    this.emit();
    if (backendConfigured()) this.refine();
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
    if (token !== this.refineToken || !this.complete) return; // stale / placement changed
    if (result && this.engine) {
      const norm = this.engine.normalizePoint(result.cost, result.latency);
      this.official = { cost: result.cost, latency: result.latency, norm, mode: "pushpull", pending: false };
    } else if (this.official) {
      this.official = { ...this.official, pending: false }; // refinement unavailable; keep estimate
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
