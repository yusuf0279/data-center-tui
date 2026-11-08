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

# name, base cost, income/sec (for the first data center).
# Cost = income x payback seconds, and payback doubles every tier (30s, 60s ... 960s):
# cheap tiers pay back fast, expensive ones are long-term bets, so every tier has its moment.
TIERS: list[tuple[str, int, int]] = [
    ("Budget VPS", 60, 2),
    ("Compute Node", 840, 14),
    ("GPU Cluster", 9_600, 80),
    ("AI Datacenter", 108_000, 450),
    ("Quantum Farm", 1_200_000, 2500),
    ("Orbital Cloud", 14_400_000, 15000),
]
# Each extra copy of a tier costs this many percent of the previous one (107 = +7%).
# Gentle everywhere, a little steeper for the big tiers, so you keep buying all six.
GROWTH_PCT = [107, 108, 109, 110, 111, 112]
# Owning this many of a tier doubles that tier's income (like Cash Inc's milestones).
MILESTONES = [25, 50, 100, 200, 300, 400, 500, 1000, 1500, 2000, 3000, 4000]
MAX_OWNED = 4000  # per tier; keeps costs finite

# Chip upgrades: 20 levels per tier = 5 families x 4 editions. Each level doubles
# that tier's income and costs 4x the previous level.
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
CHIP_BASE = 2  # level-0 chip costs this many times the tier's base cost
CHIP_GROWTH = 4  # each level costs 4x the one before (x2 income): steep enough that
#                  milestones and buying more servers stay worth it
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

# Data centers: reach the threshold in your newest one to relocate. You start from
# scratch in the next one (money, servers, chips and crew reset); you keep Fame and
# your status. Old data centers are frozen: you can visit them, but only the one you
# are in earns.
SITE_NAMES = [
    "Garage in Palo Alto", "Abandoned Mall in Ohio", "Decommissioned Missile Silo",
    "Arctic Bunker (free cooling)", "Undersea Pod off Iceland", "Lunar Regolith Campus",
    "Dyson Swarm Annex", "Pocket Universe", "Heat Death Colo",
    "The Cloud (Actually Water Vapor)",
]
EXPAND_BASE = 10**13  # money needed in data center #1 to relocate
EXPAND_SCALE = 1000  # each later data center needs 1000x more
INCOME_SCALE = 1000  # tier income multiplier per data center
COST_SCALE = 1250  # tier/chip/crew cost and starting money multiplier per data center
START_BALANCE = 500
MAX_SITES = 60
FAME_BONUS = 2  # percent income per Fame point, in every data center
# Status ladder: lifetime Fame needed for each title. Past the last one the title gets a
# numeral and each next level needs double the Fame ("Tech Overlord II", "III", ...).
RANKS: list[tuple[int, str]] = [
    (0, "Nobody"), (1, "Intern"), (3, "Junior Dev"), (6, "Senior Dev"), (10, "Tech Lead"),
    (15, "Engineering Manager"), (25, "Director"), (40, "VP of Engineering"), (60, "CTO"),
    (90, "Tech CEO"), (130, "Tech Billionaire"), (180, "Tech Overlord"),
]
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
    return TIERS[tier][1] * COST_SCALE**site * GROWTH_PCT[tier]**owned // 100**owned


def milestone_mult(owned: int) -> int:
    """Income multiplier from owning enough of a tier (x2 per milestone passed)."""
    return 2 ** sum(1 for m in MILESTONES if owned >= m)


def next_milestone(owned: int) -> int | None:
    return next((m for m in MILESTONES if owned < m), None)


def tier_income(tier: int, owned: int, chip: int, site: int = 0) -> int:
    return (owned * TIERS[tier][2] * INCOME_SCALE**site * CHIP_BOOST**chip
            * milestone_mult(owned))


def start_balance(site: int) -> int:
    return START_BALANCE * COST_SCALE**site


