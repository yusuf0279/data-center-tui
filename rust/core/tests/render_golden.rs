//! Exact comparison of `render::hall::build_cells` with every renderable case of
//! render_golden.json (the cases with `cells: null` raised IndexError in the committed
//! game and are skipped), plus a property test for `diff`.

use dc_core::color::{Palette, Rgb};
use dc_core::render::hall::*;
use dc_core::render::layout::CELL_W;
use proptest::prelude::*;
use serde_json::Value;

mod common;

fn golden() -> Value {
    serde_json::from_str(&common::read_gz("render_golden.json.gz")).expect("parse")
}

fn u(v: &Value) -> usize {
    v.as_u64().expect("unsigned") as usize
}

fn rgb(v: &Value) -> Rgb {
    let a = v.as_array().unwrap();
    Rgb(a[0].as_u64().unwrap() as u8, a[1].as_u64().unwrap() as u8, a[2].as_u64().unwrap() as u8)
}

fn hex(v: &Value) -> Option<Rgb> {
    v.as_str().map(|s| {
        let n = u32::from_str_radix(s, 16).unwrap();
        Rgb((n >> 16) as u8, (n >> 8) as u8, n as u8)
    })
}

fn palette(p: &Value) -> Palette {
    // Build through Palette::new from the raw theme colours; the golden stores the already
    // derived bg/surface/fg/primary/success/warning/error (`visible` is idempotent on them
    // only by luck), so compare derived fields below instead of trusting this blindly.
    let t = [Some(rgb(&p["bg"])), Some(rgb(&p["surface"])), Some(rgb(&p["fg"])),
             Some(rgb(&p["primary"])), Some(rgb(&p["success"])), Some(rgb(&p["warning"])),
             Some(rgb(&p["error"]))];
    Palette::new(&t, p["dark"].as_bool().unwrap())
}

fn view(p: &Value) -> HallView {
    let mut owned = [0u64; 10];
    let mut chips = [0i32; 10];
    for i in 0..10 {
        owned[i] = p["owned"][i].as_u64().unwrap();
        chips[i] = p["chips"][i].as_i64().unwrap() as i32;
    }
    let mut staff = [-1i32; 10];
    let mut chip_shown = [None; 10];
    for i in 0..10 {
        staff[i] = p["staff"][i].as_i64().unwrap() as i32;
        chip_shown[i] = p["chip_shown"][i].as_i64().map(|v| v as i32);
    }
    let fx = p["fx"].as_array().unwrap().iter().map(|f| Fx {
        kind: match f["kind"].as_str().unwrap() {
            "spark" => FxKind::Spark,
            "build" => FxKind::Build,
            "truck" => FxKind::Truck,
            "appear" => FxKind::Appear,
            "train" => FxKind::Train,
            "install" => FxKind::Install,
            other => panic!("unknown fx kind {other}"),
        },
        seed: f["seed"].as_i64().unwrap(),
        life: f["life"].as_f64().unwrap(),
        born: f["born"].as_f64().unwrap(),
        tier: u(&f["tier"]),
        big: f["big"].as_bool().unwrap(),
        slot: u(&f["slot"]),
        span: f["span"].as_f64().unwrap(),
        arrived: f["arrived"].as_bool().unwrap(),
    }).collect();
    HallView { owned, chips, chip_shown, staff, top_tier: p["top_tier"].as_u64().map(|t| t as usize),
               crisis: p["crisis"].as_bool().unwrap(), read_only: p["read_only"].as_bool().unwrap(),
               animating: p["animating"].as_bool().unwrap(), fx }
}

fn want_grid(c: &Value) -> Vec<Vec<Cell>> {
    c["cells"].as_array().unwrap().iter().map(|row| {
        let mut out = Vec::new();
        for run in row.as_array().unwrap() {
            let (fg, bg) = (hex(&run[1]), hex(&run[2]));
            out.extend(run[0].as_str().unwrap().chars().map(|ch| Cell { ch, fg, bg }));
        }
        out
    }).collect()
}

