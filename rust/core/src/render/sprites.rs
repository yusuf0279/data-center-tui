//! Rack sprites, easing curves, the deterministic hash and the LED model (port of the
//! module-level helpers and `Hall.led_*` of `data_center_tui/game.py`, commit e66836d).

use std::f64::consts::TAU;

/// Sprite legend: k frame, c tier colour, h highlight, d dark, w pale window/fan,
/// A/B blinking LEDs, . empty. One distinct silhouette per tier; 6x6 each.
pub const SPRITES: [[&str; 6]; 10] = [
    ["......", "......", ".cccc.", "chhhhc", "cddAdc", "kkkkkk"],
    ["......", "cccccc", "chhhAc", "kkkkkk", "chhhBc", "cccccc"],
    ["cccccc", "cwdwAc", "cddddc", "cwdwBc", "cddddc", "kkkkkk"],
    ["..hh..", "cccccc", "cwcwcc", "cccccc", "cwcAwc", "dddddd"],
    ["..hh..", ".hwwh.", "chwwhc", ".cwwc.", "..cc..", "..dd.."],
    ["..hA..", "cckkcc", "cchhcc", "cckkcc", "..kk..", "..dd.."],
    ["..cc..", ".chhc.", "chwwhc", "cwAAwc", "cddddc", "kkkkkk"],
    ["c....c", ".hhhh.", "hwAAwh", "hwwwwh", ".hhhh.", "c....c"],
    ["......", "..cc..", "cwhhwc", ".cwwc.", "..cc..", "..dd.."],
    [".cccc.", "chddhc", "cdAAdc", "chddhc", ".cccc.", "..dd.."],
];

/// Crew frames (a hat, s skin, c tier colour, d legs): idle0, idle1, work (arms up). The idle
/// bob differs from the first frame in the two body rows only: one text line.
pub const CREW_FRAMES: [[&str; 6]; 3] = [
    [".aaa.", ".sss.", "ccccc", ".ccc.", ".d.d.", "dd.dd"],
    [".aaa.", ".sss.", ".ccc.", "ccccc", ".d.d.", "dd.dd"],
    ["caaac", "csssc", ".ccc.", ".ccc.", ".d.d.", "dd.dd"],
];
/// Index of the arms-up frame in [`CREW_FRAMES`].
pub const CREW_WORK: usize = 2;

/// The delivery truck, facing left (c cargo in the tier colour, h highlight, k cab, w window,
/// d wheels).
pub const TRUCK: [&str; 5] = ["..ccccccc", "kkkcchhcc", "kwkcccccc", "kkkkkkkkk", ".dd...dd."];

/// Seconds an LED keeps one on/off roll.
pub const LED_SLOT_S: f64 = 0.6;
/// Fraction of a slot over which an LED fades to its new state.
pub const LED_FADE: f64 = 0.5;
/// Brightness steps of an LED fade.
pub const LED_LEVELS: i64 = 4;
/// Rate (Hz) of the slow clock that drives LEDs and the top-tier glow (12 fps / 2).
pub const SLOW_HZ: f64 = 6.0;

/// Small deterministic integer hash (FNV-style); negative inputs are masked to 32 bits.
pub fn mix32(vals: &[i64]) -> u32 {
    let mut h: u32 = 0x811C_9DC5;
    for &v in vals {
        h = (h ^ (v as u32)).wrapping_mul(0x0100_0193);
        h ^= h >> 15;
    }
    h
}

/// Ease in and out, clamped to 0..1.
pub fn smoothstep(x: f64) -> f64 {
    let x = x.clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}

/// Fast start, gentle stop, clamped to 0..1.
pub fn ease_out(x: f64) -> f64 {
    let x = x.clamp(0.0, 1.0);
    let r = 1.0 - x;
    1.0 - r * r
}

/// Smooth 0..1..0 over `period` seconds, starting at 0.
pub fn sine01(t: f64, period: f64) -> f64 {
    0.5 - 0.5 * (TAU * t / period).cos()
}

/// Is this LED pixel lit in a still hall (no animation)? A fixed pattern.
pub fn led_lit(idx: usize, y: usize, x: usize) -> bool {
    (idx + y * 2 + x).is_multiple_of(3)
}

/// LED brightness 0..1 at time `t`: it re-rolls on/off once per slot (own offset) and eases.
/// The slot number saturates for absurd (finite) `t` and the step before it wraps instead of
/// overflowing; in-domain times behave exactly as the Python game.
pub fn led_level(idx: usize, y: usize, x: usize, t: f64) -> f64 {
    let (idx, key) = (idx as i64, (y * 8 + x) as i64);
    let s = t / LED_SLOT_S + f64::from(mix32(&[idx, key, 99]) & 1023) / 1024.0;
    let k = s.floor();
    let roll = |n: i64| if mix32(&[idx, key, n]) % 5 < 2 { 1.0 } else { 0.0 };
    let (now, before) = (roll(k as i64), roll((k as i64).wrapping_sub(1)));
    before + (now - before) * smoothstep((s - k) / LED_FADE)
}

/// [`led_level`] snapped to `LED_LEVELS` brightness steps (round half to even).
pub fn led_shade(idx: usize, y: usize, x: usize, t: f64) -> f64 {
    let steps = (LED_LEVELS - 1) as f64;
    (led_level(idx, y, x, t) * steps).round_ties_even() / steps
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mix32_masks_negative() {
        assert_eq!(mix32(&[-1]), mix32(&[0xFFFF_FFFF]));
        assert_ne!(mix32(&[1, 2]), mix32(&[2, 1]));
    }

    #[test]
    fn curves_clamp() {
        assert_eq!(smoothstep(-1.0), 0.0);
        assert_eq!(smoothstep(2.0), 1.0);
        assert_eq!(ease_out(0.0), 0.0);
        assert_eq!(sine01(0.0, 3.0), 0.0);
    }

    #[test]
    fn led_level_survives_absurd_times() {
        for t in [1e300, -1e300, f64::MAX, f64::MIN, 1e19, -1e19] {
            let v = led_level(3, 2, 5, t);
            assert!(v.is_nan() || (0.0..=1.0).contains(&v), "{t} -> {v}");
        }
        assert_eq!(led_level(3, 2, 5, 12.5), led_level(3, 2, 5, 12.5));
    }

    #[test]
    fn crew_and_truck_shapes() {
        assert!(CREW_FRAMES.iter().all(|f| f.iter().all(|r| r.chars().count() == 5)));
        assert!(TRUCK.iter().all(|r| r.chars().count() == 9));
    }

    #[test]
    fn sprites_are_6x6() {
        assert!(SPRITES.iter().all(|s| s.iter().all(|r| r.chars().count() == 6)));
    }
}