def fame_gain(balance: int, site: int) -> int:
    """Fame for relocating out of data center `site` holding `balance`: 1 at the
    threshold, then growing with the square root of how far past it you got."""
    return math.isqrt(balance // expand_cost(site))


def roman(n: int) -> str:
    out = ""
    for value, symbol in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
                          (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                          (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += symbol
            n -= value
    return out


def rank_of(fame: int) -> tuple[str, int, str]:
    """(current title, Fame needed for the next title, next title)."""
    i = max(j for j, (need, _) in enumerate(RANKS) if fame >= need)
    if i + 1 < len(RANKS):
        return RANKS[i][1], RANKS[i + 1][0], RANKS[i + 1][1]
    top, name = RANKS[-1]
    level = 1  # "Tech Overlord" is level 1; each doubling of Fame adds one
    while fame >= top * 2**level and level < 3999:
        level += 1
    title = name if level == 1 else f"{name} {roman(level)}"
    return title, top * 2**level, f"{name} {roman(level + 1)}"


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


def restore_site(site: int, income: int, bonus_pct: int) -> tuple[list[int], list[int]]:
    """Rebuild a racks/chips layout worth about `income`. Older saves kept only a
    closed data center's final income, so this gives it real servers back."""
    owned = [0] * len(TIERS)
    chips = [0] * len(TIERS)
    remaining = income * 100 // (100 + bonus_pct)
    for t in range(len(TIERS) - 1, -1, -1):
        level = 0
        for level in range(MAX_CHIP + 1):  # fewest chips that still keep the count in range
            if tier_income(t, MAX_OWNED, level, site) > remaining:
                break
        lo, hi = 0, MAX_OWNED  # largest count whose income does not exceed what is left
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if tier_income(t, mid, level, site) <= remaining:
                lo = mid
            else:
                hi = mid - 1
        if lo:
            owned[t], chips[t] = lo, level
            remaining -= tier_income(t, lo, level, site)
    return owned, chips


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
        Binding("x", "expand", "Relocate"),
        Binding("left_square_bracket", "site(-1)", "Older data center", show=False),
        Binding("right_square_bracket", "site(1)", "Newer data center", show=False),
        Binding("f", "fix", "Fix"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        data = load_save()
        sites = data.get("sites")
        self.sites = sites if type(sites) is int and 0 <= sites <= MAX_SITES else 0
        n = len(TIERS)
        # Saves from before data centers reset had ONE shared balance and crew.
        old_balance = data.get("balance")
        old_balance = (old_balance if type(old_balance) is int and 0 <= old_balance < MAX_BIG
                       else START_BALANCE)
        old_staff = clean_levels(data.get("staff"), len(STAFF), -1, MAX_STAFF, -1)
        if isinstance(data.get("site_owned"), list):  # current format: every site has its own racks
            so, sc = data["site_owned"], data.get("site_chips")
            sc = sc if isinstance(sc, list) else []
            self.site_owned = [clean_levels(so[k] if k < len(so) else None, n, 0, MAX_OWNED, 0)
                               for k in range(self.sites + 1)]
            self.site_chips = [clean_levels(sc[k] if k < len(sc) else None, n, 0, MAX_CHIP, 0)
                               for k in range(self.sites + 1)]
        else:  # older saves: finished data centers kept only their final income
            legacy = [0] * self.sites
            raw_legacy = data.get("legacy")
            if isinstance(raw_legacy, list):
                for i, v in enumerate(raw_legacy[:self.sites]):
                    if type(v) is int and 0 <= v < MAX_BIG:
                        legacy[i] = v
            bonus = STAFF_BONUS * sum(level + 1 for level in old_staff if level >= 0)
            self.site_owned, self.site_chips = [], []
            for k in range(self.sites):
                o, c = restore_site(k, legacy[k], bonus)
                self.site_owned.append(o)
                self.site_chips.append(c)
            self.site_owned.append(clean_levels(data.get("owned"), n, 0, MAX_OWNED, 0))
            self.site_chips.append(clean_levels(data.get("chips"), n, 0, MAX_CHIP, 0))
        cur = data.get("cur")
        self.cur = cur if type(cur) is int and 0 <= cur <= self.sites else self.sites
        # Every data center has its own money and crew, and only the one you are in earns.
        fame = data.get("fame")
        if isinstance(data.get("site_balance"), list):
            sb, ss = data["site_balance"], data.get("site_staff")
            ss = ss if isinstance(ss, list) else []
            self.site_balance = [
                sb[k] if k < len(sb) and type(sb[k]) is int and 0 <= sb[k] < MAX_BIG
                else start_balance(k) for k in range(self.sites + 1)]
            self.site_staff = [
                clean_levels(ss[k] if k < len(ss) else None, len(STAFF), -1, MAX_STAFF, -1)
                for k in range(self.sites + 1)]
            default_fame = 0
        else:  # migrate: the money and crew you had belong to your newest data center
            self.site_balance = [0] * self.sites + [old_balance]
            self.site_staff = ([[-1] * len(STAFF) for _ in range(self.sites)] + [old_staff])
            default_fame = self.sites  # each data center you already opened counts as one Fame
        self.fame = fame if type(fame) is int and 0 <= fame < MAX_BIG else default_fame
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
                "site_balance": self.site_balance, "site_owned": self.site_owned,
                "site_chips": self.site_chips, "site_staff": self.site_staff,
                "fame": self.fame, "sites": self.sites, "cur": self.cur,
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

    # Everything below belongs to the data center you are in (self.cur).

    @property
    def balance(self) -> int:
        return self.site_balance[self.cur]

    @balance.setter
    def balance(self, value: int) -> None:
        self.site_balance[self.cur] = value

    @property
    def owned(self) -> list[int]:
        return self.site_owned[self.cur]

    @property
    def chips(self) -> list[int]:
        return self.site_chips[self.cur]

    @property
    def staff(self) -> list[int]:
        return self.site_staff[self.cur]

    def raw_income(self, k: int) -> int:
        """Data center k's income before the crew and Fame bonuses."""
        return sum(tier_income(t, n, c, k)
                   for t, (n, c) in enumerate(zip(self.site_owned[k], self.site_chips[k])))

    def crew_bonus(self, k: int) -> int:
        """Percent income bonus from data center k's crew."""
        return STAFF_BONUS * sum(level + 1 for level in self.site_staff[k] if level >= 0)

    @property
    def staff_bonus(self) -> int:
        return self.crew_bonus(self.cur)

    @property
    def fame_bonus(self) -> int:
        return FAME_BONUS * self.fame

    def site_income(self, k: int) -> int:
        """What data center k earns per second while you are in it."""
        return (self.raw_income(k) * (100 + self.crew_bonus(k)) // 100
                * (100 + self.fame_bonus) // 100)

    @property
    def base_income(self) -> int:
        """What you earn right now (only the data center you are in), ignoring crises."""
        return self.site_income(self.cur)

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
                # min_width defaults to 78, which would clip long lines instead of wrapping
                yield RichLog(id="log", classes="card", markup=False, wrap=True, min_width=20)
            with Vertical(id="side"):
                yield Static(id="stats", classes="card")
                yield Static(id="shop", classes="card")
        yield Static(id="alert")
        yield Static("1-6 pick  s c h d views  [ ] visit  x relocate  f fix  ctrl+p theme  q quit",
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
        unit = INCOME_SCALE**self.cur  # crisis rules are relative to this data center's size
        if (self.base_income >= CRISIS_MIN_INCOME * unit
                and self.rng.random() < 1 / CRISIS_MEAN):
            self.spawn_crisis()

    def spawn_crisis(self) -> None:
        sevs = [1]
        if sum(self.owned) >= 5:
            sevs.append(2)
        if self.raw_income(self.cur) >= 200 * INCOME_SCALE**self.cur:
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
        if self.side == "sites":  # key N opens data center #N (page 2 shows #7-#12, ...)
            k = self.cur // 6 * 6 + i
            if k <= self.sites:
                self.side = "servers"
                self.goto_site(k)
            return
        if self.side == "chips":
            self.buy_chip(i)
        elif self.side == "staff" and i < len(STAFF):
            self.hire_staff(i)
        self.redraw()
        self.save()

    def action_buy(self, tier: int) -> None:
        p, cost = self.pal, cost_of(tier, self.owned[tier], self.cur)
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
        cost = chip_cost(tier, level, self.cur)
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
        cost = staff_cost(role, level, self.cur)
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
        if self.cur != self.sites:
            self.say(f"! relocate from your newest data center (press ] to go to "
                     f"#{self.sites + 1})", p.error)
        elif self.balance < cost:
            self.say(f"! need ${fmt(cost)} to relocate to {site_name(self.sites + 1)}", p.error)
        else:
            # Prestige: this data center is frozen as it is, and you start the next from
            # scratch (money, servers, chips, crew). Fame and status carry over.
            gain = fame_gain(self.balance, self.sites)
            before = rank_of(self.fame)[0]
            self.fame += gain
            self.sites += 1
            self.site_owned.append([0] * len(TIERS))
            self.site_chips.append([0] * len(TIERS))
            self.site_balance.append(start_balance(self.sites))
            self.site_staff.append([-1] * len(STAFF))
            self.cur = self.sites
            self.crisis = None
            self.side = "servers"
            self.say(f"★ Relocated to {site_name(self.sites)}! +{fmt(gain)} Fame "
                     f"(+{fmt(FAME_BONUS * gain)}% income)", p.success)
            after = rank_of(self.fame)[0]
            if after != before:
                self.say(f"★ Promoted: {after}!", p.warning)
        self.redraw()
        self.save()

    def goto_site(self, k: int) -> None:
        if 0 <= k <= self.sites and k != self.cur:
            self.cur = k
            self.crisis = None  # a crisis belongs to the data center it happened in
            self.say(f"Now at #{k + 1} {site_name(k)}", self.pal.muted)
        self.redraw()
        self.save()

    def action_site(self, delta: int) -> None:
        """[ and ] step to the older / newer data center."""
        self.goto_site(self.cur + delta)

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

        rank, rank_need, _ = rank_of(self.fame)
        self.set_text("#title", Text.assemble(
            "◆ MY DATA CENTER", ("  ·  ", rgb(p.muted)), (rank, f"bold {rgb(p.success)}")))

        stats = Text()
        stats.append("Income  ", rgb(p.muted))
        stats.append(f"${fmt(self.income)}/s", f"bold {rgb(p.error if self.crisis else p.warning)}")
        stats.append("  (crisis)\n" if self.crisis else "\n", rgb(p.error))
        stats.append("Racks   ", rgb(p.muted))
        stats.append(f"{sum(self.owned):<8}", f"bold {rgb(p.primary)}")
        stats.append("Fame ", rgb(p.muted))
        stats.append(fmt(self.fame), f"bold {rgb(p.warning)}")
        bonus = f" (+{fmt(self.fame_bonus)}%)"
        if len(f"Racks   {sum(self.owned):<8}Fame {fmt(self.fame)}{bonus}") <= ROW_W:
            stats.append(bonus, rgb(p.muted))  # dropped rather than wrapped
        stats.append("\n")
        stats.append("Fleet   ", rgb(p.muted))
        for n, colour in zip(self.owned, p.tiers):
            stats.append("■ ", rgb(colour) if n else rgb(p.faint))
        stats.append(" Crew ", rgb(p.muted))
        for level, initial in zip(self.staff, "VPFSXC"):
            stats.append(f"{initial} ", rgb(p.success) if level >= 0 else rgb(p.faint))
        stats.append("\nStatus  ", rgb(p.muted))
        stats.append(rank, f"bold {rgb(p.success)}")
        progress = f" ({fmt(self.fame)}/{fmt(rank_need)})"
        if len("Status  " + rank + progress) <= ROW_W:  # drop it rather than wrap
            stats.append(progress, rgb(p.muted))
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

        self.set_title("#hall", f"#{self.cur + 1} {site_name(self.cur)} · {sum(self.owned)} racks")
        sig = (self.cur, tuple(self.owned), self.crisis is not None, id(p),
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
            cost = cost_of(i, self.owned[i], self.cur)
            ok = self.balance >= cost
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, f"x{self.owned[i]}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if self.owned[i] else rgb(p.faint))
            shop.append("     ")
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            each = tier_income(i, 1, self.chips[i], self.cur)
            shop.append(f" · +${fmt(each)}/s", rgb(p.muted))
            milestone = next_milestone(self.owned[i])
            shop.append(f" · x2@{milestone}\n" if milestone else "\n", rgb(p.warning))
        return shop

    def chips_text(self) -> Text:
        p, shop = self.pal, Text()
        for i, (tier, _, _) in enumerate(TIERS):
            level = self.chips[i]
            maxed = level >= MAX_CHIP
            name = chip_name(i, min(level, MAX_CHIP - 1))
            cost = 0 if maxed else chip_cost(i, level, self.cur)
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
                shop.append(f" · {tier} x{CHIP_BOOST}\n", rgb(p.muted))
        return shop

    def staff_text(self) -> Text:
        p, shop = self.pal, Text()
        for r, (name, _, _, cap, _) in enumerate(STAFF):
            level = self.staff[r]
            maxed = level >= MAX_STAFF
            cost = 0 if maxed else staff_cost(r, level, self.cur)
            ok = not maxed and self.balance >= cost
            accent = rgb(p.success) if ok else rgb(p.muted)
            badge = "hire" if level < 0 else "MAX" if maxed else f"Lv{level}"
            self.row(shop, r + 1, name, badge, accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if level >= 0 else rgb(p.faint))
            shop.append("     ")
            scope = STAFF_SCOPE[cap - 1]
            if maxed:
                shop.append(f"fixes {scope} · {response_secs(r, level)}s\n", rgb(p.success))
                continue
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            if level < 0:
                shop.append(f" · fixes {scope}\n", rgb(p.muted))
            else:
                shop.append(f" · {response_secs(r, level)}s -> "
                            f"{response_secs(r, level + 1)}s\n", rgb(p.muted))
        return shop

    def sites_text(self) -> Text:
        p, t, newest = self.pal, Text(), self.sites
        first = self.cur // 6 * 6  # six per page; the page follows the one you are in
        for row, k in enumerate(range(first, min(first + 6, newest + 1))):  # keys 1-6, oldest first
            here = k == self.cur
            inc = f"${fmt(self.site_income(k))}/s"
            nm, room = f"#{k + 1} {site_name(k)}", ROW_W - 6 - len(inc)
            if len(nm) > room:  # only cut what must be cut
                nm = nm[:room - 1] + "…"
            chip = rgb(p.success) if here else rgb(p.muted)
            t.append(f" {row + 1} ", f"bold {rgb(p.chip_text)} on {chip}")
            t.append(" ▶" if here else "  ", f"bold {rgb(p.success)}")
            t.append(nm, f"bold {rgb(p.primary)}" if here else rgb(p.fg))
            t.append(" " * max(1, ROW_W - 5 - len(nm) - len(inc)))
            t.append(inc + "\n", rgb(p.warning) if here else rgb(p.faint))
        if newest > 5:
            t.append(f"     #{first + 1}-{min(first + 6, newest + 1)} of {newest + 1}"
                     f"  ·  [ ] to move\n", rgb(p.faint))
        t.append("Only the one you are in earns.\n", rgb(p.faint))
        if newest >= MAX_SITES:
            t.append("You own the multiverse.\n", rgb(p.success))
            return t
        cost = expand_cost(newest)
        bal = self.site_balance[newest]
        pct = min(100, bal * 100 // cost)
        ready = bal >= cost
        t.append(f"Next: {site_name(newest + 1)}\n", f"bold {rgb(p.fg)}")
        t.append(f"${fmt(cost)} in #{newest + 1}  ·  {pct}%\n",
                 rgb(p.success) if ready else rgb(p.muted))
        filled = pct * 12 // 100  # a short bar leaves room for the hint on the same line
        t.append("█" * filled, rgb(p.success) if ready else rgb(p.primary))
        t.append("░" * (12 - filled), rgb(p.faint))
        if ready and self.cur == newest:
            t.append(f"  x: relocate +{fmt(fame_gain(bal, newest))} Fame",
                     f"bold {rgb(p.success)}")
        elif ready:
            t.append("  ] to go there, then x", f"bold {rgb(p.success)}")
        t.append("\n")
        return t


if __name__ == "__main__":
    DataCenter().run(mouse=False)  # keyboard-only: don't grab the mouse from tmux