/// The widget size of a case. The compositor (`xcheck`) cases ran in a real screen: the
/// golden records the real widget size as `hall_w` x `hall_h`.
fn view_size(c: &Value) -> (usize, usize) {
    let p = &c["params"];
    if p.get("xcheck").is_none() {
        return (u(&p["w"]), u(&p["h"]));
    }
    let (w, l) = (u(&p["hall_w"]), &c["layout"]);
    assert!(w >= u(&l["cols"]) * CELL_W + u(&l["reserve"]));
    (w, u(&p["hall_h"]))
}

fn first_diffs(got: &[Vec<Cell>], want: &[Vec<Cell>]) -> Vec<String> {
    let mut out = Vec::new();
    if got.len() != want.len() {
        out.push(format!("row count got {} want {}", got.len(), want.len()));
    }
    for (y, (g, w)) in got.iter().zip(want).enumerate() {
        if g.len() != w.len() {
            out.push(format!("row {y} width got {} want {}", g.len(), w.len()));
        }
        for (x, (a, b)) in g.iter().zip(w).enumerate() {
            if a != b {
                out.push(format!("(x={x}, y={y}) got {a:?} want {b:?}"));
            }
        }
        if out.len() >= 5 {
            break;
        }
    }
    out.truncate(5);
    out
}

#[test]
fn hall_matches_every_case() {
    let g = golden();
    let (mut compared, mut skipped) = (0, 0);
    let mut failed: Vec<String> = Vec::new();
    for (i, c) in g["cases"].as_array().unwrap().iter().enumerate() {
        if c["cells"].is_null() {
            skipped += 1;
            continue;
        }
        let p = &c["params"];
        let (w, h) = view_size(c);
        let got = build_cells(&view(p), w as u16, h as u16, p["scroll"].as_u64().map(|s| s as usize),
                              p["now"].as_f64().unwrap(), &palette(&c["palette"]));
        compared += 1;
        let d = first_diffs(&got, &want_grid(c));
        if !d.is_empty() {
            failed.push(format!("case {i} state={} {}x{} scroll={} theme={} now={}: {}",
                p["state"], p["w"], p["h"], p["scroll"], p["theme"], p["now"], d.join("; ")));
        }
    }
    println!("compared {compared} cases, skipped {skipped} (cells null)");
    let cov = coverage(&g);
    println!("coverage {cov:?}");
    assert!(cov.len() == 13 && cov.iter().all(|&(_, n)| n >= MIN_COVER), "thin coverage {cov:?}");
    assert!(failed.is_empty(), "{} of {compared} cases differ:\n{}", failed.len(),
            failed.iter().take(10).cloned().collect::<Vec<_>>().join("\n"));
}

const MIN_COVER: usize = 15;

/// How many golden cases exercise each new feature, so a golden that silently stops
/// covering one fails here instead of passing vacuously.
fn coverage(g: &Value) -> Vec<(&'static str, usize)> {
    let mut n = std::collections::BTreeMap::<&'static str, usize>::new();
    let mut bump = |k: &'static str| *n.entry(k).or_default() += 1;
    for c in g["cases"].as_array().unwrap() {
        if c["cells"].is_null() {
            continue;
        }
        let (p, l) = (&c["params"], &c["layout"]);
        if u(&l["reserve"]) > 0 {
            bump("reserve_on");
        }
        let hired = p["staff"].as_array().unwrap().iter().any(|s| s.as_i64().unwrap() >= 0);
        if hired && u(&l["reserve"]) == 0 {
            bump("reserve_off_hired");
        }
        if p["read_only"].as_bool().unwrap() && hired && u(&l["reserve"]) > 0 {
            bump("read_only_crew");
        }
        let shown_lag = (0..10).any(|i| p["chip_shown"][i].as_i64()
            .is_some_and(|v| v != p["chips"][i].as_i64().unwrap()));
        if shown_lag {
            bump("chip_shown_lag");
        }
        for i in 0..10 {
            if p["staff"][i].as_i64().unwrap() >= 10 {
                bump("hat_lv10");
                break;
            }
        }
        for f in p["fx"].as_array().unwrap() {
            let age = p["now"].as_f64().unwrap() - f["born"].as_f64().unwrap();
            match f["kind"].as_str().unwrap() {
                "truck" => {
                    let span = f["span"].as_f64().unwrap();
                    bump(if age < span { "truck_in" } else if age < span + 0.3 { "truck_parked" }
                         else if age < 2.0 * span + 0.3 { "truck_leaving" } else { "fx_truck_gone" });
                }
                "build" => bump("build"),
                "appear" => bump("appear"),
                "train" => bump("train"),
                "install" => bump("install"),
                _ => {}
            }
        }
    }
    n.into_iter().collect()
}

