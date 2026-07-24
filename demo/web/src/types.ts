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

export interface Manifest {
  topology_id: string;
  scenarios: ManifestEntry[];
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
    { node: number; strategy: string; cost: number; lt: number; lp: number }
  >;
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
  strategies: Record<StrategyId, Strategy>;
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

export type Baselines = Record<
  StrategyId,
  { cost: number; latency: number; cost_norm: number; latency_norm: number; score: number }
>;

export type Placement = Record<string, number>; // subquery name -> node id
