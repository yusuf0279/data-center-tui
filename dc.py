#!/usr/bin/env python3
"""My Data Center - pixel TUI idle tycoon.
Colours follow the active Textual theme (ctrl+p -> Change theme)."""
import colorsys
import json
import math
import os
import random
import subprocess
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

# name, base cost, income/sec (for the first data center)
TIERS: list[tuple[str, int, int]] = [
    ("Budget VPS", 100, 2),
    ("Compute Node", 600, 14),
    ("GPU Cluster", 3000, 80),
    ("AI Datacenter", 15000, 450),
    ("Quantum Farm", 80000, 2500),
    ("Orbital Cloud", 400000, 15000),
]
MAX_OWNED = 4000  # per tier; keeps costs finite

# Chip upgrades: 20 levels per tier = 5 families x 4 editions. Each level doubles
# that tier's income and costs 3x the previous level.
CHIP_FAMILIES: list[list[str]] = [
    ["GT 1030", "RX 6400", "Vega 8 (Hopeful)", "GTX 750", "Radeon HD 7000"],
    ["Ryzen 5 5600", "Ryzen 9 Zen Garden", "Threadripper 3990", "EPYC Milan", "Ryzen Z Handheld"],
    ["RTX 3090", "RTX 4090", "RTX 5090 (Paper)", "Titan RTX", "Jensen's Jacket"],
    ["A100", "H100 (a kidney)", "B200 (melts)", "GB200 NVL72", "H200 (sold out)"],
    ["MI250X", "MI300X (eXpensive)", "MI325X-ception", "MI350 Schrödinger", "Instinct Zero"],
    ["Rubin Ultra", "Zen 9 Space Ed.", "DGX Moonbase", "Feynman (TBD)", "Dyson GPU"],
]
CHIP_EDITIONS = ["", " Ti", " Super", " Ultra Max"]
MAX_CHIP = 20
CHIP_BASE = 20  # level-0 chip costs this many times the tier's base cost
CHIP_GROWTH = 3
CHIP_BOOST = 2

# On-call crew: name, hire cost, tagline, highest crisis severity handled, base response (s)
STAFF: list[tuple[str, int, str, int, float]] = [
    ("Vibecoder", 5_000, "ships it without reading the diff", 1, 10.0),
    ("Prompt Engineer", 60_000, "negotiates with the model for you", 2, 9.0),
    ("Forward Deployed Engineer", 750_000, "lives on-site, expenses everything", 3, 8.0),
    ("Site Reliability Engineer", 10_000_000, "has seen things", 3, 6.0),
    ("10x Engineer", 150_000_000, "does not exist, allegedly", 3, 4.0),
    ("Chief Hype Officer", 2_500_000_000, "raises a round to fix it", 3, 3.0),
]
STAFF_SCOPE = ["minor incidents", "outages and below", "everything"]
MAX_STAFF = 10  # training levels after hiring
RESPONSE_DECAY = 0.8  # response time multiplier per level
STAFF_BONUS = 5  # percent income per level, counting the hire as level 1

# Data centers: reach the threshold to open the next one. The old one keeps earning.
SITE_NAMES = [
    "Garage in Palo Alto", "Abandoned Mall in Ohio", "Decommissioned Missile Silo",
    "Arctic Bunker (free cooling)", "Undersea Pod off Iceland", "Lunar Regolith Campus",
    "Dyson Swarm Annex", "Pocket Universe", "Heat Death Colo",
    "The Cloud (Actually Water Vapor)",
]
EXPAND_BASE = 10**9  # cost to open data center #2
EXPAND_SCALE = 1000  # each later one needs 1000x more
INCOME_SCALE = 1000  # tier income multiplier per data center
COST_SCALE = 2500  # tier/chip/crew cost multiplier per data center
MAX_SITES = 60
MAX_BIG = 10**600  # sanity bound for numbers read from a save file

