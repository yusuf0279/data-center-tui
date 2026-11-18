//! Exact comparison of `color.rs` with the committed Python game (render_golden.json):
//! the colour_units table, the palette_units (real themes and synthetic junk themes) and
//! the palette of every render case.

use dc_core::color::*;
use serde_json::Value;

mod common;

fn golden() -> Value {
    serde_json::from_str(&common::read_gz("render_golden.json.gz")).expect("parse render_golden.json.gz")
}

fn rgb(v: &Value) -> Rgb {
    let a = v.as_array().expect("rgb array");
    let ch = |i: usize| a[i].as_u64().expect("channel") as u8;
    Rgb(ch(0), ch(1), ch(2))
}

fn opt_rgb(v: &Value) -> Option<Rgb> {
    (!v.is_null()).then(|| rgb(v))
}

fn f(v: &Value) -> f64 {
    v.as_f64().expect("float")
}

fn arr(c: Rgb) -> [u8; 3] {
    [c.0, c.1, c.2]
}

fn check_units(g: &Value) -> usize {
    let mut n = 0;
    for row in g["colour_units"].as_array().expect("colour_units") {
        let (name, a, want) = (row[0].as_str().expect("name"), &row[1], &row[2]);
        match name {
            "pip_colour" => {
                let got = pip_colour(a[0].as_i64().expect("step") as i32, rgb(&a[1]), rgb(&a[2]));
                assert_eq!(arr(got), arr(rgb(want)), "{row}");
            }
            "ensure_contrast" => {
                let got = ensure_contrast(rgb(&a[0]), rgb(&a[1]), f(&a[2]), opt_rgb(&a[3]));
                assert_eq!(arr(got), arr(rgb(want)), "{row}");
            }
            "lightness" => assert_eq!(lightness(rgb(&a[0])).to_bits(), f(want).to_bits(), "{row}"),
            "contrast" => {
                assert_eq!(contrast(rgb(&a[0]), rgb(&a[1])).to_bits(), f(want).to_bits(), "{row}");
            }
            "mix" => assert_eq!(arr(mix(rgb(&a[0]), rgb(&a[1]), f(&a[2]))), arr(rgb(want)), "{row}"),
            "hls" => assert_eq!(arr(hls_bytes(f(&a[0]), f(&a[1]), f(&a[2]))), arr(rgb(want)), "{row}"),
            "lum" => assert_eq!(lum(rgb(&a[0])).to_bits(), f(want).to_bits(), "{row}"),
            other => panic!("unknown unit {other}"),
        }
        n += 1;
    }
    n
}

/// Compare every field of a palette with its golden dump; returns the first difference.
fn diff_palette(p: &Palette, want: &Value) -> Option<String> {
    let mut fields: Vec<(String, Rgb)> = vec![
        ("bg".into(), p.bg), ("surface".into(), p.surface), ("fg".into(), p.fg),
        ("primary".into(), p.primary), ("success".into(), p.success),
        ("warning".into(), p.warning), ("error".into(), p.error), ("muted".into(), p.muted),
        ("faint".into(), p.faint), ("frame".into(), p.frame), ("shadow".into(), p.shadow),
        ("led_on".into(), p.led_on), ("led_off".into(), p.led_off),
        ("alert_on".into(), p.alert_on), ("alert_off".into(), p.alert_off),
        ("chip_text".into(), p.chip_text), ("pip_floor".into(), p.pip_floor),
    ];
    for (i, t) in p.tiers.iter().enumerate() {
        fields.push((format!("tiers[{i}]"), *t));
    }
    for (name, got) in fields {
        let w = match name.strip_prefix("tiers[") {
            Some(rest) => rgb(&want["tiers"][rest.trim_end_matches(']').parse::<usize>().unwrap()]),
            None => rgb(&want[name.as_str()]),
        };
        if got != w {
            return Some(format!("{name}: got {got:?} want {w:?}"));
        }
    }
    None
}

#[test]
fn colour_units_exact() {
    let n = check_units(&golden());
    assert_eq!(n, 2000);
    println!("colour_units: {n} exact");
}

#[test]
fn synthetic_palettes_exact() {
    let g = golden();
    let list = g["palette_units"]["synthetic"].as_array().expect("synthetic");
    let keys = ["background", "surface", "foreground", "primary", "success", "warning", "error"];
    for (i, s) in list.iter().enumerate() {
        let strs: Vec<&str> = keys.iter().map(|k| s["v"][*k].as_str().expect("str")).collect();
        let arr7: [&str; 7] = strs.try_into().expect("7 keys");
        let p = Palette::from_strs(&arr7, s["dark"].as_bool().expect("dark"));
        if let Some(d) = diff_palette(&p, &s["palette"]) {
            panic!("synthetic {i} {}: {d}", s["v"]);
        }
    }
    println!("synthetic palettes: {} exact", list.len());
}

/// The palette dumps hold the already-`visible()` accents, so feeding them back is exact
/// only while `visible` is idempotent for that colour; the case list below also records
/// that.
fn from_dump(d: &Value, dark: bool) -> Palette {
    let get = |k: &str| Some(rgb(&d[k]));
    let v: ThemeColours = [get("bg"), get("surface"), get("fg"), get("primary"), get("success"),
                          get("warning"), get("error")];
    Palette::new(&v, dark)
}

#[test]
fn real_theme_palettes_exact() {
    let g = golden();
    let themes = g["palette_units"]["themes"].as_object().expect("themes");
    for (name, t) in themes {
        let p = from_dump(&t["palette"], t["dark"].as_bool().expect("dark"));
        if let Some(d) = diff_palette(&p, &t["palette"]) {
            panic!("theme {name}: {d}");
        }
    }
    println!("theme palettes: {} exact", themes.len());
}

#[test]
fn case_palettes_exact() {
    let g = golden();
    let cases = g["cases"].as_array().expect("cases");
    for (i, c) in cases.iter().enumerate() {
        let pal = &c["palette"];
        let v: ThemeColours = ["bg", "surface", "fg", "primary", "success", "warning", "error"]
            .map(|k| Some(rgb(&pal[k])));
        let p = Palette::new(&v, pal["dark"].as_bool().expect("dark"));
        for (k, got) in [("bg", p.bg), ("surface", p.surface), ("fg", p.fg),
                         ("primary", p.primary), ("success", p.success),
                         ("warning", p.warning), ("error", p.error)] {
            assert_eq!(got, rgb(&pal[k]), "case {i} {k}");
        }
    }
    println!("case palettes: {} exact", cases.len());
}
