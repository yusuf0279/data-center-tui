#!/usr/bin/env python3
"""My Data Center - pixel TUI idle tycoon.
Colours follow the active Textual theme (ctrl+p -> Change theme)."""
import colorsys
import json
import math
import os
import random
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

# ---------------------------------------------------------------- game data

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
MAX_OWNED = 4000  # keeps 1.15**n inside float range

# Chip upgrades: three levels per tier, each level doubles that tier's income.
CHIPS: list[list[str]] = [
    ["GT 1030 (technically a GPU)", "RX 6400 (low-profile hopes)", "Integrated Graphics Ultra"],
    ["Ryzen 9 Zen Garden", "Threadripper Pro Max Ultra", "EPYC Epic Failover"],
    ["RTX 4090 Ti Super Scalper Ed", "RTX 5090 (Paper Launch)", "Jensen's Leather Jacket"],
    ["H100 (kidney sold separate)", "B200 (melts connector)", "GB200 (needs a power plant)"],
    ["MI300X (X is for eXpensive)", "MI325X-ception", "Radeon Schrödinger Pro"],
    ["Rubin Ultra (launch TBD)", "Zen 9 Space Edition", "DGX Moonbase One"],
]
CHIP_COST_MULT = (20, 200, 2000)  # x the tier's base cost, for levels 1..3
CHIP_BOOST = 2
MAX_CHIP = 3

# On-call crew: name, hire cost, tagline, what they handle
STAFF: list[tuple[str, int, str, str]] = [
    ("Vibecoder", 5_000, "ships it without reading the diff", "minor incidents"),
    ("Prompt Engineer", 60_000, "negotiates with the model for you", "outages and below"),
    ("Forward Deployed Engineer", 750_000, "lives on-site, expenses everything", "everything"),
]
STAFF_TRAIN_MULT = (3, 9, 27)  # x hire cost, for levels 1..3
MAX_STAFF = 3
BASE_RESPONSE = 10.0  # seconds to fix a crisis at level 0
RESPONSE_DECAY = 0.6  # response time multiplier per level

# Crises: severity -> titles. Income multiplier while one is active.
CRISES: dict[int, list[str]] = {
    1: ["CI is stuck on a flaky test", "Janitor unplugged a rack to vacuum",
        "Someone pasted the API key into Slack"],
    2: ["Power outage: the grid is down", "Cooling failed: the AC is a fan and a prayer",
        "Cloud bill spiked 40x overnight"],
    3: ["GPU shortage: scalpers bought every H100", "Intern force-pushed to main on a Friday",
        "Solar flare fried the Orbital Cloud"],
}
CRISIS_FACTOR = {1: 0.5, 2: 0.25, 3: 0.0}
CRISIS_WEIGHT = {1: 5, 2: 3, 3: 2}
CRISIS_MEAN = 120  # average seconds between crises
CRISIS_MIN_INCOME = 10
FIX_QUIPS = [
    "by turning it off and on again", "with one prompt and zero tests",
    "by rewriting it in Rust", "by blaming the intern",
    "with a hotfix straight to prod", "by asking the model nicely",
]

DEFAULT_THEME = "gruvbox"
OFFLINE_RATE = 0.75  # share of normal income earned while the game is closed
ROW_W = 40  # inner width of the side cards
LED_PERIOD = 2  # ticks (seconds) per LED step; every step repaints the hall

# Sprite legend: k frame, c tier colour, h highlight, d dark, w pale window/fan,
# A/B blinking LEDs, . empty. One distinct silhouette per tier.
SPRITES: list[list[str]] = [
    ["......", "......", "......", "kkkkkk", "kcccAk", "kkkkkk"],  # desktop box
    ["......", "kkkkkk", "khccAk", "kkkkkk", "khccBk", "kkkkkk"],  # two blades
    ["kkkkkk", "kwcwAk", "kddddk", "kwcwBk", "kddddk", "kkkkkk"],  # fan rack
    ["..hh..", "cccccc", "cwcwcc", "cccccc", "cwcAwc", "dddddd"],  # building
    ["..hh..", ".hwwh.", "chwwhc", ".cwwc.", "..cc..", "..dd.."],  # crystal
    ["..hA..", "cckkcc", "cchhcc", "cckkcc", "..kk..", "..dd.."],  # satellite
]
CELL_W, CELL_H = 7, 8  # 6x6 sprite, one gap column, shadow row at the bottom