# Crises: severity -> titles. Income multiplier (num, den) while one is active.
CRISES: dict[int, list[str]] = {
    1: ["CI is stuck on a flaky test", "Janitor unplugged a rack to vacuum",
        "Someone pasted the API key into Slack"],
    2: ["Power outage: the grid is down", "Cooling failed: the AC is a fan and a prayer",
        "Cloud bill spiked 40x overnight"],
    3: ["GPU shortage: scalpers bought every H100", "Intern force-pushed to main on a Friday",
        "Solar flare fried the Orbital Cloud"],
}
CRISIS_FACTOR = {1: (1, 2), 2: (1, 4), 3: (0, 1)}
CRISIS_WEIGHT = {1: 5, 2: 3, 3: 2}
CRISIS_MEAN = 120  # average seconds between crises
CRISIS_MIN_INCOME = 10
FIX_QUIPS = [
    "by turning it off and on again", "with one prompt and zero tests",
    "by rewriting it in Rust", "by blaming the intern",
    "with a hotfix straight to prod", "by asking the model nicely",
]

DEFAULT_THEME = "gruvbox"
OFFLINE_NUM, OFFLINE_DEN = 3, 4  # earn 75% of normal income while the game is closed
ROW_W = 40  # inner width of the side cards
LED_PERIOD = 2  # ticks (seconds) per LED step; every step repaints the hall
# Under tmux, any repaint of a background pane makes tmux hop the real cursor over to
# it and back. So when this pane isn't the one you're typing in, redraw only this often.
BACKGROUND_REFRESH = 20  # seconds

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


# ------------------------------------------------------------------ economy
# Pure functions (exact integer maths, so numbers can grow without limit).

def site_name(k: int) -> str:
    return SITE_NAMES[k] if k < len(SITE_NAMES) else f"Parallel Universe #{k - len(SITE_NAMES) + 1}"


def expand_cost(site: int) -> int:
    """Cost to leave data center `site` and open the next one."""
    return EXPAND_BASE * EXPAND_SCALE**site


def cost_of(tier: int, owned: int, site: int = 0) -> int:
    return TIERS[tier][1] * COST_SCALE**site * 115**owned // 100**owned


def tier_income(tier: int, owned: int, chip: int, site: int = 0) -> int:
    return owned * TIERS[tier][2] * INCOME_SCALE**site * CHIP_BOOST**chip


def chip_name(tier: int, level: int) -> str:
    return CHIP_FAMILIES[tier][level // 4] + CHIP_EDITIONS[level % 4]


def chip_cost(tier: int, level: int, site: int = 0) -> int:
    return TIERS[tier][1] * CHIP_BASE * CHIP_GROWTH**level * COST_SCALE**site


def staff_cost(role: int, level: int, site: int = 0) -> int:
    """Cost to hire (level -1) or to train from `level` to level+1."""
    hire = STAFF[role][1] * COST_SCALE**site
    return hire if level < 0 else hire * 3 * 9**level // 5**level


def response_time(role: int, level: int) -> float:
    return STAFF[role][4] * RESPONSE_DECAY**level


def response_secs(role: int, level: int) -> int:
    return max(1, math.ceil(response_time(role, level)))


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


def tmux_foreground() -> bool:
    """False only when we are in tmux and this pane is NOT the active pane of the
    visible window (focus-events are usually off, so tmux itself is the only source)."""
    pane = os.environ.get("TMUX_PANE")
    if not pane:
        return True
    try:
        out = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane, "#{pane_active}#{window_active}"],
            capture_output=True, text=True, timeout=0.5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return out not in ("10", "01", "00")


def clean_levels(raw: Any, n: int, lo: int, hi: int, default: int) -> list[int]:
    """A list of n ints in [lo, hi]; anything invalid falls back to default."""
    out = [default] * n
    if isinstance(raw, list):
        for i, v in enumerate(raw[:n]):
            if type(v) is int and lo <= v <= hi:
                out[i] = v
    return out


SUFFIXES = ["", "K", "M", "B", "T", "Qa", "Qi", "Sx", "Sp", "Oc", "No", "Dc"]


def fmt(n: int) -> str:
    n = max(0, int(n))
    if n < 1000:
        return f"{n:,}"
    digits = len(str(n))
    group = (digits - 1) // 3
    if group < len(SUFFIXES):
        mant = n / 10 ** (3 * group)
        if mant < 999.995:
            return f"{mant:.2f}{SUFFIXES[group]}"
        if group + 1 < len(SUFFIXES):  # would round up to "1000.00": use the next unit
            return f"{n / 10 ** (3 * (group + 1)):.2f}{SUFFIXES[group + 1]}"
    return f"{int(str(n)[:3]) / 100:.2f}e{digits - 1}"


