//! Pure parts of the leaderboard client: name/token rules, the submit and board
//! logic, and the refresh timing. The network is an injected [`Api`].
//!
//! Port of the online helpers in `web/core.js` (lines ~396-525) and the checks in
//! `data_center_tui/game.py`. No regex crate: the three patterns are simple enough.

use crate::fmt::fmt;
use crate::save::{big_of, int_of, Online};
use crate::state::{Game, Kind, Rng};
use num_bigint::BigInt;
use num_traits::ToPrimitive;
use serde_json::{json, Value};

/// The server rejects any Fame above this.
pub fn max_fame_online() -> BigInt {
    BigInt::from(10).pow(12)
}
/// Seconds between score updates when something changed.
pub const SUBMIT_EVERY: f64 = 120.0;
/// Seconds between board fetches unless forced.
pub const BOARD_EVERY: f64 = 5.0;
/// Python only calls `maybe_submit` every this many ticks while in front.
pub const SUBMIT_TICK_EVERY: u64 = 5;
/// Python refreshes the open board every this many ticks while in front.
pub const BOARD_TICK_EVERY: u64 = 30;
/// A pane in the background repaints only every this many seconds (Python).
pub const BACKGROUND_REFRESH: u64 = 20;
/// Per-request network limits of the Python client, in seconds (read timeout, whole request).
pub const API_READ_TIMEOUT: u64 = 6;
pub const API_DEADLINE: u64 = 8;
/// Longest `error` text from the server that is shown.
pub const ERROR_SHOWN_CHARS: usize = 60;
/// Rows the board shows at most.
pub const BOARD_LIMIT: usize = 30;

/// `^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,19}$`
pub fn is_name(s: &str) -> bool {
    let b = s.as_bytes();
    (1..=20).contains(&b.len())
        && b[0].is_ascii_alphanumeric()
        && b[1..].iter().all(|&c| c.is_ascii_alphanumeric() || matches!(c, b' ' | b'_' | b'.' | b'-'))
}

/// `^[0-9a-f]{32,64}$`
pub fn is_token(s: &str) -> bool {
    (32..=64).contains(&s.len()) && s.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

/// `^[ -~]{0,24}$`: what you may call a data center (plain printable ASCII).
pub fn is_dc_name(s: &str) -> bool {
    s.len() <= 24 && s.bytes().all(|c| (b' '..=b'~').contains(&c))
}

/// Where token bytes come from.
pub trait RandomBytes {
    /// `n` random bytes (a source returning another length is rejected by [`make_token`]).
    fn random_bytes(&mut self, n: usize) -> Vec<u8>;
}

/// Operating-system randomness via `/dev/urandom` (Unix).
pub struct OsRandom;

impl RandomBytes for OsRandom {
    fn random_bytes(&mut self, n: usize) -> Vec<u8> {
        use std::io::Read;
        let mut buf = vec![0u8; n];
        match std::fs::File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut buf)) {
            Ok(()) => buf,
            Err(_) => Vec::new(), // make_token reports the wrong length
        }
    }
}

/// Why a token could not be made.
#[derive(Debug, PartialEq, Eq)]
pub enum TokenError {
    /// The source did not return exactly 16 bytes.
    BadSource,
}

/// 32 lowercase hex chars from 16 random bytes.
pub fn make_token(src: &mut dyn RandomBytes) -> Result<String, TokenError> {
    let bytes = src.random_bytes(16);
    if bytes.len() != 16 {
        return Err(TokenError::BadSource);
    }
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// JSON body for `POST /api/submit`. Fame is integer text, as in the web port.
pub fn submit_payload<R: Rng>(game: &Game<R>, online: &Online) -> Value {
    json!({
        "token": online.token, "name": online.name,
        "fame": game.fame.to_string(), "sites": game.sites,
    })
}

/// A response: HTTP status (0 = unreachable) and the JSON body (`{}` when unparsable).
pub type Response = (u16, Value);

/// The injected network. `Err` is treated like an unreachable server (status 0).
pub trait Api {
    /// One request; `body` is the JSON body of a POST.
    fn request(&mut self, method: &str, path: &str, body: Option<&Value>) -> Result<Response, String>;
}

fn call(api: &mut dyn Api, method: &str, path: &str, body: Option<&Value>) -> Option<Response> {
    api.request(method, path, body).ok()
}

/// Mutable client state for the leaderboard (what Python keeps on the app).
#[derive(Clone, Debug)]
pub struct ClientState {
    pub busy: bool,
    /// Snapshot of the last score the server accepted (or refused for good).
    pub last_sent: Option<String>,
    pub last_attempt: f64,
    pub board_busy: bool,
    pub board_at: f64,
    pub board: Option<Board>,
}

impl Default for ClientState {
    fn default() -> Self {
        ClientState {
            busy: false,
            last_sent: None,
            last_attempt: f64::NEG_INFINITY,
            board_busy: false,
            board_at: f64::NEG_INFINITY,
            board: None,
        }
    }
}

/// What the board last fetched.
#[derive(Clone, Debug, PartialEq)]
pub struct Board {
    pub players: Vec<Value>,
    pub total: Value,
    pub at: f64,
    pub me: Option<Value>,
    pub error: bool,
}

/// `fame|sites|name`: what must change before a score is sent again.
pub fn snapshot_of<R: Rng>(game: &Game<R>, online: &Online) -> String {
    format!("{}|{}|{}", game.fame, game.sites, online.name)
}

/// What the server's answer to a submit means.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SubmitOutcome {
    Ok,
    Taken,
    Rejected,
    Retry,
}

