//! Colour maths and the theme palette: an exact port of the colour helpers and
//! `Palette` of `data_center_tui/game.py` (commit e66836d).
//!
//! Operand order and rounding follow Python exactly: `int()` truncates toward zero, there
//! are no fused multiply-adds, and `**` is `powf`, so results are bit-identical.

/// An sRGB colour, one byte per channel.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Rgb(pub u8, pub u8, pub u8);

pub const BLACK: Rgb = Rgb(0, 0, 0);
pub const WHITE: Rgb = Rgb(255, 255, 255);

/// Hue (degrees) of each server tier; the same in every theme.
pub const TIER_HUES: [u32; 10] = [340, 140, 300, 95, 262, 32, 175, 55, 215, 8];
/// HLS saturation of the tier colours.
pub const TIER_SATURATION: f64 = 0.72;
/// How far towards white a full hall pip goes.
pub const PIP_FULL_WHITE: f64 = 0.85;
/// The faintest lit pip against an empty one (WCAG ratio).
pub const PIP_MIN_CONTRAST: f64 = 3.0;
/// Editions per chip family pip.
pub const CHIP_STEPS: i32 = 4;

/// Theme colours in Palette order: background, surface, foreground, primary, success,
/// warning, error. `None` is an ANSI / transparent / unparsable value.
pub type ThemeColours = [Option<Rgb>; 7];

const FALLBACK_DARK: [Rgb; 7] = [
    Rgb(26, 27, 38),
    Rgb(36, 40, 59),
    Rgb(192, 202, 245),
    Rgb(122, 162, 247),
    Rgb(158, 206, 106),
    Rgb(224, 175, 104),
    Rgb(247, 118, 142),
];
const FALLBACK_LIGHT: [Rgb; 7] = [
    Rgb(233, 233, 237),
    Rgb(222, 222, 228),
    Rgb(52, 59, 88),
    Rgb(52, 84, 138),
    Rgb(72, 94, 48),
    Rgb(143, 94, 21),
    Rgb(140, 67, 81),
];

/// Python `int(a + (b - a) * t)` per channel (truncation toward zero).
///
/// Channels outside 0..=255 (only possible for `t` outside 0..=1) saturate.
pub fn mix(a: Rgb, b: Rgb, t: f64) -> Rgb {
    let ch = |x: u8, y: u8| -> u8 {
        let (x, y) = (f64::from(x), f64::from(y));
        (x + (y - x) * t) as u8
    };
    Rgb(ch(a.0, b.0), ch(a.1, b.1), ch(a.2, b.2))
}

/// Perceptual luma 0..1.
pub fn lum(c: Rgb) -> f64 {
    (0.299 * f64::from(c.0) + 0.587 * f64::from(c.1) + 0.114 * f64::from(c.2)) / 255.0
}

/// sRGB channel to linear light.
pub fn linear(v: u8) -> f64 {
    let x = f64::from(v) / 255.0;
    if x <= 0.03928 {
        x / 12.92
    } else {
        ((x + 0.055) / 1.055).powf(2.4)
    }
}

fn relative_luminance(c: Rgb) -> f64 {
    0.2126 * linear(c.0) + 0.7152 * linear(c.1) + 0.0722 * linear(c.2)
}

/// WCAG contrast ratio between two colours (1.0 to 21.0).
pub fn contrast(a: Rgb, b: Rgb) -> f64 {
    let (ra, rb) = (relative_luminance(a), relative_luminance(b));
    let (hi, lo) = if ra >= rb { (ra, rb) } else { (rb, ra) };
    (hi + 0.05) / (lo + 0.05)
}

/// Push `fg` towards black or white (whichever reads better on `bg`) until it reaches
/// `minimum` contrast; a colour that already passes is returned unchanged. `prefer`
/// names an end to try first.
pub fn ensure_contrast(fg: Rgb, bg: Rgb, minimum: f64, prefer: Option<Rgb>) -> Rgb {
    if contrast(fg, bg) >= minimum {
        return fg;
    }
    // Python max() keeps the first maximum: black wins a tie.
    let best = if contrast(WHITE, bg) > contrast(BLACK, bg) { WHITE } else { BLACK };
    for end in prefer.into_iter().chain([best]) {
        for step in 1..=20 {
            let c = mix(fg, end, f64::from(step) / 20.0);
            if contrast(c, bg) >= minimum {
                return c;
            }
        }
    }
    best
}

/// CIE L* (0 black .. 100 white).
pub fn lightness(c: Rgb) -> f64 {
    let y = relative_luminance(c);
    let f = if y > 0.008856 { y.powf(1.0 / 3.0) } else { 7.787 * y + 16.0 / 116.0 };
    116.0 * f - 16.0
}

const ONE_SIXTH: f64 = 1.0 / 6.0;
const ONE_THIRD: f64 = 1.0 / 3.0;
const TWO_THIRD: f64 = 2.0 / 3.0;

