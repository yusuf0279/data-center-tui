//! Save and load, plus offline earnings.
//!
//! Reads both on-disk formats: the Python one (bare big-int JSON numbers) and the web one
//! (decimal strings). Writes the Python one. Validation follows Python's
//! `type(v) is int` rules: booleans and floats such as `1.0` are not integers.
//! The path is always an argument; nothing here looks at the environment.
//!
//! Python's 4300-digit integer limit is reproduced on the raw text (see
//! `has_huge_int_token`): a `-?digits` token over 4300 digits anywhere, sign not counted,
//! duplicates and unread values included, makes the whole file garbage (a fresh game).
//!
//! Known divergences from Python that are deliberately not reproduced:
//! - `NaN`, `Infinity` and `-Infinity` literals: Python's `json.loads` accepts them (as
//!   floats), serde_json rejects the document, so Rust treats such a file as garbage.
//! - Lone surrogate escapes (`"\ud800"`): Python keeps them in the string, Rust's JSON
//!   parser rejects the document.
//! - Nesting deeper than 128 levels: serde_json stops at 128; Python's limit is the
//!   interpreter recursion depth and differs.
//! - Web-format decimal strings (1 to 601 digits) are accepted for big values only here;
//!   Python's loader treats them as invalid and falls back.
//! - Theme: Rust accepts 1 to 64 characters, otherwise the default; Python keeps any
//!   string (the UI validates the name before use anyway).
//! - `board_rows` (leaderboard) is stricter than Python: Rust filters the rows and then
//!   applies the row limit, and does no `int()` coercion of values.

use crate::data::*;
use crate::econ::{restore_site, start_balance};
use crate::fmt::{fmt, fmt_duration};
use crate::online::{is_dc_name, is_name, is_token};
use crate::state::{Game, Kind, Rng};
use num_bigint::BigInt;
use num_traits::{FromPrimitive, Signed, ToPrimitive, Zero};
use serde_json::{Map, Value};
use std::io;
use std::path::Path;

/// Theme used when the save has none.
pub const DEFAULT_THEME: &str = "gruvbox";
/// Longest accepted theme name.
pub const MAX_THEME_LEN: usize = 64;
/// Python 3.11+ refuses to parse integers with more digits than this.
const PY_MAX_INT_DIGITS: usize = 4300;

/// The leaderboard identity stored in a save.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Online {
    pub asked: bool,
    pub joined: bool,
    pub name: String,
    pub token: String,
}

/// Offline credit that was applied on load.
#[derive(Clone, Debug, PartialEq)]
pub struct Away {
    /// Seconds since the last save.
    pub seconds: f64,
    pub earned: BigInt,
}

/// Everything a save holds, plus what loading it did.
pub struct Loaded<R: Rng> {
    pub game: Game<R>,
    pub online: Online,
    pub theme: String,
    pub away: Option<Away>,
}

// ---------------------------------------------------------------- value readers

/// An integer JSON number (`-?digits`, no fraction or exponent) of any size.
pub fn int_of(v: &Value) -> Option<BigInt> {
    let Value::Number(n) = v else { return None };
    let text = n.to_string();
    let digits = text.strip_prefix('-').unwrap_or(&text);
    if digits.is_empty() || !digits.bytes().all(|c| c.is_ascii_digit()) {
        return None;
    }
    text.parse().ok()
}

/// A non-negative integer below [`max_big`]: a bare JSON integer (Python) or a string of
/// 1 to 601 decimal digits (web). Booleans, floats, negatives and the rest are `None`.
pub fn big_of(v: &Value) -> Option<BigInt> {
    let b = match v {
        Value::Number(_) => int_of(v)?,
        Value::String(s) if (1..=601).contains(&s.len()) && s.bytes().all(|c| c.is_ascii_digit()) => s.parse().ok()?,
        _ => return None,
    };
    (!b.is_negative() && b < max_big()).then_some(b)
}

fn small_of(v: &Value) -> Option<i64> {
    int_of(v)?.to_i64()
}

/// A list of `n` ints in `[lo, hi]`; anything invalid falls back to `default`.
pub fn clean_levels(raw: Option<&Value>, n: usize, lo: i64, hi: i64, default: i64) -> Vec<i64> {
    let mut out = vec![default; n];
    if let Some(Value::Array(items)) = raw {
        for (slot, v) in out.iter_mut().zip(items) {
            if let Some(x) = small_of(v).filter(|x| (lo..=hi).contains(x)) {
                *slot = x;
            }
        }
    }
    out
}

