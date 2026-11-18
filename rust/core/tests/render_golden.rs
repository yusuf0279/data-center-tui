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
    let fx = p["fx"].as_array().unwrap().iter().map(|f| Spark {
        seed: f["seed"].as_i64().unwrap(),
        life: f["life"].as_f64().unwrap(),
        born: f["born"].as_f64().unwrap(),
        tier: u(&f["tier"]),
        big: f["big"].as_bool().unwrap(),
    }).collect();
    HallView { owned, chips, top_tier: p["top_tier"].as_u64().map(|t| t as usize),
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

/// The widget size of a case. The two compositor (`xcheck`) cases ran in a real screen
/// whose width the golden does not record; the width is recovered from the golden's own
/// first row (every row of the picture is as wide as the widget when it scrolls, and at
/// least `cols * 7` otherwise), the height from `layout.height`.
fn view_size(c: &Value) -> (usize, usize) {
    let (p, l) = (&c["params"], &c["layout"]);
    if p.get("xcheck").is_none() {
        return (u(&p["w"]), u(&p["h"]));
    }
    let width: usize = c["cells"][0].as_array().unwrap().iter()
        .map(|r| r[0].as_str().unwrap().chars().count()).sum();
    assert!(width >= u(&l["cols"]) * CELL_W);
    (width, u(&l["height"]))
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
    assert!(failed.is_empty(), "{} of {compared} cases differ:\n{}", failed.len(),
            failed.iter().take(10).cloned().collect::<Vec<_>>().join("\n"));
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
    let sp = |tier| Spark { seed: 1, life: 1.0, born: 0.0, tier, big: false };
    HallView { owned: [10_000_000, 4000, 4001, u64::MAX, 3, 0, 0, 0, 0, 1], chips: [0; 10],
               top_tier: Some(10), crisis: false, read_only: false, animating: true,
               fx: vec![sp(10), sp(99), sp(0)] }
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

#[test]
fn layout_clamps_owned() {
    use dc_core::render::layout::rack_layout;
    let a = rack_layout(&[10_000_000, u64::MAX], 80, 24, Some(0));
    let b = rack_layout(&[4000, 4000], 80, 24, Some(0));
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
