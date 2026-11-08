#!/usr/bin/env python3
"""Draw the extension icons (the game's GPU-rack sprite on a gruvbox tile) with the stdlib only."""
import struct
import sys
import zlib
from pathlib import Path

BG, FRAME, FAN = (40, 40, 40), (80, 73, 69), (251, 241, 199)
BODY, DARK, LED = (250, 189, 47), (146, 108, 28), (184, 187, 38)
# k frame, c body, d dark, w fan, A/B LED   (same sprite as the game's GPU Cluster)
SPRITE = ["kkkkkk", "kwcwAk", "kddddk", "kwcwBk", "kddddk", "kkkkkk"]
COLOURS = {"k": FRAME, "c": BODY, "d": DARK, "w": FAN, "A": LED, "B": LED}


def png(size: int) -> bytes:
    margin = max(1, size // 8)
    cell = (size - 2 * margin) // 6
    ox = oy = (size - cell * 6) // 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            colour = BG
            sx, sy = (x - ox) // cell, (y - oy) // cell
            if x >= ox and y >= oy and 0 <= sx < 6 and 0 <= sy < 6:
                colour = COLOURS[SPRITE[sy][sx]]
            row += bytes(colour) + b"\xff"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("icons")
    out.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 48, 128):
        (out / f"icon{size}.png").write_bytes(png(size))
    print("wrote", ", ".join(f"icon{s}.png" for s in (16, 32, 48, 128)), "to", out)
