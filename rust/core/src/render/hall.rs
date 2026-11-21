//! The hall cell renderer: a port of `Hall.build_cells` and its helpers (`draw_bus`,
//! `draw_sparks`, `base_grid`, `header_cells`, scrollbar) from `data_center_tui/game.py`
//! (commit edf443e: crew sprites, delivery trucks, server build-in), plus the changed-span
//! diff used for partial repaints.
//!
//! Pure functions of explicit inputs. Python `round` is half-even (`round_ties_even`),
//! `int()` truncates, and operand order is kept so colours are bit-identical.

use crate::color::{
    chip_pips, ensure_contrast, hls_bytes, lum, mix, pip_colour, Palette, Rgb, BLACK, WHITE,
};
use crate::data::{MAX_CHIP, MAX_OWNED, TIERS};
use crate::render::layout::{rack_layout, Block, Kind, Layout, CELL_H, CELL_W};
use crate::render::sprites::{
    ease_out, led_lit, led_shade, mix32, sine01, smoothstep, CREW_FRAMES, CREW_WORK, SLOW_HZ, SPRITES, TRUCK,
};

/// Pixels per second of the data pulse.
pub const PULSE_PX_S: f64 = 16.0;
/// Length of the pulse tail in pixels.
pub const PULSE_TAIL: f64 = 5.0;
/// Period of the top-tier glow, seconds.
pub const TOP_PERIOD_S: f64 = 3.0;
/// Quantisation steps of the top-tier glow.
pub const PULSE_STEPS: i64 = 8;
/// Minimum WCAG contrast of tier headers.
pub const HEADER_MIN_CONTRAST: f64 = 3.0;
/// Unchanged cells at most this far apart are repainted as one span.
pub const SPAN_GAP: usize = 2;

/// A crew sprite is 5x6 pixels.
pub const CREW_H: i64 = 6;
/// A person stands one pixel lower than a rack.
pub const CREW_DY: i64 = 1;
/// The idle bob flips every half second.
pub const CREW_BOB_S: f64 = 0.5;
/// Truck sprite size in pixels.
pub const TRUCK_W: usize = 9;
/// Truck height in pixels.
pub const TRUCK_H: i64 = 5;
/// Seconds a delivery truck waits at the crew spot.
pub const TRUCK_PARK_S: f64 = 0.3;
/// Every part of a person or truck against the backdrop.
pub const CREW_MIN_CONTRAST: f64 = 3.0;
/// Hat colour of a level-0 hire: this much of the background mixed into the foreground.
pub const HAT_NEUTRAL_MIX: f64 = 0.3;
/// Hat hue (degrees) of Lv1, and the step per level.
pub const HAT_HUE0: i64 = 240;
/// Hat hue change per training level, degrees.
pub const HAT_HUE_STEP: i64 = 27;
/// Skin colour of a crew member.
pub const SKIN: Rgb = Rgb(226, 184, 148);

/// One terminal cell: a character with optional foreground and background.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Cell {
    pub ch: char,
    pub fg: Option<Rgb>,
    pub bg: Option<Rgb>,
}

/// What an [`Fx`] is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FxKind {
    /// A burst of pixels around a rack.
    Spark,
    /// A rack materialising.
    Build,
    /// A chip delivery truck.
    Truck,
    /// A crew member popping in.
    Appear,
    /// A crew member levelling up.
    Train,
    /// A crew member installing.
    Install,
}

/// One short-lived visual effect (Python `Fx`), born at clock time `born`, alive `life`
/// seconds.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Fx {
    pub kind: FxKind,
    pub seed: i64,
    pub life: f64,
    pub born: f64,
    pub tier: usize,
    /// Spark: the big (milestone) burst.
    pub big: bool,
    /// Build: which rack of the tier is arriving.
    pub slot: usize,
    /// Truck: seconds it takes to drive in.
    pub span: f64,
    /// Truck: the chips have been installed (not drawn).
    pub arrived: bool,
}

