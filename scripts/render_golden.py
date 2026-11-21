#!/usr/bin/env python3
"""Write rust/core/tests/data/render_golden.json.gz: what the REAL committed Hall draws.

The game is imported from a root given as argv[1] or $DC_GAME_ROOT (default
/mnt/bigvolume/dc-edf, a worktree of commit edf443e: crew, trucks, build-in; the older
/mnt/bigvolume/dc-e66 worktree of e66836d still works when passed) so the golden never
reflects uncommitted edits. Headless Textual app, DC_ONLINE=0, temp DC_SAVE, timers patched out.
Every case forces app state and the Hall size, then calls Hall.build_cells() directly
(pre-Strip). Deterministic: seeded, no paths or times in the output.

Cell encoding ("format" key in the file): cells[case][row] is a list of runs
[text, fg, bg]; every char of text is one cell; fg/bg are "rrggbb" or null.

Run: python3 scripts/render_golden.py [GAME_ROOT] [--out PATH]
Set DC_GOLDEN_TRACE=1 to print the game.py functions exercised to stderr.
"""
import asyncio
import collections
import colorsys
import dataclasses
import hashlib
import itertools
import importlib
import json
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import PropertyMock

from gzjson import write_gz


def import_game(root: Path) -> Any:
    """Import `game` from the checkout at `root` (new name, or the old one in older commits)."""
    name = "build_a_hyperscaler" if (root / "build_a_hyperscaler").is_dir() else "data_center_tui"
    module = importlib.import_module(f"{name}.game")
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    return module


HERE = Path(__file__).resolve().parent.parent
argv = sys.argv[1:]
OUT = HERE / "rust/core/tests/data/render_golden.json.gz"
if "--out" in argv:
    i = argv.index("--out")
    OUT = Path(argv[i + 1])
    del argv[i:i + 2]
args = [a for a in argv if not a.startswith("--")]
ROOT = Path(args[0] if args else os.environ.get("DC_GAME_ROOT", "/mnt/bigvolume/dc-edf")).resolve()
os.environ["DC_ONLINE"] = "0"
os.environ["DC_SAVE"] = str(Path(tempfile.mkdtemp()) / "save.json")
for _v in ("TMUX", "TMUX_PANE"):
    os.environ.pop(_v, None)
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from textual.geometry import Size  # noqa: E402
game = import_game(ROOT)  # noqa: E402

import test_anim  # noqa: E402  (committed tests of ROOT: screen_cells)

N = len(game.TIERS)
Hall = game.Hall
THEMES = ["gruvbox", "textual-dark", "textual-light", "nord", "solarized-light", "monokai",
          "tokyo-night"]
SIZES = [(40, 10), (50, 3), (80, 24), (110, 32), (7, 2), (200, 60)]
NOWS = [0.0, 0.1, 0.55, 1.37, 3.0, 17.31, 1000.123456789]
CRISIS = {"title": "x", "sev": 1, "fixer": None, "eta": None}


def pad(a: list[int]) -> list[int]:
    return (a + [0] * N)[:N]


STATES: dict[str, dict[str, Any]] = {
    "one": dict(owned=pad([1]), chips=pad([0]), staff=[-1] * N),
    "all10": dict(owned=[9, 7, 5, 4, 3, 2, 2, 1, 1, 1], chips=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                  staff=[-1] * N),
    "big4000": dict(owned=pad([4000, 3]), chips=pad([5, 20]), staff=[-1] * N),
    "chips": dict(owned=pad([4, 4, 4, 4, 4, 4]), chips=pad([0, 1, 4, 5, 19, 20]),
                  staff=[-1] * N),
    "crisis": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([1, 1, 1]), staff=[-1] * N, crisis=True),
    "read_only": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([2, 4, 6, 8, 10]), staff=[-1] * N,
                      read_only=True),
    "empty": dict(owned=pad([]), chips=pad([]), staff=[-1] * N),
    "topA": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([0]), staff=[-1] * N),
    "topB": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([0]), staff=[8, -1, -1, -1, 0] + [-1] * 5),
}
OLD_STATES = list(STATES)


def lv(a: list[int]) -> list[int]:
    return (a + [-1] * N)[:N]


