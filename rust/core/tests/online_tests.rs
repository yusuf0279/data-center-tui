//! Ports web/test/online.test.js with a fake api.

use dc_core::online::*;
use dc_core::save::{load_text, Online};
use dc_core::state::{Game, Rng};
use num_bigint::BigInt;
use serde_json::{json, Value};
use std::collections::VecDeque;

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

const TOKEN: &str = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd";

fn joined() -> (Game<Half>, Online) {
    let text = format!(
        r#"{{"sites": 2, "fame": "123456", "autopilot": false,
        "online": {{"asked": true, "joined": true, "name": "Ada", "token": "{TOKEN}"}}}}"#
    );
    let l = load_text(&text, Half, 1.0);
    (l.game, l.online)
}

/// Answers from a queue (the last answer repeats) and records the calls.
struct FakeApi {
    answers: VecDeque<Result<Response, String>>,
    calls: Vec<(String, String, Option<Value>)>,
}

fn fake(answers: Vec<Result<Response, String>>) -> FakeApi {
    FakeApi { answers: answers.into(), calls: Vec::new() }
}

fn ok(status: u16, body: Value) -> Result<Response, String> {
    Ok((status, body))
}

impl Api for FakeApi {
    fn request(&mut self, method: &str, path: &str, body: Option<&Value>) -> Result<Response, String> {
        self.calls.push((method.into(), path.into(), body.cloned()));
        if self.answers.len() > 1 { self.answers.pop_front().unwrap() } else { self.answers[0].clone() }
    }
}

fn last_log(g: &Game<Half>) -> (&str, &str) {
    let e = g.log.last().unwrap();
    (e.text.as_str(), e.kind.as_str())
}

#[test]
fn name_and_token_rules() {
    for good in ["A", "ada", "Ada Lovelace", "a_b.c-d", &"x".repeat(20), "0day"] {
        assert!(is_name(good), "{good}");
    }
    for bad in ["", " a", "_a", &"x".repeat(21), "a\n", "caf\u{e9}", "a<b>", "-a"] {
        assert!(!is_name(bad), "{bad:?}");
    }
    assert!(is_token(&"a".repeat(32)));
    assert!(is_token(&"0123456789abcdef".repeat(4)));
    for bad in [&"a".repeat(31), &"a".repeat(65), &"A".repeat(32), &"g".repeat(32), "", &format!("{}\n", "a".repeat(32))] {
        assert!(!is_token(bad), "{bad:?}");
    }
    assert!(is_dc_name(""));
    assert!(is_dc_name(&"x".repeat(24)));
    assert!(!is_dc_name(&"x".repeat(25)));
    assert!(!is_dc_name("a\tb") && !is_dc_name("caf\u{e9}") && !is_dc_name("a\n"));
}

struct Fixed(Vec<u8>);

impl RandomBytes for Fixed {
    fn random_bytes(&mut self, n: usize) -> Vec<u8> {
        assert_eq!(n, 16, "asks for 16 bytes");
        self.0.clone()
    }
}

#[test]
fn make_token_uses_an_injectable_source() {
    let bytes = vec![0, 1, 2, 15, 16, 255, 128, 9, 10, 11, 12, 13, 14, 171, 205, 239];
    let t = make_token(&mut Fixed(bytes)).unwrap();
    assert_eq!(t, "0001020f10ff80090a0b0c0d0eabcdef");
    assert!(is_token(&t));
    assert_eq!(make_token(&mut Fixed(vec![0; 8])), Err(TokenError::BadSource));
    assert_eq!(make_token(&mut Fixed(Vec::new())), Err(TokenError::BadSource));
    let real = make_token(&mut OsRandom).unwrap();
    assert!(is_token(&real));
    assert_ne!(real, make_token(&mut OsRandom).unwrap());
}

#[test]
fn submit_payload_fame_is_integer_text() {
    let (mut g, on) = joined();
    g.fame = BigInt::from(10).pow(12) + 123u32;
    let body = submit_payload(&g, &on);
    assert_eq!(body, json!({"token": TOKEN, "name": "Ada", "fame": "1000000000123", "sites": 2}));
    assert!(body["fame"].is_string());
    g.fame = BigInt::from(2).pow(80);
    assert_eq!(submit_payload(&g, &on)["fame"], "1208925819614629174706176");
    assert_eq!(serde_json::to_string(&submit_payload(&g, &on)).unwrap().matches("1208925819614629174706176").count(), 1);
}