fn list(v: Option<&Value>) -> &[Value] {
    match v {
        Some(Value::Array(a)) => a,
        _ => &[],
    }
}

fn is_list(v: Option<&Value>) -> bool {
    matches!(v, Some(Value::Array(_)))
}

/// Does the raw JSON text hold an integer token (`-?digits`, no fraction or exponent,
/// outside strings) of more than 4300 digits anywhere? Python's `json.loads` refuses the
/// whole document then, even when the token is an earlier duplicate of a key or sits in a
/// value nothing reads. The sign does not count as a digit. Garbage text is fine to scan:
/// the JSON parser rejects it anyway.
fn has_huge_int_token(text: &str) -> bool {
    let (mut in_str, mut esc, mut start) = (false, false, None::<usize>);
    let bytes = text.as_bytes();
    let too_long = |from: usize, to: usize| {
        let tok = &bytes[from..to];
        let digits = tok.strip_prefix(b"-").unwrap_or(tok);
        digits.len() > PY_MAX_INT_DIGITS && digits.iter().all(u8::is_ascii_digit)
    };
    for (i, &c) in bytes.iter().enumerate() {
        if in_str {
            (esc, in_str) = (!esc && c == b'\\', esc || c != b'"');
            continue;
        }
        if c.is_ascii_digit() || matches!(c, b'-' | b'+' | b'.' | b'e' | b'E') {
            start.get_or_insert(i);
            continue;
        }
        if let Some(from) = start.take() {
            if too_long(from, i) {
                return true;
            }
        }
        in_str = c == b'"';
    }
    start.is_some_and(|from| too_long(from, bytes.len()))
}

/// Parse save text into its top-level object; anything else (including garbage) is `None`.
pub fn parse_save(text: &str) -> Option<Map<String, Value>> {
    if has_huge_int_token(text) {
        return None;
    }
    match serde_json::from_str::<Value>(text) {
        Ok(Value::Object(m)) => Some(m),
        _ => None,
    }
}

// ----------------------------------------------------------------------- loading

fn to_u32(v: Vec<i64>) -> Vec<u32> {
    v.into_iter().map(|x| x as u32).collect()
}

fn to_i32(v: Vec<i64>) -> Vec<i32> {
    v.into_iter().map(|x| x as i32).collect()
}

fn get_big(data: &Map<String, Value>, key: &str) -> Option<BigInt> {
    data.get(key).and_then(big_of)
}

/// Racks and chips per data center. Older saves kept only a closed data center's final
/// income; `old_staff` gives the crew bonus that income included.
fn load_hardware(data: &Map<String, Value>, sites: usize, old_staff: &[i32]) -> (Vec<Vec<u32>>, Vec<Vec<u32>>) {
    let n = TIERS.len();
    let (mut owned, mut chips) = (Vec::new(), Vec::new());
    let so = data.get("site_owned");
    if is_list(so) {
        let (so, sc) = (list(so), list(data.get("site_chips")));
        for k in 0..=sites {
            owned.push(to_u32(clean_levels(so.get(k), n, 0, MAX_OWNED as i64, 0)));
            chips.push(to_u32(clean_levels(sc.get(k), n, 0, MAX_CHIP as i64, 0)));
        }
        return (owned, chips);
    }
    let mut legacy = vec![BigInt::zero(); sites];
    for (slot, v) in legacy.iter_mut().zip(list(data.get("legacy"))) {
        if let Some(b) = big_of(v) {
            *slot = b;
        }
    }
    let bonus = STAFF_BONUS as u64 * old_staff.iter().filter(|&&l| l >= 0).map(|&l| (l + 1) as u64).sum::<u64>();
    for (k, income) in legacy.iter().enumerate() {
        let (o, c) = restore_site(k, income, bonus);
        owned.push(o);
        chips.push(c);
    }
    owned.push(to_u32(clean_levels(data.get("owned"), n, 0, MAX_OWNED as i64, 0)));
    chips.push(to_u32(clean_levels(data.get("chips"), n, 0, MAX_CHIP as i64, 0)));
    (owned, chips)
}

