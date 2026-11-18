//! Asserts every table of web/test/golden.json (generated from the Python game).

use dc_core::data::MAX_SITES;
use dc_core::econ::*;
use dc_core::fmt::fmt;
use num_bigint::BigInt;
use serde_json::Value;

fn golden() -> Value {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/../../web/test/golden.json");
    serde_json::from_str(&std::fs::read_to_string(path).expect("read golden.json"))
        .expect("parse golden.json")
}

fn big(v: &Value) -> BigInt {
    v.as_str().expect("decimal string").parse().expect("BigInt")
}

fn int(v: &Value) -> usize {
    v.as_u64().expect("integer") as usize
}

fn rows<'a>(g: &'a Value, key: &str) -> &'a Vec<Value> {
    g[key].as_array().unwrap_or_else(|| panic!("missing {key}"))
}

#[test]
fn golden_expand_cost() {
    let r = rows(&golden(), "expandCost").clone();
    for (k, v) in r.iter().enumerate() {
        assert_eq!(expand_cost(k), big(v), "site {k}");
    }
    assert_eq!(r.len(), MAX_SITES + 1);
}

#[test]
fn golden_cost_of() {
    for r in rows(&golden(), "costOf") {
        assert_eq!(cost_of(int(&r[0]), int(&r[1]) as u32, int(&r[2])), big(&r[3]), "{r}");
    }
}

#[test]
fn golden_chip_cost() {
    for r in rows(&golden(), "chipCost") {
        assert_eq!(chip_cost(int(&r[0]), int(&r[1]) as u32, int(&r[2])), big(&r[3]), "{r}");
    }
}

#[test]
fn golden_tier_income() {
    for r in rows(&golden(), "tierIncome") {
        let got = tier_income(int(&r[0]), int(&r[1]) as u32, int(&r[2]) as u32, int(&r[3]));
        assert_eq!(got, big(&r[4]), "{r}");
    }
}

#[test]
fn golden_staff_cost() {
    for r in rows(&golden(), "staffCost") {
        let level = r[1].as_i64().unwrap() as i32;
        assert_eq!(staff_cost(int(&r[0]), level, int(&r[2])), big(&r[3]), "{r}");
    }
}

#[test]
fn golden_response_secs() {
    for r in rows(&golden(), "responseSecs") {
        let level = r[1].as_i64().unwrap() as i32;
        assert_eq!(response_secs(int(&r[0]), level), r[2].as_i64().unwrap(), "{r}");
    }
}

#[test]
fn golden_milestone_mult() {
    for r in rows(&golden(), "milestoneMult") {
        assert_eq!(milestone_mult(int(&r[0]) as u32), big(&r[1]), "{r}");
    }
}

#[test]
fn golden_crew_multiplier() {
    for r in rows(&golden(), "crewMultiplier") {
        assert_eq!(crew_multiplier(r[0].as_i64().unwrap() as i32), big(&r[1]), "{r}");
    }
}

#[test]
fn golden_fame_gain() {
    for r in rows(&golden(), "fameGain") {
        assert_eq!(fame_gain(&big(&r[0]), int(&r[1])), big(&r[2]), "{r}");
    }
}

#[test]
fn golden_rank_of() {
    for r in rows(&golden(), "rankOf") {
        let (title, need, next) = rank_of(&big(&r[0]));
        assert_eq!(title, r[1].as_str().unwrap(), "{r}");
        assert_eq!(need, big(&r[2]), "{r}");
        assert_eq!(next, r[3].as_str().unwrap(), "{r}");
    }
}

#[test]
fn golden_roman() {
    for r in rows(&golden(), "roman") {
        assert_eq!(roman(int(&r[0]) as u32), r[1].as_str().unwrap(), "{r}");
    }
}

#[test]
fn golden_start_balance() {
    for r in rows(&golden(), "startBalance") {
        assert_eq!(start_balance(int(&r[0])), big(&r[1]), "{r}");
    }
}

#[test]
fn golden_site_name() {
    for r in rows(&golden(), "siteName") {
        assert_eq!(site_name(int(&r[0])), r[1].as_str().unwrap(), "{r}");
    }
}

#[test]
fn golden_chip_name() {
    for r in rows(&golden(), "chipName") {
        assert_eq!(chip_name(int(&r[0]), int(&r[1]) as u32), r[2].as_str().unwrap(), "{r}");
    }
}

#[test]
fn golden_restore_site() {
    let g = golden();
    let r = rows(&g, "restoreSite");
    assert!(r.len() >= 40);
    for row in r {
        let (owned, chips) = restore_site(int(&row[0]), &big(&row[1]), row[2].as_u64().unwrap());
        let want_o: Vec<u32> = row[3].as_array().unwrap().iter().map(|x| int(x) as u32).collect();
        let want_c: Vec<u32> = row[4].as_array().unwrap().iter().map(|x| int(x) as u32).collect();
        assert_eq!(owned, want_o, "owned {row}");
        assert_eq!(chips, want_c, "chips {row}");
    }
}

#[test]
fn golden_fmt() {
    let g = golden();
    let r = rows(&g, "fmt");
    assert!(r.len() >= 60);
    for row in r {
        assert_eq!(fmt(&big(&row[0])), row[1].as_str().unwrap(), "fmt({})", row[0]);
    }
}

#[test]
fn fmt_spot_checks() {
    let b = |s: &str| s.parse::<BigInt>().unwrap();
    assert_eq!(fmt(&b("999995")), "1.00M");
    assert_eq!(fmt(&b("999994")), "999.99K");
    assert_eq!(fmt(&b("-5")), "0");
    assert_eq!(fmt(&BigInt::from(10).pow(36)), "1.00e36");
    assert_eq!(dc_core::fmt::fmt_duration(90061.0), "1d 1h");
    assert_eq!(dc_core::fmt::fmt_duration(3.0 * 3600.0 + 125.0), "3h 2m");
}