#[test]
fn handle_submit_status_logic() {
    let (mut g, mut on) = joined();
    let mut st = ClientState::default();
    assert_eq!(handle_submit(&mut g, &mut on, &mut st, &(200, json!({})), "snap"), SubmitOutcome::Ok);
    assert_eq!(st.last_sent.as_deref(), Some("snap"));
    assert!(on.joined);

    st = ClientState::default();
    assert_eq!(handle_submit(&mut g, &mut on, &mut st, &(409, json!({"error": "name taken"})), "snap"), SubmitOutcome::Taken);
    assert!(!on.joined);
    assert_eq!(st.last_sent, None);
    assert_eq!(last_log(&g), ("! the name 'Ada' is taken", "error"));

    st = ClientState::default();
    let r = handle_submit(&mut g, &mut on, &mut st, &(400, json!({"error": "implausible fame"})), "snap2");
    assert_eq!(r, SubmitOutcome::Rejected);
    assert_eq!(st.last_sent.as_deref(), Some("snap2"), "a refused score is not resent");
    assert_eq!(last_log(&g), ("! the leaderboard rejected the score (implausible fame)", "error"));
    for body in [json!({}), json!({"error": 7}), json!({"error": null})] {
        handle_submit(&mut g, &mut on, &mut st, &(400, body), "s");
        assert_eq!(last_log(&g).0, "! the leaderboard rejected the score (bad data)");
    }
    let long = "e".repeat(100);
    handle_submit(&mut g, &mut on, &mut st, &(400, json!({"error": long})), "s");
    assert_eq!(last_log(&g).0, format!("! the leaderboard rejected the score ({})", "e".repeat(60)));

    for status in [0u16, 429, 500, 503, 404, 201] {
        let (mut g2, mut on2) = joined();
        let mut st2 = ClientState::default();
        assert_eq!(handle_submit(&mut g2, &mut on2, &mut st2, &(status, json!({})), "x"), SubmitOutcome::Retry, "status {status}");
        assert_eq!(st2.last_sent, None);
        assert!(on2.joined);
    }
}

#[test]
fn maybe_submit_sends_once_then_only_on_change_throttled_to_120s() {
    let (mut g, mut on) = joined();
    let mut st = ClientState::default();
    let mut api = fake(vec![ok(200, json!({}))]);
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1000.0, false), Some(SubmitOutcome::Ok));
    assert_eq!(api.calls, [("POST".to_string(), "/api/submit".to_string(),
        Some(json!({"token": TOKEN, "name": "Ada", "fame": "123456", "sites": 2})))]);
    assert!(!st.busy);
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 5000.0, false), None, "unchanged");
    g.fame += 1u32;
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1100.0, false), None, "inside 120 s");
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1120.0, false), Some(SubmitOutcome::Ok));
    assert_eq!(api.calls.len(), 2);
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1121.0, true), Some(SubmitOutcome::Ok), "force");
    assert_eq!(api.calls.len(), 3);
}

#[test]
fn maybe_submit_not_joined_too_much_fame_or_busy_sends_nothing() {
    let mut api = fake(vec![ok(200, json!({}))]);
    let mut st = ClientState::default();
    let (mut out, mut on_out) = joined();
    on_out.joined = false;
    assert_eq!(maybe_submit(&mut out, &mut on_out, &mut api, &mut st, 1000.0, true), None);
    let (mut big, mut on_big) = joined();
    big.fame = max_fame_online() + 1u32;
    assert_eq!(maybe_submit(&mut big, &mut on_big, &mut api, &mut st, 1000.0, true), None);
    big.fame = max_fame_online();
    assert_eq!(maybe_submit(&mut big, &mut on_big, &mut api, &mut st, 1000.0, true), Some(SubmitOutcome::Ok));
    let (mut busy, mut on_busy) = joined();
    st.busy = true;
    assert_eq!(maybe_submit(&mut busy, &mut on_busy, &mut api, &mut st, 9999.0, true), None);
    assert_eq!(api.calls.len(), 1);
}

