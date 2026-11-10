// Type definitions mirroring the exporter's scenario_*.json schema and the
// Rust scorer's result shapes.

export interface ManifestEntry {
  id: string;
  title: string;
  emblem: string;
  difficulty: number;
  blurb: string;
  num_subqueries: number;
  file: string;
}

export interface TopologyEntry {
  id: string;
  /** Groups several concrete networks (different seed/size, same queries)
   * under one topology-bar button -- see topologies.py. */
  family: string;
  label: string;
  label_de: string;
  network_size: number;
  scenarios: ManifestEntry[];
}

export interface Manifest {
  topologies: TopologyEntry[];
}

export interface Node {
  id: number;
  layer: number;
  computational_power: number | null;
  is_cloud: boolean;
  is_leaf: boolean;
  parents: number[];
  children: number[];
  events: Record<string, number>; // letter -> local rate
}

export interface Projection {
  name: string;
  primitives: string[];
  deps: string[]; // primitive letters and/or subquery names
  selection_rate: number;
  output_rate: number;
  is_workload: boolean;
  level: number;
}

export type StrategyId = "all_push" | "inev" | "sequential" | "prepp" | "kraken";

export interface Strategy {
  label: string;
  placement: Record<string, number>;
  comm: "push" | "push_pull" | "mixed";
  cost: number;
  latency: number;
  processing_latency: number;
  per_placement?: Record<
    string,
    {
      node: number;
      strategy: string;
      cost: number;
      lt: number;
      lp: number;
      edges?: Record<string, "push" | "pull">; // dep name -> how it's acquired
    }
  >;
}

/** One player-facing "alpha" preset. Unlike the other four strategies (whose
 * placement never depends on cost_weight, only their displayed score does),
 * Kraken's own greedy search genuinely chooses a different placement per
 * alpha, so each stage carries its own real placement/per_placement, not
 * just a re-normalized score of a single fixed run. */
export interface KrakenStage extends Strategy {
  alpha: number;
  /** Paper-example round only: the full enumeration evaluated at this alpha. */
  analysis?: StageAnalysis;
  /** Paper-example round only: Kraken's greedy plan == enumeration optimum? */
  matches_reference?: boolean;
  /** Measured wall time of Kraken's search for this stage at export
   * (export_scenario.py), shown against the player's decision time. */
  solve_seconds?: number;
}

// "push_a" always equals all_push (see factory_example.py's
// ALL_SCHEMES comment) but is a real, engine-computed cell: a player's free
// per-dependency push/pull chips (same component as Reef) can build it, and
// the reveal table shows what it costs. "pull_both" (push neither) isn't
// offered at all -- pulling needs an already-pushed tuple to filter
// against, so it has nothing to filter with.
export type CommScheme = "all_push" | "push_pull" | "push_a";

/** One cell of the paper example's decision table: Kraken's CostCalculator
 * cost/latency for a (node, scheme) deployment decision, plus the same cell
 * recomputed from the paper's formulas. */
export interface Decision {
  node: number;
  scheme: CommScheme;
  cost: number;
  latency: number;
  steps: { mode: "push" | "pull"; events: string[] }[];
  paper: { cost: number; latency: number };
}

export interface DecisionRef {
  node: number;
  scheme: CommScheme;
  cost: number;
  latency: number;
}

export interface StageAnalysis {
  alpha: number;
  scores: { node: number; scheme: CommScheme; score: number }[];
  reference_optimum: DecisionRef;
  all_push_best: DecisionRef;
  sequential: Strategy & { decision: { node: number; scheme: CommScheme } };
}

/** Present only on the paper's motivating example (factory topology). */
export interface PaperRound {
  source: string;
  node_labels: Record<string, string>;
  inputs: {
    rates: Record<string, number>;
    selectivity_AB: number;
    output_rate: number;
    edges: [number, number][];
    sink: number;
  };
  comm_options: { id: CommScheme; push: string[]; pull: string[] }[];
  decision_table: Decision[];
  default_alpha: number;
}

export interface Scenario {
  schema_version: number;
  scenario_id: string;
  title: string;
  emblem: string;
  difficulty: number;
  blurb: string;
  query: string;
  config: { cost_weight: number; xi: number; sink_nodes: number[] };
  topology: {
    num_nodes: number;
    cloud_node_id: number;
    event_letters: string[];
    nodes: Node[];
    distance_matrix: number[][];
  };
  event_map: {
    producers: Record<string, number[]>;
    local_rate_lookup: Record<string, Record<string, number>>;
  };
  projections: Projection[];
  processing_order: string[];
  /** Not every round has to export every baseline. */
  strategies: Partial<Record<StrategyId, Strategy>>;
  paper_round?: PaperRound;
  /** Named cost/latency-balance presets, each with Kraken's own real
   * placement at that alpha — see KrakenStage. */
  kraken_stages: KrakenStage[];
  norm_anchors: {
    cost_min: number;
    cost_max: number;
    latency_min: number;
    latency_max: number;
  };
}

// --- Rust scorer result shapes ---

export interface PerPlacement {
  node: number;
  cost: number;
  lt: number;
  lp: number;
}

export interface ScoreResult {
  complete: boolean;
  total_cost: number;
  total_latency: number;
  cost_norm: number;
  latency_norm: number;
  score: number;
  per_placement: Record<string, PerPlacement>;
  missing: string[];
}

export interface NormPoint {
  cost_norm: number;
  latency_norm: number;
  score: number;
}

export interface BaselinePoint {
  cost: number;
  latency: number;
  cost_norm: number;
  latency_norm: number;
  score: number;
}

/** Always has "kraken"; the others only when the round exports them. */
export type Baselines = Partial<Record<StrategyId, BaselinePoint>> & { kraken: BaselinePoint };

export type Placement = Record<string, number>; // subquery name -> node id