/// React to the server's answer to a submit: 200 ok; 409 name taken (leave the board);
/// 400 refused (mark sent, never resend); anything else (0 offline, 429, 5xx): retry later.
pub fn handle_submit<R: Rng>(
    game: &mut Game<R>,
    online: &mut Online,
    st: &mut ClientState,
    res: &Response,
    snapshot: &str,
) -> SubmitOutcome {
    let (status, body) = res;
    match status {
        200 => {
            st.last_sent = Some(snapshot.to_string());
            SubmitOutcome::Ok
        }
        409 => {
            online.joined = false;
            game.say(&format!("! the name '{}' is taken", online.name), Kind::Error);
            SubmitOutcome::Taken
        }
        400 => {
            st.last_sent = Some(snapshot.to_string());
            let why: String = match body.get("error").and_then(Value::as_str) {
                Some(s) => s.chars().take(ERROR_SHOWN_CHARS).collect(),
                None => "bad data".to_string(),
            };
            game.say(&format!("! the leaderboard rejected the score ({why})"), Kind::Error);
            SubmitOutcome::Rejected
        }
        _ => SubmitOutcome::Retry,
    }
}

/// Send the score if joined and something changed (or `force`). `now` is unix seconds.
/// `None` when nothing was sent.
pub fn maybe_submit<R: Rng>(
    game: &mut Game<R>,
    online: &mut Online,
    api: &mut dyn Api,
    st: &mut ClientState,
    now: f64,
    force: bool,
) -> Option<SubmitOutcome> {
    if !online.joined || st.busy || game.fame > max_fame_online() {
        return None;
    }
    let snapshot = snapshot_of(game, online);
    let unchanged = st.last_sent.as_deref() == Some(snapshot.as_str());
    if !force && (unchanged || now - st.last_attempt < SUBMIT_EVERY) {
        return None;
    }
    st.busy = true;
    st.last_attempt = now;
    let res = call(api, "POST", "/api/submit", Some(&submit_payload(game, online))).unwrap_or((0, json!({})));
    st.busy = false;
    Some(handle_submit(game, online, st, &res, &snapshot))
}

/// Board model after a fetch. `prev` is the previous board, if any.
pub fn board_from_results(prev: Option<&Board>, top: &Response, me: &Response, now: f64) -> Board {
    if top.0 == 200 {
        if let Some(players) = top.1.get("players").and_then(Value::as_array) {
            return Board {
                players: players.clone(),
                total: top.1.get("total").cloned().unwrap_or_else(|| json!(0)),
                at: now,
                me: if me.0 == 200 { Some(me.1.clone()) } else { None },
                error: false,
            };
        }
    }
    match prev {
        Some(p) => Board { error: true, ..p.clone() },
        None => Board { players: Vec::new(), total: json!(0), at: 0.0, me: None, error: true },
    }
}

/// Fetch the top 30 and (when joined) our own rank, then store `st.board`.
pub fn refresh_board<'a>(
    online: &Online,
    api: &mut dyn Api,
    st: &'a mut ClientState,
    now: f64,
    force: bool,
) -> Option<&'a Board> {
    if st.board_busy || (!force && now - st.board_at < BOARD_EVERY) {
        return st.board.as_ref();
    }
    st.board_at = now;
    st.board_busy = true;
    let mut me: Response = (0, json!({}));
    let top = call(api, "GET", "/api/leaderboard?limit=30", None);
    if top.is_some() && online.joined && !online.token.is_empty() {
        let body = json!({ "token": online.token });
        me = call(api, "POST", "/api/me", Some(&body)).unwrap_or((0, json!({})));
    }
    st.board_busy = false;
    let top = top.unwrap_or((0, json!({})));
    st.board = Some(board_from_results(st.board.as_ref(), &top, &me, now));
    st.board.as_ref()
}

/// One displayed leaderboard line.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BoardRow {
    pub rank: i64,
    pub name: String,
    /// Fame formatted like the rest of the game (`1.23M`).
    pub fame: String,
    /// 1-based data center count (`sites + 1`).
    pub sites: u64,
    pub mine: bool,
}

fn row_of(pl: &Value) -> Option<(i64, String, BigInt, u64)> {
    let obj = pl.as_object()?;
    let fame = big_of(obj.get("fame")?)?;
    let sites = int_of(obj.get("sites")?)?.to_u64()?;
    let rank = int_of(obj.get("rank")?)?.to_i64()?;
    let name = obj.get("name")?.as_str().filter(|n| is_name(n))?;
    Some((rank, name.to_string(), fame, sites))
}

/// Display rows of a board: skips malformed entries and names that fail the name rule
/// (a server must not be able to inject control characters). At most `limit` rows.
pub fn board_rows(board: Option<&Board>, online: &Online, limit: usize) -> Vec<BoardRow> {
    let Some(board) = board else { return Vec::new() };
    board
        .players
        .iter()
        .filter_map(row_of)
        .take(limit)
        .map(|(rank, name, fame, sites)| BoardRow {
            rank,
            mine: online.joined && name.eq_ignore_ascii_case(&online.name),
            name,
            fame: fmt(&fame),
            sites: sites + 1,
        })
        .collect()
}