#[test]
fn maybe_submit_failures_retry_later_409_leaves_the_board() {
    let (mut g, mut on) = joined();
    let mut st = ClientState::default();
    let mut api = fake(vec![ok(0, json!({})), ok(500, json!({})), ok(200, json!({}))]);
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1000.0, false), Some(SubmitOutcome::Retry));
    assert_eq!(st.last_sent, None);
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1001.0, false), None, "throttled after a failure");
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1200.0, false), Some(SubmitOutcome::Retry));
    assert_eq!(maybe_submit(&mut g, &mut on, &mut api, &mut st, 1400.0, false), Some(SubmitOutcome::Ok));
    let (mut g2, mut on2) = joined();
    let mut boom = fake(vec![Err("boom".into())]);
    assert_eq!(maybe_submit(&mut g2, &mut on2, &mut boom, &mut ClientState::default(), 5.0, false), Some(SubmitOutcome::Retry));
    let (mut g3, mut on3) = joined();
    let mut taken = fake(vec![ok(409, json!({}))]);
    assert_eq!(maybe_submit(&mut g3, &mut on3, &mut taken, &mut ClientState::default(), 5.0, false), Some(SubmitOutcome::Taken));
    assert!(!on3.joined);
}

#[test]
fn board_from_results_ok_stale_and_first_failure() {
    let players = json!([{"rank": 1, "name": "Ada", "fame": "5", "sites": 0}]);
    let me = json!({"registered": true, "rank": 1, "total": 1, "name": "Ada", "fame": "5", "sites": 0});
    let good = board_from_results(None, &(200, json!({"players": players, "total": 9})), &(200, me.clone()), 50.0);
    assert_eq!(good, Board { players: players.as_array().unwrap().clone(), total: json!(9), at: 50.0, me: Some(me), error: false });
    let top = (200, json!({"players": players}));
    assert_eq!(board_from_results(None, &top, &(500, json!({})), 1.0).me, None);
    assert_eq!(board_from_results(None, &top, &(0, json!({})), 1.0).total, json!(0));
    let stale = board_from_results(Some(&good), &(0, json!({})), &(0, json!({})), 80.0);
    assert!(stale.error);
    assert_eq!(stale.at, 50.0, "keeps the old data and time");
    assert_eq!(stale.players, good.players);
    assert!(!good.error, "does not mutate the previous board");
    let none = board_from_results(None, &(0, json!({})), &(0, json!({})), 80.0);
    assert_eq!(none, Board { players: vec![], total: json!(0), at: 0.0, me: None, error: true });
    assert!(board_from_results(None, &(200, json!({"players": "x"})), &(0, json!({})), 1.0).error);
}

/// Fake server for the board: leaderboard and /api/me answer fixed bodies.
struct BoardApi {
    calls: Vec<(String, String, Option<Value>)>,
}

impl Api for BoardApi {
    fn request(&mut self, method: &str, path: &str, body: Option<&Value>) -> Result<Response, String> {
        self.calls.push((method.into(), path.into(), body.cloned()));
        Ok(if path.starts_with("/api/leaderboard") {
            (200, json!({"players": [{"rank": 1, "name": "Ada", "fame": "5", "sites": 0}], "total": 1}))
        } else {
            (200, json!({"registered": true, "rank": 1, "total": 1}))
        })
    }
}

#[test]
fn refresh_board_fetches_top_30_then_our_rank_throttled_to_5s() {
    let (_g, mut on) = joined();
    let mut st = ClientState::default();
    let mut api = BoardApi { calls: vec![] };
    let b = refresh_board(&on, &mut api, &mut st, 100.0, false).unwrap().clone();
    assert_eq!(api.calls, [
        ("GET".to_string(), "/api/leaderboard?limit=30".to_string(), None),
        ("POST".to_string(), "/api/me".to_string(), Some(json!({"token": TOKEN}))),
    ]);
    assert_eq!(b.me.as_ref().unwrap()["rank"], 1);
    assert_eq!(st.board.as_ref(), Some(&b));
    assert_eq!(refresh_board(&on, &mut api, &mut st, 102.0, false), Some(&b));
    assert_eq!(api.calls.len(), 2, "inside 5 s: no request");
    refresh_board(&on, &mut api, &mut st, 102.0, true);
    assert_eq!(api.calls.len(), 4);
    refresh_board(&on, &mut api, &mut st, 107.0, false);
    assert_eq!(api.calls.len(), 6, "5 s later it fetches again");
    on.joined = false;
    let before = api.calls.len();
    refresh_board(&on, &mut api, &mut st, 200.0, false);
    assert_eq!(api.calls.len(), before + 1, "not joined: no /api/me");
    assert_eq!(st.board.as_ref().unwrap().me, None);
    st.board_busy = true;
    refresh_board(&on, &mut api, &mut st, 999.0, true);
    assert_eq!(api.calls.len(), before + 1, "one fetch at a time");
}