# ------------------------------------------------------------------ helpers

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


def clean_levels(raw: Any, n: int, lo: int, hi: int, default: int) -> list[int]:
    """A list of n ints in [lo, hi]; anything invalid falls back to default."""
    out = [default] * n
    if isinstance(raw, list):
        for i, v in enumerate(raw[:n]):
            if type(v) is int and lo <= v <= hi:
                out[i] = v
    return out


def fmt(n: float) -> str:
    for limit, suffix in ((1e15, "Qa"), (1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= limit:
            return f"{n / limit:.2f}{suffix}"
    return f"{int(n):,}"


def fmt_duration(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m}m" if h else f"{m}m"


def cost_of(tier: int, owned: int) -> int:
    return int(TIERS[tier][1] * GROWTH**owned)


def chip_cost(tier: int, level: int) -> int:
    return TIERS[tier][1] * CHIP_COST_MULT[level]


def staff_cost(role: int, level: int) -> int:
    """Cost to hire (level -1) or to train from `level` to level+1."""
    return STAFF[role][1] * (1 if level < 0 else STAFF_TRAIN_MULT[level])


def response_time(level: int) -> float:
    return BASE_RESPONSE * RESPONSE_DECAY**level


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t),
            int(a[2] + (b[2] - a[2]) * t))


def rgb(c: RGB) -> str:
    return "rgb(%d,%d,%d)" % c


