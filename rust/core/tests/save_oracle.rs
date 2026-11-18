//! Differential test against the committed Python loader (`git show e66836d:data_center_tui/game.py`).
//! tests/data/save_oracle.json holds 600 generated saves (mixed types, bounds, legacy and
//! pre-site layouts, huge ints) with the state the Python `DataCenter.__init__` produced.
//! Only the documented divergences are excluded: see the comments below.

use dc_core::save::load_text;
use dc_core::state::{Game, Rng};
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

fn strings(v: &[num_bigint::BigInt]) -> Vec<String> {
    v.iter().map(ToString::to_string).collect()
}

fn check(g: &Game<NoRng>, want: &Value, label: &str) {
    let w = |k: &str| want[k].clone();
    assert_eq!(Value::from(g.sites), w("sites"), "{label} sites");
    assert_eq!(Value::from(g.cur), w("cur"), "{label} cur");
    assert_eq!(Value::from(strings(&g.site_balance)), w("balance"), "{label} balance");
    assert_eq!(serde_json::to_value(&g.site_owned).unwrap(), w("owned"), "{label} owned");
    assert_eq!(serde_json::to_value(&g.site_chips).unwrap(), w("chips"), "{label} chips");
    assert_eq!(serde_json::to_value(&g.site_staff).unwrap(), w("staff"), "{label} staff");
    assert_eq!(Value::from(g.fame.to_string()), w("fame"), "{label} fame");
    assert_eq!(serde_json::to_value(&g.site_names).unwrap(), w("names"), "{label} names");
    assert_eq!(Value::from(g.autopilot), w("auto"), "{label} autopilot");
}

#[test]
fn load_matches_the_python_loader_on_generated_saves() {
    let cases: Vec<Value> = serde_json::from_str(&common::read_gz("save_oracle.json.gz")).unwrap();
    assert!(cases.len() >= 500);
    let (mut credited, mut legacy, mut pre_site) = (0, 0, 0);
    for (i, c) in cases.iter().enumerate() {
        let text = c["text"].as_str().unwrap();
        let label = format!("case {i}: {text:.300}");
        let l = load_text(text, NoRng, c["now"].as_f64().unwrap());
        let want = &c["want"];
        check(&l.game, want, &label);
        // Python keeps any string as the theme; Rust only 1..=64 chars (the UI validates it anyway).
        let py_theme = want["theme"].as_str().unwrap();
        let expect = if py_theme.is_empty() || py_theme.chars().count() > 64 { "gruvbox" } else { py_theme };
        assert_eq!(l.theme, expect, "{label} theme");
        let o = want["online"].as_array().unwrap();
        let got = (l.online.asked, l.online.joined, l.online.name.as_str(), l.online.token.as_str());
        assert_eq!(got, (o[0].as_bool().unwrap(), o[1].as_bool().unwrap(), o[2].as_str().unwrap(), o[3].as_str().unwrap()), "{label} online");
        let earned = want["away"][1].as_str().unwrap();
        match &l.away {
            None => assert_eq!(earned, "0", "{label} away"),
            Some(a) => {
                credited += 1;
                assert_eq!(a.earned.to_string(), earned, "{label} earned");
                assert_eq!(a.seconds, want["away"][0].as_f64().unwrap(), "{label} seconds");
            }
        }
        legacy += usize::from(!text.contains("site_owned"));
        pre_site += usize::from(!text.contains("site_balance"));
    }
    assert!(credited > 50 && legacy > 50 && pre_site > 50, "coverage: {credited} {legacy} {pre_site}");
}