/// Money and crew per data center, and the Fame default of the migration branch.
fn load_money_and_crew(data: &Map<String, Value>, sites: usize) -> (Vec<BigInt>, Vec<Vec<i32>>, BigInt) {
    let m = STAFF.len();
    let clean = |v: Option<&Value>| to_i32(clean_levels(v, m, -1, MAX_STAFF as i64, -1));
    let sb = data.get("site_balance");
    if is_list(sb) {
        let (sb, ss) = (list(sb), list(data.get("site_staff")));
        let balances = (0..=sites).map(|k| sb.get(k).and_then(big_of).unwrap_or_else(|| start_balance(k))).collect();
        let staff = (0..=sites).map(|k| clean(ss.get(k))).collect();
        return (balances, staff, BigInt::zero());
    }
    // Before data centers reset there was one shared balance and crew: it is the newest one's.
    let old_balance = get_big(data, "balance").unwrap_or_else(|| BigInt::from(START_BALANCE));
    let mut balances = vec![BigInt::zero(); sites];
    balances.push(old_balance);
    let mut staff = vec![vec![-1; m]; sites];
    staff.push(clean(data.get("staff")));
    (balances, staff, BigInt::from(sites)) // each data center already opened counts as one Fame
}

fn load_online(data: &Map<String, Value>) -> Online {
    let empty = Map::new();
    let on = data.get("online").and_then(Value::as_object).unwrap_or(&empty);
    let name = on.get("name").and_then(Value::as_str).filter(|s| is_name(s));
    let token = on.get("token").and_then(Value::as_str).filter(|s| is_token(s));
    let asked = on.get("asked") == Some(&Value::Bool(true));
    match (name, token) {
        (Some(name), Some(token)) => Online {
            asked,
            joined: on.get("joined") == Some(&Value::Bool(true)),
            name: name.to_string(),
            token: token.to_string(),
        },
        _ => Online { asked, ..Online::default() },
    }
}

fn load_theme(data: &Map<String, Value>) -> String {
    match data.get("theme").and_then(Value::as_str) {
        Some(t) if !t.is_empty() && t.chars().count() <= MAX_THEME_LEN => t.to_string(),
        _ => DEFAULT_THEME.to_string(),
    }
}

/// Seconds since a valid `saved_at`, or `None` when it is missing, not a number, not
/// finite or not positive (booleans and strings never count).
fn elapsed_since_save(data: &Map<String, Value>, now: f64) -> Option<f64> {
    let Some(Value::Number(n)) = data.get("saved_at") else { return None };
    let at: f64 = n.to_string().parse().ok()?; // too big for a float: parses as infinity
    (at.is_finite() && at > 0.0).then(|| (now - at).max(0.0))
}

/// Build the game from a parsed save object (never fails: bad fields fall back).
pub fn load_object<R: Rng>(data: &Map<String, Value>, rng: R, now: f64) -> Loaded<R> {
    let mut g = Game::new(rng);
    let sites = data.get("sites").and_then(small_of).filter(|s| (0..=MAX_SITES as i64).contains(s));
    g.sites = sites.unwrap_or(0) as usize;
    let old_staff = to_i32(clean_levels(data.get("staff"), STAFF.len(), -1, MAX_STAFF as i64, -1));
    (g.site_owned, g.site_chips) = load_hardware(data, g.sites, &old_staff);
    g.cur = data.get("cur").and_then(small_of).filter(|c| (0..=g.sites as i64).contains(c)).map_or(g.sites, |c| c as usize);
    let (balances, staff, default_fame) = load_money_and_crew(data, g.sites);
    (g.site_balance, g.site_staff) = (balances, staff);
    g.fame = get_big(data, "fame").unwrap_or(default_fame);
    let raw_names = list(data.get("site_names"));
    g.site_names = (0..=g.sites)
        .map(|k| match raw_names.get(k).and_then(Value::as_str) {
            Some(s) if is_dc_name(s) => s.to_string(),
            _ => String::new(),
        })
        .collect();
    // On for a brand-new game, off for an existing save so nothing spends your money unasked.
    g.autopilot = match data.get("autopilot") {
        Some(Value::Bool(b)) => *b,
        _ => data.is_empty(),
    };
    let away = elapsed_since_save(data, now).and_then(|secs| apply_offline(&mut g, secs));
    Loaded { game: g, online: load_online(data), theme: load_theme(data), away }
}