impl Fx {
    /// An effect with the optional fields at their Python defaults.
    pub fn new(kind: FxKind, seed: i64, life: f64, born: f64, tier: usize) -> Fx {
        Fx { kind, seed, life, born, tier, big: false, slot: 0, span: 0.0, arrived: false }
    }

    /// 0.0 when born, 1.0 when it expires.
    pub fn progress(&self, now: f64) -> f64 {
        ((now - self.born) / self.life).clamp(0.0, 1.0)
    }
}

/// Everything the hall draws from, besides size, scroll, time and palette.
#[derive(Clone, Debug, PartialEq)]
pub struct HallView {
    pub owned: [u64; 10],
    pub chips: [i32; 10],
    /// The chip level the pips show per tier (`None`: the real one; a truck is en route).
    pub chip_shown: [Option<i32>; 10],
    /// Crew training level per tier (-1: not hired).
    pub staff: [i32; 10],
    /// The tier earning the most right now (`None` in an empty hall).
    pub top_tier: Option<usize>,
    /// An active crisis (LEDs go to the alert colour).
    pub crisis: bool,
    /// A decommissioned data center.
    pub read_only: bool,
    /// Animations run (foreground, ANIM on, live data center).
    pub animating: bool,
    pub fx: Vec<Fx>,
}

impl HallView {
    /// The chip level the hall's pips show for `tier`.
    pub fn shown_chip(&self, tier: usize) -> i32 {
        self.chip_shown[tier].unwrap_or(self.chips[tier])
    }
}

type Grid = Vec<Vec<Rgb>>;
/// An LED pixel: x, y, rack index, sprite position (`y * 8 + x`).
type Led = (usize, usize, usize, usize);

fn cell(ch: char, fg: Option<Rgb>, bg: Option<Rgb>) -> Cell {
    Cell { ch, fg, bg }
}

/// A tier's colour in this hall: washed out to grey in a decommissioned one.
pub fn tier_colour(view: &HallView, pal: &Palette, tier: usize) -> Rgb {
    let colour = pal.tiers[tier];
    if view.read_only {
        let grey = (lum(colour) * 255.0) as u8;
        return mix(Rgb(grey, grey, grey), pal.surface, 0.55);
    }
    colour
}

/// "NAME xN · chip L3/20", shortened step by step to fit `room` cells: the word chip goes
/// first, then the dot, then the name is cut with an ellipsis.
pub fn header_label(name: &str, count: u64, level: i32, room: i64) -> String {
    let chip = format!("L{level}/{MAX_CHIP}");
    let tails = [format!(" x{count} · chip {chip}"), format!(" x{count} · {chip}"),
                 format!(" x{count} {chip}")];
    let n = name.chars().count() as i64;
    for tail in &tails {
        if n + tail.chars().count() as i64 <= room {
            return format!("{name}{tail}");
        }
    }
    let last = &tails[2];
    let keep = room - last.chars().count() as i64;
    if keep >= 4 {
        let cut: String = name.chars().take((keep - 1) as usize).collect();
        return format!("{}…{last}", cut.trim_end());
    }
    format!("{name}{last}").chars().take(room.max(0) as usize).collect()
}

/// One tier's header line: buy-key badge, label in the tier colour, then a rule.
pub fn header_cells(view: &HallView, pal: &Palette, b: &Block, width: usize, under: Rgb)
    -> Vec<Cell> {
    let colour = tier_colour(view, pal, b.tier);
    let key = (b.tier + 1) % 10;
    let badge_fg = ensure_contrast(pal.chip_text, colour, HEADER_MIN_CONTRAST, None);
    let text_fg = ensure_contrast(colour, under, HEADER_MIN_CONTRAST, None);
    let label = header_label(&TIERS[b.tier].0.to_uppercase(), view.owned[b.tier],
                             view.chips[b.tier], width as i64 - 4);
    let mut cells: Vec<Cell> = format!(" {key} ").chars()
        .map(|ch| cell(ch, Some(badge_fg), Some(colour))).collect();
    cells.push(cell(' ', None, Some(under)));
    cells.extend(label.chars().map(|ch| cell(ch, Some(text_fg), Some(under))));
    if cells.len() < width {
        cells.push(cell(' ', None, Some(under)));
    }
    while cells.len() < width {
        cells.push(cell('─', Some(pal.frame), Some(under)));
    }
    cells.truncate(width);
    cells
}