# crew states (staff levels: -1 not hired, 0 hired, 1..10 trained); "shown" = chip_shown
STATES.update({
    "crew_one": dict(owned=pad([1]), chips=pad([0]), staff=lv([0])),
    "crew_small": dict(owned=pad([2, 2, 1]), chips=pad([1, 0, 3]), staff=lv([3, 1, 0])),
    "nocrew_small": dict(owned=pad([2, 2, 1]), chips=pad([1, 0, 3]), staff=lv([])),
    "hire_lv": dict(owned=[3] * N, chips=list(range(N)), staff=list(range(N))),
    "hire_lv2": dict(owned=[2, 5, 1, 4, 3, 2, 6, 1, 2, 3], chips=[0, 20, 5, 1, 0, 9, 2, 0, 4, 7],
                     staff=[10, 0, 5, -1, 9, 2, 10, 1, -1, 3]),
    "hire_lv3": dict(owned=[4] * N, chips=[20, 19, 18, 1, 0, 2, 3, 4, 5, 6],
                     staff=[10, 9, 8, 7, 6, 5, 4, 3, 2, 1]),
    "crew_big": dict(owned=pad([4000, 3]), chips=pad([5, 20]), staff=lv([10, 5])),
    "crew_scroll": dict(owned=pad([30, 20, 10]), chips=pad([3, 3, 3]), staff=lv([2, 7, 1])),
    "crew_ro": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([2, 4, 6, 8, 10]),
                    staff=lv([0, 3, 5, 7, 10]), read_only=True),
    "crew_crisis": dict(owned=pad([8, 6, 4, 2, 1]), chips=pad([1, 1, 1]),
                        staff=lv([1, 2, 3, 4, 5]), crisis=True),
    "hired_unowned": dict(owned=pad([2, 0, 0, 3]), chips=pad([]), staff=lv([-1, 5, 2, -1])),
    "hired_half": dict(owned=pad([2, 0, 3]), chips=pad([1, 0, 2]), staff=lv([-1, 4, 6])),
    "nocrew_two": dict(owned=pad([2]), chips=pad([1]), staff=lv([])),
    "last3": dict(owned=pad([3]), chips=pad([1]), staff=lv([3])),
    "last3n": dict(owned=pad([3]), chips=pad([1]), staff=lv([])),
    "last6": dict(owned=pad([6]), chips=pad([2]), staff=lv([5])),
    "last6n": dict(owned=pad([6]), chips=pad([2]), staff=lv([])),
    "crew_lag": dict(owned=pad([4, 4, 4]), chips=pad([3, 5, 20]), staff=lv([2, -1, 4]),
                     shown={0: 1, 2: 0}),
    "crew_lag2": dict(owned=pad([4, 4, 4, 2]), chips=pad([3, 5, 20, 20]), staff=lv([-1, -1, -1, -1]),
                      shown={0: 3, 1: 9, 3: 4}),
})
CREW_STATES = [s for s in STATES if s not in OLD_STATES]




TRACED: set[str] = set()


def tracer(frame: Any, event: str, _arg: Any) -> None:
    if event == "call" and frame.f_code.co_filename == game.__file__:
        TRACED.add(frame.f_code.co_qualname)


def hx(c: Any) -> str | None:
    return None if c is None else "%02x%02x%02x" % tuple(c)


def runs(row: list[Any]) -> list[Any]:
    return [["".join(ch for ch, _, _ in g), hx(k[0]), hx(k[1])]
            for k, g in itertools.groupby(row, key=lambda c: (c[1], c[2]))]


def key_of(p: dict[str, Any]) -> str:
    q = dict(p)
    if not p["animating"]:
        q["now"] = None
    return json.dumps(q, sort_keys=True)


