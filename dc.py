#!/usr/bin/env python3
"""My Data Center - pixel TUI prototype. Keys 1-6 buy, q quits.
Colours follow the active Textual theme (ctrl+p -> Change theme)."""
import colorsys
import json
import math
import os
import time
from pathlib import Path
from typing import Any, ClassVar, cast

from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import RichLog, Static

RGB = tuple[int, int, int]

# name, base cost, income/sec
TIERS: list[tuple[str, int, int]] = [
    ("Budget VPS", 100, 2),
    ("Compute Node", 600, 14),
    ("GPU Cluster", 3000, 80),
    ("AI Datacenter", 15000, 450),
    ("Quantum Farm", 80000, 2500),
    ("Orbital Cloud", 400000, 15000),
]
GROWTH = 1.15

# Sprite legend: k frame, c tier colour, h highlight, d dark, w pale window/fan,
# A/B blinking LEDs, . empty. One distinct silhouette per tier.
SPRITES: list[list[str]] = [
    # Budget VPS: a small desktop box
    ["......", "......", "......", "kkkkkk", "kcccAk", "kkkkkk"],
    # Compute Node: two stacked blades
    ["......", "kkkkkk", "khccAk", "kkkkkk", "khccBk", "kkkkkk"],
    # GPU Cluster: tall rack with cooling fans
    ["kkkkkk", "kwcwAk", "kddddk", "kwcwBk", "kddddk", "kkkkkk"],
    # AI Datacenter: office-style building with windows
    ["..hh..", "cccccc", "cwcwcc", "cccccc", "cwcAwc", "dddddd"],
    # Quantum Farm: glowing crystal
    ["..hh..", ".hwwh.", "chwwhc", ".cwwc.", "..cc..", "..dd.."],
    # Orbital Cloud: satellite with solar panels
    ["..hA..", "cckkcc", "cchhcc", "cckkcc", "..kk..", "..dd.."],
]
CELL_W, CELL_H = 7, 8  # 6x6 rack, one gap column, shadow row at the bottom


DEFAULT_THEME = "gruvbox"
OFFLINE_RATE = 0.75  # share of normal income earned while the game is closed


def fmt_duration(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m}m" if h else f"{m}m"


def save_path() -> Path:
    if os.environ.get("DC_SAVE"):  # override, handy for tests
        return Path(os.environ["DC_SAVE"])
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "dc-tui" / "save.json"