/// A cable along the top of every rack row with a data pulse gliding down it; the head sits
/// at a fractional pixel and blends into its two neighbours.
fn draw_bus(grid: &mut Grid, lay: &Layout, pal: &Palette, t: f64) {
    for b in &lay.blocks[lay.start..lay.end] {
        if b.kind != Kind::Rack {
            continue;
        }
        let width = b.count * CELL_W - 1;
        let row = &mut grid[(b.line0 - lay.top_line()) * 2];
        for x in (0..width).step_by(2) {
            row[x] = pal.frame;
        }
        let head = (t * PULSE_PX_S + (b.row * 9) as f64) % (width as f64 + PULSE_TAIL);
        let colour = pal.tiers[b.tier];
        let lo = (head - PULSE_TAIL).ceil().max(0.0) as usize;
        let hi = width.min(head as usize + 2);
        for (x, px) in row.iter_mut().enumerate().take(hi).skip(lo) {
            let d = head - x as f64;
            let a = if d < 0.0 { 1.0 + d } else { let r = 1.0 - d / PULSE_TAIL; r * r };
            if a > 0.0 {
                *px = mix(*px, colour, a.min(1.0));
            }
        }
    }
}

/// The hall's background at pixel row `y` of `gh`: a soft top-to-bottom gradient.
fn backdrop(pal: &Palette, y: i64, gh: usize) -> Rgb {
    mix(pal.bg, pal.surface, y as f64 / gh.saturating_sub(1).max(1) as f64)
}

/// Sparkle bursts around the newest rack of a tier (hall centre if it is off screen).
fn draw_sparks(grid: &mut Grid, lay: &Layout, view: &HallView, pal: &Palette, now: f64) {
    let (gh, gw) = (grid.len(), grid.first().map_or(0, Vec::len));
    if gh == 0 || gw == 0 {
        return;
    }
    for fx in view.fx.iter().filter(|f| f.kind == FxKind::Spark) {
        let u = fx.progress(now);
        let n = view.owned[fx.tier];
        let at = if n > 0 {
            lay.rack_xy(lay.tier_first[fx.tier] + n as usize - 1, fx.tier)
        } else {
            None
        };
        let (cx, cy) = at.map_or(((gw / 2) as i64, (gh / 2) as i64),
                                 |(x, y)| (x as i64 + 3, y as i64 + 3));
        let base = if fx.big { pal.warning } else { mix(pal.tiers[fx.tier], pal.fg, 0.5) };
        let colour = mix(base, pal.bg, smoothstep(u));
        for i in 0..(if fx.big { 20 } else { 9 }) {
            let h = mix32(&[fx.seed, i]);
            let reach = 1.0 + f64::from(h >> 8 & 3) * 0.5 + 8.0 * ease_out(u);
            let ang = f64::from(h & 255) * std::f64::consts::TAU / 256.0;
            let x = cx + (ang.cos() * reach).round_ties_even() as i64;
            let y = cy + (ang.sin() * reach).round_ties_even() as i64;
            if (0..gw as i64).contains(&x) && (0..gh as i64).contains(&y) {
                grid[y as usize][x as usize] = colour;
            }
        }
    }
}