def make_params(state: str, size: tuple[int, int], scroll: Any, theme: str, now: float,
                fx: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    st = STATES[state]
    return {"state": state, "w": size[0], "h": size[1], "scroll": scroll,
            "owned": st["owned"], "chips": st["chips"], "staff": st["staff"],
            "chip_shown": [st.get("shown", {}).get(i) for i in range(N)],
            "crisis": bool(st.get("crisis")), "read_only": bool(st.get("read_only")),
            "anim_enabled": True, "foreground": True, "fx": fx or [], "now": now, "theme": theme}


def palette_of(app: Any, theme: str) -> dict[str, Any]:
    p = app.pal
    return {"bg": list(p.bg), "surface": list(p.surface), "fg": list(p.fg),
            "primary": list(p.primary), "success": list(p.success),
            "warning": list(p.warning), "error": list(p.error),
            "dark": bool(app.get_theme(theme).dark)}


def layout_of(lay: Any) -> dict[str, Any]:
    blocks = [[b.kind, b.tier, b.first, b.count, b.line0, b.height, b.row] for b in lay.blocks]
    return {"cols": lay.cols, "height": lay.height, "start": lay.start, "end": lay.end,
            "total_lines": lay.total_lines, "total_rows": lay.total_rows,
            "tier_block": lay.tier_block, "tier_first": lay.tier_first,
            "blocks_n": len(lay.blocks),
            "blocks": blocks if len(blocks) <= 300 else None,
            "blocks_visible": blocks[lay.start:lay.end],
            "blocks_sha256": hashlib.sha256(json.dumps(blocks).encode()).hexdigest(),
            "scrolled": lay.scrolled, "top_line": lay.top_line, "used": lay.used,
            "max_start": lay.max_start, "reserve": getattr(lay, "reserve", 0),
            "grid_w": lay.cols * game.CELL_W + getattr(lay, "reserve", 0),
            "crew_x": lay.cols * game.CELL_W}


def apply(app: Any, hall: Any, p: dict[str, Any]) -> None:
    """Force the app into the state of params `p` (scroll already resolved)."""
    ro = p["read_only"]
    app.sites = 1 if ro else 0
    app.cur = 0
    app.site_owned = [list(p["owned"])] + ([[0] * N] if ro else [])
    app.site_chips = [list(p["chips"])] + ([[0] * N] if ro else [])
    app.site_staff = [list(p["staff"])] + ([[-1] * N] if ro else [])
    app.crisis = dict(CRISIS) if p["crisis"] else None
    app.hall_scroll = p["scroll"]
    app.chip_shown = {i: v for i, v in enumerate(p["chip_shown"]) if v is not None}
    known = {f.name for f in dataclasses.fields(game.Fx)}  # e66836d's Fx has fewer fields
    app.fx = [game.Fx(**{k: v for k, v in f.items() if k in known}) for f in p["fx"]]
    app.foreground = p["foreground"]
    app.now = p["now"]
    game.ANIM = p["anim_enabled"]
    if app.theme != p["theme"]:
        app.theme = p["theme"]
    app._pal = None  # a fresh palette every case; the golden is the uncached truth
    hall._base_key, hall._blocks_owned, hall._blocks = None, (), {}
    getattr(hall, "_crew_cache", {}).clear()


def record(app: Any, hall: Any, p: dict[str, Any]) -> dict[str, Any]:
    apply(app, hall, p)
    with mock.patch.object(Hall, "size", new_callable=PropertyMock,
                           return_value=Size(p["w"], p["h"])):
        try:
            cells = hall.build_cells()
            error = None
        except IndexError as exc:  # empty grid + animating: draw_sparks reads grid[0]
            cells, error = None, f"IndexError: {exc}"
        lay = hall.rack_layout()
        special = hall.special()
    params = dict(p)
    params["animating"] = bool(app.animating)
    params["top_tier"] = app.top_tier()
    out = {"params": params, "palette": palette_of(app, p["theme"]), "layout": layout_of(lay),
           "special": None if special is None else special.plain,
           "cells": None if cells is None else [runs(r) for r in cells], "error": error}
    return out


def mid_scroll(app: Any, hall: Any, p: dict[str, Any]) -> int:
    q = dict(p, scroll=None)
    apply(app, hall, q)
    with mock.patch.object(Hall, "size", new_callable=PropertyMock,
                           return_value=Size(p["w"], p["h"])):
        return len(hall.rack_layout().blocks) // 2


def fx_spark(tier: int, u: float, big: bool, now: float, seed: int) -> dict[str, Any]:
    life = game.SPARK_LIFE_S
    return {"kind": "spark", "seed": seed, "life": life, "born": now - u * life,
            "tier": tier, "big": big, "slot": 0, "span": 0.0, "arrived": False}


def matrix_specs(rng: random.Random) -> list[tuple[str, tuple[int, int], Any, str, float]]:
    """(state, size, scroll token, theme, now), pruned from the full product."""
    scrolls = ["none", 0, "mid", "huge"]
    specs: list[tuple[Any, ...]] = []
    G = "gruvbox"
    small = [(40, 10), (80, 24), (110, 32)]
    # core: every size x state x scroll, two times, default theme
    core = [(s, z, sc, G, n) for s in OLD_STATES for z in SIZES for sc in scrolls for n in (0.0, 1.37)]
    rng.shuffle(core)
    specs += core
    # theme sweep
    sweep = [(s, z, sc, th, 0.55) for s in OLD_STATES for z in small for sc in ("none", "mid")
             for th in THEMES]
    rng.shuffle(sweep)
    specs += sweep
    # time sweep
    times = [(s, z, "none", G, n) for s in OLD_STATES for z in small for n in NOWS]
    rng.shuffle(times)
    specs += times
    # random sample of the rest of the full product
    full = list(itertools.product(OLD_STATES, SIZES, scrolls, THEMES, NOWS))
    rng.shuffle(full)
    specs += [f for f in full if f[1] != (200, 60)][:900]
    specs += [f for f in full if f[1] == (200, 60)][:40]

    caps = {(40, 10): 110, (50, 3): 80, (80, 24): 31, (110, 32): 13, (7, 2): 40, (200, 60): 4}
    used: collections.Counter[Any] = collections.Counter()
    seen: set[Any] = set()
    picked = []
    for sp in specs:
        anim = sp[0] not in ("read_only", "empty")
        k = (sp[0], sp[1], sp[2], sp[3], sp[4] if anim else None)
        if k in seen or used[sp[1]] >= caps[sp[1]]:
            continue
        seen.add(k)
        used[sp[1]] += 1
        picked.append(sp)
    return picked  # type: ignore[return-value]


def spark_specs() -> list[dict[str, Any]]:
    out = []
    now = 3.0
    for state in ("one", "topA", "big4000"):
        for size in ((80, 24), (40, 10)):
            for u in ((0.0, 0.4, 1.0, 1.7) if size == (40, 10) else (0.4, 1.0)):
                for big in (False, True):
                    tiers = [0, 9] if state != "one" else [0, 5]
                    if size == (80, 24) and state == "topA":
                        tiers = [9]
                    for tier in tiers:
                        out.append(dict(state=state, size=size, u=u, big=big, tier=tier,
                                        theme="gruvbox" if tier != 9 else "textual-light",
                                        scroll="none", seed=1000 + tier * 7 + int(u * 10)))
    # off-screen rack: the 4000-rack tier scrolled to the top, its newest rack is far below
    for u in (0.0, 0.4, 1.0):
        for big in (False, True):
            out.append(dict(state="big4000", size=(80, 24), u=u, big=big, tier=0, theme="gruvbox",
                            scroll=0, seed=77))
    out.append(dict(state="all10", size=(110, 32), u=0.4, big=True, tier=2, theme="nord",
                    scroll=0, seed=5, extra=[(7, 0.2, False)]))
    return out


# ------------------------------------------------------------------ crew, trucks, build-in

def fx_dict(kind: str, tier: int, now: float, u: float, life: float, **kw: Any) -> dict[str, Any]:
    """An Fx born so that its progress at `now` is u (u may lie outside 0..1)."""
    d = {"kind": kind, "seed": 4000 + tier * 13 + int(u * 100), "life": life,
         "born": now - u * life, "tier": tier, "big": False, "slot": 0, "span": 0.0,
         "arrived": False}
    d.update(kw)
    return d


def truck_fx(tier: int, now: float, age: float, span: float) -> dict[str, Any]:
    return fx_dict("truck", tier, now, 0.0, 2 * span + game.TRUCK_PARK_S, born=now - age,
                   span=span, arrived=age >= span)


def crew_specs(rng: random.Random) -> list[tuple[str, dict[str, Any], Any]]:
    """(tag, params, scroll token) for crew sprites, trucks, build-ins and chip_shown."""
    out: list[tuple[str, dict[str, Any], Any]] = []
    G = "gruvbox"

    def add(tag: str, state: str, size: tuple[int, int], sc: Any = "none", theme: str = G,
            now: float = 3.0, fx: list[dict[str, Any]] | None = None) -> None:
        out.append((tag, make_params(state, size, None, theme, now, fx), sc))

    # core: crew states x sizes x scroll x time (bob flips at multiples of 0.5 s)
    sizes = [(40, 10), (80, 24), (110, 32), (13, 6), (14, 6), (20, 8), (27, 12), (7, 2), (50, 3)]
    core = [(s, z, sc, n) for s in CREW_STATES for z in sizes for sc in ("none", 0, "mid")
            for n in (0.0, 0.55, 1.0, 1.37)]
    rng.shuffle(core)
    cap = {(40, 10): 30, (80, 24): 22, (110, 32): 8, (13, 6): 40, (14, 6): 40, (20, 8): 40,
           (27, 12): 40, (7, 2): 20, (50, 3): 30}
    used: collections.Counter[Any] = collections.Counter()
    for s, z, sc, n in core:
        if used[z] < cap[z]:
            used[z] += 1
            add("core", s, z, sc, now=n)
    # every theme: hat colours, grey crew, contrast clamps
    for th in THEMES:
        for s, z, n in (("hire_lv", (40, 10), 0.55), ("hire_lv2", (80, 24), 0.55),
                        ("crew_ro", (80, 24), 0.55), ("crew_ro", (40, 10), 1.0),
                        ("crew_small", (40, 10), 1.0)):
            add("theme", s, z, "none" if s == "crew_small" else 0, th, n)
    # reserve margin on/off at narrow and hall widths, scrolled and not
    widths = [12, 13, 14, 15, 16, 19, 20, 21, 22, 26, 27, 28, 29, *range(63, 81)]
    for w in widths:
        edge = w < 30 or w in (63, 64, 70, 71, 79, 80)
        for s, h in (("crew_small", 24), ("crew_small", 8), ("hire_lv", 24), ("nocrew_small", 24),
                     ("nocrew_small", 8), ("hired_half", 8)):
            if h == 8 and not edge:
                continue
            if s == "nocrew_small" and w not in (13, 14, 15, 63, 64, 70, 71, 77, 78, 79, 80):
                continue
            add("width", s, (w, h), "none", G, 1.0 if w % 2 else 0.0)
    # staff hired on several tiers/levels, every level 0..10 under one hat colour each
    for s in ("hire_lv", "hire_lv2", "hire_lv3"):
        for z in ((80, 24), (40, 10)):
            for sc in ("none", 0):
                for n in (0.0, 0.5):
                    add("hats", s, z, sc, G, n)
    # trucks at several progress points
    for span in (0.6, 1.4, 2.5):
        life = 2 * span + game.TRUCK_PARK_S
        ages = sorted({-0.1, 0.0, 0.07 * span, 0.3 * span, 0.7 * span, 0.99 * span, span,
                       span + 0.1, span + game.TRUCK_PARK_S - 1e-9, span + game.TRUCK_PARK_S,
                       span + game.TRUCK_PARK_S + 0.05 * span, span + game.TRUCK_PARK_S + 0.4 * span,
                       span + game.TRUCK_PARK_S + 0.8 * span, life - 1e-9, life})
        for age in ages:
            for tier, z, th, s in ((0, (80, 24), G, "crew_small"), (1, (40, 10), "textual-light", "crew_small"),
                                   (2, (110, 32), "nord", "hire_lv"), (0, (20, 8), G, "crew_lag"),
                                   (0, (50, 6), G, "nocrew_small"), (4, (80, 24), G, "crew_ro")):
                if span != 1.4 and (tier, z) not in ((0, (80, 24)), (1, (40, 10)), (0, (50, 6))):
                    continue
                if span != 1.4 and z == (80, 24):
                    z = (50, 6)
                add("truck", s, z, "none" if s != "hire_lv" else 0, th, 3.0,
                    [truck_fx(tier, 3.0, age, span)])
    for age in (0.2, 0.8, 1.4, 1.5, 1.9, 2.4):  # two trucks, one mirrored; truck + crew fx; truck + build
        add("truck2", "crew_small", (80, 24), fx=[truck_fx(0, 3.0, age, 1.0), truck_fx(1, 3.0, age + 0.7, 1.0)])
        add("truck2", "crew_small", (80, 24), fx=[truck_fx(0, 3.0, age, 1.0),
                                                 fx_dict("install", 0, 3.0, 0.3, game.INSTALL_S),
                                                 fx_dict("build", 0, 3.0, 0.5, game.BUILD_S, slot=1),
                                                 fx_dict("spark", 0, 3.0, 0.3, game.SPARK_LIFE_S, big=True, seed=5)])
    add("truck-off", "crew_scroll", (80, 10), 0, G, 3.0, [truck_fx(0, 3.0, 0.5, 1.0), truck_fx(2, 3.0, 0.5, 1.0)])
    add("truck-off", "crew_scroll", (80, 10), 1000000, G, 3.0, [truck_fx(0, 3.0, 0.5, 1.0), truck_fx(2, 3.0, 0.5, 1.0)])
    for tier in (3, 9):  # a truck for a tier that owns nothing
        add("truck-none", "crew_small", (80, 24), fx=[truck_fx(tier, 3.0, 0.5, 1.0)])
    # appear / train / install at several progress points
    for kind, life, us in (("appear", game.APPEAR_S, (0.0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0, 1.2)),
                           ("train", game.TRAIN_S, (0.0, 0.25, 0.5, 0.75, 1.0)),
                           ("install", game.INSTALL_S, (0.0, 0.125, 0.25, 0.375, 0.5, 0.75, 0.9, 1.0))):
        for u in us:
            for tier, s, z, th in ((0, "crew_small", (80, 24), G), (2, "hire_lv", (40, 10), "textual-light"),
                                   (9, "hire_lv2", (80, 24), "nord"), (1, "crew_ro", (40, 10), "solarized-light")):
                if tier == 9 and u not in (0.1, 0.5, 0.8):
                    continue
                if s == "hire_lv" and tier == 2:
                    sc = 0
                else:
                    sc = "none"
                add(kind, s, z, sc, th, 1.37, [fx_dict(kind, tier, 1.37, u, life)])
    add("fx-multi", "hire_lv", (80, 24), 0, G, 1.0, [fx_dict("train", 1, 1.0, 0.2, 0.6),
                                                     fx_dict("install", 1, 1.0, 0.1, 0.5),
                                                     fx_dict("appear", 3, 1.0, 0.1, 0.5)])
    add("fx-multi", "hire_lv", (80, 24), 0, G, 1.0, [fx_dict("install", 1, 1.0, 0.1, 0.5),
                                                     fx_dict("train", 1, 1.0, 0.2, 0.6)])
    add("fx-unhired", "crew_small", (80, 24), fx=[fx_dict("appear", 5, 3.0, 0.2, 0.5)])
    add("fx-noreserve", "hired_unowned", (80, 24), fx=[fx_dict("install", 1, 3.0, 0.2, 0.5)])
    # build-in at several progress values; slots in the first, later and wrapped rows
    for u in (0.0, 0.07, 0.14, 0.2, 0.3, 0.43, 0.5, 0.6, 0.72, 0.86, 0.95, 0.9999, 1.0, 1.3):
        for s, z, sl, tier in (("crew_small", (80, 24), 1, 0), ("hire_lv", (40, 10), 2, 1),
                               ("crew_small", (14, 6), 1, 1), ("nocrew_small", (80, 24), 0, 2),
                               ("crew_scroll", (80, 10), 11, 0), ("crew_crisis", (80, 24), 7, 0)):
            if z == (80, 10) and u not in (0.3, 0.72, 1.0):
                continue
            if z == (80, 24) and u not in (0.0, 0.14, 0.3, 0.5, 0.72, 0.95, 1.0):
                continue
            add("build", s, z, 0 if s == "crew_scroll" else "none", G, 1.37,
                [fx_dict("build", tier, 1.37, u, game.BUILD_S, slot=sl)])
    add("build-skip", "crew_small", (80, 24), fx=[fx_dict("build", 0, 3.0, 0.5, 0.4, slot=2),  # not owned yet
                                                 fx_dict("build", 0, 3.0, 0.5, 0.4, slot=50),
                                                 fx_dict("build", 4, 3.0, 0.5, 0.4, slot=0)])
    add("build-off", "crew_scroll", (80, 10), 0, G, 3.0, [fx_dict("build", 2, 3.0, 0.5, 0.4, slot=3)])
    add("build-many", "hire_lv", (110, 32), 0, G, 3.0,
        [fx_dict("build", t, 3.0, 0.1 + 0.07 * t, 0.4, slot=t % 3) for t in range(10)])
    add("layers", "crew_small", (80, 24), fx=[fx_dict("build", 0, 3.0, 0.5, 0.4, slot=1),
                                              truck_fx(0, 3.0, 1.0, 1.0),
                                              fx_dict("spark", 0, 3.0, 0.4, game.SPARK_LIFE_S, seed=9),
                                              fx_dict("install", 0, 3.0, 0.2, 0.5)])
    # truck x on an exact .5 tie (no crew margin: x = stop + 2.5 at age == span / 2), so
    # round-half-even vs half-away is pinned; binary-exact spans and ages
    for w in (14, 17, 20, 28, 35, 50, 63, 80):
        for span, age in ((1.0, 0.5), (2.0, 1.0), (0.5, 0.25), (2.5, 1.25), (1.5, 0.75)):
            add("tie", "nocrew_two", (w, 6), "none", G, 3.0, [truck_fx(0, 3.0, age, span)])
    # a truck parked over / leaving across the LAST rack column while a build-in runs on
    # that rack (trucks are drawn over builds), with and without the crew margin
    for n, sfx in ((3, ""), (6, ""), (3, "n")):
        for u in (0.3, 0.6, 0.9):
            for age in (1.1, 1.5):
                add("last-col", f"last{n}{sfx}", (n * 7 + 6, 6), "none", G, 3.0,
                    [fx_dict("build", 0, 3.0, u, game.BUILD_S, slot=n - 1), truck_fx(0, 3.0, age, 1.0)])
    # a fresh build-in under the spark burst of the same purchase (sparks, then builds)
    for n in (3, 6):
        for ub in (0.0, 0.15, 0.5):
            for us in (0.0, 0.05, 0.1):
                for big in (False, True):
                    add("spark-build", f"last{n}n", (n * 7, 6), "none", G, 3.0,
                        [fx_dict("build", 0, 3.0, ub, game.BUILD_S, slot=n - 1),
                         fx_dict("spark", 0, 3.0, us, game.SPARK_LIFE_S, big=big, seed=40 + n)])
    # chip_shown differing from chips (the pips lag), header still reads the real level
    for s in ("crew_lag", "crew_lag2"):
        for z in ((80, 24), (40, 10), (14, 6)):
            for th in (G, "textual-light"):
                add("lag", s, z, "none", th, 1.0 if z[0] == 80 else 0.0)
    # read-only crew: grey hats and skin, with and without effects and scroll
    for u in (0.2, 0.7):
        add("ro-fx", "crew_ro", (80, 24), fx=[fx_dict("install", 0, 3.0, u, 0.5), fx_dict("train", 3, 3.0, u, 0.6)])
    # animation off / background pane: crew does not bob
    for s in ("crew_small", "hire_lv"):
        for flag in ("anim_off", "background"):
            for n in (0.0, 0.55):
                p = make_params(s, (80, 24), None, G, n)
                p["anim_enabled"] = flag != "anim_off"
                p["foreground"] = flag != "background"
                out.append(("still", p, "none"))
    return out


# ------------------------------------------------------------------ units

def rgb_rand(rng: random.Random) -> list[int]:
    return [rng.randrange(256) for _ in range(3)]


def colour_units(rng: random.Random, tiers: list[list[int]], floors: list[list[int]]) -> list[Any]:
    rows: list[Any] = []
    t = tuple
    edge = [[0, 0, 0], [255, 255, 255], [128, 128, 128], [255, 0, 0], [0, 255, 0], [0, 0, 255]]

    def pick() -> list[int]:
        r = rng.random()
        return rng.choice(edge) if r < 0.1 else rgb_rand(rng)

    for _ in range(550):
        hue = rng.choice(tiers) if rng.random() < 0.5 else pick()
        floor = rng.choice(floors) if rng.random() < 0.5 else pick()
        step = rng.randrange(0, 5)
        rows.append(["pip_colour", [step, hue, floor], list(game.pip_colour(step, t(hue), t(floor)))])
    for _ in range(550):
        fg, bg = pick(), pick()
        mn = rng.choice([1.0, 3.0, 4.5, 7.0, 21.0, round(rng.uniform(1, 21), 3)])
        pref = rng.choice([None, [0, 0, 0], [255, 255, 255], pick()])
        res = game.ensure_contrast(t(fg), t(bg), mn, None if pref is None else t(pref))
        rows.append(["ensure_contrast", [fg, bg, mn, pref], list(res)])
    for _ in range(250):
        c = pick()
        rows.append(["lightness", [c], game.lightness(t(c))])
    for _ in range(250):
        a, b = pick(), pick()
        rows.append(["contrast", [a, b], game.contrast(t(a), t(b))])
    for _ in range(250):
        a, b = pick(), pick()
        tt = rng.choice([0.0, 1.0, 0.5, rng.random(), rng.random(), 0.25, 0.35, 0.6, 0.85])
        rows.append(["mix", [a, b, tt], list(game.mix(t(a), t(b), tt))])
    for _ in range(100):  # the inline expression Palette uses for tier colours
        h = rng.choice(game.TIER_HUES)
        light = rng.choice([0.62, 0.38])
        res = tuple(int(x * 255) for x in colorsys.hls_to_rgb(h / 360, light, game.TIER_SATURATION))
        rows.append(["hls", [h, light, game.TIER_SATURATION], list(res)])
    for _ in range(50):
        c = pick()
        rows.append(["lum", [c], game.lum(t(c))])
    assert len(rows) == 2000
    return rows


def pal_dump(p: Any) -> dict[str, Any]:
    f = lambda c: list(c)  # noqa: E731
    return {"bg": f(p.bg), "surface": f(p.surface), "fg": f(p.fg), "primary": f(p.primary),
            "success": f(p.success), "warning": f(p.warning), "error": f(p.error),
            "tiers": [f(c) for c in p.tiers], "muted": f(p.muted), "faint": f(p.faint),
            "frame": f(p.frame), "shadow": f(p.shadow), "led_on": f(p.led_on),
            "led_off": f(p.led_off), "alert_on": f(p.alert_on), "alert_off": f(p.alert_off),
            "chip_text": f(p.chip_text), "pip_floor": f(p.pip_floor)}


def synthetic_palettes(rng: random.Random) -> list[Any]:
    """Palette(v, dark) on made-up theme dicts: ANSI, transparent and junk values too."""
    keys = ["background", "surface", "foreground", "primary", "success", "warning", "error"]
    odd = ["ansi_red", "transparent", "rgba(10,20,30,0.5)", "nonsense", "", "#fff", "red"]
    out = []
    for i in range(40):
        v = {k: ("#%06x" % rng.randrange(1 << 24) if rng.random() < 0.8 else rng.choice(odd))
             for k in keys}
        dark = bool(i % 2)
        out.append({"v": v, "dark": dark, "palette": pal_dump(game.Palette(v, dark))})
    return out


def diff_cases(rng: random.Random) -> dict[str, Any]:
    """Random (old, new) row pairs with the spans of the real Hall.changed_spans."""
    table = [[" ", None, None], ["\u2580", "ff0000", "000000"], ["\u2580", "00ff00", "000000"],
             ["\u2580", "ff0000", "0000ff"], ["#", None, "000000"], [" ", None, "000000"]]
    cells = [(c, f, b) for c, f, b in table]
    out: list[Any] = []
    while len(out) < 700:
        n = rng.choice([1, 2, 3, 5, 8, 13, 24, 40])
        density = rng.choice([0.1, 0.25, 0.4, 0.6])
        old = [rng.choice(cells) for _ in range(n)]
        new = [rng.choice(cells) if rng.random() < density else c for c in old]
        if rng.random() < 0.12:  # width changes
            new = new[:rng.randrange(0, n + 1)] if rng.random() < 0.5 else new + [cells[1]] * 3
        if not old and not new:
            continue
        spans = Hall.changed_spans(old, new)
        ix = {c: i for i, c in enumerate(cells)}
        out.append({"old": [ix[c] for c in old], "new": [ix[c] for c in new],
                    "spans": [list(sp) for sp in spans]})
    return {"cells": table, "cases": out}


def header_label_cases() -> list[Any]:
    """name x count x level x room, room -3..69, with the real header_label."""
    names = ["A", game.TIERS[0][0].upper(), max((t[0] for t in game.TIERS), key=len).upper(),
             "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
    out = []
    for name in names:
        for count in (1, 10, 4000, 123456):
            for level in (0, 3, 20):
                for room in range(-3, 70):
                    out.append([name, count, level, room,
                                game.header_label(name, count, level, room)])
    return out


# ------------------------------------------------------------------ main

async def crosscheck(cases: list[dict[str, Any]]) -> None:
    """Two cases through test_anim.screen_cells (the compositor) == build_cells."""
    import types
    saved = (game.ANIM, game.clock, game.tmux_foreground)
    game.tmux_foreground = lambda: True
    for state, size, T in (("topB", (110, 32), 1000.0), ("big4000", (80, 24), 3.0)):
        game.clock = lambda T=T: T
        save = {"site_balance": [5000], "site_owned": [STATES[state]["owned"]],
                "site_chips": [STATES[state]["chips"]], "site_staff": [STATES[state]["staff"]],
                "sites": 0, "cur": 0, "fame": 0, "autopilot": False,
                "online": {"asked": True, "joined": False}}
        Path(os.environ["DC_SAVE"]).write_text(json.dumps(save))
        app = game.DataCenter()
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.1)
            app.foreground = True
            app.hall_scroll = 0 if state == "big4000" else None
            app.redraw()
            await pilot.pause(0.2)
            hall = app.query_one(game.Hall)
            hall._rows, hall._base_key, hall._strips = None, None, {}
            app._hall_sig = None
            app.now = T
            app.draw_hall()
            await pilot.pause(0.2)
            screen = test_anim.screen_cells(app)
            built = hall.build_cells()
            compared = 0
            for y, row in enumerate(built):
                for x, (ch, fg, bg) in enumerate(row):
                    sch, sfg, sbg = screen[y][x]
                    assert sch == ch, (state, y, x, sch, ch)
                    if fg is not None and bg is not None:
                        assert (sfg, sbg) == (fg, bg), (state, y, x, (sfg, sbg), (fg, bg))
                        compared += 1
            assert compared > 100, compared
            p = make_params(state, size, app.hall_scroll, app.theme, T)
            p["xcheck"] = "compositor"
            p["hall_w"], p["hall_h"] = hall.size.width, hall.size.height
            p["theme"] = app.theme
            rec = {"params": dict(p, animating=bool(app.animating), top_tier=app.top_tier()),
                   "palette": palette_of(app, app.theme), "layout": layout_of(hall.rack_layout()),
                   "special": None, "cells": [runs(r) for r in built]}
            cases.append(rec)
    game.ANIM, game.clock, game.tmux_foreground = saved


async def build() -> dict[str, Any]:
    rng = random.Random(20261118)
    game.ONLINE = False
    game.tmux_foreground = lambda: True
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    Path(os.environ["DC_SAVE"]).write_text("{}")
    with mock.patch.object(game.DataCenter, "set_interval", lambda self, *a, **k: None):
        app = game.DataCenter()
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause(0.1)
            hall = app.query_one(Hall)
            todo: list[dict[str, Any]] = []
            for state, size, sc, theme, now in matrix_specs(rng):
                p = make_params(state, size, None, theme, now)
                todo.append(("m", p, sc))  # type: ignore[arg-type]
            for sp in spark_specs():
                now = 3.0
                fx = [fx_spark(sp["tier"], sp["u"], sp["big"], now, sp["seed"])]
                for t2, u2, b2 in sp.get("extra", []):
                    fx.append(fx_spark(t2, u2, b2, now, 9))
                p = make_params(sp["state"], sp["size"], None, sp["theme"], now, fx)
                todo.append(("s", p, sp["scroll"]))  # type: ignore[arg-type]
            # widths that are multiples of 7 (Layout (w-1)/7 vs w/7), scrolled and not
            for state in ("one", "all10", "big4000", "chips"):
                for size in ((14, 6), (21, 8), (28, 10), (140, 30)):
                    for sc in ("none", 0):
                        p = make_params(state, size, None, "gruvbox", 0.0)
                        todo.append(("w7", p, sc))  # type: ignore[arg-type]
            # a few non-animating variants (DC_ANIM off / background pane)
            for state in ("one", "topA", "all10", "chips"):
                for flag in ("anim_off", "background"):
                    p = make_params(state, (80, 24), None, "gruvbox", 0.55)
                    p["anim_enabled"] = flag != "anim_off"
                    p["foreground"] = flag != "background"
                    todo.append(("a", p, "none"))  # type: ignore[arg-type]
            # the crew/truck/build-in matrix needs edf443e; e66836d has none of it
            for tag, p, sc in (crew_specs(random.Random(20261121)) if hasattr(game, "CREW_W") else []):
                todo.append((tag, p, sc))
            todo.sort(key=lambda it: it[1]["theme"])  # theme changes are costly
            for _, p, sc in todo:
                if sc == "none":
                    p["scroll"] = None
                elif sc == "mid":
                    p["scroll"] = mid_scroll(app, hall, p)
                elif sc == "huge":
                    p["scroll"] = 10**6
                else:
                    p["scroll"] = sc
                k = key_of(dict(p, animating=p["anim_enabled"] and p["foreground"]
                                and not p["read_only"]))
                if k in seen:
                    continue
                seen.add(k)
                cases.append(record(app, hall, p))
                if app.theme != p["theme"]:
                    await pilot.pause(0.02)
            themes = {}
            for name in sorted(app.available_themes):
                app.theme = name
                app._pal = None
                themes[name] = {"dark": bool(app.get_theme(name).dark), "palette": pal_dump(app.pal)}
            app.theme = "gruvbox"
    await crosscheck(cases)
    tiers = [c for t in themes.values() for c in t["palette"]["tiers"]]
    floors = [t["palette"]["pip_floor"] for t in themes.values()]
    commit = None
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    cases_sorted = cases
    return {"format": "cells[case][row] = runs [text, fg, bg]; one cell per char of text; "
                      "colours 'rrggbb' or null. layout.blocks rows = [kind,tier,first,count,"
                      "line0,height,row]; blocks is null above 300 blocks (see blocks_visible, blocks_sha256 of json.dumps(blocks)). cells null + error set = build_cells raised in the committed game (empty grid). layout.reserve/grid_w/crew_x: the crew margin. params.chip_shown: per tier the level the pips show or null. xcheck cases carry the real Hall size as hall_w/hall_h.",
            "source_commit": commit, "cell_w": game.CELL_W, "cell_h": game.CELL_H,
            "cases": cases_sorted, "colour_units": colour_units(random.Random(7), tiers, floors),
            "palette_units": {"themes": themes, "synthetic": synthetic_palettes(random.Random(11))},
            "diff_cases": diff_cases(random.Random(13)), "header_label": header_label_cases()}


def main() -> None:
    if os.environ.get("DC_GOLDEN_TRACE"):
        sys.setprofile(tracer)
    data = asyncio.run(build())
    sys.setprofile(None)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_gz(OUT, json.dumps(data, separators=(",", ":")) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, {len(data['cases'])} cases, "
          f"game={game.__file__})")
    if TRACED:
        print("GAME_FUNCS:\n" + "\n".join(sorted(TRACED)), file=sys.stderr)


if __name__ == "__main__":
    main()