fn golden_cell(table: &Value, i: &Value) -> Cell {
    let t = &table[u(i)];
    Cell { ch: t[0].as_str().unwrap().chars().next().unwrap(), fg: hex(&t[1]), bg: hex(&t[2]) }
}

/// `diff` against the spans of the real `Hall.changed_spans` on 700 random row pairs
/// (equal and unequal widths), exactly: this pins SPAN_GAP and the merge rule.
#[test]
fn diff_matches_python_changed_spans() {
    let g = golden();
    let d = &g["diff_cases"];
    let (mut merged, mut unequal) = (0, 0);
    for (i, c) in d["cases"].as_array().unwrap().iter().enumerate() {
        let row = |k: &str| -> Vec<Cell> {
            c[k].as_array().unwrap().iter().map(|x| golden_cell(&d["cells"], x)).collect()
        };
        let (old, new) = (row("old"), row("new"));
        let want: Vec<(usize, usize, usize)> = c["spans"].as_array().unwrap().iter()
            .map(|s| (0, u(&s[0]), u(&s[1]))).collect();
        assert_eq!(diff(std::slice::from_ref(&old), std::slice::from_ref(&new)), want, "diff case {i}");
        unequal += usize::from(old.len() != new.len());
        merged += usize::from(want.len() == 1 && old.len() == new.len() && want[0].1 + 1 < want[0].2);
    }
    assert!(merged > 50 && unequal > 20, "coverage {merged} {unequal}");
}

#[test]
fn header_label_matches_python() {
    let g = golden();
    let rows = g["header_label"].as_array().unwrap();
    assert!(rows.len() > 3000);
    let (mut cut, mut hard) = (0, 0);
    for r in rows {
        let got = header_label(r[0].as_str().unwrap(), r[1].as_u64().unwrap(),
                               r[2].as_i64().unwrap() as i32, r[3].as_i64().unwrap());
        assert_eq!(got, r[4].as_str().unwrap(), "header_label {} {} {} {}", r[0], r[1], r[2], r[3]);
        cut += usize::from(got.contains('…'));
        hard += usize::from(r[3].as_i64().unwrap() < 20);
    }
    assert!(cut > 100 && hard > 100, "coverage {cut} {hard}");
}

fn hostile_view() -> HallView {
    let sp = |tier| Fx::new(FxKind::Spark, 1, 1.0, 0.0, tier);
    let mut truck = Fx::new(FxKind::Truck, 1, 2.3, 0.0, 99);
    truck.span = 1.0;
    HallView { owned: [10_000_000, 4000, 4001, u64::MAX, 3, 0, 0, 0, 0, 1], chips: [0; 10],
               chip_shown: [None; 10], staff: [3; 10], top_tier: Some(10), crisis: false,
               read_only: false, animating: true, fx: vec![sp(10), sp(99), sp(0), truck] }
}

/// Out-of-domain views are clamped or ignored, never a panic or a gigabyte allocation.
#[test]
fn out_of_domain_view_is_clamped() {
    let pal = Palette::new(&[None; 7], true);
    let bad = hostile_view();
    let mut clamped = bad.clone();
    clamped.owned = [4000, 4000, 4000, 4000, 3, 0, 0, 0, 0, 1];
    clamped.top_tier = None;
    clamped.fx.retain(|f| f.tier < 10);
    for (w, h, scroll) in [(80u16, 24u16, None), (7, 2, Some(0)), (140, 30, Some(5))] {
        let got = build_cells(&bad, w, h, scroll, 0.5, &pal);
        assert_eq!(got, build_cells(&clamped, w, h, scroll, 0.5, &pal), "{w}x{h}");
    }
}