/// Build the game from save text; garbage gives a fresh game.
pub fn load_text<R: Rng>(text: &str, rng: R, now: f64) -> Loaded<R> {
    load_object(&parse_save(text).unwrap_or_default(), rng, now)
}

/// Build the game from the file at `path`; a missing or unreadable file gives a fresh game.
pub fn load_path<R: Rng>(path: &Path, rng: R, now: f64) -> Loaded<R> {
    let text = std::fs::read_to_string(path).unwrap_or_default();
    load_text(&text, rng, now)
}

// --------------------------------------------------------------- offline earnings

/// Credit 75% of the live data center's income for `elapsed` seconds away (whole seconds),
/// and log the welcome-back line. Returns what was credited, if anything.
pub fn apply_offline<R: Rng>(g: &mut Game<R>, elapsed: f64) -> Option<Away> {
    let whole = elapsed.floor();
    if whole.is_nan() || whole <= 0.0 {
        return None;
    }
    let secs = BigInt::from_f64(whole)?;
    let earned = secs * g.site_income(g.sites) * OFFLINE_NUM / OFFLINE_DEN;
    if !earned.is_positive() {
        return None;
    }
    g.site_balance[g.sites] += &earned;
    let msg = format!(
        "Welcome back! Away {}, earned ${} ({}% offline rate)",
        fmt_duration(elapsed),
        fmt(&earned),
        OFFLINE_NUM * 100 / OFFLINE_DEN
    );
    g.say(&msg, Kind::Warning);
    Some(Away { seconds: elapsed, earned })
}

// ------------------------------------------------------------------------ saving

fn json_str(s: &str) -> String {
    let mut out = String::from("\"");
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (' '..='~').contains(&c) => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for unit in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

fn json_list<T: ToString>(items: &[T]) -> String {
    let parts: Vec<String> = items.iter().map(ToString::to_string).collect();
    format!("[{}]", parts.join(", "))
}

fn json_grid<T: ToString>(rows: &[Vec<T>]) -> String {
    let parts: Vec<String> = rows.iter().map(|r| json_list(r)).collect();
    format!("[{}]", parts.join(", "))
}

/// The save text in the Python format: bare integers, same keys and order as `json.dumps`.
pub fn to_save_string<R: Rng>(g: &Game<R>, online: &Online, theme: &str, saved_at: f64) -> String {
    let names: Vec<String> = g.site_names.iter().map(|s| json_str(s)).collect();
    let at = if saved_at.is_finite() { format!("{saved_at:?}") } else { "0.0".to_string() };
    format!(
        "{{\"site_balance\": {}, \"site_owned\": {}, \"site_chips\": {}, \"site_staff\": {}, \
         \"fame\": {}, \"sites\": {}, \"cur\": {}, \"autopilot\": {}, \"site_names\": {}, \
         \"online\": {{\"asked\": {}, \"joined\": {}, \"name\": {}, \"token\": {}}}, \
         \"theme\": {}, \"saved_at\": {}}}",
        json_list(&g.site_balance),
        json_grid(&g.site_owned),
        json_grid(&g.site_chips),
        json_grid(&g.site_staff),
        g.fame,
        g.sites,
        g.cur,
        g.autopilot,
        json_list(&names),
        online.asked,
        online.joined,
        json_str(&online.name),
        json_str(&online.token),
        json_str(theme),
        at
    )
}

/// Write `text` to `path` atomically: parent directories are created, the text goes to
/// a sibling `.tmp` file, which is then renamed over `path`.
pub fn write_atomic(path: &Path, text: &str) -> io::Result<()> {
    if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, path).inspect_err(|_| {
        let _ = std::fs::remove_file(&tmp);
    })
}

/// Save the game to `path` (see [`write_atomic`]). The caller decides what to do about
/// an error; Python ignores it so a failed save never crashes the game.
pub fn save_game<R: Rng>(path: &Path, g: &Game<R>, online: &Online, theme: &str, saved_at: f64) -> io::Result<()> {
    write_atomic(path, &to_save_string(g, online, theme, saved_at))
}
