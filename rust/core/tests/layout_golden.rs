//! Exact comparison of `render::layout` with every case of render_golden.json (864 cases,
//! including the 50 whose `cells` are null because the committed game raised IndexError
//! while drawing: those cases still record a valid layout, so they are covered here).
//!
//! Blocks are compared structurally when the golden holds them (<= 300 blocks); for larger
//! halls the golden has only blocks_n, blocks_visible and the sha256 of Python's
//! `json.dumps(blocks)`, which is reproduced here byte for byte (", " separators) with a
//! small in-file SHA-256.

use dc_core::render::layout::*;
use serde_json::Value;

mod common;

fn golden() -> Value {
    serde_json::from_str(&common::read_gz("render_golden.json.gz")).expect("parse render_golden.json.gz")
}

fn u(v: &Value) -> usize {
    v.as_u64().expect("unsigned") as usize
}

fn block_row(b: &Block) -> String {
    format!("[\"{}\", {}, {}, {}, {}, {}, {}]", b.kind.as_str(), b.tier, b.first, b.count,
            b.line0, b.height, b.row)
}

/// `json.dumps(list_of_rows)` of the blocks.
fn dumps(blocks: &[Block]) -> String {
    let rows: Vec<String> = blocks.iter().map(block_row).collect();
    format!("[{}]", rows.join(", "))
}

fn golden_row(v: &Value) -> String {
    let a = v.as_array().expect("row");
    format!("[{}, {}, {}, {}, {}, {}, {}]", a[0], u(&a[1]), u(&a[2]), u(&a[3]), u(&a[4]),
            u(&a[5]), u(&a[6]))
}

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

fn sha256_hex(data: &[u8]) -> String {
    let mut h: [u32; 8] = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
                           0x1f83d9ab, 0x5be0cd19];
    let mut msg = data.to_vec();
    msg.push(0x80);
    while msg.len() % 64 != 56 {
        msg.push(0);
    }
    msg.extend_from_slice(&((data.len() as u64) * 8).to_be_bytes());
    for chunk in msg.chunks(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes(chunk[4 * i..4 * i + 4].try_into().unwrap());
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16].wrapping_add(s0).wrapping_add(w[i - 7]).wrapping_add(s1);
        }
        let mut v = h;
        for i in 0..64 {
            let s1 = v[4].rotate_right(6) ^ v[4].rotate_right(11) ^ v[4].rotate_right(25);
            let ch = (v[4] & v[5]) ^ (!v[4] & v[6]);
            let t1 = v[7].wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);
            let s0 = v[0].rotate_right(2) ^ v[0].rotate_right(13) ^ v[0].rotate_right(22);
            let maj = (v[0] & v[1]) ^ (v[0] & v[2]) ^ (v[1] & v[2]);
            let t2 = s0.wrapping_add(maj);
            v = [t1.wrapping_add(t2), v[0], v[1], v[2], v[3].wrapping_add(t1), v[4], v[5], v[6]];
        }
        for i in 0..8 {
            h[i] = h[i].wrapping_add(v[i]);
        }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

/// The Hall widget size of a case. Normal cases force params w x h. The two `xcheck`
/// (compositor) cases ran in a real 110x32 screen, so the Hall is smaller than params say;
/// there the golden does not record the width, so it is recovered from `cols` (the width is
/// cols*7, plus the scrollbar column when the hall scrolls) and only `height` is taken from
/// the golden. Every other field is still checked independently.
fn view_size(c: &Value) -> (usize, usize) {
    let (p, l) = (&c["params"], &c["layout"]);
    if p.get("xcheck").is_none() {
        return (u(&p["w"]), u(&p["h"]));
    }
    let bar = usize::from(l["scrolled"].as_bool().unwrap());
    (u(&l["cols"]) * CELL_W + bar, u(&l["height"]))
}

