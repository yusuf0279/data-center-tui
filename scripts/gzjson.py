"""Deterministic gzip writer for the Rust test fixtures (same input -> same bytes)."""
import gzip
from pathlib import Path


def write_gz(path: Path, text: str) -> None:
    """Write text as gzip: level 9, mtime 0, no filename in the header."""
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            gz.write(text.encode("utf-8"))