def load_save() -> dict[str, Any]:
    try:
        data = json.loads(save_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def fmt(n: float) -> str:
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= limit:
            return f"{n / limit:.2f}{suffix}"
    return f"{int(n):,}"


def cost_of(tier: int, owned: int) -> int:
    return int(TIERS[tier][1] * GROWTH**owned)


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def rgb(c: RGB) -> str:
    return "rgb(%d,%d,%d)" % c


def lum(c: RGB) -> float:
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


FALLBACK_DARK: dict[str, RGB] = {
    "background": (26, 27, 38), "surface": (36, 40, 59), "foreground": (192, 202, 245),
    "primary": (122, 162, 247), "success": (158, 206, 106),
    "warning": (224, 175, 104), "error": (247, 118, 142),
}
FALLBACK_LIGHT: dict[str, RGB] = {
    "background": (233, 233, 237), "surface": (222, 222, 228), "foreground": (52, 59, 88),
    "primary": (52, 84, 138), "success": (72, 94, 48),
    "warning": (143, 94, 21), "error": (140, 67, 81),
}


class Palette:
    """Every colour the game draws with, derived from the active theme."""

    def __init__(self, v: dict[str, str], dark: bool) -> None:
        fallback = FALLBACK_DARK if dark else FALLBACK_LIGHT

        def get(key: str) -> RGB:
            # ANSI / transparent theme values have no real RGB: use a fixed palette
            try:
                c = Color.parse(v[key])
            except Exception:
                return fallback[key]
            if c.ansi is not None or c.a < 1:
                return fallback[key]
            return (c.r, c.g, c.b)

        self.bg, self.surface, self.fg = get("background"), get("surface"), get("foreground")

        def visible(c: RGB) -> RGB:  # keep accents readable on any theme
            for _ in range(6):
                if abs(lum(c) - lum(self.surface)) >= 0.3:
                    break
                c = mix(c, self.fg, 0.25)
            return c

        primary, success = get("primary"), get("success")
        warning, error = get("warning"), get("error")
        self.primary, self.success = visible(primary), visible(success)
        self.warning, self.error = visible(warning), visible(error)
        # Six evenly spaced hues starting at the theme's primary: always distinct,
        # with saturation/lightness kept in a readable band for the theme.
        hue, light, sat = colorsys.rgb_to_hls(*(x / 255 for x in primary))
        sat = min(max(sat, 0.5), 0.85)
        light = (min(max(light, 0.58), 0.72) if lum(self.surface) < 0.5
                 else min(max(light, 0.28), 0.42))
        self.tiers = [
            visible(cast(RGB, tuple(int(x * 255) for x in
                                    colorsys.hls_to_rgb((hue + i / 6) % 1, light, sat))))
            for i in range(len(TIERS))
        ]
        self.muted = mix(self.fg, self.surface, 0.45)
        self.faint = mix(self.fg, self.surface, 0.75)
        self.frame = mix(self.surface, self.fg, 0.2)
        self.shadow = mix(self.bg, (0, 0, 0), 0.5)
        self.led_on = self.success
        self.led_off = mix(self.success, self.bg, 0.8)
        self.chip_text = self.bg


class Hall(Widget):
    """Pixel view of every rack you own, drawn with half-block characters."""

    @property
    def game(self) -> "DataCenter":
        return cast("DataCenter", self.app)

    def render(self) -> Text:
        game, p = self.game, self.game.pal
        racks = [t for t, n in enumerate(game.owned) for _ in range(n)]
        w, h = self.size.width, self.size.height
        if not racks:
            return Text("\n  Empty hall. Press 1 to buy your first server.",
                        style=rgb(p.muted))
        cols, rows = max(1, w // CELL_W), max(1, h // (CELL_H // 2))
        shown = racks[-(cols * rows):]
        gw, gh = cols * CELL_W, rows * CELL_H
        grid: list[list[RGB]] = [
            [mix(p.bg, p.surface, y / max(1, gh - 1))] * gw for y in range(gh)
        ]
        for i, tier in enumerate(shown):
            ox, oy = (i % cols) * CELL_W, (i // cols) * CELL_H + 1
            colour = p.tiers[tier]
            palette: dict[str, RGB] = {
                "k": p.frame,
                "c": colour,
                "h": mix(colour, (255, 255, 255), 0.45),
                "d": mix(colour, (0, 0, 0), 0.55),
                "w": mix(colour, (255, 255, 255), 0.8),
            }
            for x in range(1, 6):  # soft floor shadow
                grid[oy + 6][ox + x] = p.shadow
            for y, row in enumerate(SPRITES[tier]):
                for x, ch in enumerate(row):
                    if ch == ".":
                        continue
                    if ch in "AB":
                        on = (game.phase + i + y * 2 + x) % 3 == 0
                        grid[oy + y][ox + x] = p.led_on if on else p.led_off
                    else:
                        grid[oy + y][ox + x] = palette[ch]
        out = Text(no_wrap=True)
        for y in range(0, gh, 2):
            for x in range(gw):
                out.append("▀", Style(color=rgb(grid[y][x]),
                                      bgcolor=rgb(grid[y + 1][x])))
            out.append("\n")
        return out


class DataCenter(App):
    TITLE = "MY DATA CENTER"
    CSS = """
    Screen { background: $background; color: $foreground; }
    #top { height: 2; padding: 1 2 0 2; }
    #title { width: 1fr; text-style: bold; color: $primary; }
    #cash { width: auto; text-style: bold; color: $success; }
    #main { height: 1fr; padding: 0 1; }
    #left { width: 1fr; }
    #side { width: 46; }
    .card {
        background: $surface; border: round $primary 50%;
        border-title-color: $primary; border-title-style: bold; padding: 0 1;
    }
    #hall { height: 1fr; background: $background; padding: 0; }
    #log { height: 6; scrollbar-size-vertical: 1; }
    #stats { height: 5; }
    #shop { height: 1fr; }
    #hint { height: 1; color: $text-muted; padding: 0 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(str(i + 1), f"buy({i})", t[0]) for i, t in enumerate(TIERS)),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        data = load_save()
        balance = data.get("balance")
        self.balance = balance if type(balance) is int and balance >= 0 else 500
        self.owned = [0] * len(TIERS)
        raw = data.get("owned")
        if isinstance(raw, list):
            for i, n in enumerate(raw[:len(TIERS)]):
                if type(n) is int and n >= 0:
                    self.owned[i] = n
        theme = data.get("theme")
        self.saved_theme = theme if isinstance(theme, str) else DEFAULT_THEME
        # Offline earnings: OFFLINE_RATE of income for the time since the last save
        self.away = (0.0, 0)
        saved_at = data.get("saved_at")
        if isinstance(saved_at, (int, float)) and not isinstance(saved_at, bool):
            try:  # huge ints overflow float conversion; treat those as "no data"
                if math.isfinite(saved_at) and saved_at > 0:
                    elapsed = max(0.0, time.time() - saved_at)
                    earned = int(elapsed * self.income * OFFLINE_RATE)
                    if earned > 0:
                        self.balance += earned
                        self.away = (elapsed, earned)
            except OverflowError:
                pass
        self.phase = 0
        self._pal: Palette | None = None

    def save(self) -> None:
        path = save_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(
                {"balance": self.balance, "owned": self.owned, "theme": self.theme,
                 "saved_at": time.time()}))
            os.replace(tmp, path)
        except OSError:
            pass  # never crash the game over a failed save

    async def action_quit(self) -> None:
        self.save()
        self.exit()

    @property
    def pal(self) -> Palette:
        if self._pal is None:
            # Read the named theme directly: theme_variables lags behind a fresh
            # `self.theme = ...` assignment during startup.
            theme = self.get_theme(self.theme)
            if theme is None:
                self._pal = Palette(self.theme_variables, self.current_theme.dark)
            else:
                self._pal = Palette(theme.to_color_system().generate(), theme.dark)
        return self._pal

    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static("◆ MY DATA CENTER", id="title")
            yield Static(id="cash")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Hall(id="hall", classes="card")
                yield RichLog(id="log", classes="card", markup=False)
            with Vertical(id="side"):
                yield Static(id="stats", classes="card")
                yield Static(id="shop", classes="card")
        yield Static("1-6  buy server    ctrl+p  change theme    q  quit", id="hint")

    def on_mount(self) -> None:
        self.query_one("#hall").border_title = "DATA HALL"
        self.query_one("#stats").border_title = "OVERVIEW"
        self.query_one("#shop").border_title = "MARKETPLACE"
        self.query_one("#log").border_title = "ACTIVITY"
        self.theme = (self.saved_theme if self.saved_theme in self.available_themes
                      else DEFAULT_THEME)
        self._pal = None  # rebuild colours for the theme we just applied
        self.theme_changed_signal.subscribe(self, self.on_theme_changed)
        log = self.query_one(RichLog)
        log.write("Welcome. Buy servers with keys 1-6.")
        if self.away[1] > 0:
            log.write(Text(
                f"Welcome back! Away {fmt_duration(self.away[0])}, "
                f"earned ${fmt(self.away[1])} ({OFFLINE_RATE:.0%} offline rate)",
                style=rgb(self.pal.warning)))
        self.set_interval(1.0, self.tick)
        self.set_interval(0.4, self.blink)
        self.redraw()

    def on_theme_changed(self, _theme: object) -> None:
        self._pal = None
        self.redraw()
        self.save()

    @property
    def income(self) -> int:
        return sum(n * t[2] for n, t in zip(self.owned, TIERS))

    def tick(self) -> None:
        self.balance += self.income
        self.redraw()
        self.save()

    def blink(self) -> None:
        self.phase += 1
        self.query_one(Hall).refresh()

    def action_buy(self, tier: int) -> None:
        p = self.pal
        log, cost = self.query_one(RichLog), cost_of(tier, self.owned[tier])
        if self.balance >= cost:
            self.balance -= cost
            self.owned[tier] += 1
            log.write(Text(f"+ {TIERS[tier][0]}  -${fmt(cost)}", style=rgb(p.success)))
        else:
            log.write(Text(f"! need ${fmt(cost)} for {TIERS[tier][0]}", style=rgb(p.error)))
        self.redraw()
        self.save()

    def redraw(self) -> None:
        p = self.pal
        self.query_one("#cash", Static).update(
            Text.assemble(("$ ", rgb(p.muted)), fmt(self.balance)))
        stats = Text()
        stats.append("Income  ", rgb(p.muted))
        stats.append(f"${fmt(self.income)}/s\n", f"bold {rgb(p.warning)}")
        stats.append("Racks   ", rgb(p.muted))
        stats.append(f"{sum(self.owned)}\n", f"bold {rgb(p.primary)}")
        stats.append("Fleet   ", rgb(p.muted))
        for n, colour in zip(self.owned, p.tiers):
            stats.append("■ ", rgb(colour) if n else rgb(p.faint))
        self.query_one("#stats", Static).update(stats)
        shop = Text()
        for i, (name, _, inc) in enumerate(TIERS):
            cost = cost_of(i, self.owned[i])
            ok = self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            shop.append(f" {i + 1} ", f"bold {rgb(p.chip_text)} on {accent}")
            shop.append(f"  {name}", f"bold {accent}" if ok else rgb(p.muted))
            badge = f"x{self.owned[i]}"
            shop.append(" " * max(1, 31 - len(name) - len(badge)))
            shop.append(badge + "\n", rgb(p.fg) if self.owned[i] else rgb(p.faint))
            shop.append("     ")
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            shop.append(f"  ·  +${fmt(inc)}/s\n", rgb(p.muted))
        self.query_one("#shop", Static).update(shop)
        self.query_one("#hall").border_title = f"DATA HALL · {sum(self.owned)} racks"
        self.query_one(Hall).refresh()


if __name__ == "__main__":
    DataCenter().run(mouse=False)  # keyboard-only: don't grab the mouse from tmux