/// Everything that doesn't move: backdrop, sprites, chip pips; plus the LED pixels.
fn base_grid(lay: &Layout, view: &HallView, pal: &Palette, pulse: i64) -> (Grid, Vec<Led>) {
    let (gw, gh) = (lay.grid_w(), lay.used() * 2);
    let mut grid: Grid = (0..gh).map(|y| vec![backdrop(pal, y as i64, gh); gw]).collect();
    let mut leds = Vec::new();
    for b in &lay.blocks[lay.start..lay.end] {
        if b.kind != Kind::Rack {
            continue;
        }
        let (tier, oy) = (b.tier, (b.line0 - lay.top_line()) * 2 + 1);
        let hue = tier_colour(view, pal, tier);
        let mut colour = hue;
        if view.animating && view.top_tier == Some(tier) {
            colour = mix(colour, pal.fg, 0.25 * pulse as f64 / PULSE_STEPS as f64);
        }
        let shade = |ch: char| match ch {
            'k' => pal.frame,
            'c' => colour,
            'h' => mix(colour, WHITE, 0.35),
            'd' => mix(colour, BLACK, 0.5),
            _ => mix(colour, WHITE, 0.6),
        };
        let pips = chip_pips(view.shown_chip(tier)).map(|s| pip_colour(s, hue, pal.pip_floor));
        for c in 0..b.count {
            let (ox, idx) = (c * CELL_W, b.first + c);
            for (x, pip) in pips.iter().enumerate() {
                grid[oy + 6][ox + 1 + x] = *pip;
            }
            for (y, row) in SPRITES[tier].iter().enumerate() {
                for (x, ch) in row.chars().enumerate() {
                    match ch {
                        '.' => {}
                        'A' | 'B' => leds.push((ox + x, oy + y, idx, y * 8 + x)),
                        _ => grid[oy + y][ox + x] = shade(ch),
                    }
                }
            }
        }
    }
    (grid, leds)
}

/// Pixel row of the first visible rack row of every visible tier, in screen order: where
/// its crew stands (right of the racks) and its trucks park.
fn tier_rows(lay: &Layout) -> Vec<(usize, i64)> {
    let mut rows: Vec<(usize, i64)> = Vec::new();
    for b in &lay.blocks[lay.start..lay.end] {
        if b.kind == Kind::Rack && !rows.iter().any(|r| r.0 == b.tier) {
            rows.push((b.tier, ((b.line0 - lay.top_line()) * 2 + 1) as i64));
        }
    }
    rows
}

/// The crew hat by training level: grey when just hired, then a hue per level.
pub fn hat_colour(pal: &Palette, level: i32) -> Rgb {
    if level <= 0 {
        return mix(pal.fg, pal.bg, HAT_NEUTRAL_MIX);
    }
    let hue = (HAT_HUE0 - (i64::from(level) - 1) * HAT_HUE_STEP).rem_euclid(360);
    hls_bytes(hue as f64, 0.6, 0.95)
}

/// `(x, y, colour)` of one crew frame; every part keeps `CREW_MIN_CONTRAST` against `under`.
fn crew_pixels(view: &HallView, pal: &Palette, tier: usize, level: i32, frame: usize,
               under: Rgb) -> Vec<(usize, usize, Rgb)> {
    let body = tier_colour(view, pal, tier);
    let (mut hat, mut skin) = (hat_colour(pal, level), SKIN);
    if view.read_only {
        // a decommissioned hall is grey: so are its people, hat and skin too
        let grey = |c: Rgb| {
            let g = (lum(c) * 255.0) as u8;
            mix(Rgb(g, g, g), pal.surface, 0.55)
        };
        (hat, skin) = (grey(hat), grey(skin));
    }
    let fix = |c: Rgb| ensure_contrast(c, under, CREW_MIN_CONTRAST, None);
    let (a, s, c, d) = (fix(hat), fix(skin), fix(body), fix(mix(body, BLACK, 0.5)));
    let mut px = Vec::new();
    for (y, row) in CREW_FRAMES[frame].iter().enumerate() {
        for (x, ch) in row.chars().enumerate() {
            let colour = match ch {
                'a' => a,
                's' => s,
                'c' => c,
                'd' => d,
                _ => continue,
            };
            px.push((x, y, colour));
        }
    }
    px
}

