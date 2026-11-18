#!/usr/bin/env python3
"""Write rust/core/tests/data/render_golden.json.gz: what the REAL committed Hall draws.

The game is imported from a root given as argv[1] or $DC_GAME_ROOT (default
/mnt/bigvolume/dc-e66, a worktree of the committed code) so the golden never reflects
uncommitted edits. Headless Textual app, DC_ONLINE=0, temp DC_SAVE, timers patched out.
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
import hashlib
import itertools
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

HERE = Path(__file__).resolve().parent.parent
argv = sys.argv[1:]
OUT = HERE / "rust/core/tests/data/render_golden.json.gz"
if "--out" in argv:
    i = argv.index("--out")
    OUT = Path(argv[i + 1])
    del argv[i:i + 2]
args = [a for a in argv if not a.startswith("--")]
ROOT = Path(args[0] if args else os.environ.get("DC_GAME_ROOT", "/mnt/bigvolume/dc-e66")).resolve()
os.environ["DC_ONLINE"] = "0"
os.environ["DC_SAVE"] = str(Path(tempfile.mkdtemp()) / "save.json")
for _v in ("TMUX", "TMUX_PANE"):
    os.environ.pop(_v, None)
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT))

from textual.geometry import Size  # noqa: E402
from data_center_tui import game  # noqa: E402

assert Path(game.__file__).resolve().is_relative_to(ROOT), game.__file__
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
            "max_start": lay.max_start}


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
    app.fx = [game.Fx(**f) for f in p["fx"]]
    app.foreground = p["foreground"]
    app.now = p["now"]
    game.ANIM = p["anim_enabled"]
    if app.theme != p["theme"]:
        app.theme = p["theme"]
    app._pal = None  # a fresh palette every case; the golden is the uncached truth
    hall._base_key, hall._blocks_owned, hall._blocks = None, (), {}


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
            "tier": tier, "big": big}


def matrix_specs(rng: random.Random) -> list[tuple[str, tuple[int, int], Any, str, float]]:
    """(state, size, scroll token, theme, now), pruned from the full product."""
    scrolls = ["none", 0, "mid", "huge"]
    specs: list[tuple[Any, ...]] = []
    G = "gruvbox"
    small = [(40, 10), (80, 24), (110, 32)]
    # core: every size x state x scroll, two times, default theme
    core = [(s, z, sc, G, n) for s in STATES for z in SIZES for sc in scrolls for n in (0.0, 1.37)]
    rng.shuffle(core)
    specs += core
    # theme sweep
    sweep = [(s, z, sc, th, 0.55) for s in STATES for z in small for sc in ("none", "mid")
             for th in THEMES]
    rng.shuffle(sweep)
    specs += sweep
    # time sweep
    times = [(s, z, "none", G, n) for s in STATES for z in small for n in NOWS]
    rng.shuffle(times)
    specs += times
    # random sample of the rest of the full product
    full = list(itertools.product(STATES, SIZES, scrolls, THEMES, NOWS))
    rng.shuffle(full)
    specs += [f for f in full if f[1] != (200, 60)][:900]
    specs += [f for f in full if f[1] == (200, 60)][:40]
    caps = {(40, 10): 240, (50, 3): 200, (80, 24): 110, (110, 32): 90, (7, 2): 100, (200, 60): 14}
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
            for u in (0.0, 0.4, 1.0, 1.7):
                for big in (False, True):
                    tiers = [0, 9] if state != "one" else [0, 5]
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
                      "line0,height,row]; blocks is null above 300 blocks (see blocks_visible, blocks_sha256 of json.dumps(blocks)). cells null + error set = build_cells raised in the committed game (empty grid). Layout has no 'reserve' field in this commit.",
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