def lum(c: RGB) -> float:
    return (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255


# ------------------------------------------------------------------ palette

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
        self.alert_on = self.error
        self.alert_off = mix(self.error, self.bg, 0.8)
        self.chip_text = self.bg


# --------------------------------------------------------------------- hall

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
        led_on = p.alert_on if game.crisis else p.led_on
        led_off = p.alert_off if game.crisis else p.led_off
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
                        on = (game.phase // LED_PERIOD + i + y * 2 + x) % 3 == 0
                        grid[oy + y][ox + x] = led_on if on else led_off
                    else:
                        grid[oy + y][ox + x] = palette[ch]
        # Merge runs of identical pixels into single segments: far fewer bytes
        # per frame, which keeps a background tmux pane quiet.
        out = Text(no_wrap=True)
        for y in range(0, gh, 2):
            run_key: tuple[RGB, RGB] | None = None
            run_len = 0
            for x in range(gw):
                key = (grid[y][x], grid[y + 1][x])
                if key == run_key:
                    run_len += 1
                    continue
                if run_key is not None:
                    out.append("▀" * run_len, Style(color=rgb(run_key[0]),
                                                    bgcolor=rgb(run_key[1])))
                run_key, run_len = key, 1
            if run_key is not None:
                out.append("▀" * run_len, Style(color=rgb(run_key[0]),
                                                bgcolor=rgb(run_key[1])))
            out.append("\n")
        return out


# ---------------------------------------------------------------------- app

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
    #stats { height: 6; }
    #shop { height: 1fr; }
    #alert {
        height: 1; background: $error; color: $background;
        text-style: bold; padding: 0 2; display: none;
    }
    #hint { height: 1; color: $text-muted; padding: 0 2; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(str(i + 1), f"pick({i})", "Pick", show=False) for i in range(6)),
        Binding("s", "view('servers')", "Servers"),
        Binding("c", "view('chips')", "Chips"),
        Binding("h", "view('staff')", "Staff"),
        Binding("f", "fix", "Fix"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        data = load_save()
        balance = data.get("balance")
        self.balance = balance if type(balance) is int and 0 <= balance < 10**100 else 500
        self.owned = clean_levels(data.get("owned"), len(TIERS), 0, MAX_OWNED, 0)
        self.chips = clean_levels(data.get("chips"), len(TIERS), 0, MAX_CHIP, 0)
        self.staff = clean_levels(data.get("staff"), len(STAFF), -1, MAX_STAFF, -1)
        theme = data.get("theme")
        self.saved_theme = theme if isinstance(theme, str) else DEFAULT_THEME
        self.side = "servers"
        self.crisis: dict[str, Any] | None = None
        self.rng = random.Random()
        self.phase = 0
        self._pal: Palette | None = None
        self._last: dict[str, Text] = {}
        self._titles: dict[str, str] = {}
        self._hall_sig: tuple[Any, ...] | None = None
        # Offline earnings: OFFLINE_RATE of income for the time since the last save
        self.away = (0.0, 0)
        saved_at = data.get("saved_at")
        if isinstance(saved_at, (int, float)) and not isinstance(saved_at, bool):
            try:  # huge ints overflow float conversion; treat those as "no data"
                if math.isfinite(saved_at) and saved_at > 0:
                    elapsed = max(0.0, time.time() - saved_at)
                    earned = int(elapsed * self.base_income * OFFLINE_RATE)
                    if earned > 0:
                        self.balance += earned
                        self.away = (elapsed, earned)
            except OverflowError:
                pass

    # -- persistence -------------------------------------------------------

    def save(self) -> None:
        path = save_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "balance": self.balance, "owned": self.owned, "chips": self.chips,
                "staff": self.staff, "theme": self.theme, "saved_at": time.time(),
            }))
            os.replace(tmp, path)
        except OSError:
            pass  # never crash the game over a failed save

    async def action_quit(self) -> None:
        self.save()
        self.exit()

    # -- derived state -----------------------------------------------------

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

    @property
    def base_income(self) -> int:
        return sum(n * t[2] * CHIP_BOOST**c
                   for n, t, c in zip(self.owned, TIERS, self.chips))

    @property
    def income(self) -> int:
        factor = CRISIS_FACTOR[self.crisis["sev"]] if self.crisis else 1.0
        return int(self.base_income * factor)

    # -- layout ------------------------------------------------------------

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
        yield Static(id="alert")
        yield Static("1-6 pick  s servers  c chips  h staff  f fix  ctrl+p theme  q quit",
                     id="hint")

    def on_mount(self) -> None:
        self.query_one("#hall").border_title = "DATA HALL"
        self.query_one("#stats").border_title = "OVERVIEW"
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
        self.set_interval(1.0, self.tick)  # one frame per second keeps tmux calm
        self.redraw()

    def on_theme_changed(self, _theme: object) -> None:
        self._pal = None
        self.redraw()
        self.save()

    # -- game loop ---------------------------------------------------------

    def tick(self) -> None:
        self.balance += self.income
        self.phase += 1
        self.update_crisis()
        self.redraw()
        self.save()

    def say(self, text: str, colour: RGB) -> None:
        self.query_one(RichLog).write(Text(text, style=rgb(colour)))

    # -- crises ------------------------------------------------------------

    def fixer_for(self, sev: int) -> int | None:
        """Cheapest hired role that can handle this severity."""
        for role in range(sev - 1, len(STAFF)):
            if self.staff[role] >= 0:
                return role
        return None

    def update_crisis(self) -> None:
        c = self.crisis
        if c is not None:
            if c["fixer"] is None:  # someone may have been hired since it started
                c["fixer"] = self.fixer_for(c["sev"])
                if c["fixer"] is not None:
                    c["eta"] = math.ceil(response_time(self.staff[c["fixer"]]))
            if c["fixer"] is not None:
                c["eta"] -= 1
                if c["eta"] <= 0:
                    self.resolve(c["fixer"])
            return
        if (self.base_income >= CRISIS_MIN_INCOME
                and self.rng.random() < 1 / CRISIS_MEAN):
            self.spawn_crisis()

    def spawn_crisis(self) -> None:
        sevs = [1]
        if sum(self.owned) >= 5:
            sevs.append(2)
        if self.base_income >= 200:
            sevs.append(3)
        sev = self.rng.choices(sevs, [CRISIS_WEIGHT[s] for s in sevs])[0]
        title = self.rng.choice(CRISES[sev])
        fixer = self.fixer_for(sev)
        eta = math.ceil(response_time(self.staff[fixer])) if fixer is not None else None
        self.crisis = {"title": title, "sev": sev, "fixer": fixer, "eta": eta}
        cut = round((1 - CRISIS_FACTOR[sev]) * 100)
        self.say(f"! {title} (income -{cut}%)", self.pal.error)

    def resolve(self, fixer: int | None) -> None:
        if self.crisis is None:
            return
        title = self.crisis["title"]
        self.crisis = None
        who = "You" if fixer is None else STAFF[fixer][0]
        self.say(f"✓ {who} fixed '{title}' {self.rng.choice(FIX_QUIPS)}", self.pal.success)

    def action_fix(self) -> None:
        if self.crisis is None:
            self.say("Nothing to fix. For now.", self.pal.muted)
        else:
            self.resolve(None)
        self.redraw()

    # -- actions -----------------------------------------------------------

    def action_view(self, name: str) -> None:
        self.side = name
        self.redraw()

    def action_pick(self, i: int) -> None:
        if self.side == "servers":
            self.action_buy(i)
            return
        if self.side == "chips":
            self.buy_chip(i)
        elif i < len(STAFF):
            self.hire_staff(i)
        self.redraw()
        self.save()

    def action_buy(self, tier: int) -> None:
        p, cost = self.pal, cost_of(tier, self.owned[tier])
        if self.owned[tier] >= MAX_OWNED:
            self.say(f"{TIERS[tier][0]}: that's enough, truly", p.muted)
        elif self.balance >= cost:
            self.balance -= cost
            self.owned[tier] += 1
            self.say(f"+ {TIERS[tier][0]}  -${fmt(cost)}", p.success)
        else:
            self.say(f"! need ${fmt(cost)} for {TIERS[tier][0]}", p.error)
        self.redraw()
        self.save()

    def buy_chip(self, tier: int) -> None:
        p, level = self.pal, self.chips[tier]
        if level >= MAX_CHIP:
            self.say(f"{TIERS[tier][0]} chips are maxed out", p.muted)
        elif self.owned[tier] == 0:
            self.say(f"! buy a {TIERS[tier][0]} first", p.error)
        elif self.balance < chip_cost(tier, level):
            self.say(f"! need ${fmt(chip_cost(tier, level))} for the {CHIPS[tier][level]}", p.error)
        else:
            self.balance -= chip_cost(tier, level)
            self.chips[tier] += 1
            self.say(f"+ {CHIPS[tier][level]}: {TIERS[tier][0]} income x{CHIP_BOOST}", p.success)

    def hire_staff(self, role: int) -> None:
        p, level = self.pal, self.staff[role]
        name = STAFF[role][0]
        if level >= MAX_STAFF:
            self.say(f"{name} is already a 10x legend", p.muted)
            return
        cost = staff_cost(role, level)
        if self.balance < cost:
            self.say(f"! need ${fmt(cost)} for the {name}", p.error)
            return
        self.balance -= cost
        self.staff[role] += 1
        verb = "Hired a" if level < 0 else "Trained the"
        self.say(f"+ {verb} {name} (Lv {self.staff[role]})", p.success)

    # -- drawing -----------------------------------------------------------

    def set_text(self, wid: str, text: Text) -> None:
        """Update a Static only when its content really changed."""
        if self._last.get(wid) == text:
            return
        self._last[wid] = text
        self.query_one(wid, Static).update(text)

    def set_title(self, wid: str, title: str) -> None:
        """Assign a card title only when it changed: re-assigning repaints the card."""
        if self._titles.get(wid) != title:  # border_title doesn't read back as a str
            self._titles[wid] = title
            self.query_one(wid).border_title = title

    def redraw(self) -> None:
        p = self.pal
        self.set_text("#cash", Text.assemble(("$ ", rgb(p.muted)), fmt(self.balance)))

        stats = Text()
        stats.append("Income  ", rgb(p.muted))
        stats.append(f"${fmt(self.income)}/s", f"bold {rgb(p.error if self.crisis else p.warning)}")
        stats.append("  (crisis)\n" if self.crisis else "\n", rgb(p.error))
        stats.append("Racks   ", rgb(p.muted))
        stats.append(f"{sum(self.owned)}\n", f"bold {rgb(p.primary)}")
        stats.append("Fleet   ", rgb(p.muted))
        for n, colour in zip(self.owned, p.tiers):
            stats.append("■ ", rgb(colour) if n else rgb(p.faint))
        stats.append("\nCrew    ", rgb(p.muted))
        for level, initial in zip(self.staff, "VPF"):
            stats.append(f"{initial} ", rgb(p.success) if level >= 0 else rgb(p.faint))
        self.set_text("#stats", stats)

        titles = {"servers": "MARKETPLACE  [s]", "chips": "CHIP UPGRADES  [c]",
                  "staff": "ON-CALL CREW  [h]"}
        self.set_title("#shop", titles[self.side])
        self.set_text("#shop", {"servers": self.servers_text, "chips": self.chips_text,
                                "staff": self.staff_text}[self.side]())

        c = self.crisis
        alert = self.query_one("#alert", Static)
        if alert.display != (c is not None):  # re-assigning it forces a repaint
            alert.display = c is not None
        if c is not None:
            cut = round((1 - CRISIS_FACTOR[c["sev"]]) * 100)
            who = (f"{STAFF[c['fixer']][0]} responding ({c['eta']}s)"
                   if c["fixer"] is not None else "press F to fix")
            self.set_text("#alert", Text(f"⚠ {c['title']}  ·  income -{cut}%  ·  {who}"))

        self.set_title("#hall", f"DATA HALL · {sum(self.owned)} racks")
        sig =(tuple(self.owned), self.crisis is not None, id(p),
               self.phase // LED_PERIOD if sum(self.owned) else 0)
        if sig != self._hall_sig:  # a static hall costs nothing to leave alone
            self._hall_sig = sig
            self.query_one(Hall).refresh()

    def row(self, text: Text, index: int, name: str, badge: str, accent: str,
            name_style: str, badge_style: str) -> None:
        text.append(f" {index} ", f"bold {rgb(self.pal.chip_text)} on {accent}")
        text.append(f"  {name}", name_style)
        text.append(" " * max(1, ROW_W - 5 - len(name) - len(badge)))
        text.append(badge + "\n", badge_style)

    def servers_text(self) -> Text:
        p, shop = self.pal, Text()
        for i, (name, _, inc) in enumerate(TIERS):
            cost = cost_of(i, self.owned[i])
            ok = self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            badge = f"x{self.owned[i]}"
            self.row(shop, i + 1, name, badge, accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if self.owned[i] else rgb(p.faint))
            shop.append("     ")
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            shop.append(f"  ·  +${fmt(inc * CHIP_BOOST**self.chips[i])}/s\n", rgb(p.muted))
        return shop

    def chips_text(self) -> Text:
        p, shop = self.pal, Text()
        for i, (tier, _, _) in enumerate(TIERS):
            level = self.chips[i]
            maxed = level >= MAX_CHIP
            name = CHIPS[i][min(level, MAX_CHIP - 1)]
            cost = 0 if maxed else chip_cost(i, level)
            ok = not maxed and self.owned[i] > 0 and self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, "MAX" if maxed else f"Lv{level}/{MAX_CHIP}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.success) if maxed else rgb(p.fg) if level else rgb(p.faint))
            shop.append("     ")
            if maxed:
                shop.append(f"{tier} income x{CHIP_BOOST**MAX_CHIP}\n", rgb(p.success))
            elif self.owned[i] == 0:
                shop.append(f"buy a {tier} first\n", rgb(p.faint))
            else:
                shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
                shop.append(f"  ·  {tier} x{CHIP_BOOST}\n", rgb(p.muted))
        return shop

    def staff_text(self) -> Text:
        p, shop = self.pal, Text()
        for r, (name, _, tagline, scope) in enumerate(STAFF):
            level = self.staff[r]
            maxed = level >= MAX_STAFF
            cost = 0 if maxed else staff_cost(r, level)
            ok = not maxed and self.balance >= cost
            accent = rgb(p.success) if ok else rgb(p.muted)
            badge = "hire" if level < 0 else "MAX" if maxed else f"Lv{level}"
            self.row(shop, r + 1, name, badge, accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if level >= 0 else rgb(p.faint))
            shop.append("     ")
            if maxed:
                shop.append(f"fixes {scope}  ·  {math.ceil(response_time(level))}s\n",
                            rgb(p.success))
            else:
                shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
                if level < 0:
                    shop.append(f"  ·  fixes {scope}\n", rgb(p.muted))
                else:
                    shop.append(f"  ·  train: {math.ceil(response_time(level))}s"
                                f" -> {math.ceil(response_time(level + 1))}s\n", rgb(p.muted))
            shop.append(f"     {tagline}\n", rgb(p.faint))
        return shop


if __name__ == "__main__":
    DataCenter().run(mouse=False)  # keyboard-only: don't grab the mouse from tmux
