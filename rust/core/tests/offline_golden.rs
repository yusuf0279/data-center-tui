//! Replays the `offline` cases (last entry of `run`) of web/test/golden.json against `load_object`.
//! Mirrors the offline test in web/test/game.test.js.

use dc_core::econ::rank_of;
use dc_core::save::{load_object, Loaded};
use dc_core::state::{Game, Rng};
use serde_json::{json, Value};

/// The offline cases make no random calls.
struct NoRng;

impl Rng for NoRng {
    fn random(&mut self) -> f64 {
        panic!("loading must not use the rng")
    }
    fn weighted(&mut self, _: &[u32]) -> usize {
        panic!("loading must not use the rng")
    }
    fn index(&mut self, _: usize) -> usize {
        panic!("loading must not use the rng")
    }
}

fn view(g: &Game<NoRng>) -> Value {
    let crisis = g.crisis.as_ref().map_or(Value::Null, |c| json!({"title": c.title, "sev": c.sev, "fixer": c.fixer, "eta": c.eta}));
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

#[test]
fn golden_offline_cases() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../web/test/golden.json");
    let golden: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    let last = golden["run"].as_array().unwrap().last().unwrap();
    assert_eq!(last["op"], "offline");
    let cases = last["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 3);
    let mut credited = 0;
    for c in cases {
        let now = c["now"].as_f64().unwrap();
        let Loaded { game, away, .. } = load_object(c["save"].as_object().unwrap(), NoRng, now);
        assert_eq!(view(&game), c["state"], "offline now={now}");
        if c["away"].is_null() {
            assert!(away.is_none());
            continue;
        }
        credited += 1;
        let want = c["away"].as_array().unwrap();
        let away = away.expect("credited");
        assert_eq!(away.seconds, want[0].as_f64().unwrap());
        assert_eq!(away.earned.to_string(), want[1].as_str().unwrap());
        let msg = game.log.last().unwrap();
        assert_eq!(
            msg.text,
            format!("Welcome back! Away {}, earned ${} (75% offline rate)", want[2].as_str().unwrap(), want[3].as_str().unwrap())
        );
        assert_eq!(msg.kind.as_str(), "warning");
    }
    assert_eq!(credited, 2);
}
