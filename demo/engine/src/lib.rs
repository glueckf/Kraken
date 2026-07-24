//! Client-side scorer for the Kraken interactive demo.
//!
//! Reproduces the engine's **all-push** cost model exactly (additive `Σ dist·rate`
//! + sink egress) and its critical-path latency recursion, then a demo-defined
//! normalized 0–1 "Kraken score" = `cost_weight·cost_norm + latency_weight·lat_norm`
//! against the scenario's precomputed baseline anchors.
//!
//! Push-pull (PrePP) costs are NOT computed here — they are precomputed for the
//! baselines and refined on the backend for a user placement. This module is the
//! instant, offline, client-side estimate + the single source of truth for the
//! normalization formula (shared with the backend-refined number via `normalize_point`).

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use wasm_bindgen::prelude::*;

// ---------------------------------------------------------------------------
// Scenario model (deserialized from the exporter's scenario_*.json).
// Only the fields the scorer needs are declared; unknown fields are ignored.
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
pub struct Scenario {
    pub config: Config,
    pub topology: Topology,
    pub event_map: EventMap,
    pub projections: Vec<Projection>,
    pub processing_order: Vec<String>,
    #[serde(default)]
    pub strategies: HashMap<String, StrategyMetrics>,
    pub norm_anchors: Anchors,
    #[serde(default)]
    pub goldens: Vec<Golden>,
}

#[derive(Deserialize)]
pub struct Config {
    pub cost_weight: f64,
    pub xi: f64,
    pub sink_nodes: Vec<usize>,
}

#[derive(Deserialize)]
pub struct Topology {
    pub num_nodes: usize,
    pub distance_matrix: Vec<Vec<f64>>,
}

#[derive(Deserialize)]
pub struct EventMap {
    /// event letter -> { source node id -> local rate }
    pub local_rate_lookup: HashMap<String, HashMap<usize, f64>>,
}

#[derive(Deserialize)]
pub struct Projection {
    pub name: String,
    pub deps: Vec<String>,
    pub output_rate: f64,
    pub is_workload: bool,
}

#[derive(Deserialize)]
pub struct StrategyMetrics {
    pub cost: f64,
    pub latency: f64,
}

#[derive(Deserialize)]
pub struct Anchors {
    pub cost_min: f64,
    pub cost_max: f64,
    pub latency_min: f64,
    pub latency_max: f64,
}

#[derive(Deserialize)]
pub struct Golden {
    pub name: String,
    pub placement: HashMap<String, usize>,
    pub all_push_cost: f64,
    pub all_push_latency: f64,
}

// ---------------------------------------------------------------------------
// Result types (serialized back to JS).
// ---------------------------------------------------------------------------

#[derive(Serialize, Default)]
pub struct PerPlacement {
    pub node: usize,
    pub cost: f64,
    pub lt: f64,
    pub lp: f64,
}

#[derive(Serialize, Default)]
pub struct ScoreResult {
    pub complete: bool,
    pub total_cost: f64,
    pub total_latency: f64,
    pub cost_norm: f64,
    pub latency_norm: f64,
    pub score: f64,
    pub per_placement: HashMap<String, PerPlacement>,
    /// names of projections still missing a node (empty when complete)
    pub missing: Vec<String>,
}

#[derive(Serialize)]
pub struct NormPoint {
    pub cost_norm: f64,
    pub latency_norm: f64,
    pub score: f64,
}

// ---------------------------------------------------------------------------
// Pure scoring logic (no wasm types) — exercised directly by native tests.
// ---------------------------------------------------------------------------

impl Scenario {
    fn proj_by_name(&self) -> HashMap<&str, &Projection> {
        self.projections.iter().map(|p| (p.name.as_str(), p)).collect()
    }

    /// clamp((x - lo) / (hi - lo), >= 0.0); returns 0 when the range is empty.
    fn norm(&self, x: f64, lo: f64, hi: f64) -> f64 {
        if hi <= lo {
            0.0
        } else {
            let v = (x - lo) / (hi - lo);
            if v < 0.0 {
                0.0
            } else {
                v
            }
        }
    }

    /// Weighted normalized score for an arbitrary (cost, latency) point against the
    /// scenario anchors. Shared by the client all-push estimate and the backend
    /// push-pull refinement so both use one formula.
    pub fn normalize_point(&self, cost: f64, latency: f64) -> NormPoint {
        let a = &self.norm_anchors;
        let cost_norm = self.norm(cost, a.cost_min, a.cost_max);
        let latency_norm = self.norm(latency, a.latency_min, a.latency_max);
        let cw = self.config.cost_weight;
        let lw = 1.0 - cw;
        NormPoint {
            cost_norm,
            latency_norm,
            score: cw * cost_norm + lw * latency_norm,
        }
    }