fn hls_v(m1: f64, m2: f64, hue: f64) -> f64 {
    let hue = hue.rem_euclid(1.0); // Python float %: the sign of the divisor
    if hue < ONE_SIXTH {
        return m1 + (m2 - m1) * hue * 6.0;
    }
    if hue < 0.5 {
        return m2;
    }
    if hue < TWO_THIRD {
        return m1 + (m2 - m1) * (TWO_THIRD - hue) * 6.0;
    }
    m1
}

/// Port of Python `colorsys.hls_to_rgb` (floats 0..1).
pub fn hls_to_rgb(h: f64, l: f64, s: f64) -> (f64, f64, f64) {
    if s == 0.0 {
        return (l, l, l);
    }
    let m2 = if l <= 0.5 { l * (1.0 + s) } else { l + s - (l * s) };
    let m1 = 2.0 * l - m2;
    (hls_v(m1, m2, h + ONE_THIRD), hls_v(m1, m2, h), hls_v(m1, m2, h - ONE_THIRD))
}

/// `tuple(int(x * 255) for x in hls_to_rgb(h / 360, l, s))` for a hue in degrees.
pub fn hls_bytes(hue_deg: f64, l: f64, s: f64) -> Rgb {
    let (r, g, b) = hls_to_rgb(hue_deg / 360.0, l, s);
    Rgb((r * 255.0) as u8, (g * 255.0) as u8, (b * 255.0) as u8)
}

/// The chip pip fills (0..=4) of the 5 family pips for an installed chip level.
pub fn chip_pips(level: i32) -> [i32; 5] {
    let mut out = [0; 5];
    for (i, p) in out.iter_mut().enumerate() {
        *p = level.saturating_sub(CHIP_STEPS * i as i32).clamp(0, CHIP_STEPS);
    }
    out
}

/// Smallest mix of `floor` towards `peak` (14-step bisection) satisfying `reached`.
fn solve(floor: Rgb, peak: Rgb, reached: impl Fn(Rgb) -> bool) -> f64 {
    let (mut lo, mut hi) = (0.0_f64, 1.0_f64);
    for _ in 0..14 {
        let mid = (lo + hi) / 2.0;
        if reached(mix(floor, peak, mid)) {
            hi = mid;
        } else {
            lo = mid;
        }
    }
    hi
}

/// One hall pip: `floor` when empty, then a tint of the tier colour `hue` that gets lighter
/// with every edition (`step` 0..=4).
pub fn pip_colour(step: i32, hue: Rgb, floor: Rgb) -> Rgb {
    if step == 0 {
        return floor;
    }
    let peak = mix(hue, WHITE, PIP_FULL_WHITE);
    let first = mix(
        floor,
        peak,
        solve(floor, peak, |c| contrast(c, floor) >= PIP_MIN_CONTRAST),
    );
    let (l1, l4) = (lightness(first), lightness(peak));
    let want = l1 + (l4 - l1) * f64::from(step - 1) / f64::from(CHIP_STEPS - 1);
    mix(floor, peak, solve(floor, peak, |c| lightness(c) >= want))
}

/// Keep an accent readable: pull it towards `fg` (up to 6 times) until it is at least
/// 0.3 luma away from `surface`.
pub fn visible(mut c: Rgb, surface: Rgb, fg: Rgb) -> Rgb {
    for _ in 0..6 {
        if (lum(c) - lum(surface)).abs() >= 0.3 {
            break;
        }
        c = mix(c, fg, 0.25);
    }
    c
}

const NAMED: [(&str, Rgb); 17] = [
    ("black", Rgb(0, 0, 0)),
    ("white", Rgb(255, 255, 255)),
    ("red", Rgb(255, 0, 0)),
    ("green", Rgb(0, 128, 0)),
    ("blue", Rgb(0, 0, 255)),
    ("yellow", Rgb(255, 255, 0)),
    ("cyan", Rgb(0, 255, 255)),
    ("magenta", Rgb(255, 0, 255)),
    ("gray", Rgb(128, 128, 128)),
    ("grey", Rgb(128, 128, 128)),
    ("orange", Rgb(255, 165, 0)),
    ("purple", Rgb(128, 0, 128)),
    ("silver", Rgb(192, 192, 192)),
    ("maroon", Rgb(128, 0, 0)),
    ("navy", Rgb(0, 0, 128)),
    ("olive", Rgb(128, 128, 0)),
    ("teal", Rgb(0, 128, 128)),
];

fn hex_pair(s: &str) -> Option<u8> {
    u8::from_str_radix(s, 16).ok()
}

fn parse_hex(h: &str) -> Option<Rgb> {
    if !h.is_ascii() {
        return None;
    }
    let (rgb, alpha) = match h.len() {
        3 | 4 => {
            let d: Vec<String> = h.chars().map(|c| format!("{c}{c}")).collect();
            (Rgb(hex_pair(&d[0])?, hex_pair(&d[1])?, hex_pair(&d[2])?), d.get(3).cloned())
        }
        6 | 8 => (
            Rgb(hex_pair(&h[0..2])?, hex_pair(&h[2..4])?, hex_pair(&h[4..6])?),
            h.get(6..8).map(str::to_string),
        ),
        _ => return None,
    };
    match alpha {
        Some(a) if hex_pair(&a)? < 255 => None, // translucent: no real RGB
        _ => Some(rgb),
    }
}

