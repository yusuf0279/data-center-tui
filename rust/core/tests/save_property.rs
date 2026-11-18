//! Property test: save -> load round-trips arbitrary valid states, in both encodings.

use dc_core::data::*;
use dc_core::save::*;
use dc_core::state::{Game, Rng};
use num_bigint::BigInt;
use proptest::prelude::*;

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

#[derive(Clone, Debug)]
struct Site {
    balance: BigInt,
    owned: Vec<u32>,
    chips: Vec<u32>,
    staff: Vec<i32>,
    name: String,
}

#[derive(Clone, Debug)]
struct State {
    sites: Vec<Site>,
    cur: usize,
    fame: BigInt,
    autopilot: bool,
    online: Online,
    theme: String,
}

/// Non-negative big integers below 10^600, from a few random 64-bit limbs up to ~590 digits.
fn big_value() -> impl Strategy<Value = BigInt> {
    prop_oneof![
        Just(BigInt::from(0)),
        any::<u64>().prop_map(BigInt::from),
        prop::collection::vec(any::<u32>(), 1..61).prop_map(|limbs| {
            let v = limbs.iter().fold(BigInt::from(0), |acc, &l| (acc << 32u32) + l);
            v % dc_core::data::max_big()
        }),
        Just(dc_core::data::max_big() - 1u32),
    ]
}

fn site() -> impl Strategy<Value = Site> {
    (
        big_value(),
        prop::collection::vec(0..=MAX_OWNED, TIERS.len()),
        prop::collection::vec(0..=MAX_CHIP, TIERS.len()),
        prop::collection::vec(-1..=MAX_STAFF, STAFF.len()),
        "[ -~]{0,24}",
    )
        .prop_map(|(balance, owned, chips, staff, name)| Site { balance, owned, chips, staff, name })
}

fn online() -> impl Strategy<Value = Online> {
    prop_oneof![
        any::<bool>().prop_map(|asked| Online { asked, ..Online::default() }),
        (any::<bool>(), any::<bool>(), "[A-Za-z0-9][A-Za-z0-9 _.-]{0,19}", "[0-9a-f]{32,64}")
            .prop_map(|(asked, joined, name, token)| Online { asked, joined, name, token }),
    ]
}

fn state() -> impl Strategy<Value = State> {
    (prop::collection::vec(site(), 1..6), any::<prop::sample::Index>(), big_value(), any::<bool>(), online(), "[a-z][a-z-]{0,20}")
        .prop_map(|(sites, cur, fame, autopilot, online, theme)| {
            let cur = cur.index(sites.len());
            State { sites, cur, fame, autopilot, online, theme }
        })
}

fn build(s: &State) -> Game<Half> {
    let mut g = Game::new(Half);
    g.sites = s.sites.len() - 1;
    g.cur = s.cur;
    g.site_balance = s.sites.iter().map(|x| x.balance.clone()).collect();
    g.site_owned = s.sites.iter().map(|x| x.owned.clone()).collect();
    g.site_chips = s.sites.iter().map(|x| x.chips.clone()).collect();
    g.site_staff = s.sites.iter().map(|x| x.staff.clone()).collect();
    g.site_names = s.sites.iter().map(|x| x.name.clone()).collect();
    g.fame = s.fame.clone();
    g.autopilot = s.autopilot;
    g
}

fn assert_same(g: &Game<Half>, s: &State, l: &Loaded<Half>) {
    let h = &l.game;
    assert_eq!((h.sites, h.cur, h.autopilot), (g.sites, g.cur, g.autopilot));
    assert_eq!(h.site_balance, g.site_balance);
    assert_eq!(h.site_owned, g.site_owned);
    assert_eq!(h.site_chips, g.site_chips);
    assert_eq!(h.site_staff, g.site_staff);
    assert_eq!(h.site_names, g.site_names);
    assert_eq!(h.fame, g.fame);
    assert_eq!(l.online, s.online);
    assert_eq!(l.theme, s.theme);
    assert!(l.away.is_none());
}

/// The web encoding of the same state: decimal strings for every big number.
fn web_text(g: &Game<Half>, s: &State) -> String {
    let text = to_save_string(g, &s.online, &s.theme, 1000.0);
    let mut v: serde_json::Value = serde_json::from_str(&text).unwrap();
    v["site_balance"] = g.site_balance.iter().map(|b| b.to_string()).collect::<Vec<_>>().into();
    v["fame"] = g.fame.to_string().into();
    v.to_string()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(128))]

    #[test]
    fn save_then_load_round_trips_valid_states(s in state()) {
        let g = build(&s);
        let text = to_save_string(&g, &s.online, &s.theme, 1000.0);
        let l = load_text(&text, Half, 1000.0); // saved_at == now: nothing earned
        assert_same(&g, &s, &l);
        prop_assert_eq!(to_save_string(&l.game, &l.online, &l.theme, 1000.0), text);
    }

    #[test]
    fn the_web_encoding_loads_to_the_same_state(s in state()) {
        let g = build(&s);
        let l = load_text(&web_text(&g, &s), Half, 1000.0);
        assert_same(&g, &s, &l);
    }

    #[test]
    fn arbitrary_text_never_panics_and_stays_sane(text in ".{0,200}") {
        let l = load_text(&text, Half, 1.0);
        prop_assert!(l.game.cur <= l.game.sites && l.game.sites <= MAX_SITES);
    }
}
