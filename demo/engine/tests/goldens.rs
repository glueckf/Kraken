//! Integration test: the Rust all-push scorer must reproduce the exporter's goldens
//! (cost + latency) exactly for every curated scenario. The goldens themselves are
//! cross-checked against the real Python engine in export_scenario.py.

use kraken_demo_engine::Scenario;
use std::collections::HashMap;

const SCENARIOS: &[&str] = &["seq_abc", "seq_abcd", "seq_abcde", "and_nested"];

fn load(id: &str) -> Scenario {
    // "medium" is the original hand-built 12-node reef these goldens were
    // written against; scenarios now live under a per-topology subfolder
    // (see export_scenario.py's topologies.py) since the network-size
    // feature added "large" alongside it.
    let path = format!(
        "{}/../web/scenarios/medium/{}.json",
        env!("CARGO_MANIFEST_DIR"),
        id
    );
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("read {path}: {e} (run demo/export/export_scenario.py first)"));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {path}: {e}"))
}

fn close(a: f64, b: f64) -> bool {
    (a - b).abs() <= 1e-6_f64.max(1e-9 * a.abs().max(b.abs()))
}

#[test]
fn goldens_match_all_push_reference() {
    let mut checked = 0;
    for id in SCENARIOS {
        let sc = load(id);
        assert!(!sc.goldens.is_empty(), "{id}: no goldens");
        for g in &sc.goldens {
            let placement: HashMap<String, usize> = g.placement.clone();
            let res = sc.score_all_push(&placement);
            assert!(res.complete, "{id}/{}: scored incomplete", g.name);
            assert!(
                close(res.total_cost, g.all_push_cost),
                "{id}/{}: cost {} != golden {}",
                g.name,
                res.total_cost,
                g.all_push_cost
            );
            assert!(
                close(res.total_latency, g.all_push_latency),
                "{id}/{}: latency {} != golden {}",
                g.name,
                res.total_latency,
                g.all_push_latency
            );
            checked += 1;
        }
    }
    assert!(checked >= 8, "expected several goldens, checked {checked}");
    eprintln!("verified {checked} goldens across {} scenarios", SCENARIOS.len());
}

#[test]
fn incomplete_placement_flagged() {
    let sc = load("seq_abc");
    let empty: HashMap<String, usize> = HashMap::new();
    let res = sc.score_all_push(&empty);
    assert!(!res.complete);
    assert!(!res.missing.is_empty());
}

#[test]
fn kraken_beats_baselines_on_combined_score() {
    // Sanity: on every curated scenario Kraken should have the lowest normalized score.
    for id in SCENARIOS {
        let sc = load(id);
        let kr = &sc.strategies["kraken"];
        let kr_score = sc.normalize_point(kr.cost, kr.latency).score;
        for (name, m) in &sc.strategies {
            if name == "kraken" {
                continue;
            }
            let s = sc.normalize_point(m.cost, m.latency).score;
            assert!(
                kr_score <= s + 1e-9,
                "{id}: kraken score {kr_score} not <= {name} {s}"
            );
        }
    }
}
