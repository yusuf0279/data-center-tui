//! Replays the scripted play-through in web/test/golden.json (`run`) against `Game`,
//! step by step: rng calls, log lines and full state snapshot. Mirrors web/test/game.test.js.

use dc_core::econ::rank_of;
use dc_core::state::{Game, Rng};
use serde_json::{json, Value};
use std::collections::{HashSet, VecDeque};

/// Rng that replays one step's recorded calls `[kind, value, size]`; strict about order.
#[derive(Default)]
struct Scripted {
    queue: VecDeque<Value>,
    calls: Vec<Value>,
}

impl Scripted {
    fn take(&mut self, kind: &str, size: usize) -> Value {
        let call = self.queue.pop_front().unwrap_or_else(|| panic!("Rust made an rng call ({kind}) Python did not"));
        assert_eq!(call[0].as_str().unwrap(), kind, "rng call kind");
        assert_eq!(call[2].as_u64().unwrap() as usize, size, "rng call size for {kind}");
        self.calls.push(call.clone());
        call[1].clone()
    }
}

impl Rng for Scripted {
    fn random(&mut self) -> f64 {
        self.take("r", 0).as_f64().unwrap()
    }
    fn weighted(&mut self, weights: &[u32]) -> usize {
        self.take("w", weights.len()).as_u64().unwrap() as usize
    }
    fn index(&mut self, n: usize) -> usize {
        self.take("i", n).as_u64().unwrap() as usize
    }
}

fn view(g: &Game<Scripted>) -> Value {
    let crisis = g.crisis.as_ref().map_or(Value::Null, |c| {
        json!({"title": c.title, "sev": c.sev, "fixer": c.fixer, "eta": c.eta})
    });
    json!({
        "balance": g.site_balance.iter().map(|b| b.to_string()).collect::<Vec<_>>(),
        "owned": g.site_owned, "chips": g.site_chips, "staff": g.site_staff,
        "names": g.site_names, "fame": g.fame.to_string(), "sites": g.sites, "cur": g.cur,
        "readOnly": g.read_only(), "phase": g.phase, "autopilot": g.autopilot,
        "crisis": crisis,
        "income": g.income().to_string(), "baseIncome": g.base_income().to_string(),
        "siteIncome": (0..=g.sites).map(|k| g.site_income(k).to_string()).collect::<Vec<_>>(),
        "rank": rank_of(&g.fame).0,
    })
}

fn apply(g: &mut Game<Scripted>, op: &str, arg: &Value) {
    let n = || arg.as_i64().expect("integer arg");
    match op {
        "set_balance" => g.set_balance(arg.as_str().unwrap().parse().unwrap()),
        "buy" => g.buy(n() as usize),
        "chip" => g.buy_chip(n() as usize),
        "hire" => g.hire(n() as usize),
        "tick" => g.tick(),
        "fix" => g.fix(),
        "relocate" => g.relocate(),
        "goto" => g.goto(n()),
        "site" => if n() < 0 { g.prev() } else { g.next() },
        "autopilot" => g.toggle_autopilot(),
        other => panic!("unknown op {other}"),
    }
}

#[test]
fn golden_run_matches_python_step_by_step() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../web/test/golden.json");
    let golden: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let steps: Vec<&Value> = golden["run"].as_array().unwrap().iter().filter(|s| s["op"] != "offline").collect();
    assert!(steps.len() > 100);
    let mut g = Game::new(Scripted::default());
    assert!(g.autopilot, "a brand-new game has autopilot on");
    let mut seen = HashSet::new();
    for (i, st) in steps.iter().enumerate() {
        let op = st["op"].as_str().unwrap();
        seen.insert(op);
        g.rng.queue = st["rng"].as_array().unwrap().iter().cloned().collect();
        g.rng.calls.clear();
        let log_from = g.log_id;
        apply(&mut g, op, &st["arg"]);
        let label = format!("step {i} {op} {}", st["arg"]);
        assert!(g.rng.queue.is_empty(), "{label}: the game skipped rng calls Python made");
        assert_eq!(Value::Array(g.rng.calls.clone()), st["rng"], "{label}: rng calls");
        let log: Vec<Value> = g.log.iter().filter(|e| e.id > log_from).map(|e| json!([e.text, e.kind.as_str()])).collect();
        assert_eq!(Value::Array(log), st["log"], "{label}: log");
        assert_eq!(view(&g), st["state"], "{label}: state");
    }
    for op in ["buy", "chip", "hire", "tick", "fix", "relocate", "goto", "site", "autopilot"] {
        assert!(seen.contains(op), "run covers {op}");
    }
    let text: String = steps.iter().flat_map(|s| s["log"].as_array().unwrap()).map(|l| l[0].as_str().unwrap()).collect::<Vec<_>>().join("\n");
    for needle in ["decommissioned: view only", "Promoted", "Relocated to", "fixed", "income -100%", "income -75%", "income -50%", "Hired a"] {
        assert!(text.contains(needle), "run exercises: {needle}");
    }
}
