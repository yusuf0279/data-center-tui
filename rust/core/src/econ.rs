//! Economy formulas. Exact `BigInt` maths; every division is on non-negative
//! operands, so truncating division equals Python's floor division.

use crate::data::*;
use num_bigint::BigInt;
use num_integer::Integer;


fn big(n: u64) -> BigInt {
    BigInt::from(n)
}

/// `base^k` as a `BigInt`.
fn pow(base: u64, k: u32) -> BigInt {
    big(base).pow(k)
}

/// Display name of data center `k` (0-based).
pub fn site_name(k: usize) -> String {
    match SITE_NAMES.get(k) {
        Some(name) => (*name).to_string(),
        None => format!("Parallel Universe #{}", k - SITE_NAMES.len() + 1),
    }
}

/// Cost to leave data center `site` and open the next one.
pub fn expand_cost(site: usize) -> BigInt {
    big(EXPAND_BASE) * pow(EXPAND_SCALE, site as u32)
}

/// Cost of the next copy of `tier` when `owned` are already in data center `site`.
pub fn cost_of(tier: usize, owned: u32, site: usize) -> BigInt {
    let num = big(TIERS[tier].1) * pow(COST_SCALE, site as u32) * pow(GROWTH_PCT[tier], owned);
    num.div_floor(&pow(100, owned))
}

/// Income multiplier from owning enough of a tier (x2 per milestone passed).
pub fn milestone_mult(owned: u32) -> BigInt {
    let n = MILESTONES.iter().filter(|&&m| owned >= m).count() as u32;
    pow(2, n)
}

/// The next milestone above `owned`, if any.
pub fn next_milestone(owned: u32) -> Option<u32> {
    MILESTONES.iter().copied().find(|&m| owned < m)
}

/// Income per second of `owned` servers of `tier` with chip level `chip`.
pub fn tier_income(tier: usize, owned: u32, chip: u32, site: usize) -> BigInt {
    BigInt::from(owned)
        * big(TIERS[tier].2)
        * pow(INCOME_SCALE, site as u32)
        * pow(CHIP_BOOST, chip)
        * milestone_mult(owned)
}

/// A tier's specialist doubles its income at each milestone level (Lv4, Lv8).
pub fn crew_multiplier(level: i32) -> BigInt {
    let n = DOUBLE_LEVELS.iter().filter(|&&m| level >= m).count() as u32;
    pow(2, n)
}

/// Balance a data center starts with.
pub fn start_balance(site: usize) -> BigInt {
    big(START_BALANCE) * pow(COST_SCALE, site as u32)
}

/// Fame for relocating out of data center `site` holding `balance`.
pub fn fame_gain(balance: &BigInt, site: usize) -> BigInt {
    balance.div_floor(&expand_cost(site)).sqrt()
}

/// Roman numeral for `n` (empty for 0).
pub fn roman(mut n: u32) -> String {
    const TABLE: [(u32, &str); 13] = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ];
    let mut out = String::new();
    for (value, symbol) in TABLE {
        while n >= value {
            out.push_str(symbol);
            n -= value;
        }
    }
    out
}

/// (current title, Fame needed for the next title, next title).
pub fn rank_of(fame: &BigInt) -> (String, BigInt, String) {
    let i = RANKS.iter().rposition(|&(need, _)| *fame >= big(need)).unwrap_or(0);
    if i + 1 < RANKS.len() {
        return (RANKS[i].1.to_string(), big(RANKS[i + 1].0), RANKS[i + 1].1.to_string());
    }
    let (top, name) = RANKS[RANKS.len() - 1];
    let mut level: u32 = 1; // the last title is level 1; each doubling of Fame adds one
    while *fame >= big(top) * pow(2, level) && level < 3999 {
        level += 1;
    }
    let title = if level == 1 { name.to_string() } else { format!("{} {}", name, roman(level)) };
    (title, big(top) * pow(2, level), format!("{} {}", name, roman(level + 1)))
}

/// Name of chip `level` for `tier`.
pub fn chip_name(tier: usize, level: u32) -> String {
    format!("{}{}", CHIP_FAMILIES[tier][(level / 4) as usize], CHIP_EDITIONS[(level % 4) as usize])
}

/// Cost of the chip at `level` for `tier`.
pub fn chip_cost(tier: usize, level: u32, site: usize) -> BigInt {
    big(TIERS[tier].1) * big(CHIP_BASE) * pow(CHIP_GROWTH, level) * pow(COST_SCALE, site as u32)
}

/// Cost to hire (level -1) or to train from `level` to level+1.
pub fn staff_cost(role: usize, level: i32, site: usize) -> BigInt {
    let hire = big(STAFF[role].1) * pow(COST_SCALE, site as u32);
    if level < 0 {
        return hire;
    }
    let l = level as u32;
    (hire * 3u32 * pow(9, l)).div_floor(&pow(5, l))
}

/// Response time in seconds (the only float in the game).
pub fn response_time(role: usize, level: i32) -> f64 {
    STAFF[role].4 * RESPONSE_DECAY.powf(f64::from(level))
}

/// Whole seconds a specialist needs, at least 1.
pub fn response_secs(role: usize, level: i32) -> i64 {
    (response_time(role, level).ceil() as i64).max(1)
}

/// Rebuild an (owned, chips) layout worth about `income` (legacy saves).
pub fn restore_site(site: usize, income: &BigInt, bonus_pct: u64) -> (Vec<u32>, Vec<u32>) {
    let n = TIERS.len();
    let mut owned = vec![0u32; n];
    let mut chips = vec![0u32; n];
    let mut remaining = (income * 100u32).div_floor(&big(100 + bonus_pct));
    for t in (0..n).rev() {
        // fewest chips that keep the count in range (Python's range() leaves the last value)
        let level = (0..=MAX_CHIP)
            .find(|&l| tier_income(t, MAX_OWNED, l, site) > remaining)
            .unwrap_or(MAX_CHIP);
        let (mut lo, mut hi) = (0u32, MAX_OWNED);
        while lo < hi {
            let mid = (lo + hi).div_ceil(2);
            if tier_income(t, mid, level, site) <= remaining {
                lo = mid;
            } else {
                hi = mid - 1;
            }
        }
        if lo > 0 {
            owned[t] = lo;
            chips[t] = level;
            remaining -= tier_income(t, lo, level, site);
        }
    }
    (owned, chips)
}
