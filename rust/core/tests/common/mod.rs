//! Shared helpers for integration tests.

use flate2::read::GzDecoder;
use std::io::Read;

/// Reads a gzip-compressed fixture and returns its decompressed UTF-8 text.
///
/// Args:
///     name: file name inside `tests/data/`, e.g. `render_golden.json.gz`.
///
/// Panics:
///     If the file is missing, is not valid gzip, or is not UTF-8.
pub fn read_gz(name: &str) -> String {
    let path = format!("{}/tests/data/{}", env!("CARGO_MANIFEST_DIR"), name);
    let file = std::fs::File::open(&path).unwrap_or_else(|e| panic!("open {path}: {e}"));
    let mut text = String::new();
    GzDecoder::new(file)
        .read_to_string(&mut text)
        .unwrap_or_else(|e| panic!("gunzip {path}: {e}"));
    text
}