/// One person per hired specialist, right of its tier's first visible rack row. They bob
/// while the hall animates; an effect (pop-in, level-up, install) overrides that.
fn draw_crew(grid: &mut Grid, lay: &Layout, view: &HallView, pal: &Palette, now: f64,
             moving: bool) {
    let gh = grid.len();
    let gw = grid.first().map_or(0, Vec::len);
    if lay.reserve == 0 || gh == 0 {
        return;
    }
    let mut fx_of: [Option<&Fx>; 10] = [None; 10];
    for f in view.fx.iter().filter(|f| matches!(f.kind, FxKind::Appear | FxKind::Train | FxKind::Install)) {
        fx_of[f.tier] = Some(f);
    }
    for (tier, row) in tier_rows(lay) {
        let level = view.staff[tier];
        if level < 0 {
            continue;
        }
        let fx = fx_of[tier];
        let mut frame = if moving { ((now / CREW_BOB_S + tier as f64) as i64 & 1) as usize } else { 0 };
        let u = fx.map_or(0.0, |f| f.progress(now));
        if fx.is_some_and(|f| f.kind != FxKind::Appear) {
            frame = CREW_WORK;
        }
        let oy = row + CREW_DY;
        let under = backdrop(pal, oy + CREW_H / 2, gh);
        let mut rows = CREW_H;
        if fx.is_some_and(|f| f.kind == FxKind::Appear) {
            rows = CREW_H.min((CREW_H as f64 * ease_out(u / 0.6)).ceil() as i64);
        }
        let mut glow = 0.0;
        if let Some(f) = fx {
            // a bright flash that dies away; the install flash blinks twice
            glow = if f.kind == FxKind::Install {
                0.5 * (u * std::f64::consts::PI * 2.0).sin().abs()
            } else {
                0.8 * (1.0 - u)
            };
        }
        for (x, y, colour) in crew_pixels(view, pal, tier, level, frame, under) {
            let y = y as i64;
            if y < CREW_H - rows {
                continue; // a pop-in builds up from the feet
            }
            let colour = if glow != 0.0 { mix(colour, WHITE, glow) } else { colour };
            let (gy, gx) = (oy + y, lay.crew_x() + x);
            if 0 <= gy && gy < gh as i64 && gx < gw {
                grid[gy as usize][gx] = colour;
            }
        }
    }
}

/// `(x, y, colour)` of the delivery truck in the tier colour, mirrored when it drives off.
fn truck_pixels(view: &HallView, pal: &Palette, tier: usize, under: Rgb,
                facing_left: bool) -> Vec<(usize, usize, Rgb)> {
    let body = tier_colour(view, pal, tier);
    let fix = |c: Rgb| ensure_contrast(c, under, CREW_MIN_CONTRAST, None);
    let (c, h, k, w, d) = (fix(body), fix(mix(body, WHITE, 0.35)), fix(mix(pal.fg, pal.bg, 0.4)),
                           fix(mix(body, WHITE, 0.6)), fix(mix(body, BLACK, 0.5)));
    let mut px = Vec::new();
    for (y, row) in TRUCK.iter().enumerate() {
        let chars: Vec<char> = if facing_left { row.chars().collect() } else { row.chars().rev().collect() };
        for (x, ch) in chars.into_iter().enumerate() {
            let colour = match ch {
                'c' => c,
                'h' => h,
                'k' => k,
                'w' => w,
                'd' => d,
                _ => continue,
            };
            px.push((x, y, colour));
        }
    }
    px
}

/// Left pixel column of a truck: eases in to `stop`, waits, then drives off back to `start`.
/// `None` once it is gone.
fn truck_x(fx: &Fx, now: f64, start: f64, stop: f64) -> Option<f64> {
    let age = now - fx.born;
    if age < fx.span {
        return Some(stop + (start - stop) * (1.0 - ease_out(age / fx.span)));
    }
    if age < fx.span + TRUCK_PARK_S {
        return Some(stop);
    }
    let back = (age - fx.span - TRUCK_PARK_S) / fx.span;
    (back < 1.0).then(|| stop + (start - stop) * smoothstep(back))
}