    /// All-push cost + critical-path latency for a complete subquery→node placement.
    pub fn score_all_push(&self, placement: &HashMap<String, usize>) -> ScoreResult {
        let by_name = self.proj_by_name();
        let dist = &self.topology.distance_matrix;
        let n_nodes = self.topology.num_nodes;
        let local = &self.event_map.local_rate_lookup;
        let sinks = &self.config.sink_nodes;
        let xi = self.config.xi;

        // completeness: every projection must have a valid node
        let mut missing: Vec<String> = Vec::new();
        for name in &self.processing_order {
            match placement.get(name) {
                Some(&node) if node < n_nodes => {}
                _ => missing.push(name.clone()),
            }
        }
        if !missing.is_empty() {
            return ScoreResult {
                complete: false,
                missing,
                ..Default::default()
            };
        }

        let mut e2e: HashMap<&str, f64> = HashMap::new();
        let mut total_cost = 0.0;
        let mut per: HashMap<String, PerPlacement> = HashMap::new();

        for name in &self.processing_order {
            let proj = by_name[name.as_str()];
            let n = placement[name];
            let mut cost = 0.0;
            let mut tlat: f64 = 0.0;

            for dep in &proj.deps {
                let mut dep_lat: f64 = 0.0;
                if let Some(sources) = local.get(dep) {
                    // primitive event: sum over every source node
                    for (&src, &rate) in sources {
                        cost += dist[src][n] * rate;
                        dep_lat = dep_lat.max(dist[src][n]);
                    }
                } else {
                    // already-placed sub-projection: single source = its node
                    let src = placement[dep];
                    let out_rate = by_name[dep.as_str()].output_rate;
                    cost += dist[src][n] * out_rate;
                    dep_lat = dist[src][n];
                }
                tlat = tlat.max(dep_lat);
            }

            // egress to sink(s), only for workload roots placed off-sink
            if proj.is_workload && !sinks.contains(&n) {
                let out_rate = proj.output_rate;
                let mut egress_cost = 0.0;
                let mut egress_lat: f64 = 0.0;
                for &s in sinks {
                    egress_cost += dist[n][s] * out_rate;
                    egress_lat = egress_lat.max(dist[n][s]);
                }
                cost += egress_cost;
                tlat += egress_lat;
            }

            let proc = proj.output_rate;
            total_cost += cost;

            let latest = proj
                .deps
                .iter()
                .filter_map(|d| e2e.get(d.as_str()).copied())
                .fold(0.0_f64, f64::max);
            e2e.insert(proj.name.as_str(), xi * proc + tlat + latest);

            per.insert(
                proj.name.clone(),
                PerPlacement { node: n, cost, lt: tlat, lp: proc },
            );
        }

        let total_latency = e2e.values().copied().fold(0.0_f64, f64::max);
        let np = self.normalize_point(total_cost, total_latency);

        ScoreResult {
            complete: true,
            total_cost,
            total_latency,
            cost_norm: np.cost_norm,
            latency_norm: np.latency_norm,
            score: np.score,
            per_placement: per,
            missing: Vec::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// WASM boundary.
// ---------------------------------------------------------------------------

#[wasm_bindgen]
pub struct Scorer {
    scenario: Scenario,
}

#[wasm_bindgen]
impl Scorer {
    /// Parse a scenario_*.json string once; score many placements cheaply.
    #[wasm_bindgen(constructor)]
    pub fn new(scenario_json: &str) -> Result<Scorer, JsError> {
        let scenario: Scenario =
            serde_json::from_str(scenario_json).map_err(|e| JsError::new(&e.to_string()))?;
        Ok(Scorer { scenario })
    }

    /// Score a placement (JSON object `{ "SEQ(A, B)": 4, ... }`). Returns JSON `ScoreResult`.
    pub fn score(&self, placement_json: &str) -> Result<String, JsError> {
        let placement: HashMap<String, usize> =
            serde_json::from_str(placement_json).map_err(|e| JsError::new(&e.to_string()))?;
        let res = self.scenario.score_all_push(&placement);
        serde_json::to_string(&res).map_err(|e| JsError::new(&e.to_string()))
    }

    /// Normalized score for an externally computed (cost, latency) — e.g. the backend
    /// push-pull refinement — using the same formula as `score`.
    #[wasm_bindgen(js_name = normalizePoint)]
    pub fn normalize_point(&self, cost: f64, latency: f64) -> Result<String, JsError> {
        let np = self.scenario.normalize_point(cost, latency);
        serde_json::to_string(&np).map_err(|e| JsError::new(&e.to_string()))
    }

    /// The five baselines with their normalized scores, as JSON `{ id: {cost, latency, score, ...} }`.
    pub fn baselines(&self) -> Result<String, JsError> {
        let mut out: HashMap<String, NormPoint> = HashMap::new();
        let mut costs: HashMap<String, (f64, f64)> = HashMap::new();
        for (id, m) in &self.scenario.strategies {
            let np = self.scenario.normalize_point(m.cost, m.latency);
            out.insert(id.clone(), np);
            costs.insert(id.clone(), (m.cost, m.latency));
        }
        // merge raw cost/latency in for convenience
        #[derive(Serialize)]
        struct B {
            cost: f64,
            latency: f64,
            cost_norm: f64,
            latency_norm: f64,
            score: f64,
        }
        let merged: HashMap<String, B> = out
            .into_iter()
            .map(|(id, np)| {
                let (c, l) = costs[&id];
                (
                    id,
                    B {
                        cost: c,
                        latency: l,
                        cost_norm: np.cost_norm,
                        latency_norm: np.latency_norm,
                        score: np.score,
                    },
                )
            })
            .collect();
        serde_json::to_string(&merged).map_err(|e| JsError::new(&e.to_string()))
    }
}
