//! Ports web/test/save.test.js, plus the Python-format cases (bare big ints, bool/float
//! rejection, legacy and pre-site saves) and the atomic write.

use dc_core::data::*;
use dc_core::econ::{restore_site, start_balance};
use dc_core::save::*;
use dc_core::state::{Game, Rng};
use num_bigint::BigInt;
use std::path::PathBuf;

struct Half;

impl Rng for Half {
    fn random(&mut self) -> f64 {
        0.5
    }
    fn weighted(&mut self, _: &[u32]) -> usize {
        0
    }
    fn index(&mut self, _: usize) -> usize {
        0
    }
}

const TOKEN: &str = "abababababababababababababababab";

fn load(text: &str) -> Loaded<Half> {
    load_text(text, Half, 1000.0)
}

fn load_at(text: &str, now: f64) -> Loaded<Half> {
    load_text(text, Half, now)
}

fn g(text: &str) -> Game<Half> {
    load(text).game
}

fn big(s: &str) -> BigInt {
    s.parse().unwrap()
}

fn pow10(n: u32) -> BigInt {
    BigInt::from(10).pow(n)
}

/// Invariants every loaded game must satisfy, whatever it was fed.
fn assert_sane(g: &Game<Half>) {
    let n = g.sites + 1;
    assert!(g.sites <= 60 && g.cur <= g.sites);
    assert_eq!(g.site_balance.len(), n);
    assert_eq!(g.site_owned.len(), n);
    assert_eq!(g.site_chips.len(), n);
    assert_eq!(g.site_staff.len(), n);
    assert_eq!(g.site_names.len(), n);
    assert!(g.site_balance.iter().all(|b| *b >= BigInt::from(0) && *b < max_big()));
    assert!(g.site_owned.iter().all(|a| a.len() == 10 && a.iter().all(|&v| v <= 4000)));
    assert!(g.site_chips.iter().all(|a| a.iter().all(|&v| v <= 20)));
    assert!(g.site_staff.iter().all(|a| a.len() == 10 && a.iter().all(|&v| (-1..=10).contains(&v))));
    assert!(g.site_names.iter().all(|s| s.len() <= 24 && s.bytes().all(|c| (b' '..=b'~').contains(&c))));
    assert!(g.fame >= BigInt::from(0) && g.fame < max_big());
    let _ = g.income();
}

#[test]
fn garbage_saves_fall_back_to_a_fresh_game_with_autopilot_on() {
    let junk = ["", "{", "[]", "[1,2]", "\"x\"", "null", "{}", "garbage", "42", "true", "NaN", "\u{0}", "{\"a\":", "{} {}"];
    for raw in junk {
        let l = load(raw);
        assert_sane(&l.game);
        assert_eq!(l.game.sites, 0, "{raw:?}");
        assert_eq!(l.game.site_balance[0], BigInt::from(500));
        assert_eq!(l.game.fame, BigInt::from(0));
        assert!(l.game.autopilot, "brand-new save: {raw:?}");
        assert_eq!(l.online, Online::default());
        assert_eq!(l.theme, "gruvbox");
        assert!(l.away.is_none());
    }
}

#[test]
fn missing_and_unreadable_files_are_a_fresh_game() {
    let dir = scratch("missing");
    let l = load_path(&dir.join("nope.json"), Half, 5.0);
    assert!(l.game.autopilot && l.game.site_balance[0] == BigInt::from(500));
    let bad = dir.join("bad.json");
    std::fs::write(&bad, [0xffu8, 0xfe, 0x7b]).unwrap();
    assert!(load_path(&bad, Half, 5.0).game.autopilot);
    assert!(load_path(&dir, Half, 5.0).game.autopilot, "a directory is not a save");
}