/// Chip delivery trucks drive along their tier's first rack row to the crew spot (in front
/// of the racks, behind the crew).
fn draw_trucks(grid: &mut Grid, lay: &Layout, view: &HallView, pal: &Palette, now: f64) {
    let rows = tier_rows(lay);
    let (gh, gw) = (grid.len(), grid.first().map_or(0, Vec::len));
    let stop = (lay.crew_x() as i64 - 1 - TRUCK_W as i64).max(0);
    for fx in view.fx.iter().filter(|f| f.kind == FxKind::Truck) {
        let Some(&(_, row)) = rows.iter().find(|r| r.0 == fx.tier) else { continue };
        let Some(x) = truck_x(fx, now, gw as f64, stop as f64) else { continue };
        let oy = row + 1;
        let leaving = now - fx.born >= fx.span + TRUCK_PARK_S;
        let under = backdrop(pal, oy + TRUCK_H / 2, gh);
        let left = x.round_ties_even() as i64;
        for (px, py, colour) in truck_pixels(view, pal, fx.tier, under, !leaving) {
            let (gx, gy) = (left + px as i64, oy + py as i64);
            if 0 <= gx && gx < gw as i64 && 0 <= gy && gy < gh as i64 {
                grid[gy as usize][gx as usize] = colour;
            }
        }
    }
}

/// A new rack materialises column by column behind a bright scan edge: the columns not yet
/// built show the backdrop again.
fn draw_builds(grid: &mut Grid, lay: &Layout, view: &HallView, pal: &Palette, now: f64) {
    let gh = grid.len();
    for fx in view.fx.iter().filter(|f| f.kind == FxKind::Build) {
        if fx.slot as u64 >= view.owned[fx.tier] {
            continue;
        }
        let Some((ox, oy)) = lay.rack_xy(lay.tier_first[fx.tier] + fx.slot, fx.tier) else { continue };
        let built = (fx.progress(now) * CELL_W as f64) as i64;
        for x in 0..CELL_W - 1 {
            if (x as i64) < built - 1 {
                continue;
            }
            for y in 0..CELL_H - 1 {
                // sprite rows and the pip row below
                grid[oy + y][ox + x] = if x as i64 >= built {
                    backdrop(pal, (oy + y) as i64, gh)
                } else {
                    mix(grid[oy + y][ox + x], WHITE, 0.6)
                };
            }
        }
    }
}

/// The scrollbar column: a thumb in `muted` on a `frame` track.
fn add_scrollbar(cells: &mut [Vec<Cell>], lay: &Layout, pal: &Palette, w: usize) {
    let lines = cells.len() as i64;
    let total = lay.total_lines as i64;
    let thumb_len = (((lines * lines) as f64 / total as f64).round_ties_even() as i64).max(1);
    let thumb_pos = (((lines - thumb_len) * lay.top_line() as i64) as f64
        / (total - lines).max(1) as f64).round_ties_even() as i64;
    for (line, row) in cells.iter_mut().enumerate() {
        while row.len() < w.saturating_sub(1) {
            row.push(cell(' ', None, None));
        }
        let line = line as i64;
        let thumb = thumb_pos <= line && line < thumb_pos + thumb_len;
        row.push(cell(' ', None, Some(if thumb { pal.muted } else { pal.frame })));
    }
}

/// `view` with every field inside the domain the renderer indexes with.
fn sanitised(view: &HallView) -> HallView {
    let mut v = view.clone();
    for n in &mut v.owned {
        *n = (*n).min(u64::from(MAX_OWNED));
    }
    // chip levels live in 0..=MAX_CHIP; anything else is clamped (the header shows the clamped level)
    for c in &mut v.chips {
        *c = (*c).clamp(0, MAX_CHIP as i32);
    }
    for c in v.chip_shown.iter_mut().flatten() {
        *c = (*c).clamp(0, MAX_CHIP as i32);
    }
    v.top_tier = v.top_tier.filter(|&t| t < TIERS.len());
    v.fx.retain(|f| f.tier < TIERS.len());
    v
}

