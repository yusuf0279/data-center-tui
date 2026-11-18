//! Number and duration formatting, exact for arbitrarily large integers.

use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::{One, Zero};

const SUFFIXES: [&str; 12] = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc"];

fn bit_len(x: &BigInt) -> i64 {
    x.bits() as i64
}

/// Integer division rounded to nearest, ties to even.
fn div_round_even(a: &BigInt, b: &BigInt) -> BigInt {
    let (q, r) = a.div_rem(b);
    let twice: BigInt = r * 2;
    if twice > *b || (twice == *b && q.is_odd()) {
        q + 1
    } else {
        q
    }
}

/// `n / d` as Python's `f"{n / d:.2f}"`: round to the nearest double first (as true
/// division does), then print half-to-even. Returns (double < 999.995, text).
fn quot2(n: &BigInt, d: &BigInt) -> (bool, String) {
    let sh = 55 - (bit_len(n) - bit_len(d));
    let num = if sh >= 0 { n << sh as usize } else { n >> (-sh) as usize };
    let (t, rem_q) = num.div_rem(d);
    let sticky = !rem_q.is_zero();
    let extra = bit_len(&t) - 53;
    let mut m: BigInt = &t >> extra as usize;
    let rem: BigInt = &t & ((BigInt::one() << extra as usize) - 1);
    let half: BigInt = BigInt::one() << (extra - 1) as usize;
    if rem > half || (rem == half && (sticky || m.is_odd())) {
        m += 1;
    }
    let s = sh - extra; // value = m / 2^s
    // n / d is in [1, 1000), so s > 0 here
    let cents = div_round_even(&(&m * 100), &(BigInt::one() << s as usize));
    let (whole, frac) = cents.div_rem(&BigInt::from(100));
    (below_threshold(&m, s), format!("{}.{:02}", whole, frac))
}

/// Whether the double `m / 2^s` is below the double 999.995, compared exactly.
fn below_threshold(m: &BigInt, s: i64) -> bool {
    let (mant, exp, _) = num_traits::float::FloatCore::integer_decode(999.995f64);
    // m / 2^s < mant * 2^exp  <=>  m < mant * 2^(exp + s)   (exp + s may be negative)
    let shift = exp as i64 + s;
    if shift >= 0 {
        *m < (BigInt::from(mant) << shift as usize)
    } else {
        (m << (-shift) as usize) < BigInt::from(mant)
    }
}

/// Format a non-negative amount like `1.23M`; huge values use `1.23e40`.
pub fn fmt(n: &BigInt) -> String {
    let zero = BigInt::zero();
    let v = if *n < zero { &zero } else { n };
    if *v < BigInt::from(1000) {
        return v.to_string();
    }
    let s = v.to_string();
    let digits = s.len();
    let group = (digits - 1) / 3;
    if group < SUFFIXES.len() {
        let (below, text) = quot2(v, &BigInt::from(10).pow(3 * group as u32));
        if below {
            return format!("{}{}", text, SUFFIXES[group]);
        }
        if group + 1 < SUFFIXES.len() {
            let (_, text) = quot2(v, &BigInt::from(10).pow(3 * (group as u32 + 1)));
            return format!("{}{}", text, SUFFIXES[group + 1]);
        }
    }
    format!("{}.{}e{}", &s[..1], &s[1..3], digits - 1)
}

/// Format whole seconds as `Xd Yh`, `Xh Ym` or `Xm`.
pub fn fmt_duration(seconds: f64) -> String {
    let total = seconds.floor() as i64;
    let d = total / 86_400;
    let h = (total % 86_400) / 3_600;
    let m = (total % 3_600) / 60;
    if d > 0 {
        format!("{}d {}h", d, h)
    } else if h > 0 {
        format!("{}h {}m", h, m)
    } else {
        format!("{}m", m)
    }
}