/// Chip levels are clamped to 0..=20 (no overflow at i32::MIN/MAX) and a non-finite `now`
/// draws as 0.0, for every size and scroll.
#[test]
fn chips_clamped_and_non_finite_now() {
    let pal = Palette::new(&[None; 7], true);
    let mut bad = hostile_view();
    bad.owned = [3; 10];
    bad.chips = [i32::MIN, i32::MAX, -1, 21, 0, 20, 5, 1, 2, 3];
    bad.chip_shown = [Some(i32::MIN), Some(i32::MAX), Some(-3), Some(99), None, Some(20), None, None,
                      Some(0), Some(7)];
    bad.fx.clear();
    let mut ok = bad.clone();
    ok.chips = [0, 20, 0, 20, 0, 20, 5, 1, 2, 3];
    ok.chip_shown = [Some(0), Some(20), Some(0), Some(20), None, Some(20), None, None, Some(0), Some(7)];
    for (w, h) in [(80u16, 24u16), (40, 10), (14, 6)] {
        assert_eq!(build_cells(&bad, w, h, None, 1.0, &pal), build_cells(&ok, w, h, None, 1.0, &pal));
        let zero = build_cells(&ok, w, h, Some(0), 0.0, &pal);
        for now in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY] {
            assert_eq!(build_cells(&ok, w, h, Some(0), now, &pal), zero, "now={now}");
        }
        for now in [1e300, -1e300, f64::MAX, f64::MIN] {
            let _ = build_cells(&ok, w, h, None, now, &pal); // finite but absurd: no panic
        }
    }
}

#[test]
fn layout_clamps_owned() {
    use dc_core::render::layout::rack_layout;
    let a = rack_layout(&[10_000_000, u64::MAX], &[0, 0], 80, 24, Some(0));
    let b = rack_layout(&[4000, 4000], &[0, 0], 80, 24, Some(0));
    assert_eq!((a.total_lines, a.blocks.len()), (b.total_lines, b.blocks.len()));
}

fn arb_cell() -> impl Strategy<Value = Cell> {
    (0u8..3, 0u8..3).prop_map(|(a, b)| Cell {
        ch: if a == 0 { ' ' } else { '▀' },
        fg: if a == 2 { None } else { Some(Rgb(a, 0, 0)) },
        bg: Some(Rgb(b, 0, 0)),
    })
}

fn arb_grid() -> impl Strategy<Value = Vec<Vec<Cell>>> {
    prop::collection::vec(prop::collection::vec(arb_cell(), 0..24), 0..6)
}

proptest! {
    #[test]
    fn spans_reproduce_new(old in arb_grid(), new in arb_grid()) {
        let mut pic = old.clone();
        pic.truncate(new.len());
        pic.resize(new.len(), Vec::new());
        let spans = diff(&old, &new);
        for &(y, x0, x1) in &spans {
            prop_assert!(x0 < x1);
            if y >= pic.len() {
                pic.resize(y + 1, Vec::new());
            }
            if pic[y].len() < x1 {
                pic[y].resize(x1, Cell { ch: '?', fg: None, bg: None });
            }
            let e = x1.min(new[y].len());
            pic[y][x0..e].copy_from_slice(&new[y][x0..e]);
        }
        for row in pic.iter_mut().zip(&new) { row.0.truncate(row.1.len()); }
        prop_assert_eq!(pic, new);
    }

    #[test]
    fn same_rows_equal_width_gap_merge(row in prop::collection::vec(arb_cell(), 1..24),
                                       flips in prop::collection::vec(0usize..24, 0..6)) {
        let mut new = row.clone();
        for f in flips { if f < new.len() { new[f].ch = '#'; } }
        let spans = diff(std::slice::from_ref(&row), std::slice::from_ref(&new));
        for w in spans.windows(2) {
            prop_assert!(w[1].1 - w[0].2 > SPAN_GAP);
        }
    }
}
