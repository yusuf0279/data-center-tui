//! The 4300-digit integer limit against the committed Python loader
//! (tests/data/save_edge_oracle.json, from scripts/save_edge_oracle.py): 4300 vs 4301
//! digits, positive and negative (the sign is not a digit), as the last value, an earlier
//! duplicate, nested, in a string or as a float (no limit).

use dc_core::save::{load_text, parse_save};
use dc_core::state::Rng;
use serde_json::Value;

mod common;

struct NoRng;

impl Rng for NoRng {
    fn random(&mut self) -> f64 {
        0.0
    }
    fn weighted(&mut self, _: &[u32]) -> usize {
        0
    }
    fn index(&mut self, _: usize) -> usize {
        0
    }
}

fn cases() -> Vec<Value> {
    serde_json::from_str(&common::read_gz("save_edge_oracle.json.gz")).unwrap()
}

#[test]
fn digit_limit_matches_python() {
    let (mut loaded, mut rejected) = (0, 0);
    for (i, c) in cases().iter().enumerate() {
        let text = c["text"].as_str().unwrap();
        let want = &c["want"];
        let l = load_text(text, NoRng, c["now"].as_f64().unwrap());
        let label = format!("case {i}: {:.60}...{}", text, &text[text.len() - 30..]);
        assert_eq!(Value::from(l.game.sites), want["sites"], "{label} sites");
        let bal: Vec<String> = l.game.site_balance.iter().map(ToString::to_string).collect();
        assert_eq!(Value::from(bal), want["balance"], "{label} balance");
        assert_eq!(Value::from(l.game.fame.to_string()), want["fame"], "{label} fame");
        assert_eq!(serde_json::to_value(&l.game.site_owned).unwrap(), want["owned"], "{label}");
        assert_eq!(l.theme, want["theme"].as_str().unwrap(), "{label} theme");
        assert_eq!(parse_save(text).is_some(), want["sites"] == 2, "{label} parse_save");
        if want["sites"] == 2 { loaded += 1 } else { rejected += 1 }
    }
    assert!(loaded > 40 && rejected >= 10, "coverage {loaded} {rejected}");
}

fn doc(int: &str) -> String {
    format!("{{\"sites\": 2, \"junk\": {int}}}")
}

#[test]
fn sign_is_not_a_digit() {
    for (sign, digits, ok) in [("", 4300, true), ("", 4301, false), ("-", 4300, true), ("-", 4301, false)] {
        let text = doc(&format!("{sign}{}", "9".repeat(digits)));
        assert_eq!(parse_save(&text).is_some(), ok, "{sign}{digits}");
    }
}

#[test]
fn earlier_duplicate_key_still_rejects() {
    let big = "9".repeat(4301);
    assert!(parse_save(&format!("{{\"a\": {big}, \"a\": 1}}")).is_none());
    assert!(parse_save(&format!("{{\"a\": \"{big}\", \"b\": {big}.5, \"c\": 1}}")).is_some());
}