#[test]
fn sha256_known_answer() {
    assert_eq!(sha256_hex(b"abc"),
               "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
}

#[test]
fn layout_matches_every_case() {
    let g = golden();
    let cases = g["cases"].as_array().expect("cases");
    let (mut full, mut hashed, mut null_cells) = (0, 0, 0);
    for (i, c) in cases.iter().enumerate() {
        let (p, l) = (&c["params"], &c["layout"]);
        let owned: Vec<u64> = p["owned"].as_array().unwrap().iter()
            .map(|x| x.as_u64().unwrap()).collect();
        let scroll = p["scroll"].as_u64().map(|s| s as usize);
        let (w, h) = view_size(c);
        let lay = rack_layout(&owned, w, h, scroll);
        let ctx = format!("case {i} {} {}x{} scroll {:?}", p["state"], p["w"], p["h"], scroll);
        assert_eq!(lay.cols, u(&l["cols"]), "{ctx} cols");
        assert_eq!(lay.height, u(&l["height"]), "{ctx} height");
        assert_eq!(lay.start, u(&l["start"]), "{ctx} start");
        assert_eq!(lay.end, u(&l["end"]), "{ctx} end");
        assert_eq!(lay.total_lines, u(&l["total_lines"]), "{ctx} total_lines");
        assert_eq!(lay.total_rows, u(&l["total_rows"]), "{ctx} total_rows");
        let tb: Vec<i64> = l["tier_block"].as_array().unwrap().iter()
            .map(|x| x.as_i64().unwrap()).collect();
        let tf: Vec<usize> = l["tier_first"].as_array().unwrap().iter().map(u).collect();
        assert_eq!(lay.tier_block, tb, "{ctx} tier_block");
        assert_eq!(lay.tier_first, tf, "{ctx} tier_first");
        assert_eq!(lay.blocks.len(), u(&l["blocks_n"]), "{ctx} blocks_n");
        assert_eq!(lay.scrolled(), l["scrolled"].as_bool().unwrap(), "{ctx} scrolled");
        assert_eq!(lay.top_line(), u(&l["top_line"]), "{ctx} top_line");
        assert_eq!(lay.used(), u(&l["used"]), "{ctx} used");
        assert_eq!(lay.max_start(), u(&l["max_start"]), "{ctx} max_start");
        let vis: Vec<String> = lay.blocks[lay.start..lay.end].iter().map(block_row).collect();
        let want_vis: Vec<String> = l["blocks_visible"].as_array().unwrap().iter()
            .map(golden_row).collect();
        assert_eq!(vis, want_vis, "{ctx} blocks_visible");
        if let Some(all) = l["blocks"].as_array() {
            let want: Vec<String> = all.iter().map(golden_row).collect();
            let got: Vec<String> = lay.blocks.iter().map(block_row).collect();
            assert_eq!(got, want, "{ctx} blocks");
            full += 1;
        }
        // the sha256 of Python's json.dumps(blocks) is present for every case
        assert_eq!(sha256_hex(dumps(&lay.blocks).as_bytes()),
                   l["blocks_sha256"].as_str().unwrap(), "{ctx} blocks_sha256");
        hashed += 1;
        null_cells += usize::from(c["cells"].is_null());
    }
    println!("layout: {} cases exact ({full} with full blocks, {hashed} sha256-checked, \
              {null_cells} with cells=null still covered)", cases.len());
}

#[test]
fn rack_xy_consistent_with_blocks() {
    let g = golden();
    let mut checked = 0;
    for c in g["cases"].as_array().unwrap() {
        let p = &c["params"];
        let owned: Vec<u64> = p["owned"].as_array().unwrap().iter()
            .map(|x| x.as_u64().unwrap()).collect();
        let (w, h) = view_size(c);
        let lay = rack_layout(&owned, w, h, p["scroll"].as_u64().map(|s| s as usize));
        for b in &lay.blocks[lay.start..lay.end] {
            for k in 0..b.count {
                let xy = lay.rack_xy(b.first + k, b.tier).expect("visible rack has a position");
                assert_eq!(xy, (k * CELL_W, (b.line0 - lay.top_line()) * 2 + 1));
                checked += 1;
            }
        }
        for b in lay.blocks[..lay.start].iter().chain(&lay.blocks[lay.end..]) {
            if b.kind == Kind::Rack {
                assert_eq!(lay.rack_xy(b.first, b.tier), None);
            }
        }
    }
    println!("rack_xy: {checked} visible racks checked");
}