#[test]
fn refresh_board_unreachable_server_gives_an_error_board() {
    let (_g, on) = joined();
    let mut st = ClientState::default();
    let b = refresh_board(&on, &mut fake(vec![ok(0, json!({}))]), &mut st, 10.0, false).unwrap().clone();
    assert_eq!(b, Board { players: vec![], total: json!(0), at: 0.0, me: None, error: true });
    assert!(!st.board_busy);
    let mut st2 = ClientState::default();
    let b2 = refresh_board(&on, &mut fake(vec![Err("x".into())]), &mut st2, 10.0, false).unwrap();
    assert!(b2.error);
}

#[test]
fn refresh_board_failed_me_keeps_the_top() {
    let (_g, on) = joined();
    let mut st = ClientState::default();
    let top = ok(200, json!({"players": [], "total": 0}));
    let b = refresh_board(&on, &mut fake(vec![top, Err("x".into())]), &mut st, 10.0, false).unwrap();
    assert!(!b.error && b.me.is_none());
}

#[test]
fn board_rows_format_fame_and_skip_bad_rows_and_names() {
    let (_g, mut on) = joined();
    let board = Board {
        players: json!([
            {"rank": 1, "name": "Ada", "fame": "1234567", "sites": 3},
            {"rank": 2, "name": "bob", "fame": "12", "sites": 0},
            {"rank": 3, "name": "\u{1b}[31mred", "fame": "5", "sites": 0},
            {"rank": 4, "name": "x".repeat(21), "fame": "5", "sites": 0},
            {"rank": 5, "name": "ok", "fame": "NaN", "sites": 0},
            {"rank": "6", "name": "ok", "fame": "5", "sites": 0},
            {"rank": 7, "name": "ok", "fame": "5", "sites": -1},
            {"rank": 8, "name": "ok", "fame": "5", "sites": 1.5},
            null, "str", [],
            {"rank": 9, "name": "ADA", "fame": "5", "sites": 1},
            {"rank": 10, "name": "n", "fame": 7, "sites": 0},
            {"rank": 11, "name": "n", "fame": true, "sites": 0},
            {"name": "n", "fame": "5", "sites": 0}
        ]).as_array().unwrap().clone(),
        total: json!(0),
        at: 1.0,
        me: None,
        error: false,
    };
    let rows = board_rows(Some(&board), &on, 30);
    assert_eq!(rows.iter().map(|r| r.rank).collect::<Vec<_>>(), [1, 2, 9, 10]);
    assert_eq!(rows[0], BoardRow { rank: 1, name: "Ada".into(), fame: "1.23M".into(), sites: 4, mine: true });
    assert!(!rows[1].mine);
    assert!(rows[2].mine, "names compare case-insensitively like Python");
    assert_eq!(rows[3].fame, "7");
    on.joined = false;
    assert!(!board_rows(Some(&board), &on, 30)[0].mine);
    assert_eq!(board_rows(Some(&board), &on, 1).len(), 1);
    assert_eq!(board_rows(Some(&board), &on, 3).len(), 3, "the limit counts shown rows, not skipped ones");
    assert!(board_rows(None, &on, 30).is_empty());
    let odd = Board { players: vec![], ..board };
    assert!(board_rows(Some(&odd), &on, 30).is_empty());
}

#[test]
fn timing_constants_match_the_clients() {
    assert_eq!((SUBMIT_EVERY, BOARD_EVERY), (120.0, 5.0));
    assert_eq!((SUBMIT_TICK_EVERY, BOARD_TICK_EVERY, BACKGROUND_REFRESH), (5, 30, 20));
    assert_eq!((API_READ_TIMEOUT, API_DEADLINE, BOARD_LIMIT), (6, 8, 30));
    assert_eq!(max_fame_online(), BigInt::from(10).pow(12));
}