def fmt_duration(seconds: float) -> str:
    d, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m}m" if h else f"{m}m"


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
        Binding("h", "view('staff')", "Crew"),
        Binding("d", "view('sites')", "Data centers"),
        Binding("x", "expand", "Expand"),
        Binding("f", "fix", "Fix"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        data = load_save()
        balance = data.get("balance")
        self.balance = balance if type(balance) is int and 0 <= balance < MAX_BIG else 500
        sites = data.get("sites")
        self.sites = sites if type(sites) is int and 0 <= sites <= MAX_SITES else 0
        self.legacy = [0] * self.sites  # final income of each finished data center
        raw_legacy = data.get("legacy")
        if isinstance(raw_legacy, list):
            for i, v in enumerate(raw_legacy[:self.sites]):
                if type(v) is int and 0 <= v < MAX_BIG:
                    self.legacy[i] = v
        self.owned = clean_levels(data.get("owned"), len(TIERS), 0, MAX_OWNED, 0)
        self.chips = clean_levels(data.get("chips"), len(TIERS), 0, MAX_CHIP, 0)
        self.staff = clean_levels(data.get("staff"), len(STAFF), -1, MAX_STAFF, -1)
        theme = data.get("theme")
        self.saved_theme = theme if isinstance(theme, str) else DEFAULT_THEME
        self.side = "servers"
        self.crisis: dict[str, Any] | None = None
        self.rng = random.Random()
        self.phase = 0
        self.foreground = True
        self._pal: Palette | None = None
        self._last: dict[str, Text] = {}
        self._titles: dict[str, str] = {}
        self._hall_sig: tuple[Any, ...] | None = None
        # Offline earnings: 75% of income for the time since the last save
        self.away = (0.0, 0)
        saved_at = data.get("saved_at")
        if isinstance(saved_at, (int, float)) and not isinstance(saved_at, bool):
            try:  # huge ints overflow float conversion; treat those as "no data"
                if math.isfinite(saved_at) and saved_at > 0:
                    elapsed = max(0.0, time.time() - saved_at)
                    earned = int(elapsed) * self.base_income * OFFLINE_NUM // OFFLINE_DEN
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
                "staff": self.staff, "sites": self.sites, "legacy": self.legacy,
                "theme": self.theme, "saved_at": time.time(),
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
    def site_base(self) -> int:
        """This data center's income before the crew bonus."""
        return sum(tier_income(t, n, c, self.sites)
                   for t, (n, c) in enumerate(zip(self.owned, self.chips)))

    @property
    def staff_bonus(self) -> int:
        """Percent income bonus from the crew."""
        return STAFF_BONUS * sum(level + 1 for level in self.staff if level >= 0)

    @property
    def site_income(self) -> int:
        return self.site_base * (100 + self.staff_bonus) // 100

    @property
    def base_income(self) -> int:
        """Everything earning right now, ignoring any crisis."""
        return self.site_income + sum(self.legacy)

    @property
    def income(self) -> int:
        num, den = CRISIS_FACTOR[self.crisis["sev"]] if self.crisis else (1, 1)
        return self.base_income * num // den

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
        yield Static("1-6 pick  s c h d views  x expand  f fix  ctrl+p theme  q quit",
                     id="hint")

    def on_mount(self) -> None:
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
                f"earned ${fmt(self.away[1])} ({OFFLINE_NUM * 100 // OFFLINE_DEN}% offline rate)",
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
        self.foreground = tmux_foreground()
        if self.foreground or self.phase % BACKGROUND_REFRESH == 0:
            self.redraw()  # coming back to the front redraws on the very next tick
        self.save()

    def say(self, text: str, colour: RGB) -> None:
        self.query_one(RichLog).write(Text(text, style=rgb(colour)))

    # -- crises ------------------------------------------------------------

    def fixer_for(self, sev: int) -> int | None:
        """The hired crew member who can handle this severity and responds fastest."""
        best: tuple[float, int] | None = None
        for role, (_, _, _, cap, _) in enumerate(STAFF):
            if self.staff[role] >= 0 and cap >= sev:
                t = response_time(role, self.staff[role])
                if best is None or t < best[0]:
                    best = (t, role)
        return None if best is None else best[1]

    def update_crisis(self) -> None:
        c = self.crisis
        if c is not None:
            if c["fixer"] is None:  # someone may have been hired since it started
                c["fixer"] = self.fixer_for(c["sev"])
                if c["fixer"] is not None:
                    c["eta"] = response_secs(c["fixer"], self.staff[c["fixer"]])
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
        if sum(self.owned) >= 5 or self.sites > 0:
            sevs.append(2)
        if self.sites > 0 or self.site_base >= 200:
            sevs.append(3)
        sev = self.rng.choices(sevs, [CRISIS_WEIGHT[s] for s in sevs])[0]
        title = self.rng.choice(CRISES[sev])
        fixer = self.fixer_for(sev)
        eta = response_secs(fixer, self.staff[fixer]) if fixer is not None else None
        self.crisis = {"title": title, "sev": sev, "fixer": fixer, "eta": eta}
        num, den = CRISIS_FACTOR[sev]
        self.say(f"! {title} (income -{100 - num * 100 // den}%)", self.pal.error)

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
        elif self.side == "staff" and i < len(STAFF):
            self.hire_staff(i)
        self.redraw()
        self.save()

    def action_buy(self, tier: int) -> None:
        p, cost = self.pal, cost_of(tier, self.owned[tier], self.sites)
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
            return
        cost = chip_cost(tier, level, self.sites)
        if self.owned[tier] == 0:
            self.say(f"! buy a {TIERS[tier][0]} first", p.error)
        elif self.balance < cost:
            self.say(f"! need ${fmt(cost)} for the {chip_name(tier, level)}", p.error)
        else:
            self.balance -= cost
            self.chips[tier] += 1
            self.say(f"+ {chip_name(tier, level)}: {TIERS[tier][0]} income x{CHIP_BOOST}",
                     p.success)

    def hire_staff(self, role: int) -> None:
        p, level = self.pal, self.staff[role]
        name, _, tagline, _, _ = STAFF[role]
        if level >= MAX_STAFF:
            self.say(f"{name} is already a 10x legend", p.muted)
            return
        cost = staff_cost(role, level, self.sites)
        if self.balance < cost:
            self.say(f"! need ${fmt(cost)} for the {name}", p.error)
            return
        self.balance -= cost
        self.staff[role] += 1
        if level < 0:
            self.say(f"+ Hired a {name}: {tagline}", p.success)
        else:
            self.say(f"+ Trained the {name} (Lv {self.staff[role]})", p.success)

    def action_expand(self) -> None:
        p = self.pal
        if self.sites >= MAX_SITES:
            self.say("You own the multiverse. For now.", p.muted)
            return
        cost = expand_cost(self.sites)
        if self.balance < cost:
            self.say(f"! need ${fmt(cost)} to open {site_name(self.sites + 1)}", p.error)
        else:
            self.balance -= cost
            self.legacy.append(self.site_income)
            self.sites += 1
            self.owned = [0] * len(TIERS)
            self.chips = [0] * len(TIERS)
            self.crisis = None
            self.side = "servers"
            self.say(f"★ Opened {site_name(self.sites)}! {site_name(self.sites - 1)} keeps "
                     f"earning ${fmt(self.legacy[-1])}/s", p.success)
        self.redraw()
        self.save()

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
        for level, initial in zip(self.staff, "VPFSXC"):
            stats.append(f"{initial} ", rgb(p.success) if level >= 0 else rgb(p.faint))
        self.set_text("#stats", stats)

        titles = {"servers": "MARKETPLACE  [s]", "chips": "CHIP UPGRADES  [c]",
                  "staff": f"ON-CALL CREW · +{self.staff_bonus}% income  [h]",
                  "sites": "DATA CENTERS  [d]"}
        self.set_title("#shop", titles[self.side])
        self.set_text("#shop", {"servers": self.servers_text, "chips": self.chips_text,
                                "staff": self.staff_text, "sites": self.sites_text}[self.side]())

        c = self.crisis
        alert = self.query_one("#alert", Static)
        if alert.display != (c is not None):  # re-assigning it forces a repaint
            alert.display = c is not None
        if c is not None:
            num, den = CRISIS_FACTOR[c["sev"]]
            who = (f"{STAFF[c['fixer']][0]} responding ({c['eta']}s)"
                   if c["fixer"] is not None else "press F to fix")
            self.set_text("#alert", Text(
                f"⚠ {c['title']}  ·  income -{100 - num * 100 // den}%  ·  {who}"))

        self.set_title("#hall", f"{site_name(self.sites)} · {sum(self.owned)} racks")
        sig = (tuple(self.owned), self.crisis is not None, id(p),
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
            cost = cost_of(i, self.owned[i], self.sites)
            ok = self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, f"x{self.owned[i]}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if self.owned[i] else rgb(p.faint))
            shop.append("     ")
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            each = tier_income(i, 1, self.chips[i], self.sites)
            shop.append(f"  ·  +${fmt(each)}/s\n", rgb(p.muted))
        return shop

    def chips_text(self) -> Text:
        p, shop = self.pal, Text()
        for i, (tier, _, _) in enumerate(TIERS):
            level = self.chips[i]
            maxed = level >= MAX_CHIP
            name = chip_name(i, min(level, MAX_CHIP - 1))
            cost = 0 if maxed else chip_cost(i, level, self.sites)
            ok = not maxed and self.owned[i] > 0 and self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, "MAX" if maxed else f"L{level}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.success) if maxed else rgb(p.fg) if level else rgb(p.faint))
            shop.append("     ")
            if maxed:
                shop.append(f"{tier} income x{CHIP_BOOST**MAX_CHIP:,}\n", rgb(p.success))
            elif self.owned[i] == 0:
                shop.append(f"buy a {tier} first\n", rgb(p.faint))
            else:
                shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
                shop.append(f"  ·  {tier} x{CHIP_BOOST}\n", rgb(p.muted))
        return shop

    def staff_text(self) -> Text:
        p, shop = self.pal, Text()
        for r, (name, _, _, cap, _) in enumerate(STAFF):
            level = self.staff[r]
            maxed = level >= MAX_STAFF
            cost = 0 if maxed else staff_cost(r, level, self.sites)
            ok = not maxed and self.balance >= cost
            accent = rgb(p.success) if ok else rgb(p.muted)
            badge = "hire" if level < 0 else "MAX" if maxed else f"Lv{level}"
            self.row(shop, r + 1, name, badge, accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if level >= 0 else rgb(p.faint))
            shop.append("     ")
            scope = STAFF_SCOPE[cap - 1]
            if maxed:
                shop.append(f"fixes {scope}  ·  {response_secs(r, level)}s\n", rgb(p.success))
                continue
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            if level < 0:
                shop.append(f"  ·  fixes {scope}\n", rgb(p.muted))
            else:
                shop.append(f"  ·  {response_secs(r, level)}s -> "
                            f"{response_secs(r, level + 1)}s\n", rgb(p.muted))
        return shop

    def sites_text(self) -> Text:
        p, t, cur = self.pal, Text(), self.sites
        t.append("▶ ", f"bold {rgb(p.success)}")
        t.append(f"#{cur + 1} {site_name(cur)}\n", f"bold {rgb(p.primary)}")
        t.append(f"    ${fmt(self.site_income)}/s  ·  {sum(self.owned)} racks\n", rgb(p.muted))
        for k in range(cur - 1, max(-1, cur - 6), -1):
            nm = f"#{k + 1} {site_name(k)}"[:30]
            inc = f"${fmt(self.legacy[k] if k < len(self.legacy) else 0)}/s"
            t.append(f"  {nm}", rgb(p.fg))
            t.append(" " * max(1, ROW_W - 2 - len(nm) - len(inc)))
            t.append(inc + "\n", rgb(p.warning))
        if cur > 6:
            t.append(f"  ... and {cur - 6} older\n", rgb(p.faint))
        t.append("\n")
        if cur >= MAX_SITES:
            t.append("You own the multiverse.\n", rgb(p.success))
            return t
        cost = expand_cost(cur)
        pct = min(100, self.balance * 100 // cost)
        ready = self.balance >= cost
        t.append(f"Next: {site_name(cur + 1)}\n", f"bold {rgb(p.fg)}")
        t.append(f"${fmt(cost)} to open  ·  {pct}%\n",
                 rgb(p.success) if ready else rgb(p.muted))
        filled = pct * 20 // 100
        t.append("█" * filled, rgb(p.success) if ready else rgb(p.primary))
        t.append("░" * (20 - filled), rgb(p.faint))
        t.append("  press x to expand\n" if ready else "\n", f"bold {rgb(p.success)}")
        return t


if __name__ == "__main__":
    DataCenter().run(mouse=False)  # keyboard-only: don't grab the mouse from tmux