fn parse_func(body: &str) -> Option<Rgb> {
    let parts: Vec<&str> = body.split(',').map(str::trim).collect();
    if parts.len() != 3 && parts.len() != 4 {
        return None;
    }
    let ch = |s: &str| s.parse::<f64>().ok().map(|v| v.round_ties_even().clamp(0.0, 255.0) as u8);
    let rgb = Rgb(ch(parts[0])?, ch(parts[1])?, ch(parts[2])?);
    match parts.get(3) {
        Some(a) if a.parse::<f64>().ok()? < 1.0 => None,
        _ => Some(rgb),
    }
}

/// Parse a theme colour string the way the palette needs it: `Some` only for a real,
/// opaque RGB (hex, `rgb()`/`rgba()`, a few CSS names); `None` for ANSI names,
/// `transparent`, translucent colours and anything unparsable.
pub fn parse_colour(raw: &str) -> Option<Rgb> {
    let s = raw.trim().to_ascii_lowercase();
    if let Some(h) = s.strip_prefix('#') {
        return parse_hex(h);
    }
    for pre in ["rgba(", "rgb("] {
        if let Some(rest) = s.strip_prefix(pre) {
            return parse_func(rest.strip_suffix(')')?);
        }
    }
    NAMED.iter().find(|(n, _)| *n == s).map(|(_, c)| *c)
}

/// Every colour the game draws with, derived from the active theme.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Palette {
    pub bg: Rgb,
    pub surface: Rgb,
    pub fg: Rgb,
    pub primary: Rgb,
    pub success: Rgb,
    pub warning: Rgb,
    pub error: Rgb,
    pub tiers: [Rgb; 10],
    pub muted: Rgb,
    pub faint: Rgb,
    pub frame: Rgb,
    pub shadow: Rgb,
    pub led_on: Rgb,
    pub led_off: Rgb,
    pub alert_on: Rgb,
    pub alert_off: Rgb,
    pub chip_text: Rgb,
    pub pip_floor: Rgb,
}

impl Palette {
    /// Build the palette from the theme's seven colours (see [`ThemeColours`]); a missing
    /// one falls back to the fixed dark / light palette.
    pub fn new(v: &ThemeColours, dark: bool) -> Palette {
        let fallback = if dark { &FALLBACK_DARK } else { &FALLBACK_LIGHT };
        let get = |i: usize| v[i].unwrap_or(fallback[i]);
        let (bg, surface, fg) = (get(0), get(1), get(2));
        let vis = |c: Rgb| visible(c, surface, fg);
        let light = if lum(surface) < 0.5 { 0.62 } else { 0.38 };
        let tiers = TIER_HUES.map(|h| vis(hls_bytes(f64::from(h), light, TIER_SATURATION)));
        let (success, error) = (vis(get(4)), vis(get(6)));
        let shadow = mix(bg, BLACK, 0.5);
        Palette {
            bg,
            surface,
            fg,
            primary: vis(get(3)),
            success,
            warning: vis(get(5)),
            error,
            tiers,
            muted: mix(fg, surface, 0.45),
            faint: mix(fg, surface, 0.75),
            frame: mix(surface, fg, 0.2),
            shadow,
            led_on: success,
            led_off: mix(success, bg, 0.8),
            alert_on: error,
            alert_off: mix(error, bg, 0.8),
            chip_text: bg,
            pip_floor: if lum(surface) < 0.5 { shadow } else { mix(bg, BLACK, 0.8) },
        }
    }

    /// Like [`Palette::new`] from raw theme strings (see [`parse_colour`]).
    pub fn from_strs(v: &[&str; 7], dark: bool) -> Palette {
        Palette::new(&v.map(parse_colour), dark)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mix_truncates() {
        assert_eq!(mix(Rgb(0, 0, 0), Rgb(255, 255, 255), 0.5), Rgb(127, 127, 127));
    }

    #[test]
    fn parse_variants() {
        assert_eq!(parse_colour("#fff"), Some(WHITE));
        assert_eq!(parse_colour("#102030"), Some(Rgb(16, 32, 48)));
        assert_eq!(parse_colour("red"), Some(Rgb(255, 0, 0)));
        assert_eq!(parse_colour("rgba(10,20,30,0.5)"), None);
        assert_eq!(parse_colour("rgb(10,20,30)"), Some(Rgb(10, 20, 30)));
        for bad in ["ansi_red", "transparent", "nonsense", "", "#12"] {
            assert_eq!(parse_colour(bad), None, "{bad}");
        }
    }

    #[test]
    fn chip_pips_fill_left_to_right() {
        assert_eq!(chip_pips(0), [0; 5]);
        assert_eq!(chip_pips(6), [4, 2, 0, 0, 0]);
        assert_eq!(chip_pips(20), [4; 5]);
    }
}