/// The picture, one cell at a time: pixel hall, tier headers, effects, scrollbar. The
/// widget is `w` x `h` cells; `scroll` is the hall's block scroll (`None` follows newest).
///
/// Out-of-domain views are made safe rather than rejected: `owned` is clamped to `MAX_OWNED`
/// (the header then shows the clamped count), `chips` and `chip_shown` to `0..=MAX_CHIP`, a
/// non-finite `now` is taken as 0.0, and a `top_tier` or spark tier outside the
/// ten tiers is ignored.
pub fn build_cells(view: &HallView, w: u16, h: u16, scroll: Option<usize>, now: f64,
                   pal: &Palette) -> Vec<Vec<Cell>> {
    let view = &sanitised(view);
    let now = if now.is_finite() { now } else { 0.0 };
    let w = usize::from(w);
    let slow = (now * SLOW_HZ).floor() / SLOW_HZ;
    let lay = rack_layout(&view.owned, &view.staff, w, usize::from(h), scroll);
    let pulse = if view.animating {
        (PULSE_STEPS as f64 * sine01(slow, TOP_PERIOD_S)).round_ties_even() as i64
    } else {
        0
    };
    let (mut grid, leds) = base_grid(&lay, view, pal, pulse);
    let alert = view.crisis && !view.read_only;
    let (mut on, mut off) = if alert { (pal.alert_on, pal.alert_off) }
                            else { (pal.led_on, pal.led_off) };
    if view.read_only {
        on = mix(pal.frame, pal.bg, 0.4);
        off = on;
    }
    for &(x, y, idx, pos) in &leds {
        grid[y][x] = if view.animating {
            mix(off, on, led_shade(idx, pos / 8, pos % 8, slow))
        } else if led_lit(idx, pos / 8, pos % 8) {
            on
        } else {
            off
        };
    }
    if view.animating {
        if !view.crisis {
            draw_bus(&mut grid, &lay, pal, now);
        }
        draw_sparks(&mut grid, &lay, view, pal, now);
        draw_builds(&mut grid, &lay, view, pal, now);
        draw_trucks(&mut grid, &lay, view, pal, now);
    }
    draw_crew(&mut grid, &lay, view, pal, now, view.animating);
    let mut cells: Vec<Vec<Cell>> = (0..grid.len()).step_by(2)
        .map(|y| (0..lay.grid_w())
            .map(|x| cell('▀', Some(grid[y][x]), Some(grid[y + 1][x]))).collect())
        .collect();
    let scrolled = lay.scrolled();
    for b in &lay.blocks[lay.start..lay.end] {
        if b.kind == Kind::Head {
            let line = b.line0 - lay.top_line();
            let width = if scrolled { w.saturating_sub(1) } else { w };
            cells[line] = header_cells(view, pal, b, width, grid[line * 2][0]);
        }
    }
    if scrolled {
        add_scrollbar(&mut cells, &lay, pal, w);
    }
    cells
}

/// Changed spans `(y, x0, x1)` (half-open) between two pictures; spans with at most
/// `SPAN_GAP` unchanged cells between them merge. A row whose width changed, or that is new,
/// is one full span (a missing old row counts as empty). Rows only in `old` need no span (the picture got shorter).
pub fn diff(old: &[Vec<Cell>], new: &[Vec<Cell>]) -> Vec<(usize, usize, usize)> {
    let mut out = Vec::new();
    for (y, b) in new.iter().enumerate() {
        let empty: &[Cell] = &[];
        let a = old.get(y).map_or(empty, Vec::as_slice);
        if a.len() != b.len() {
            if !a.is_empty() || !b.is_empty() {
                out.push((y, 0, a.len().max(b.len())));
            }
            continue;
        }
        let mut last: Option<(usize, usize)> = None;
        for (x, (p, q)) in a.iter().zip(b).enumerate() {
            if p == q {
                continue;
            }
            match last {
                Some((s, e)) if x - e <= SPAN_GAP => last = Some((s, x + 1)),
                Some((s, e)) => {
                    out.push((y, s, e));
                    last = Some((x, x + 1));
                }
                None => last = Some((x, x + 1)),
            }
        }
        if let Some((s, e)) = last {
            out.push((y, s, e));
        }
    }
    out
}
