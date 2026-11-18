//! Tests that pin behaviour a mutation run found unguarded: fixer tie-break, exact
//! integer sqrt in `fame_gain`, the 1/120 crisis dice and the severity gates.
//! Expected values come from the real Python game: `python3 scripts/gap_vectors.py`.

use dc_core::data::{CRISIS_MEAN, STAFF};
use dc_core::econ::fame_gain;
use dc_core::state::{Crisis, Game, Rng};
use num_bigint::BigInt;
use serde_json::Value;
use std::collections::VecDeque;

mod common;

fn vectors() -> Value {
    serde_json::from_str(&common::read_gz("gap_vectors.json.gz")).expect("parse gap_vectors.json.gz")
}

/// Replays recorded `[kind, value, size]` calls; strict about kind, size and count.
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

fn u32s(v: &Value) -> Vec<u32> {
    v.as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as u32).collect()
}

fn i32s(v: &Value) -> Vec<i32> {
    v.as_array().unwrap().iter().map(|x| x.as_i64().unwrap() as i32).collect()
}

/// A game with `site + 1` data centers, viewing the live one, with the given layout.
fn game_at(site: usize, owned: &[u32], chips: &[u32], staff: &[i32]) -> Game<Scripted> {
    let mut g = Game::new(Scripted::default());
    g.autopilot = false; // tick() would otherwise buy things; crisis logic is what we test
    while g.sites < site {
        g.site_balance.push(BigInt::from(0));
        g.site_owned.push(vec![0; owned.len()]);
        g.site_chips.push(vec![0; owned.len()]);
        g.site_staff.push(vec![-1; staff.len()]);
        g.site_names.push(String::new());
        g.sites += 1;
    }
    g.cur = site;
    g.site_owned[site] = owned.to_vec();
    g.site_chips[site] = chips.to_vec();
    g.site_staff[site] = staff.to_vec();
    g
}

fn crisis_json(c: &Option<Crisis>) -> Value {
    c.as_ref().map_or(Value::Null, |c| serde_json::json!({"title": c.title, "sev": c.sev, "fixer": c.fixer, "eta": c.eta}))
}

/// Run one tick with `calls` as the rng script; return (crisis, rng calls, new log lines).
fn run_tick(g: &mut Game<Scripted>, calls: &Value) -> (Value, Value, Vec<String>) {
    g.rng.queue = calls.as_array().unwrap().iter().cloned().collect();
    g.rng.calls.clear();
    let from = g.log_id;
    g.tick();
    assert!(g.rng.queue.is_empty(), "the game skipped rng calls Python made");
    let log = g.log.iter().filter(|e| e.id > from).map(|e| e.text.clone()).collect();
    (crisis_json(&g.crisis), Value::Array(g.rng.calls.clone()), log)
}

fn strs(v: &Value) -> Vec<String> {
    v.as_array().unwrap().iter().map(|x| x.as_str().unwrap().to_string()).collect()
}

#[test]
fn fixer_choice_matches_python_including_ties() {
    let v = vectors();
    let cases = v["fixer"].as_array().unwrap();
    assert!(cases.len() >= 500);
    let mut ties = 0;
    for c in cases {
        let staff = i32s(&c["staff"]);
        let sev = c["sev"].as_u64().unwrap() as u8;
        let mut g = game_at(0, &[0; 10], &[0; 10], &staff);
        g.crisis = Some(Crisis { title: "T", sev, fixer: None, eta: None });
        let (crisis, calls, log) = run_tick(&mut g, &c["calls"]);
        let label = format!("staff {staff:?} sev {sev}");
        assert_eq!(crisis, c["crisis"], "{label}: crisis");
        assert_eq!(calls, c["calls"], "{label}: rng calls");
        assert_eq!(log, strs(&c["log"]), "{label}: log");
        // when the countdown has not finished, the fixer is visible: it must be Python's
        if !crisis.is_null() {
            assert_eq!(crisis["fixer"], c["fixer"], "{label}: fixer");
        }
        ties += usize::from(c["log"].as_array().unwrap().iter().any(|l| l.as_str().unwrap().contains("fixed")));
    }
    assert!(ties > 0);
}

#[test]
fn fixer_tie_goes_to_the_first_role() {
    // Vibecoder Lv1 (10*0.8) ties Forward Deployed Engineer Lv0 (8.0): the Vibecoder wins.
    let mut staff = vec![-1; STAFF.len()];
    staff[0] = 1;
    staff[2] = 0;
    let mut g = game_at(0, &[0; 10], &[0; 10], &staff);
    g.crisis = Some(Crisis { title: "T", sev: 1, fixer: None, eta: None });
    g.tick();
    let c = g.crisis.as_ref().expect("still counting down");
    assert_eq!(c.fixer, Some(0));
}

#[test]
fn fame_gain_is_an_exact_integer_sqrt() {
    let v = vectors();
    let rows = v["fame"].as_array().unwrap();
    assert!(rows.len() > 3000);
    for r in rows {
        let balance: BigInt = r[1].as_str().unwrap().parse().unwrap();
        let want: BigInt = r[2].as_str().unwrap().parse().unwrap();
        assert_eq!(fame_gain(&balance, r[0].as_u64().unwrap() as usize), want, "{r}");
    }
}

#[test]
fn crisis_dice_boundary_matches_python() {
    let v = vectors();
    let cases = v["spawn"].as_array().unwrap();
    let mut spawned = 0;
    let mut quiet_at_edge = 0;
    for c in cases {
        let (site, owned, chips, staff) = (c["site"].as_u64().unwrap() as usize, u32s(&c["owned"]), u32s(&c["chips"]), i32s(&c["staff"]));
        let mut g = game_at(site, &owned, &chips, &staff);
        let (crisis, calls, log) = run_tick(&mut g, &c["calls"]);
        let label = format!("{c}");
        assert_eq!(g.base_income().to_string(), c["base"].as_str().unwrap(), "{label}");
        assert_eq!(crisis, c["crisis"], "{label}: crisis");
        assert_eq!(calls, c["calls"], "{label}: rng calls");
        assert_eq!(log, strs(&c["log"]), "{label}: log");
        spawned += usize::from(!crisis.is_null());
        quiet_at_edge += usize::from(crisis.is_null() && c["script"][0][1].as_f64() == Some(1.0 / f64::from(CRISIS_MEAN)));
    }
    assert!(spawned > 10 && quiet_at_edge > 0);
}

#[test]
fn severity_gates_match_python() {
    let v = vectors();
    let cases = v["gates"].as_array().unwrap();
    let mut by_sev = [0usize; 3];
    for c in cases {
        let (site, owned, chips, staff) = (c["site"].as_u64().unwrap() as usize, u32s(&c["owned"]), u32s(&c["chips"]), i32s(&c["staff"]));
        let mut g = game_at(site, &owned, &chips, &staff);
        assert_eq!(g.raw_income(site).to_string(), c["raw"].as_str().unwrap());
        let (crisis, calls, log) = run_tick(&mut g, &c["calls"]);
        let label = format!("{c}");
        assert_eq!(crisis, c["crisis"], "{label}: crisis");
        assert_eq!(calls, c["calls"], "{label}: rng calls (pool sizes)");
        assert_eq!(log, strs(&c["log"]), "{label}: log");
        by_sev[crisis["sev"].as_u64().unwrap() as usize - 1] += 1;
    }
    assert!(by_sev.iter().all(|&n| n > 5), "all severities exercised: {by_sev:?}");
}