#[test]
fn autopilot_defaults_on_only_for_an_empty_save() {
    assert!(g("{}").autopilot);
    assert!(!g(r#"{"sites": 0}"#).autopilot, "an existing save without the key");
    assert!(!g(r#"{"autopilot": false}"#).autopilot);
    assert!(g(r#"{"autopilot": true}"#).autopilot);
    for bad in ["\"yes\"", "1", "0", "null", "1.0", "[]"] {
        assert!(!g(&format!(r#"{{"autopilot": {bad}}}"#)).autopilot, "{bad}");
    }
}

#[test]
fn sites_bounds_0_to_60_and_python_int_rules() {
    let cases = [("0", 0), ("1", 1), ("60", 60), ("61", 0), ("-1", 0), ("1.5", 0), ("\"3\"", 0), ("true", 0),
        ("false", 0), ("null", 0), ("1e300", 0), ("1.0", 0), ("3.0", 0), ("2e0", 0), ("-0", 0),
        ("1000000000000000000000000000000", 0)];
    for (v, want) in cases {
        let game = g(&format!(r#"{{"sites": {v}, "autopilot": false}}"#));
        assert_sane(&game);
        assert_eq!(game.sites, want, "sites={v}");
    }
    assert_eq!(g(r#"{"sites": 60}"#).site_owned.len(), 61);
}

#[test]
fn levels_reset_individually() {
    let game = g(r#"{"sites": 1, "autopilot": false, "site_balance": [1, 2],
        "site_owned": [[4000, 4001, -1, 1.5, "5", null, 7, true, 0, 3999], "nope"],
        "site_chips": [[20, 21, -1, 0, 5, 1000000000, "x", null, 2, 3], null],
        "site_staff": [[10, 11, -2, -1, 0, 5, 0.5, "3", null, 9], {"0": 1}]}"#);
    assert_sane(&game);
    assert_eq!(game.site_owned[0], [4000, 0, 0, 0, 0, 0, 7, 0, 0, 3999]);
    assert_eq!(game.site_chips[0], [20, 0, 0, 0, 5, 0, 0, 0, 2, 3]);
    assert_eq!(game.site_staff[0], [10, -1, -1, -1, 0, 5, -1, -1, -1, 9]);
    assert_eq!(game.site_owned[1], [0; 10]);
    assert_eq!(game.site_staff[1], [-1; 10]);
    let h = g(r#"{"sites": 0, "site_owned": [[1,2,3,4,5,6,7,8,9,10,11,12]], "site_chips": [[1]]}"#);
    assert_eq!(h.site_owned[0], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
    assert_eq!(h.site_chips[0], [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
}

#[test]
fn levels_reject_bool_and_float_one() {
    let game = g(r#"{"site_owned": [[1.0, true, false, 2, 3e0, 4, -0, 5, 6, 7]], "site_balance": [5]}"#);
    assert_eq!(game.site_owned[0], [0, 0, 0, 2, 0, 4, 0, 5, 6, 7], "-0 is the int 0");
}

#[test]
fn balances_python_format_bare_ints() {
    let max = (pow10(600) - 1u32).to_string();
    let over = pow10(600).to_string();
    let text = format!(
        r#"{{"sites": 4, "cur": 0, "site_balance": [{max}, {over}, -5, 12.5, 123456789, true, 1.0, null, "abc"]}}"#
    );
    let game = g(&text);
    assert_sane(&game);
    assert_eq!(game.site_balance[0], pow10(600) - 1u32);
    assert_eq!(game.site_balance[1], start_balance(1), "10^600 itself is out");
    assert_eq!(game.site_balance[2], start_balance(2));
    assert_eq!(game.site_balance[3], start_balance(3));
    assert_eq!(game.site_balance[4], BigInt::from(123456789));
    let b = g(r#"{"site_balance": [true]}"#);
    assert_eq!(b.site_balance[0], BigInt::from(500));
    assert_eq!(g(r#"{"site_balance": [1.0]}"#).site_balance[0], BigInt::from(500), "1.0 is a float");
    assert_eq!(g(r#"{"site_balance": [1e30]}"#).site_balance[0], BigInt::from(500));
    assert_eq!(g(r#"{"site_balance": [1000000000000000019884624838656]}"#).site_balance[0], big("1000000000000000019884624838656"));
}

#[test]
fn balances_web_format_decimal_strings() {
    let max = (pow10(600) - 1u32).to_string();
    let big601 = format!("1{}", "0".repeat(600));
    let text = format!(
        r#"{{"sites": 5, "site_balance": ["{max}", "{big601}", "-5", "12.5", "abc", 123456789, -3, 1e30, null, {{}}], "cur": 0}}"#
    );
    let game = g(&text);
    assert_sane(&game);
    assert_eq!(game.site_balance[0], pow10(600) - 1u32);
    for k in 1..=4 {
        assert_eq!(game.site_balance[k], start_balance(k), "k={k}");
    }
    assert_eq!(game.site_balance[5], BigInt::from(123456789));
    assert_eq!(g(r#"{"site_balance": "not a list"}"#).site_balance[0], BigInt::from(500));
    assert_eq!(g(r#"{"site_balance": ["007"]}"#).site_balance[0], BigInt::from(7));
    assert_eq!(g(r#"{"site_balance": [""]}"#).site_balance[0], BigInt::from(500));
}

#[test]
fn big_values_1e500_both_encodings() {
    let digits = pow10(500).to_string();
    for text in [
        format!(r#"{{"site_balance": [{digits}], "fame": {digits}}}"#),
        format!(r#"{{"site_balance": ["{digits}"], "fame": "{digits}"}}"#),
    ] {
        let game = g(&text);
        assert_eq!(game.site_balance[0], pow10(500));
        assert_eq!(game.fame, pow10(500));
        assert_sane(&game);
    }
}

#[test]
fn fame_below_max_big_else_zero() {
    assert_eq!(g(r#"{"site_balance": [1], "fame": "12345678901234567890"}"#).fame, big("12345678901234567890"));
    assert_eq!(g(r#"{"site_balance": [1], "fame": 12345678901234567890123}"#).fame, big("12345678901234567890123"));
    assert_eq!(g(r#"{"fame": 7, "site_balance": []}"#).fame, BigInt::from(7));
    let huge = format!("1{}", "0".repeat(600));
    for bad in ["\"-1\"", "\"1e3\"", "\"\"", "\"x\"", "null", "-1", "1.5", "1.0", "true", "[]", "{}", &format!("\"{huge}\""), &huge] {
        let text = format!(r#"{{"site_balance": [1], "fame": {bad}}}"#);
        assert_eq!(g(&text).fame, BigInt::from(0), "{bad}");
    }
}

#[test]
fn cur_in_range_or_the_newest() {
    for (v, want) in [("1", 1), ("4", 3), ("-1", 3), ("\"x\"", 3), ("0.5", 3), ("1.0", 3), ("true", 3), ("0", 0)] {
        assert_eq!(g(&format!(r#"{{"sites": 3, "cur": {v}}}"#)).cur, want, "cur={v}");
    }
}

#[test]
fn site_names_printable_ascii_up_to_24() {
    let long25 = "x".repeat(25);
    let long24 = "x".repeat(24);
    let text = format!(r#"{{"sites": 5, "site_names": ["Home", "{long24}", "{long25}", "tab\there", "café", 7]}}"#);
    let game = g(&text);
    assert_eq!(game.site_names, ["Home", long24.as_str(), "", "", "", ""]);
    assert_eq!(game.site_label(0), "Home");
    assert_eq!(game.site_label(2), dc_core::econ::site_name(2));
    assert_eq!(g(r#"{"sites": 0, "site_names": ["   "]}"#).site_label(0), dc_core::econ::site_name(0), "blank = default");
    assert_eq!(g(r#"{"site_names": ["a\n"]}"#).site_names, [""], "a trailing newline is not printable");
}

#[test]
fn online_block_needs_valid_name_and_token() {
    let on = |body: &str| load(&format!(r#"{{"online": {body}}}"#)).online;
    let ok = on(&format!(r#"{{"asked": true, "joined": true, "name": "Ada_1", "token": "{TOKEN}"}}"#));
    assert_eq!(ok, Online { asked: true, joined: true, name: "Ada_1".into(), token: TOKEN.into() });
    let gone = Online { asked: true, ..Online::default() };
    assert_eq!(on(&format!(r#"{{"asked": true, "joined": true, "name": "_bad", "token": "{TOKEN}"}}"#)), gone);
    assert_eq!(on(r#"{"asked": true, "joined": true, "name": "Ada", "token": "XYZ"}"#), gone);
    let not_joined = on(&format!(r#"{{"asked": "yes", "joined": "true", "name": "Ada", "token": "{TOKEN}"}}"#));
    assert_eq!(not_joined, Online { asked: false, joined: false, name: "Ada".into(), token: TOKEN.into() });
    assert!(!on(r#""x""#).joined);
    assert!(!on("[]").asked);
    assert!(!on(&format!(r#"{{"name": "{}", "token": "{TOKEN}", "joined": true}}"#, "a".repeat(21))).joined);
    assert!(!on(&format!(r#"{{"name": "Ada", "token": "{TOKEN}", "joined": 1}}"#)).joined);
    assert!(!on(&format!(r#"{{"name": 5, "token": "{TOKEN}", "joined": true}}"#)).joined);
}

#[test]
fn theme_must_be_a_short_non_empty_string() {
    assert_eq!(load(r#"{"theme": "nord"}"#).theme, "nord");
    let long = format!("\"{}\"", "x".repeat(65));
    for bad in ["\"\"", "5", "null", &long, "{}"] {
        assert_eq!(load(&format!(r#"{{"theme": {bad}}}"#)).theme, "gruvbox", "{bad}");
    }
}

#[test]
fn round_trip_through_python_format_text() {
    let mut l = load_at("{}", 5000.0);
    let game = &mut l.game;
    game.site_balance[0] = big("123456789012345678901234567890");
    game.site_owned[0][2] = 40;
    game.site_chips[0][2] = 3;
    game.site_staff[0][1] = 4;
    game.fame = big("99999999999999999999");
    game.sites = 1;
    game.site_owned.push(vec![1; 10]);
    game.site_chips.push(vec![0; 10]);
    game.site_balance.push(BigInt::from(777));
    game.site_staff.push(vec![-1; 10]);
    game.site_names = vec!["Home".into(), String::new()];
    game.cur = 0;
    game.autopilot = false;
    let online = Online { asked: true, joined: true, name: "Zed".into(), token: TOKEN.into() };
    let text = to_save_string(game, &online, "nord", 5000.0);
    assert!(text.contains(r#""site_balance": [123456789012345678901234567890, 777]"#), "{text}");
    assert!(text.contains(r#""fame": 99999999999999999999, "sites": 1, "cur": 0, "autopilot": false"#), "{text}");
    assert!(text.ends_with(r#""theme": "nord", "saved_at": 5000.0}"#), "{text}");
    let keys: Vec<String> = parse_save(&text).unwrap().keys().cloned().collect();
    assert_eq!(keys, ["autopilot", "cur", "fame", "online", "saved_at", "site_balance", "site_chips", "site_names",
        "site_owned", "site_staff", "sites", "theme"].map(String::from), "serde_json sorts keys: same set");
    let h = load_at(&text, 5000.0); // saved_at == now: nothing earned
    assert!(h.away.is_none());
    assert_eq!(to_save_string(&h.game, &h.online, &h.theme, 5000.0), text);
    assert_eq!((h.online, h.theme.as_str()), (online, "nord"));
}

#[test]
fn web_format_input_resaves_as_python_format() {
    let web = format!(
        r#"{{"site_balance": ["{}"], "site_owned": [[1,0,0,0,0,0,0,0,0,0]], "site_chips": [[0,0,0,0,0,0,0,0,0,0]],
        "site_staff": [[-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]], "fame": "12", "sites": 0, "cur": 0, "autopilot": false,
        "site_names": [""], "online": {{"asked": false, "joined": false, "name": "", "token": ""}},
        "theme": "gruvbox", "saved_at": 1000}}"#,
        pow10(500)
    );
    let l = load_at(&web, 1000.0);
    let out = to_save_string(&l.game, &l.online, &l.theme, 1000.0);
    assert!(out.contains(&format!("[{}]", pow10(500))), "bare integer");
    assert!(!out.contains(&format!("\"{}\"", pow10(500))), "not a string");
    assert!(out.contains(r#""fame": 12,"#));
    let again = load_at(&out, 1000.0);
    assert_eq!(again.game.site_balance, l.game.site_balance);
}

#[test]
fn strings_are_escaped_like_json() {
    let mut l = load("{}");
    l.game.site_names = vec!["a\"b\\c".into()];
    let text = to_save_string(&l.game, &l.online, "caf\u{e9} \u{1F600}", 1.0);
    assert!(text.contains(r#""site_names": ["a\"b\\c"]"#));
    assert!(text.contains(r#""theme": "caf\u00e9 \ud83d\ude00""#));
    let back = load_at(&text, 1.0);
    assert_eq!(back.game.site_names, ["a\"b\\c"]);
    assert_eq!(back.theme, "caf\u{e9} \u{1F600}");
}

// ------------------------------------------------------------- legacy migration

#[test]
fn pre_site_save_moves_balance_and_crew_to_the_newest_site() {
    let l = load(
        r#"{"sites": 2, "balance": 12345, "staff": [3, -1, 2], "owned": [1, 2], "chips": [0, 1],
            "legacy": [5000000000000, "x"], "saved_at": 0}"#,
    );
    let game = l.game;
    assert_sane(&game);
    assert_eq!(game.site_balance, [BigInt::from(0), BigInt::from(0), BigInt::from(12345)]);
    assert_eq!(game.fame, BigInt::from(2), "each data center already opened counts as one Fame");
    assert_eq!(game.site_staff[2], [3, -1, 2, -1, -1, -1, -1, -1, -1, -1]);
    assert_eq!(game.site_staff[0], [-1; 10]);
    let bonus = 5 * ((3 + 1) + (2 + 1));
    let (o, c) = restore_site(0, &BigInt::from(5_000_000_000_000u64), bonus);
    assert_eq!((&game.site_owned[0], &game.site_chips[0]), (&o, &c));
    assert_eq!(game.site_owned[1], [0; 10], "an unusable legacy income restores nothing");
    assert_eq!(game.site_owned[2], [1, 2, 0, 0, 0, 0, 0, 0, 0, 0]);
    assert_eq!(game.site_chips[2], [0, 1, 0, 0, 0, 0, 0, 0, 0, 0]);
    assert!(!game.autopilot);
}

#[test]
fn pre_site_balance_must_be_a_valid_int() {
    for bad in ["-1", "1.5", "true", "null", "1.0"] {
        let game = g(&format!(r#"{{"sites": 0, "balance": {bad}}}"#));
        assert_eq!(game.site_balance[0], BigInt::from(500), "{bad}");
    }
    assert_eq!(g(r#"{"balance": 0}"#).site_balance[0], BigInt::from(0));
}

#[test]
fn mixed_formats_pick_branches_independently() {
    // current-format hardware with a pre-site balance: balance migrates, fame defaults to `sites`
    let game = g(r#"{"sites": 1, "site_owned": [[1],[2]], "balance": 77}"#);
    assert_eq!(game.site_balance, [BigInt::from(0), BigInt::from(77)]);
    assert_eq!(game.fame, BigInt::from(1));
    assert_eq!(game.site_owned[1][0], 2);
    // current-format money with legacy hardware: fame defaults to 0
    let game = g(r#"{"sites": 1, "site_balance": [5, 6], "owned": [3], "fame": null}"#);
    assert_eq!(game.fame, BigInt::from(0));
    assert_eq!(game.site_owned[1][0], 3);
}

#[test]
fn integers_beyond_python_limits_make_the_whole_file_garbage() {
    let text = format!(r#"{{"sites": 1, "fame": {}}}"#, "9".repeat(4301));
    let l = load(&text);
    assert!(l.game.autopilot && l.game.sites == 0, "Python 3.11+ json.loads raises ValueError");
    let ok = format!(r#"{{"sites": 1, "fame": {}}}"#, "9".repeat(4300));
    assert_eq!(g(&ok).sites, 1);
}

// ------------------------------------------------------------------ offline

fn offline_save(extra: &str) -> String {
    format!(
        r#"{{"sites": 1, "cur": 0, "autopilot": false, "fame": "3",
        "site_balance": ["1000", "2000"],
        "site_owned": [[9,9,9,9,9,9,9,9,9,9], [10,0,0,0,0,0,0,0,0,0]]{extra}}}"#
    )
}

fn offline(saved_at: &str, now: f64) -> Loaded<Half> {
    let extra = if saved_at.is_empty() { String::new() } else { format!(r#", "saved_at": {saved_at}"#) };
    load_at(&offline_save(&extra), now)
}

#[test]
fn offline_75_percent_of_the_live_site_only_whole_seconds() {
    let l = offline("100", 100.0 + 3600.9);
    let live = l.game.site_income(1);
    assert_eq!(live, BigInt::from(21200));
    assert_eq!(l.game.site_balance[1], BigInt::from(2000) + BigInt::from(3600) * &live * 3u32 / 4u32);
    assert_eq!(l.game.site_balance[0], BigInt::from(1000), "decommissioned data centers do not earn");
    let away = l.away.unwrap();
    assert_eq!(away.seconds, 3600.9);
    assert_eq!(away.earned, BigInt::from(3600) * &live * 3u32 / 4u32);
    let msg = l.game.log.last().unwrap();
    assert_eq!(msg.text, "Welcome back! Away 1h 0m, earned $57.24M (75% offline rate)");
    assert_eq!(l.game.cur, 0, "the view is kept");
}

#[test]
fn offline_bad_saved_at_is_ignored() {
    for bad in ["0", "-5", "\"100\"", "null", "true", "false", "[]", "{}", "1e999", "-1e999", "0.0"] {
        let l = offline(bad, 100.0 + 5000.0);
        assert_eq!(l.game.site_balance[1], BigInt::from(2000), "saved_at={bad}");
        assert!(l.away.is_none(), "saved_at={bad}");
    }
    let huge_int = format!("1{}", "0".repeat(400));
    assert!(offline(&huge_int, 1e9).away.is_none(), "an int too big for a float is 'no data'");
    assert!(offline("", 99999.0).away.is_none());
    let future = offline("10000", 100.0);
    assert_eq!(future.game.site_balance[1], BigInt::from(2000), "clock went backwards: no gain");
}

#[test]
fn offline_integer_saved_at_counts() {
    let l = offline("100", 160.0);
    assert_eq!(l.away.unwrap().earned, BigInt::from(60) * 21200u32 * 3u32 / 4u32);
}

#[test]
fn offline_nothing_under_one_second_or_without_income() {
    assert_eq!(offline("100", 100.99).game.site_balance[1], BigInt::from(2000));
    let idle = load_at(
        r#"{"sites": 1, "site_owned": [[0],[0]], "site_balance": ["1000","2000"], "saved_at": 100}"#, 1e9);
    assert_eq!(idle.game.site_balance[1], BigInt::from(2000));
    assert!(idle.away.is_none());
}

#[test]
fn offline_absurd_elapsed_times_stay_exact_and_do_not_panic() {
    let l = offline("1e-300", 1e300);
    assert_sane(&l.game);
    assert!(l.game.site_balance[1] > pow10(300));
    let edge = offline("1.7976931348623157e308", 1.0);
    assert_eq!(edge.game.site_balance[1], BigInt::from(2000));
    let both = offline("1e-300", f64::MAX);
    assert!(both.away.is_some());
    assert!(offline("100", f64::INFINITY).away.is_none(), "an infinite clock is no data");
}

#[test]
fn offline_only_for_the_live_site_even_when_viewing_another() {
    let l = offline("100", 200.0);
    assert_eq!(l.game.cur, 0);
    assert_eq!(l.game.site_balance[0], BigInt::from(1000));
    assert!(l.game.site_balance[1] > BigInt::from(2000));
}

// ------------------------------------------------------------- atomic write

fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("dc-core-save-{}-{name}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn save_game_is_atomic_and_creates_parent_directories() {
    let dir = scratch("atomic");
    let path = dir.join("deep").join("er").join("save.json");
    let l = load("{}");
    save_game(&path, &l.game, &l.online, &l.theme, 123.0).unwrap();
    assert!(path.exists());
    assert!(!path.with_extension("tmp").exists(), "no temp file is left behind");
    let back = load_path(&path, Half, 123.0);
    assert!(back.game.autopilot && back.away.is_none());
    // overwriting replaces the file
    let mut l2 = load("{}");
    l2.game.autopilot = false;
    save_game(&path, &l2.game, &l2.online, "nord", 124.0).unwrap();
    let again = load_path(&path, Half, 124.0);
    assert!(!again.game.autopilot);
    assert_eq!(again.theme, "nord");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn save_game_reports_failure_and_leaves_no_temp_file() {
    let dir = scratch("fail");
    let target = dir.join("save.json");
    std::fs::create_dir(&target).unwrap(); // renaming a file over a directory fails
    let l = load("{}");
    assert!(save_game(&target, &l.game, &l.online, &l.theme, 1.0).is_err());
    assert!(!target.with_extension("tmp").exists());
    assert!(target.is_dir());
    let _ = std::fs::remove_dir_all(&dir);
}
