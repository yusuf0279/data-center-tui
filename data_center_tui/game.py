#!/usr/bin/env python3
"""My Data Center - pixel TUI idle tycoon.
Colours follow the active Textual theme (ctrl+p -> Change theme)."""
import argparse
import colorsys
import http.client
import inspect
import json
import math
import os
import random
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Any, ClassVar, cast

from rich.control import Control
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.geometry import Region
from textual.screen import ModalScreen
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

from . import __version__

try:  # Textual internals, used only to trim what a partial repaint sends (see crop_update)
    from textual._compositor import ChopsUpdate, CompositorUpdate
except ImportError:  # an unknown Textual: its own (wider) updates are fine, just bigger
    ChopsUpdate = CompositorUpdate = None  # type: ignore[assignment, misc]
try:
    from importlib.metadata import version as _dist_version
    TEXTUAL_VERSION = _dist_version("textual")
except Exception:  # noqa: BLE001 - metadata missing or odd: the gate below turns the trim off
    TEXTUAL_VERSION = ""

RGB = tuple[int, int, int]

# ---------------------------------------------------------------- game data

# name, base cost, income/sec (for the first data center).
# Cost = income x payback seconds. Payback doubles every tier up to 960s (16 min), then
# climbs more gently to ~40 min: cheap tiers pay back fast, expensive ones are long-term
# bets, so every tier has its moment.
TIERS: list[tuple[str, int, int]] = [
    ("Budget VPS", 60, 2),
    ("Compute Node", 840, 14),
    ("GPU Cluster", 9_600, 80),
    ("AI Datacenter", 108_000, 450),
    ("Quantum Farm", 1_200_000, 2500),
    ("Orbital Cloud", 14_400_000, 15000),
    ("Fusion Campus", 108_000_000, 90_000),
    ("Dyson Swarm", 864_000_000, 540_000),
    ("Neutron Star Farm", 6_400_000_000, 3_200_000),
    ("Black Hole Colo", 47_500_000_000, 19_000_000),
]
# Each extra copy of a tier costs this many percent of the previous one (107 = +7%).
# Gentle everywhere, a little steeper for the big tiers, so you keep buying all of them.
GROWTH_PCT = [107, 108, 109, 110, 111, 112, 112, 112, 113, 113]
# Owning this many of a tier doubles that tier's income (like Cash Inc's milestones).
MILESTONES = [25, 50, 100, 200, 300, 400, 500, 1000, 1500, 2000, 3000, 4000]
MAX_OWNED = 4000  # per tier; keeps costs finite
# Fixed colours per tier: rose, green, magenta, lime, violet, orange, teal, yellow, blue, red.
# The order alternates warm and cool so neighbouring tiers are never similar colours.
TIER_HUES = (340, 140, 300, 95, 262, 32, 175, 55, 215, 8)
TIER_SATURATION = 0.72

# Chip upgrades: 20 levels per tier = 5 families x 4 editions. Each level doubles
# that tier's income and costs 4x the previous level.
CHIP_FAMILIES: list[list[str]] = [
    ["GeForceless 1030", "Radeoff 6400", "Vague 8 (Hopeful)", "G-Tex 750", "Radeoff HD 7000"],
    ["Rizzen 5 5600", "Rizzen 9 Garden", "Thread-Shred 3990", "Epick Milano", "Rizzen Z Handheld"],
    ["RTZ 3090", "RTZ 4090", "RTZ 5090 (Paper)", "Colossus RTZ", "Leather Jacket Ed."],
    ["A-100", "H-100 (a kidney)", "Bee-200 (melts)", "GB-200 (Rack-ish)", "H-200 (sold out)"],
    ["MX250X", "MX300X (eXpensive)", "MX325-ception", "MX350 Schrödinger", "Insti-Zero"],
    ["Ruby Ultra", "Rizzen Space Ed.", "DGZ Moonbase", "Physicist (TBD)", "Sphere GPU"],
    ["Tokamak TK-1", "Stellarator S7", "ITER Junior", "Cold Fusion (lol)", "Plasma Rack"],
    ["Solar Sail", "Swarm Node", "Mirror Array", "Mercury Strip Mine", "Matrioshka Lite"],
    ["Pulsar Clock", "Magnetar Mk I", "Neutronium Sink", "Quark Fabric", "Strange Matter"],
    ["Event Horizon", "Hawking Cooler", "Singularity Rack", "Penrose Engine", "Info Paradox"],
]
CHIP_EDITIONS = ["", " Ti", " Super", " Ultra Max"]
MAX_CHIP = 20
CHIP_BASE = 2  # level-0 chip costs this many times the tier's base cost
CHIP_GROWTH = 4  # each level costs 4x the one before (x2 income): steep enough that
#                  milestones and buying more servers stay worth it
CHIP_BOOST = 2

# On-call crew, one specialist per tier (role N manages tier N). name, hire cost, tagline,
# highest crisis severity handled, base response (s). As they are trained they unlock perks:
#   Lv0 fixes crises   Lv2 auto-buys its tier's servers   Lv4 x2 its tier's income
#   Lv6 auto-buys its tier's chips   Lv8 x2 again          (and every level adds +5% income)
STAFF: list[tuple[str, int, str, int, float]] = [
    ("Vibecoder", 5_000, "ships it without reading the diff", 1, 10.0),
    ("Prompt Engineer", 60_000, "negotiates with the model for you", 2, 9.0),
    ("Forward Deployed Engineer", 750_000, "lives on-site, expenses everything", 3, 8.0),
    ("Site Reliability Engineer", 10_000_000, "has seen things", 3, 6.0),
    ("10x Engineer", 150_000_000, "does not exist, allegedly", 3, 4.0),
    ("Chief Hype Officer", 2_500_000_000, "raises a round to fix it", 3, 3.0),
    ("Distinguished Engineer", 40_000_000_000, "has opinions about your architecture", 3, 2.5),
    ("Chief AI Officer", 700_000_000_000, "puts AI in the press release", 3, 2.0),
    ("Head of Synergy", 12_000_000_000_000, "aligns stakeholders at light speed", 3, 1.5),
    ("Founder Mode CEO", 200_000_000_000_000, "is personally in the weeds", 3, 1.0),
]
CREW_INITIALS = "VPFSXCDAHO"
AUTO_SERVERS_LEVEL, DOUBLE_LEVELS, AUTO_CHIPS_LEVEL = 2, (4, 8), 6
AUTO_BUYS_PER_TICK = 10  # servers one specialist may buy per second
# Autopilot only buys things that cost at most 1/50 of one second of your income, so it
# can spend at most ~20% of your earnings and you can always save up for the big purchases.
AUTO_AFFORD_DIV = 50
PERKS = [(AUTO_SERVERS_LEVEL, "buys cheap servers"), (DOUBLE_LEVELS[0], "x2 its income"),
         (AUTO_CHIPS_LEVEL, "buys cheap chips"), (DOUBLE_LEVELS[1], "x2 its income")]
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
EXPAND_BASE = 10**16  # money needed in data center #1 to relocate
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
    3: ["GPU shortage: scalpers bought every one", "Intern force-pushed to main on a Friday",
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

# Online leaderboard (opt-in). DC_ONLINE=0 turns every online feature off; DC_SERVER points
# the game at another server.
SERVER = os.environ.get("DC_SERVER", "https://data-center.openexplorer.xyz").rstrip("/")
ONLINE = os.environ.get("DC_ONLINE", "1") != "0" and SERVER.startswith(("https://", "http://"))
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,19}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{32,64}$")
DC_NAME_RE = re.compile(r"^[ -~]{0,24}$")  # what you may call a data center: plain printable text
MAX_FAME_ONLINE = 10**12  # the server rejects anything above this
SUBMIT_EVERY = 120  # seconds between score updates when something changed

DEFAULT_THEME = "gruvbox"
OFFLINE_NUM, OFFLINE_DEN = 3, 4  # earn 75% of normal income while the game is closed
ROW_W = 40  # inner width of the side cards
# Under tmux, any repaint of a background pane makes tmux hop the real cursor over to
# it and back. So when this pane isn't the one you're typing in, redraw only this often.
BACKGROUND_REFRESH = 20  # seconds

# Animation. One clock (a single set_interval at ANIM_FPS) runs only while something can
# move: ANIM on, this pane in front, a live (not decommissioned) data center. Motion is a
# function of a time `t` in seconds from clock() (patchable in tests), never of a frame
# count, so a dropped frame skips ahead instead of slowing down. The 1 s game tick is a
# separate timer and the only place that asks tmux whether we are in front (frames never
# shell out). DC_ANIM=0 / --no-anim turns all of it off.
ANIM = os.environ.get("DC_ANIM", "1") != "0"
FPS_DEFAULT, FPS_MIN, FPS_MAX = 12.0, 4.0, 30.0


def anim_fps(raw: str | None) -> float:
    """Frames per second from DC_ANIM_FPS: default 12, anything unusable falls back to
    the default, and the result is clamped to 4..30."""
    try:
        fps = float(raw) if raw else FPS_DEFAULT
    except ValueError:
        fps = FPS_DEFAULT
    if not math.isfinite(fps):
        fps = FPS_DEFAULT
    return min(FPS_MAX, max(FPS_MIN, fps))


ANIM_FPS = anim_fps(os.environ.get("DC_ANIM_FPS"))
FRAME_S = 1 / ANIM_FPS  # seconds between frames
BANNER_MIN_CONTRAST = 3.0  # WCAG ratio the banner fade never drops below
HEADER_MIN_CONTRAST = 3.0  # ... and the hall's tier headers
SPARK_LIFE_S, RESOLVE_S, CASH_FLASH_S = 0.8, 1.0, 0.6
RELOC_S, RELOC_STAGGER_S, RELOC_FADE_S = 1.6, 0.25, 0.45
LED_SLOT_S, LED_FADE = 0.6, 0.5  # an LED re-rolls every slot and fades over half of it
PULSE_PX_S, PULSE_TAIL = 16.0, 5.0  # data pulse speed (pixels/s) and tail length
TOP_PERIOD_S, BANNER_PERIOD_S, PULSE_STEPS = 3.0, 1.2, 8  # PULSE_STEPS quantises the top-tier glow
# Bandwidth (the game is played over SSH): LEDs and the glow move at SLOW_FPS (about, it is a
# whole fraction of the frame rate), the LED fade has LED_LEVELS brightness steps, and a repaint
# sends only the changed cells; spans closer than SPAN_GAP unchanged cells are sent as one.
SLOW_FPS, LED_LEVELS, SPAN_GAP = 6.0, 4, 2
SLOW_HZ = ANIM_FPS / max(1, round(ANIM_FPS / SLOW_FPS))  # every n-th frame: no uneven beat


def clock() -> float:
    """Monotonic seconds. Every animation reads time from here so tests can patch it."""
    return time.monotonic()


def smoothstep(x: float) -> float:
    """Ease in and out, clamped to 0..1."""
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def ease_out(x: float) -> float:
    """Fast start, gentle stop, clamped to 0..1."""
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 2


def sine01(t: float, period: float) -> float:
    """Smooth 0..1..0 over `period` seconds, starting at 0."""
    return 0.5 - 0.5 * math.cos(math.tau * t / period)


# Sprite legend: k frame, c tier colour, h highlight, d dark, w pale window/fan,
# A/B blinking LEDs, . empty. One distinct silhouette per tier.
SPRITES: list[list[str]] = [
    ["......", "......", ".cccc.", "chhhhc", "cddAdc", "kkkkkk"],  # desktop box
    ["......", "cccccc", "chhhAc", "kkkkkk", "chhhBc", "cccccc"],  # two blades
    ["cccccc", "cwdwAc", "cddddc", "cwdwBc", "cddddc", "kkkkkk"],  # fan rack
    ["..hh..", "cccccc", "cwcwcc", "cccccc", "cwcAwc", "dddddd"],  # building
    ["..hh..", ".hwwh.", "chwwhc", ".cwwc.", "..cc..", "..dd.."],  # crystal
    ["..hA..", "cckkcc", "cchhcc", "cckkcc", "..kk..", "..dd.."],  # satellite
    ["..cc..", ".chhc.", "chwwhc", "cwAAwc", "cddddc", "kkkkkk"],  # fusion reactor dome
    ["c....c", ".hhhh.", "hwAAwh", "hwwwwh", ".hhhh.", "c....c"],  # dyson swarm: sun + panels
    ["......", "..cc..", "cwhhwc", ".cwwc.", "..cc..", "..dd.."],  # neutron star with a ring
    [".cccc.", "chddhc", "cdAAdc", "chddhc", ".cccc.", "..dd.."],  # black hole
]
CELL_W, CELL_H = 7, 8  # 6x6 sprite, one gap column, shadow row at the bottom


def mix32(*vals: int) -> int:
    """Small deterministic integer hash: the same inputs always give the same frame."""
    h = 0x811C9DC5
    for v in vals:
        h = ((h ^ (v & 0xFFFFFFFF)) * 0x01000193) & 0xFFFFFFFF
        h ^= h >> 15
    return h


@dataclass
class Fx:
    """One short-lived visual effect, born at clock time `born` and alive for `life` seconds.
    `spark` = a burst of pixels around a rack."""
    kind: str
    seed: int
    life: float
    born: float
    tier: int = 0
    big: bool = False

    def progress(self, now: float) -> float:
        """0.0 when born, 1.0 when it expires."""
        return min(1.0, max(0.0, (now - self.born) / self.life))


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


def crew_multiplier(level: int) -> int:
    """A tier's specialist doubles its income at each milestone level (Lv4, Lv8)."""
    return 2 ** sum(1 for m in DOUBLE_LEVELS if level >= m)


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


def read_within(fp: Any, deadline: float, limit: int = 1 << 16) -> bytes | None:
    """Read at most `limit` bytes but give up at `deadline`: a server that drips one byte at
    a time cannot hold the game's network thread (urlopen's timeout is per read only)."""
    # read1 returns after one network read; read(n) would wait for n bytes, so a server
    # dripping bytes could stall it far past the deadline
    inner = getattr(fp, "fp", None)
    reader = (getattr(fp, "read1", None) or getattr(inner, "read1", None) or fp.read)
    chunks, size = [], 0
    while size < limit:
        if time.monotonic() > deadline:
            return None
        chunk = reader(min(4096, limit - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


def api(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """One request to the leaderboard server. Never raises: status 0 means unreachable.
    The whole thing, headers included, is cut off after 8 seconds: urlopen's own timeout
    only limits each single read, so a server dripping its headers could hold it for minutes."""
    result: list[tuple[int, dict[str, Any]]] = []
    worker = threading.Thread(target=lambda: result.append(_request(method, path, body)), daemon=True)
    worker.start()
    worker.join(8)
    return result[0] if result else (0, {})  # a stuck worker is abandoned; it dies with its socket


def _request(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    deadline = time.monotonic() + 8
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            SERVER + path, data=data, method=method,
            headers={"Content-Type": "application/json", "User-Agent": f"data-center-tui/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                status, raw = resp.status, read_within(resp, deadline)
        except urllib.error.HTTPError as err:
            status, raw = err.code, read_within(err, deadline)
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return 0, {}
    if raw is None:
        return 0, {}
    try:
        parsed = json.loads(raw or b"{}")
    except ValueError:
        return status, {}
    return status, parsed if isinstance(parsed, dict) else {}


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


def fmt(n: int, decimals: int = 2) -> str:
    n = max(0, int(n))
    if n < 1000:
        return f"{n:,}"
    digits = len(str(n))
    group = (digits - 1) // 3
    if group < len(SUFFIXES):
        mant = n / 10 ** (3 * group)
        if round(mant, decimals) < 1000:
            return f"{mant:.{decimals}f}{SUFFIXES[group]}"
        if group + 1 < len(SUFFIXES):  # would round up to "1000.00": use the next unit
            return f"{n / 10 ** (3 * (group + 1)):.{decimals}f}{SUFFIXES[group + 1]}"
    return f"{int(str(n)[:3]) / 100:.{decimals}f}e{digits - 1}"


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


def _linear(v: int) -> float:
    x = v / 255
    return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4


def contrast(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio between two colours (1.0 to 21.0)."""
    def rel(c: RGB) -> float:
        return 0.2126 * _linear(c[0]) + 0.7152 * _linear(c[1]) + 0.0722 * _linear(c[2])
    hi, lo = sorted((rel(a), rel(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg: RGB, bg: RGB, minimum: float, prefer: RGB | None = None) -> RGB:
    """Push `fg` towards black or white (whichever reads better on `bg`) until it reaches
    the minimum contrast. A colour that already passes is returned unchanged. `prefer`
    names an end to try first, so a fading background doesn't flip the text between
    black and white from one frame to the next."""
    if contrast(fg, bg) >= minimum:
        return fg
    best: RGB = max(((0, 0, 0), (255, 255, 255)), key=lambda e: contrast(e, bg))
    for end in ((prefer, best) if prefer else (best,)):
        for step in range(1, 21):
            c = mix(fg, end, step / 20)
            if contrast(c, bg) >= minimum:
                return c
    return best


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
        # A tier keeps the same hue in every theme, so a server is always recognisable;
        # only the lightness follows the theme's background.
        light = 0.62 if lum(self.surface) < 0.5 else 0.38
        self.tiers = [
            visible(cast(RGB, tuple(int(x * 255) for x in
                                    colorsys.hls_to_rgb(h / 360, light, TIER_SATURATION))))
            for h in TIER_HUES
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
        # the empty chip pips: as dark as the shadow, and darker still on a light theme so the
        # lit pips have room to stand out
        self.pip_floor = self.shadow if lum(self.surface) < 0.5 else mix(self.bg, (0, 0, 0), 0.8)


# --------------------------------------------------------------------- hall

Run = tuple[str, "RGB | None", "RGB | None"]  # a stretch of text with its fg / bg colour
Cell = tuple[str, "RGB | None", "RGB | None"]  # one terminal cell: char, fg, bg


class StyleCache(dict[tuple["RGB | None", "RGB | None"], Style]):
    """Rich Style objects are slow to parse: build each (fg, bg) pair once."""

    def __missing__(self, key: tuple["RGB | None", "RGB | None"]) -> Style:
        fg, bg = key
        style = self[key] = Style(color=rgb(fg) if fg else None, bgcolor=rgb(bg) if bg else None)
        return style


STYLES = StyleCache()

CHIP_PIPS, CHIP_STEPS = 5, 4  # a chip level (0..20) is 5 family pips of 4 editions each
PIP_GLYPHS = "·▂▄▆█"  # a pip in the side card, by how many of its 4 editions are installed
PIP_FULL_WHITE = 0.85  # how far towards white a full pip goes
PIP_MIN_CONTRAST = 3.0  # the faintest lit pip against an empty one
HEADER_LINES, RACK_LINES = 1, CELL_H // 2  # terminal lines per tier header / per rack row


def chip_pips(level: int) -> list[int]:
    """Fill (0..4) of each of the 5 family pips for an installed chip level: pips fill left
    to right, one step per edition, so 0 is empty, 4 is one family and 20 is all five."""
    return [min(CHIP_STEPS, max(0, level - CHIP_STEPS * i)) for i in range(CHIP_PIPS)]


def lightness(c: RGB) -> float:
    """CIE L* (0 black .. 100 white): equal steps look like equal steps of brightness."""
    y = 0.2126 * _linear(c[0]) + 0.7152 * _linear(c[1]) + 0.0722 * _linear(c[2])
    return 116 * (y ** (1 / 3) if y > 0.008856 else 7.787 * y + 16 / 116) - 16


def pip_colour(step: int, hue: RGB, floor: RGB) -> RGB:
    """One hall pip: `floor` when empty, then a tint of the tier colour that gets lighter with
    every edition. The first edition is just PIP_MIN_CONTRAST above the floor and the last
    is the palest tint; the steps between are evenly spaced in lightness, so each one is
    clearly brighter than the last on any theme."""
    if not step:
        return floor
    peak = mix(hue, (255, 255, 255), PIP_FULL_WHITE)

    def solve(reached: Callable[[RGB], bool]) -> float:  # smallest mix that satisfies `reached`
        lo, hi = 0.0, 1.0
        for _ in range(14):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if reached(mix(floor, peak, mid)) else (mid, hi)
        return hi

    first = mix(floor, peak, solve(lambda c: contrast(c, floor) >= PIP_MIN_CONTRAST))
    l1, l4 = lightness(first), lightness(peak)
    want = l1 + (l4 - l1) * (step - 1) / (CHIP_STEPS - 1)
    return mix(floor, peak, solve(lambda c: lightness(c) >= want))


def header_label(name: str, count: int, level: int, room: int) -> str:
    """"NAME xN · chip L3/20", shortened step by step to fit `room` cells: the word chip goes
    first, then the dot, then the name is cut with an ellipsis."""
    chip = f"L{level}/{MAX_CHIP}"
    tails = (f" x{count} · chip {chip}", f" x{count} · {chip}", f" x{count} {chip}")
    for tail in tails:
        if len(name) + len(tail) <= room:
            return name + tail
    keep = room - len(tails[-1])
    if keep >= 4:
        return name[:keep - 1].rstrip() + "…" + tails[-1]
    return (name + tails[-1])[:max(0, room)]


@dataclass
class Block:
    """One stretch of the hall: a tier header line or one row of racks."""
    kind: str  # "head" or "rack"
    tier: int
    first: int  # index of the first rack (racks are numbered cheapest tier first)
    count: int  # racks in this row (0 for a header)
    line0: int  # terminal line the block starts on, counted from the top of the whole hall
    height: int
    row: int  # rack-row number (0-based); a header takes the number of the row below it


@dataclass
class Layout:
    """Where everything in the hall goes: every tier's header and rack rows laid end to end,
    and which of those blocks are on screen (blocks[start:end], all fully visible)."""
    cols: int
    height: int  # terminal lines available
    blocks: list[Block]
    start: int
    end: int
    total_lines: int
    total_rows: int
    tier_block: list[int]  # index of each tier's header block (-1: none owned)
    tier_first: list[int]  # index of each tier's first rack

    @property
    def scrolled(self) -> bool:
        return self.total_lines > self.height

    @property
    def top_line(self) -> int:
        return self.blocks[self.start].line0 if self.blocks else 0

    @property
    def used(self) -> int:
        """Terminal lines the visible blocks take."""
        return sum(b.height for b in self.blocks[self.start:self.end])

    @property
    def max_start(self) -> int:
        """The first block of the last full screen (what the hall shows while following)."""
        s = len(self.blocks) - 1
        while s > 0 and self.total_lines - self.blocks[s - 1].line0 <= self.height:
            s -= 1
        return max(0, s)

    def rack_xy(self, idx: int, tier: int) -> tuple[int, int] | None:
        """Pixel (x, y) of the top left of rack `idx` of `tier`, None if it is off screen."""
        if self.tier_block[tier] < 0:
            return None
        k, c = divmod(idx - self.tier_first[tier], self.cols)
        bi = self.tier_block[tier] + 1 + k
        if not self.start <= bi < self.end:
            return None
        return c * CELL_W, (self.blocks[bi].line0 - self.top_line) * 2 + 1


class Hall(Widget):
    """Pixel view of the racks you own, drawn with half-block characters. Racks are
    listed by tier (cheapest first), each tier under its own header line; scroll with
    up/down/pageup/pagedown/home/end (one header or rack row at a time)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._rows: list[list[Run]] | None = None  # last picture, for partial repaints
        self._cells: list[list[Cell]] = []  # the same picture cell by cell (to find what changed)
        self._strips: dict[int, Strip] = {}
        self._base_key: tuple[Any, ...] | None = None
        self._base: tuple[list[list[RGB]], list[tuple[int, int, int, int]]] = ([], [])
        self._blocks_owned: tuple[int, ...] = ()
        self._blocks: dict[int, tuple[list[Block], int, list[int], list[int]]] = {}  # by columns

    @property
    def game(self) -> "DataCenter":
        return cast("DataCenter", self.app)

    def on_resize(self, event: events.Resize) -> None:
        self.game.redraw()  # the title shows which rack rows fit, so it depends on our size

    def make_blocks(self, cols: int) -> tuple[list[Block], int, list[int], list[int]]:
        """Every block of the whole hall for `cols` racks per row (cached while the fleet and
        the width stay the same): (blocks, total lines, tier header index, tier first rack)."""
        owned = tuple(self.game.owned)
        if owned != self._blocks_owned:
            self._blocks_owned, self._blocks = owned, {}
        if cols in self._blocks:
            return self._blocks[cols]
        blocks: list[Block] = []
        tier_block, tier_first = [-1] * len(owned), [0] * len(owned)
        line = row = first = 0
        for tier, n in enumerate(owned):
            tier_first[tier] = first
            if not n:
                continue
            tier_block[tier] = len(blocks)
            blocks.append(Block("head", tier, first, 0, line, HEADER_LINES, row))
            line += HEADER_LINES
            for k in range(-(-n // cols)):
                blocks.append(Block("rack", tier, first + k * cols, min(cols, n - k * cols),
                                    line, RACK_LINES, row))
                line += RACK_LINES
                row += 1
            first += n
        self._blocks[cols] = (blocks, line, tier_block, tier_first)
        return self._blocks[cols]

    def rack_layout(self) -> Layout:
        """Place the tier headers and rack rows, and pick the visible blocks: the newest at
        the bottom unless the player scrolled (game.hall_scroll is a block number)."""
        game = self.game
        w, height = self.size.width, max(self.size.height, HEADER_LINES + RACK_LINES)
        cols = max(1, w // CELL_W)
        blocks, total, tier_block, tier_first = self.make_blocks(cols)
        if total > height:  # a scrollbar needs one column of its own
            cols = max(1, (w - 1) // CELL_W)
            blocks, total, tier_block, tier_first = self.make_blocks(cols)
        lay = Layout(cols, height, blocks, 0, 0, total, sum(b.kind == "rack" for b in blocks),
                     tier_block, tier_first)
        lay.start = lay.max_start if game.hall_scroll is None else min(game.hall_scroll, lay.max_start)
        lay.end, used = lay.start, 0
        while lay.end < len(blocks) and used + blocks[lay.end].height <= height:
            used += blocks[lay.end].height
            lay.end += 1
        if lay.end - 1 > lay.start and blocks[lay.end - 1].kind == "head":
            lay.end -= 1  # a header never ends the screen without a rack row under it
        return lay

    @staticmethod
    def led_lit(idx: int, y: int, x: int) -> bool:
        """Is this LED pixel lit in a still hall (no animation)? A fixed pattern."""
        return (idx + y * 2 + x) % 3 == 0

    @staticmethod
    def led_level(idx: int, y: int, x: int, t: float) -> float:
        """LED brightness 0..1 at time t: each LED re-rolls on/off once per slot (with its
        own offset, so they never blink in step) and eases to the new state."""
        key = y * 8 + x
        s = t / LED_SLOT_S + (mix32(idx, key, 99) & 1023) / 1024
        k = math.floor(s)
        now = 1.0 if mix32(idx, key, k) % 5 < 2 else 0.0
        before = 1.0 if mix32(idx, key, k - 1) % 5 < 2 else 0.0
        return before + (now - before) * smoothstep((s - k) / LED_FADE)

    @classmethod
    def led_shade(cls, idx: int, y: int, x: int, t: float) -> float:
        """led_level snapped to LED_LEVELS brightness steps: the fade stays smooth to the eye
        but far fewer LED cells change from one frame to the next."""
        steps = LED_LEVELS - 1
        return round(cls.led_level(idx, y, x, t) * steps) / steps

    def render_reloc(self) -> Text:
        """The relocation transition: lines fade in one after another, then all fade out."""
        game, p = self.game, self.game.pal
        reloc = cast(dict[str, Any], game.reloc)
        age = game.now - reloc["t0"]
        lines = [("★ RELOCATING ★", p.primary), (f"Fame +{fmt(reloc['gain'])}", p.warning)]
        if reloc["rank"]:
            lines.append((f"Promoted: {reloc['rank']}!", p.success))
        lines.append((f"Welcome to {game.site_label(game.cur)}", p.fg))
        w, h = self.size.width, self.size.height
        top = max(0, (h - len(lines)) // 2)
        out_fade = smoothstep((RELOC_S - age) / 0.3)  # the last 0.3 s fade everything away
        out = Text(no_wrap=True)
        for y in range(h):
            k = y - top
            if 0 <= k < len(lines):
                text, colour = lines[k][0][:w], lines[k][1]
                fade = smoothstep((age - k * RELOC_STAGGER_S) / RELOC_FADE_S) * out_fade
                if fade > 0:
                    out.append(" " * ((w - len(text)) // 2) + text,
                               Style(color=rgb(mix(p.bg, colour, fade)), bold=True))
            out.append("\n")
        return out

    def draw_bus(self, grid: list[list[RGB]], lay: Layout, t: float) -> None:
        """A cable along the top of every rack row with a data pulse gliding down it. The
        head sits at a fractional pixel: its two neighbours share the colour in proportion,
        so it moves continuously rather than in cell steps."""
        p = self.game.pal
        for b in lay.blocks[lay.start:lay.end]:
            if b.kind != "rack":
                continue
            width = b.count * CELL_W - 1
            row = grid[(b.line0 - lay.top_line) * 2]
            for x in range(0, width, 2):
                row[x] = p.frame
            head = (t * PULSE_PX_S + b.row * 9) % (width + PULSE_TAIL)
            colour = p.tiers[b.tier]
            for x in range(max(0, math.ceil(head - PULSE_TAIL)), min(width, int(head) + 2)):
                d = head - x  # distance behind the head; the leading edge blends in
                a = 1 + d if d < 0 else (1 - d / PULSE_TAIL) ** 2
                if a > 0:
                    row[x] = mix(row[x], colour, min(1.0, a))

    def draw_sparks(self, grid: list[list[RGB]], lay: Layout) -> None:
        """Sparkle bursts around the rack that was just bought (hall centre if off screen):
        the sparks fly out with ease-out and fade smoothly."""
        game, p = self.game, self.game.pal
        gh, gw = len(grid), len(grid[0])
        for fx in game.fx:
            if fx.kind != "spark":
                continue
            u = fx.progress(game.now)
            at = (lay.rack_xy(lay.tier_first[fx.tier] + game.owned[fx.tier] - 1, fx.tier)
                  if game.owned[fx.tier] else None)
            cx, cy = (at[0] + 3, at[1] + 3) if at else (gw // 2, gh // 2)
            base = p.warning if fx.big else mix(p.tiers[fx.tier], p.fg, 0.5)
            colour = mix(base, p.bg, smoothstep(u))
            for i in range(20 if fx.big else 9):
                h = mix32(fx.seed, i)
                reach = 1 + (h >> 8 & 3) * 0.5 + 8 * ease_out(u)
                x = cx + round(math.cos((h & 255) * math.tau / 256) * reach)
                y = cy + round(math.sin((h & 255) * math.tau / 256) * reach)
                if 0 <= x < gw and 0 <= y < gh:
                    grid[y][x] = colour

    def base_grid(self, lay: Layout, pulse: int) -> tuple[list[list[RGB]], list[tuple[int, int, int, int]]]:
        """Everything that doesn't move: backdrop, sprites, chip pips. Also the LED pixels as
        (x, y, rack index, sprite position). Cached; see build_cells()."""
        game, p = self.game, self.game.pal
        gw, gh = lay.cols * CELL_W, lay.used * 2
        grid: list[list[RGB]] = [
            [mix(p.bg, p.surface, y / max(1, gh - 1))] * gw for y in range(gh)
        ]
        leds: list[tuple[int, int, int, int]] = []
        top = game.top_tier()
        for b in lay.blocks[lay.start:lay.end]:
            if b.kind != "rack":
                continue
            tier, oy = b.tier, (b.line0 - lay.top_line) * 2 + 1
            hue = self.tier_colour(tier)
            colour = hue
            if game.animating and tier == top:  # gentle pulse on the best earner
                colour = mix(colour, p.fg, 0.25 * pulse / PULSE_STEPS)
            palette: dict[str, RGB] = {
                "k": p.frame, "c": colour, "h": mix(colour, (255, 255, 255), 0.35),
                "d": mix(colour, (0, 0, 0), 0.5), "w": mix(colour, (255, 255, 255), 0.6),
            }
            pips = [pip_colour(s, hue, p.pip_floor) for s in chip_pips(game.chips[tier])]
            for c in range(b.count):
                ox, idx = c * CELL_W, b.first + c
                for x, pip in enumerate(pips):  # the floor shadow row doubles as the chip level
                    grid[oy + 6][ox + 1 + x] = pip
                for y, row in enumerate(SPRITES[tier]):
                    for x, ch in enumerate(row):
                        if ch == ".":
                            continue
                        if ch in "AB":
                            leds.append((ox + x, oy + y, idx, y * 8 + x))
                        else:
                            grid[oy + y][ox + x] = palette[ch]
        return grid, leds

    def tier_colour(self, tier: int) -> RGB:
        """A tier's colour in this hall: washed out to grey in a decommissioned one."""
        p, colour = self.game.pal, self.game.pal.tiers[tier]
        if self.game.read_only:
            grey = int(lum(colour) * 255)
            return mix((grey, grey, grey), p.surface, 0.55)
        return colour

    def header_cells(self, b: Block, width: int, under: RGB) -> list[Cell]:
        """One tier's header line: its buy key as a badge, then "NAME xN · chip L3/20" in the
        tier colour (contrast against the backdrop kept at HEADER_MIN_CONTRAST) and a rule."""
        game, p = self.game, self.game.pal
        colour = self.tier_colour(b.tier)
        key = (b.tier + 1) % 10  # the number key that buys this tier
        badge_fg = ensure_contrast(p.chip_text, colour, HEADER_MIN_CONTRAST)
        text_fg = ensure_contrast(colour, under, HEADER_MIN_CONTRAST)
        label = header_label(TIERS[b.tier][0].upper(), game.owned[b.tier], game.chips[b.tier],
                             width - 4)
        cells: list[Cell] = [(ch, badge_fg, colour) for ch in f" {key} "]
        cells.append((" ", None, under))
        cells.extend((ch, text_fg, under) for ch in label)
        if len(cells) < width:
            cells.append((" ", None, under))
        cells.extend(("─", p.frame, under) for _ in range(width - len(cells)))
        return cells[:width]

    def special(self) -> Text | None:
        """The hall's text-only states (relocation transition, empty hall), else None."""
        game, p = self.game, self.game.pal
        if game.animating and game.reloc is not None:
            return self.render_reloc()
        if not sum(game.owned):
            return Text("\n  Empty hall. Press 1 to buy your first server.", style=rgb(p.muted))
        return None

    def build_cells(self) -> list[list[Cell]]:
        """The picture, one (char, fg, bg) cell at a time: pixel hall, tier headers, effects,
        scrollbar. Rack rows are gw cells wide (gw + padding + scrollbar when it scrolls)."""
        game, p = self.game, self.game.pal
        animating = game.animating
        w, t = self.size.width, game.now
        slow = math.floor(t * SLOW_HZ) / SLOW_HZ  # LEDs and glow tick slower than the pulse
        lay = self.rack_layout()
        gw, dead = lay.cols * CELL_W, game.read_only
        pulse = round(PULSE_STEPS * sine01(slow, TOP_PERIOD_S)) if animating else 0
        key = (game.pal_serial, tuple(game.owned), tuple(game.chips), game.top_tier(), lay.start,
               lay.end, lay.cols, lay.height, dead, animating, pulse)
        if self._base_key != key:  # sprites only change when the layout, a chip or the pulse step does
            self._base_key = key
            self._base = self.base_grid(lay, pulse)
        base, leds = self._base
        grid = [row[:] for row in base]
        alert = game.crisis is not None and not dead
        led_on = p.alert_on if alert else p.led_on
        led_off = p.alert_off if alert else p.led_off
        if dead:  # decommissioned: every light is off
            led_on = led_off = mix(p.frame, p.bg, 0.4)
        for x, y, idx, pos in leds:
            if animating:
                grid[y][x] = mix(led_off, led_on, self.led_shade(idx, pos // 8, pos % 8, slow))
            else:
                grid[y][x] = led_on if self.led_lit(idx, pos // 8, pos % 8) else led_off
        if animating:
            if not game.crisis:  # data stops flowing while something is broken
                self.draw_bus(grid, lay, t)
            self.draw_sparks(grid, lay)
        cells: list[list[Cell]] = [[("▀", grid[y][x], grid[y + 1][x]) for x in range(gw)]
                                   for y in range(0, len(grid), 2)]
        scrolled = lay.scrolled
        for b in lay.blocks[lay.start:lay.end]:
            if b.kind == "head":
                line = b.line0 - lay.top_line
                cells[line] = self.header_cells(b, w - 1 if scrolled else w, grid[line * 2][0])
        if scrolled:  # scrollbar on the right edge when there is more hall than fits
            lines = len(cells)
            thumb_len = max(1, round(lines * lines / lay.total_lines))
            thumb_pos = round((lines - thumb_len) * lay.top_line
                              / max(1, lay.total_lines - lines))
            for line, row in enumerate(cells):
                row.extend([(" ", None, None)] * max(0, w - 1 - len(row)))
                thumb = thumb_pos <= line < thumb_pos + thumb_len
                row.append((" ", None, p.muted if thumb else p.frame))
        return cells

    @staticmethod
    def to_runs(row: list[Cell]) -> list[Run]:
        """Merge runs of identical cells into single segments: far fewer bytes per frame."""
        return [(ch * len(list(run)), fg, bg) for (ch, fg, bg), run in groupby(row)]

    def build_rows(self) -> list[list[Run]]:
        """The picture as rows of runs (text, fg, bg)."""
        return [self.to_runs(row) for row in self.build_cells()]

    def render(self) -> Text:
        text = self.special()
        if text is not None:
            return text
        out = Text(no_wrap=True)
        for runs in self.build_rows():
            for chars, fg, bg in runs:
                out.append(chars, Style(color=rgb(fg) if fg else None,
                                        bgcolor=rgb(bg) if bg else None))
            out.append("\n")
        return out

    # -- partial repaints: only the cells that changed are rendered and sent again ------

    @staticmethod
    def changed_spans(old: list[Cell], new: list[Cell], gap: int = SPAN_GAP) -> list[tuple[int, int]]:
        """Half-open (start, end) column spans covering every cell that differs between two
        rows; spans with at most `gap` unchanged cells between them are joined into one."""
        if len(old) != len(new):  # the row's width changed (scrollbar came or went): repaint it all
            return [(0, max(len(old), len(new)))]
        spans: list[list[int]] = []
        for x, (a, b) in enumerate(zip(old, new)):
            if a == b:
                continue
            if spans and x - spans[-1][1] <= gap:
                spans[-1][1] = x + 1
            else:
                spans.append([x, x + 1])
        return [(a, b) for a, b in spans]

    def update_rows(self) -> None:
        """Rebuild the picture and ask Textual to repaint just the spans of cells that differ."""
        if self.special() is not None:  # text states go through the normal render() path
            self._rows = None
            self.refresh()
            return
        cells = self.build_cells()
        old, self._cells = self._cells, cells
        had = self._rows is not None
        self._rows = [self.to_runs(row) for row in cells]
        self._strips = {}
        if not had or len(old) != len(cells):
            self.refresh()
            return
        regions: list[Region] = []
        for y, (a, b) in enumerate(zip(old, cells)):
            regions.extend(Region(x1, y, x2 - x1, 1) for x1, x2 in self.changed_spans(a, b))
        if regions:
            self.refresh(*regions)

    def render_line(self, y: int) -> Strip:
        if self._rows is None:
            return super().render_line(y)
        if y >= len(self._rows):
            return Strip.blank(self.size.width, self.rich_style)
        strip = self._strips.get(y)
        if strip is None:
            base = self.rich_style  # the hall's own colours: padding must keep its background
            segs = [Segment(chars, base + STYLES[(fg, bg)]) for chars, fg, bg in self._rows[y]]
            strip = self._strips[y] = Strip(segs).adjust_cell_length(self.size.width, base)
        return strip


# ------------------------------------------------------------------- dialogs

class YesNo(ModalScreen[bool]):
    """A small yes/no question: y or n (escape counts as no)."""

    BINDINGS = [("y", "answer(True)", "Yes"), ("n", "answer(False)", "No"),
                ("escape", "answer(False)", "No")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text, self.body_text = title, body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.title_text, id="dialog-title")
            yield Static(self.body_text, id="dialog-body")
            yield Static("[y] yes    [n] no", id="dialog-keys")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)


class NameInput(ModalScreen[str | None]):
    """Asks for a name: a leaderboard name by default, or e.g. a data center name."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, name: str = "", error: str = "", title: str = "Pick a leaderboard name",
                 rule: "re.Pattern[str]" = NAME_RE, max_len: int = 20,
                 placeholder: str = "1-20 letters, digits, space _ . -",
                 complaint: str = "Use 1-20 letters, digits, spaces, _ . - (start with a letter or digit)",
                 keys: str = "[enter] join    [esc] cancel") -> None:
        super().__init__()
        self.initial, self.error, self.heading = name, error, title
        self.rule, self.max_len, self.placeholder = rule, max_len, placeholder
        self.complaint, self.keys = complaint, keys

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.heading, id="dialog-title")
            yield Input(value=self.initial, max_length=self.max_len, id="name",
                        placeholder=self.placeholder)
            yield Static(self.error, id="dialog-error")
            yield Static(self.keys, id="dialog-keys")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if self.rule.fullmatch(name):
            self.dismiss(name)
        else:
            self.query_one("#dialog-error", Static).update(self.complaint)

    def action_cancel(self) -> None:
        self.dismiss(None)


class Menu(ModalScreen[str | None]):
    """The game menu: press a number to choose, escape or m to close."""

    BINDINGS = [*(Binding(str(i + 1), f"choose({i})", show=False) for i in range(9)),
                Binding("escape", "close", show=False), Binding("m", "close", show=False)]

    def __init__(self, items: list[tuple[str, str, bool]]) -> None:
        super().__init__()
        self.items = items  # (id, label, enabled)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("Menu", id="dialog-title")
            lines = Text()
            for n, (_, label, enabled) in enumerate(self.items, 1):
                lines.append(f" {n} ", "bold reverse" if enabled else "dim reverse")
                lines.append(f"  {label}\n", "" if enabled else "dim")
            yield Static(lines, id="dialog-body")
            yield Static("[1-9] choose    [esc] close", id="dialog-keys")

    def action_choose(self, i: int) -> None:
        if i < len(self.items) and self.items[i][2]:
            self.dismiss(self.items[i][0])

    def action_close(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------- app

CROP_TESTED = ((8, 0), (8, 3))  # Textual versions [8.0, 8.3) are the ones CroppedChops was checked on


def textual_in_range(raw: str) -> bool:
    """Is this Textual version string inside CROP_TESTED? Anything unparsable is not."""
    m = re.match(r"^(\d+)\.(\d+)", raw.strip()) if isinstance(raw, str) else None
    return bool(m) and CROP_TESTED[0] <= (int(m.group(1)), int(m.group(2))) < CROP_TESTED[1]  # type: ignore[union-attr]


def crop_supported(raw_version: str, chops: Any, base: Any, app: Any) -> bool:
    """May CroppedChops replace Textual's partial-repaint output? Only on a tested Textual
    whose private pieces still look the way it expects; otherwise stock rendering is used."""
    try:
        if not textual_in_range(raw_version) or chops is None or base is None:
            return False
        if list(inspect.signature(app._display).parameters) != ["self", "screen", "renderable"]:
            return False
        init = list(inspect.signature(chops.__init__).parameters)
        return init == ["self", "chops", "spans", "chop_ends"] and callable(
            getattr(chops, "render_segments", None))
    except Exception:  # noqa: BLE001 - any surprise means "not supported"
        return False


CROP_OK = crop_supported(TEXTUAL_VERSION, ChopsUpdate, CompositorUpdate, App)

if CompositorUpdate is not None:
    class CroppedChops(CompositorUpdate):  # type: ignore[misc, valid-type]
        """A partial repaint that sends exactly the dirty cells. Textual's own ChopsUpdate
        starts each piece at the left edge of the widget's line and only crops its right
        end, so one changed cell re-sends everything to its left. Any failure falls back
        to Textual's own output: this is an optimisation and must never break painting."""

        def __init__(self, update: Any) -> None:
            self.update = update

        def render_segments(self, console: Any) -> str:
            try:
                return self.cropped(console)
            except Exception:  # noqa: BLE001 - fall back to the stock, wider repaint
                return str(self.update.render_segments(console))

        def cropped(self, console: Any) -> str:
            move_to = Control.move_to
            out: list[str] = []
            update = self.update
            for y, x1, x2 in update.spans:
                for end, (x, strip) in zip(update.chop_ends[y], update.chops[y].items()):
                    lo, hi = max(x, x1), min(end, x2)
                    if strip is None or lo >= hi:
                        continue
                    if (lo, hi) != (x, end):
                        strip = strip.crop(lo - x, hi - x)
                    out.append(move_to(lo, y).segment.text)  # every piece is placed explicitly
                    out.append(strip.render(console))
            return "".join(out)


def crop_update(update: Any) -> Any:
    """`update` with a partial repaint narrowed to its dirty cells (anything else as is,
    and everything as is when this Textual is outside the tested range)."""
    if (CROP_OK and CompositorUpdate is not None and type(update) is ChopsUpdate
            and all(hasattr(update, a) for a in ("spans", "chop_ends", "chops"))):
        return CroppedChops(update)
    return update


class DataCenter(App):
    TITLE = "MY DATA CENTER"
    AUTO_FOCUS = ""  # nothing grabs the arrow keys: they scroll the hall
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
        border-title-color: $primary; border-title-style: bold; border-subtitle-color: $primary;
        padding: 0 1;
    }
    #hall { height: 1fr; background: $background; padding: 0; }
    #log { height: 6; scrollbar-size-vertical: 1; }
    #stats { height: 6; }
    #shop { height: 1fr; }
    #alert {
        height: 1; background: $error; color: $background;
        text-style: bold; padding: 0 2; display: none;
    }
    #hint { height: 1; color: $text-muted; padding: 0 1; }
    ModalScreen { align: center middle; }
    #dialog {
        width: 64; height: auto; padding: 1 2; background: $surface; border: round $primary;
    }
    #dialog-title { text-style: bold; color: $primary; margin-bottom: 1; }
    #dialog-error { color: $error; height: 1; }
    #dialog-keys { color: $text-muted; margin-top: 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(str((i + 1) % 10), f"pick({i})", "Pick", show=False) for i in range(10)),
        Binding("s", "view('servers')", "Servers"),
        Binding("c", "view('chips')", "Chips"),
        Binding("h", "view('staff')", "Crew"),
        Binding("d", "view('sites')", "Data centers"),
        Binding("x", "expand", "Relocate"),
        Binding("left_square_bracket", "site(-1)", "Older data center", show=False),
        Binding("right_square_bracket", "site(1)", "Newer data center", show=False),
        Binding("f", "fix", "Fix"),
        Binding("a", "autopilot", "Autopilot"),
        Binding("b", "view('board')", "Leaderboard"),
        Binding("j", "join", "Join/leave the leaderboard"),
        Binding("n", "rename", "Name this data center"),
        Binding("m", "menu", "Menu"),
        Binding("escape", "menu", "Menu", show=False),
        Binding("comma", "shop(-1)", "Shop up", show=False),
        Binding("full_stop", "shop(1)", "Shop down", show=False),
        Binding("up", "hall('up')", "Scroll hall", show=False),
        Binding("down", "hall('down')", "Scroll hall", show=False),
        Binding("pageup", "hall('pageup')", "Scroll hall", show=False),
        Binding("pagedown", "hall('pagedown')", "Scroll hall", show=False),
        Binding("home", "hall('home')", "Scroll hall", show=False),
        Binding("end", "hall('end')", "Scroll hall", show=False),
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
        raw_names = data.get("site_names")
        raw_names = raw_names if isinstance(raw_names, list) else []
        self.site_names: list[str] = []  # your own names for data centers ("" = the default)
        for k in range(self.sites + 1):
            label = raw_names[k] if k < len(raw_names) else ""
            self.site_names.append(label if isinstance(label, str) and DC_NAME_RE.fullmatch(label) else "")
        theme = data.get("theme")
        self.saved_theme = theme if isinstance(theme, str) else DEFAULT_THEME
        self.side = "servers"
        self.shop_top: int | None = None  # None = the card follows your furthest tier
        self._note = ""
        # Autopilot is on for a brand-new game, but off for an existing save so that
        # nothing starts spending your money until you press `a`.
        auto = data.get("autopilot")
        self.autopilot = auto if isinstance(auto, bool) else not data
        raw_online = data.get("online")
        online: dict[str, Any] = raw_online if isinstance(raw_online, dict) else {}
        name, token = online.get("name"), online.get("token")
        valid = (isinstance(name, str) and NAME_RE.fullmatch(name) is not None
                 and isinstance(token, str) and TOKEN_RE.fullmatch(token) is not None)
        self.online_asked = online.get("asked") is True
        self.online_joined = valid and online.get("joined") is True
        self.online_name = name if valid and isinstance(name, str) else ""
        self.online_token = token if valid and isinstance(token, str) else ""
        self.board: dict[str, Any] | None = None
        self._net_busy = self._board_busy = False
        self._board_at = -1e9
        self._last_sent: tuple[int, int, str] | None = None
        self._last_attempt = 0.0
        self.crisis: dict[str, Any] | None = None
        self.rng = random.Random()
        self.phase = 0
        self.foreground = True
        self.fx: list[Fx] = []
        self.fx_seq = 0  # numbers the effects: their look is a function of this and the phase
        self.now = clock()  # animation time, refreshed by every frame and redraw
        self.cash_flash = 0  # +1 balance just rose, -1 it just fell, 0 no flash
        self.cash_t0 = 0.0
        self.resolve_t0: float | None = None  # when the crisis was fixed, while the banner fades
        self.resolved = ""
        self.reloc: dict[str, Any] | None = None  # the relocation transition, while it plays
        self._anim_timer: Timer | None = None
        self._alert_bg: RGB | None = None
        self.hall_scroll: int | None = None  # None = follow the newest racks at the bottom
        self._pal: Palette | None = None
        self._last: dict[str, Text] = {}
        self._titles: dict[str, str] = {}
        self._hall_sig: tuple[Any, ...] | None = None
        self.pal_serial = 0  # bumped whenever the palette is rebuilt
        self._seen_balance = self.site_balance[self.cur]
        # Offline earnings: 75% of income for the time since the last save
        self.away = (0.0, 0)
        saved_at = data.get("saved_at")
        if isinstance(saved_at, (int, float)) and not isinstance(saved_at, bool):
            try:  # huge ints overflow float conversion; treat those as "no data"
                if math.isfinite(saved_at) and saved_at > 0:
                    elapsed = max(0.0, time.time() - saved_at)
                    earned = int(elapsed) * self.site_income(self.sites) * OFFLINE_NUM // OFFLINE_DEN
                    if earned > 0:
                        self.site_balance[self.sites] += earned
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
                "autopilot": self.autopilot, "site_names": self.site_names,
                "online": {"asked": self.online_asked, "joined": self.online_joined,
                           "name": self.online_name, "token": self.online_token},
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
            self.pal_serial += 1  # a real identity: id() of a freed palette can be reused
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
        return sum(tier_income(t, n, c, k) * crew_multiplier(self.site_staff[k][t])
                   for t, (n, c) in enumerate(zip(self.site_owned[k], self.site_chips[k])))

    def crew_bonus(self, k: int) -> int:
        """Percent income bonus from data center k's crew."""
        return STAFF_BONUS * sum(level + 1 for level in self.site_staff[k] if level >= 0)

    @property
    def staff_bonus(self) -> int:
        return self.crew_bonus(self.cur)

    @property
    def read_only(self) -> bool:
        """You are looking at a decommissioned data center: view only, nothing earns there."""
        return self.cur != self.sites

    def site_label(self, k: int) -> str:
        return (self.site_names[k].strip() if k < len(self.site_names) else "") or site_name(k)

    def guard_read_only(self) -> bool:
        if self.read_only:
            self.say(f"#{self.cur + 1} is decommissioned: view only "
                     f"(your live data center is #{self.sites + 1})", self.pal.muted)
            self.redraw()
        return self.read_only

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
        yield Static("1-0 pick  s c h d b views  x relocate  f fix  m menu  q quit",
                     id="hint")

    def _display(self, screen: Any, renderable: Any) -> None:
        super()._display(screen, crop_update(renderable))

    def on_mount(self) -> None:
        self.query_one("#stats").border_title = "OVERVIEW"
        self.query_one("#log").border_title = "ACTIVITY"
        self.theme = (self.saved_theme if self.saved_theme in self.available_themes
                      else DEFAULT_THEME)
        self._pal = None  # rebuild colours for the theme we just applied
        self.theme_changed_signal.subscribe(self, self.on_theme_changed)
        log = self.query_one(RichLog)
        log.write("Welcome. Buy servers with keys 1-9 and 0. Press m for the menu.")
        if self.away[1] > 0:
            log.write(Text(
                f"Welcome back! Away {fmt_duration(self.away[0])}, "
                f"earned ${fmt(self.away[1])} ({OFFLINE_NUM * 100 // OFFLINE_DEN}% offline rate)",
                style=rgb(self.pal.warning)))
        self.set_interval(1.0, self.tick)  # the game tick; animation has its own clock
        self.redraw()
        if ONLINE and not self.online_asked:
            self.call_after_refresh(self.ask_to_join)

    def on_resize(self, event: events.Resize) -> None:
        self.redraw()  # titles and windows depend on the size

    def on_unmount(self) -> None:
        self.stop_clock()

    def on_theme_changed(self, _theme: object) -> None:
        self._pal = None
        STYLES.clear()
        self._hall_sig = None  # forget the cached hall picture: it holds the old colours
        hall = self.query_one(Hall)
        hall._rows, hall._base_key = None, None
        hall._strips = {}
        self.redraw()
        self.save()

    # -- game loop ---------------------------------------------------------

    def tick(self) -> None:
        if not self.is_running:  # the timer can fire while the app is shutting down
            return
        view = self.cur
        self.cur = self.sites  # the live data center keeps working while you look at an old one
        try:
            self.balance += self.income
            self.phase += 1
            self.run_autopilot()
            self.update_crisis()
        finally:
            self.cur = view
        self.foreground = tmux_foreground()
        self.anim_tick()
        if ONLINE and self.foreground:
            if self.phase % 5 == 0:
                self.maybe_submit()
            if self.side == "board" and self.phase % 30 == 0:
                self.refresh_board()
        if self.foreground or self.phase % BACKGROUND_REFRESH == 0:
            self.redraw()  # coming back to the front redraws on the very next tick
        self.save()

    def run_autopilot(self) -> None:
        """Each specialist buys for its own tier: servers from Lv2, chips from Lv6."""
        if not self.autopilot:
            return
        cheap = self.site_income(self.cur) // AUTO_AFFORD_DIV  # the most one purchase may cost
        for t, level in enumerate(self.staff):
            if level < AUTO_SERVERS_LEVEL:
                continue
            for _ in range(AUTO_BUYS_PER_TICK):
                cost = cost_of(t, self.owned[t], self.cur)
                if self.owned[t] >= MAX_OWNED or self.balance < cost or cost > cheap:
                    break
                self.balance -= cost
                self.owned[t] += 1
            if level >= AUTO_CHIPS_LEVEL and self.owned[t] > 0 and self.chips[t] < MAX_CHIP:
                cost = chip_cost(t, self.chips[t], self.cur)
                if self.balance >= cost and cost <= cheap:
                    self.balance -= cost
                    self.chips[t] += 1

    def action_autopilot(self) -> None:
        self.autopilot = not self.autopilot
        self.say("Autopilot ON: trained specialists buy for their tier" if self.autopilot
                 else "Autopilot OFF: you buy everything yourself",
                 self.pal.success if self.autopilot else self.pal.muted)
        self.redraw()
        self.save()

    # -- animation ---------------------------------------------------------

    @property
    def animating(self) -> bool:
        """Animate only the live data center, and only in a pane that is in front."""
        return ANIM and self.foreground and not self.read_only

    def top_tier(self) -> int | None:
        """The tier earning the most right now (None in an empty hall)."""
        best = max(range(len(TIERS)), key=lambda t: tier_income(
            t, self.owned[t], self.chips[t], self.cur) * crew_multiplier(self.staff[t]))
        return best if self.owned[best] else None

    def add_fx(self, kind: str, life: float, **kw: Any) -> None:
        self.fx_seq += 1
        self.now = clock()
        self.fx.append(Fx(kind, mix32(self.fx_seq, self.phase), life, self.now, **kw))

    def sparkle(self, tier: int, big: bool = False) -> None:
        """A burst around a rack: a small one for a purchase, a big one for a milestone."""
        if self.animating:
            self.add_fx("spark", SPARK_LIFE_S, tier=tier, big=big)
            self.sync_clock()

    def anim_tick(self) -> None:
        """Once a second: make sure the frame clock matches whether we are in front (this
        reads self.foreground, which tick() cached: frames never ask tmux)."""
        if not self.animating:
            self.clear_fx()
            return
        self.now = clock()
        self.expire_fx()
        self.sync_clock()

    def expire_fx(self) -> None:
        """Drop every effect whose time is up (compares against self.now)."""
        self.fx = [fx for fx in self.fx if self.now - fx.born < fx.life]
        if self.cash_flash and self.now - self.cash_t0 >= CASH_FLASH_S:
            self.cash_flash = 0
        if self.resolve_t0 is not None and self.now - self.resolve_t0 >= RESOLVE_S:
            self.resolve_t0 = None
        if self.reloc is not None and self.now - self.reloc["t0"] >= RELOC_S:
            self.reloc = None

    def needs_frames(self) -> bool:
        """Does anything on screen move? An empty, calm hall costs no frames at all."""
        return self.animating and bool(
            sum(self.owned) or self.fx or self.crisis or self.resolve_t0 is not None
            or self.cash_flash or self.reloc is not None)

    def sync_clock(self) -> None:
        """Run the single frame timer exactly while there is something to animate."""
        if self.is_running and self.needs_frames():
            if self._anim_timer is None:
                self._anim_timer = self.set_interval(FRAME_S, self.anim_frame)
        else:
            self.stop_clock()

    def stop_clock(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None

    def anim_frame(self) -> None:
        """One animation frame: advance the clock, then repaint only what moves."""
        if not (self.is_running and self.animating):  # also fires while shutting down
            self.clear_fx()
            return
        self.now = clock()
        self.expire_fx()
        self.draw_cash()
        self.draw_alert()
        self.draw_hall()
        self.sync_clock()

    def clear_fx(self) -> None:
        """Drop every effect (background pane, old data center, animation off)."""
        self.fx.clear()
        self.cash_flash = 0
        self.resolve_t0 = None
        self.reloc = None
        self.stop_clock()

    def alert_banner(self, msg: str) -> Text:
        """The crisis banner: it pulses red on a smooth sine while it lasts, then fades
        calmly to green once fixed. Text contrast is re-checked on every frame."""
        p = self.pal
        if not self.animating:
            self._set_alert_bg(None)
            return Text(msg)
        calm = self.crisis is None
        # Dim as far as the text colour still reads on it: the fade is as deep as this
        # theme allows without the text having to change colour mid-fade.
        hi = p.success if calm else p.error
        lo = hi
        for k in (0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1):
            if k <= (0.8 if calm else 0.6) and contrast(p.bg, mix(hi, p.bg, k)) >= BANNER_MIN_CONTRAST:
                lo = mix(hi, p.bg, k)
                break
        if calm:  # fades out as the fix settles
            bg = mix(hi, lo, ease_out((self.now - (self.resolve_t0 or self.now)) / RESOLVE_S))
        else:  # pulses on a sine
            bg = mix(lo, hi, sine01(self.now, BANNER_PERIOD_S))
        end = max(((0, 0, 0), (255, 255, 255)),
                  key=lambda e: min(contrast(e, lo), contrast(e, hi)))  # one end for the whole fade
        # Text is the theme background colour when that reads over the whole fade, else a
        # fixed black/white: it never flips mid-pulse. Contrast is re-checked every frame.
        base = p.bg if min(contrast(p.bg, lo), contrast(p.bg, hi)) >= BANNER_MIN_CONTRAST else end
        fg = ensure_contrast(base, bg, BANNER_MIN_CONTRAST, end)
        self._set_alert_bg(bg)
        width = max(0, self.size.width - 4)
        if len(msg) + 10 <= width and not calm:
            msg = f"▓▒░ {msg} ░▒▓"
        return Text(msg.ljust(width), style=f"bold {rgb(fg)} on {rgb(bg)}")

    def _set_alert_bg(self, bg: RGB | None) -> None:
        if bg == self._alert_bg:
            return
        self._alert_bg = bg
        alert = self.query_one("#alert", Static)
        if bg is None:
            alert.styles.clear_rule("background")
        else:
            alert.styles.background = rgb(bg)

    # -- online leaderboard ------------------------------------------------

    def net(self, work: Callable[[], Any], done: Callable[[Any], None]) -> None:
        """Run `work` on a thread so a slow or dead server never freezes the game."""
        def run() -> None:
            result = work()
            try:
                self.call_from_thread(done, result)
            except Exception:  # the app may already have closed
                pass
        threading.Thread(target=run, daemon=True).start()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """While a dialog is open the game's own keys do nothing (typing a name must never
        buy servers). Quit, the command palette and theme changes still work."""
        ours = {"pick", "view", "hall", "shop", "site", "expand", "fix", "autopilot", "join",
                "menu", "rename"}
        if action in ours and isinstance(self.screen, ModalScreen):
            return False
        return True

    def action_menu(self) -> None:
        """m / escape: the game menu, where the leaderboard can be joined or left at any time."""
        joined = self.online_joined
        self.push_screen(Menu([
            ("board", f"Leaderboard: {'leave it' if joined else 'join'}", ONLINE),
            ("boardname", "Change my leaderboard name", ONLINE and joined),
            ("rename", f"Rename data center #{self.cur + 1}", True),
            ("auto", f"Crew autopilot: {'ON' if self.autopilot else 'OFF'} (switch)", True),
            ("theme", "Change theme", True),
            ("quit", "Save and quit", True),
        ]), self.on_menu)

    def on_menu(self, choice: str | None) -> None:
        if choice == "board":
            self.action_join()
        elif choice == "boardname":
            self.push_screen(NameInput(self.online_name), self.on_name_chosen)
        elif choice == "rename":
            self.action_rename()
        elif choice == "auto":
            self.action_autopilot()
        elif choice == "theme":
            self.search_themes()
        elif choice == "quit":
            self.save()
            self.exit()

    def action_rename(self) -> None:
        """n: give the data center you are looking at your own name (blank = the default)."""
        k = self.cur
        self.push_screen(
            NameInput(self.site_names[k], title=f"Name data center #{k + 1}", rule=DC_NAME_RE,
                      max_len=24, placeholder=f"blank = {site_name(k)}",
                      complaint="Use up to 24 plain characters", keys="[enter] save    [esc] cancel"),
            lambda name: self.on_site_named(k, name))

    def on_site_named(self, k: int, name: str | None) -> None:
        if name is None:
            return
        self.site_names[k] = name
        self.say(f"Data center #{k + 1} is now '{self.site_label(k)}'", self.pal.success)
        self.redraw()
        self.save()

    def ask_to_join(self) -> None:
        host = SERVER.split("//", 1)[-1]
        self.push_screen(YesNo(
            "Join the online leaderboard?",
            "Compete with other players. If you join, your chosen name, your Fame and your "
            f"number of data centers are sent to {host} and shown on a public board.\n"
            "Nothing else is sent. You can leave at any time (press j)."), self.on_join_answer)

    def on_join_answer(self, yes: bool | None) -> None:
        self.online_asked = True
        if yes:
            self.push_screen(NameInput(self.online_name), self.on_name_chosen)
        else:
            self.say("Leaderboard off. Press j to join any time.", self.pal.muted)
            self.save()

    def on_name_chosen(self, name: str | None) -> None:
        self.online_asked = True
        if not name:
            self.say("Not joined. Press j to join any time.", self.pal.muted)
            self.save()
            return
        self.online_name = name
        if not self.online_token:
            self.online_token = secrets.token_hex(16)  # your private key to your own row
        self.online_joined = True
        self._last_sent = None
        self.side = "board"
        self.say(f"Joining the leaderboard as {name}...", self.pal.success)
        self.maybe_submit(force=True)
        self.refresh_board(force=True)
        self.redraw()
        self.save()

    def action_join(self) -> None:
        """j: join the leaderboard, or leave it if you are already on it."""
        if not ONLINE:
            self.say("Online features are off (DC_ONLINE=0).", self.pal.muted)
        elif self.online_joined:
            self.push_screen(YesNo("Leave the leaderboard?",
                                   "Your entry is deleted from the server. You can join again later."),
                             self.on_leave_answer)
        else:
            self.push_screen(NameInput(self.online_name), self.on_name_chosen)

    def on_leave_answer(self, yes: bool | None) -> None:
        if not yes:
            return
        token = self.online_token
        self.online_joined = False
        self.board = None
        self.say("Left the leaderboard.", self.pal.muted)
        self.save()
        self.net(lambda: api("POST", "/api/leave", {"token": token}), lambda _res: None)
        self.redraw()

    def maybe_submit(self, force: bool = False) -> None:
        if not (ONLINE and self.online_joined) or self._net_busy or self.fame > MAX_FAME_ONLINE:
            return
        snapshot = (self.fame, self.sites, self.online_name)
        now = time.time()
        if not force and (snapshot == self._last_sent or now - self._last_attempt < SUBMIT_EVERY):
            return
        payload = {"token": self.online_token, "name": self.online_name,
                   "fame": self.fame, "sites": self.sites}
        self._net_busy, self._last_attempt = True, now
        self.net(lambda: api("POST", "/api/submit", payload),
                 lambda res: self.on_submit(res, snapshot))

    def on_submit(self, res: tuple[int, dict[str, Any]], snapshot: tuple[int, int, str]) -> None:
        self._net_busy = False
        status, body = res
        if status == 200:
            self._last_sent = snapshot
            if self.side == "board":
                self.refresh_board(force=True)
        elif status == 409:
            self.online_joined = False
            self.say(f"! the name '{self.online_name}' is taken", self.pal.error)
            self.save()
            self.push_screen(NameInput(self.online_name, "That name is taken, pick another"),
                             self.on_name_chosen)
        elif status == 400:
            self._last_sent = snapshot  # don't keep resending data the server refuses
            self.say(f"! the leaderboard rejected the score ({body.get('error', 'bad data')})",
                     self.pal.error)
        # offline (0), 429 or 5xx: simply try again later

    def refresh_board(self, force: bool = False) -> None:
        if not ONLINE or self._board_busy:
            return
        if not force and time.monotonic() - self._board_at < 5:
            return  # holding the key must not hammer the server
        self._board_at = time.monotonic()
        self._board_busy = True
        token = self.online_token if self.online_joined else ""

        def work() -> tuple[tuple[int, dict[str, Any]], tuple[int, dict[str, Any]]]:
            top = api("GET", "/api/leaderboard?limit=30")
            me = api("POST", "/api/me", {"token": token}) if token else (0, {})
            return top, me

        self.net(work, self.on_board)

    def on_board(self, res: tuple[tuple[int, dict[str, Any]], tuple[int, dict[str, Any]]]) -> None:
        self._board_busy = False
        (status, top), (me_status, me) = res
        if status == 200 and isinstance(top.get("players"), list):
            self.board = {"players": top["players"], "total": top.get("total", 0), "at": time.time(),
                          "me": me if me_status == 200 else None}
        elif self.board is not None:
            self.board["error"] = True
        else:
            self.board = {"players": [], "total": 0, "at": 0.0, "me": None, "error": True}
        self.redraw()

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
        if self.animating:
            self.now = clock()
            self.resolve_t0, self.resolved = self.now, f"✓ {who} fixed '{title}'"
            self.sync_clock()
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
        self.shop_top = None
        if name == "board":
            self.refresh_board()
        self.redraw()

    def window(self, count: int, frontier: int) -> tuple[int, int]:
        """(first row, row count) of a two-line-per-row card that fits the card's height,
        by default showing your furthest tier and the next two."""
        height = max(2, self.query_one("#shop").size.height)
        n = max(1, min(count, height // 2))
        top = max(0, min(count - n, frontier + 3 - n))
        if self.shop_top is not None:
            top = max(0, min(count - n, self.shop_top))
        self._note = f" · {top + 1}-{top + n}/{count}" if n < count else ""
        return top, n

    def action_shop(self, delta: int) -> None:
        """, and . scroll the marketplace / chips / crew card when it has more rows than fit."""
        if self.side not in ("servers", "chips", "staff"):
            return
        frontier = {"servers": self.frontier(self.owned), "chips": self.frontier(self.owned),
                    "staff": self.frontier([l + 1 for l in self.staff])}[self.side]
        top, _ = self.window(len(TIERS), frontier)
        self.shop_top = max(0, top + delta)
        self.redraw()

    @staticmethod
    def frontier(counts: list[int]) -> int:
        return max((i for i, n in enumerate(counts) if n > 0), default=0)

    def action_hall(self, how: str) -> None:
        """Scroll the data hall: up/down one block (a tier header or a rack row), pageup/
        pagedown a screenful, home/end to the ends (the bottom follows new racks)."""
        lay = self.query_one(Hall).rack_layout()
        last, blocks = lay.max_start, lay.blocks
        back = next((i for i, b in enumerate(blocks) if b.line0 >= lay.top_line - lay.height), 0)
        target = {"up": lay.start - 1, "down": lay.start + 1,
                  "pageup": min(back, lay.start - 1), "pagedown": max(lay.end, lay.start + 1),
                  "home": 0, "end": last}[how]
        target = max(0, min(last, target))
        self.hall_scroll = None if target >= last else target
        self.redraw()

    def action_pick(self, i: int) -> None:
        if self.side == "servers":
            self.action_buy(i)
            return
        if self.side == "sites":  # key N opens data center #N (page 2 shows #7-#12, ...)
            k = self.cur // 6 * 6 + i
            if i < 6 and k <= self.sites:
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
        if self.guard_read_only():
            return
        p, cost = self.pal, cost_of(tier, self.owned[tier], self.cur)
        if self.owned[tier] >= MAX_OWNED:
            self.say(f"{TIERS[tier][0]}: that's enough, truly", p.muted)
        elif self.balance >= cost:
            before = milestone_mult(self.owned[tier])
            self.balance -= cost
            self.owned[tier] += 1
            self.sparkle(tier, milestone_mult(self.owned[tier]) > before)
            self.say(f"+ {TIERS[tier][0]}  -${fmt(cost)}", p.success)
        else:
            self.say(f"! need ${fmt(cost)} for {TIERS[tier][0]}", p.error)
        self.redraw()
        self.save()

    def buy_chip(self, tier: int) -> None:
        if self.guard_read_only():
            return
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
            self.sparkle(tier)
            self.say(f"+ {chip_name(tier, level)}: {TIERS[tier][0]} income x{CHIP_BOOST}",
                     p.success)

    def hire_staff(self, role: int) -> None:
        if self.guard_read_only():
            return
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
        self.sparkle(role)
        if level < 0:
            self.say(f"+ Hired a {name}: {tagline} (runs {TIERS[role][0]})", p.success)
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
            self.site_names.append("")
            self.cur = self.sites
            self.crisis = None
            self.hall_scroll = None
            self.shop_top = None
            self.side = "servers"
            self.say(f"★ Relocated to {self.site_label(self.sites)}! +{fmt(gain)} Fame "
                     f"(+{fmt(FAME_BONUS * gain)}% income)", p.success)
            after = rank_of(self.fame)[0]
            if after != before:
                self.say(f"★ Promoted: {after}!", p.warning)
            if self.animating:
                self.fx.clear()
                self.now = clock()
                self.reloc = {"t0": self.now, "gain": gain,
                              "rank": after if after != before else None}
                self.sync_clock()
            self.maybe_submit(force=True)
        self.redraw()
        self.save()

    def goto_site(self, k: int) -> None:
        if 0 <= k <= self.sites and k != self.cur:
            self.cur = k
            self.hall_scroll = None
            where = f"Now at #{k + 1} {self.site_label(k)}"
            self.say(where + (" (decommissioned, view only)" if k != self.sites else ""),
                     self.pal.muted)
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

    def set_subtitle(self, wid: str, subtitle: str) -> None:
        """Like set_title, for the text on a card's bottom border."""
        if self._titles.get(wid + ":sub") != subtitle:
            self._titles[wid + ":sub"] = subtitle
            self.query_one(wid).border_subtitle = subtitle

    def draw_cash(self) -> None:
        """The balance; after a change it flashes and eases back to the normal colour."""
        p = self.pal
        tint = None
        if self.cash_flash:
            base = mix(p.success, p.fg, 0.7) if self.cash_flash > 0 else p.warning
            tint = mix(base, p.fg, smoothstep((self.now - self.cash_t0) / CASH_FLASH_S))
        self.set_text("#cash", Text.assemble(
            ("$ ", rgb(p.muted)), (fmt(self.balance), f"bold {rgb(tint)}") if tint
            else fmt(self.balance)))

    def draw_alert(self) -> None:
        c = self.crisis
        show = c is not None or self.resolve_t0 is not None
        alert = self.query_one("#alert", Static)
        if alert.display != show:  # re-assigning it forces a repaint
            alert.display = show
        if c is not None:
            num, den = CRISIS_FACTOR[c["sev"]]
            who = (f"{STAFF[c['fixer']][0]} responding ({c['eta']}s)"
                   if c["fixer"] is not None else "press F to fix")
            self.set_text("#alert", self.alert_banner(
                f"⚠ {c['title']}  ·  income -{100 - num * 100 // den}%  ·  {who}"))
        elif show:
            self.set_text("#alert", self.alert_banner(self.resolved))

    def draw_hall(self) -> None:
        """Repaint the hall only if its look changed: the signature holds the layout plus
        the current frame number while anything moves."""
        anim = self.animating
        moving = anim and bool(sum(self.owned) or self.fx or self.reloc)
        sig = (self.cur, self.sites, tuple(self.owned), self.crisis is not None, self.pal_serial,
               tuple(self.chips), self.hall_scroll, self.query_one(Hall).size, int(self.now * ANIM_FPS) if moving else 0, anim,
               tuple((f.kind, f.seed) for f in self.fx), self.reloc is not None)
        if sig != self._hall_sig:  # a static hall costs nothing to leave alone
            self._hall_sig = sig
            self.query_one(Hall).update_rows()

    def redraw(self) -> None:
        p = self.pal
        self.now = clock()
        if not self.animating:
            self.clear_fx()
        else:
            self.expire_fx()
        if self.animating and self.balance != self._seen_balance:
            self.cash_flash = 1 if self.balance > self._seen_balance else -1
            self.cash_t0 = self.now
        self._seen_balance = self.balance
        self.draw_cash()

        rank, rank_need, _ = rank_of(self.fame)
        self.set_text("#title", Text.assemble(
            "◆ MY DATA CENTER", ("  ·  ", rgb(p.muted)), (rank, f"bold {rgb(p.success)}")))

        stats = Text()
        if self.read_only:
            stats.append("Final   ", rgb(p.muted))
            stats.append(f"${fmt(self.site_income(self.cur))}/s", f"bold {rgb(p.muted)}")
            stats.append("  decommissioned\n", rgb(p.muted))
        else:
            stats.append("Income  ", rgb(p.muted))
            stats.append(f"${fmt(self.income)}/s",
                         f"bold {rgb(p.error if self.crisis else p.warning)}")
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
            stats.append("■", rgb(colour) if n else rgb(p.faint))
        stats.append(" Crew ", rgb(p.muted))
        for level, initial in zip(self.staff, CREW_INITIALS):
            stats.append(initial, rgb(p.success) if level >= 0 else rgb(p.faint))
        stats.append("\nStatus  ", rgb(p.muted))
        stats.append(rank, f"bold {rgb(p.success)}")
        progress = f" ({fmt(self.fame)}/{fmt(rank_need)})"
        if len("Status  " + rank + progress) <= ROW_W:  # drop it rather than wrap
            stats.append(progress, rgb(p.muted))
        self.set_text("#stats", stats)

        self._note = ""
        body = {"servers": self.servers_text, "chips": self.chips_text, "staff": self.staff_text,
                "sites": self.sites_text, "board": self.board_text}[self.side]()
        ro = " · view only" if self.read_only else ""
        titles = {"servers": f"MARKETPLACE{ro}{self._note}  [s]",
                  "chips": f"CHIP UPGRADES{ro}{self._note}  [c]",
                  "staff": (f"CREW{ro}{self._note}  [h]" if self.read_only else
                            f"CREW +{self.staff_bonus}% · auto {'ON' if self.autopilot else 'OFF'}"
                            f"{self._note}  [h]"),
                  "sites": "DATA CENTERS  [d]", "board": "LEADERBOARD  [b]"}
        self.set_title("#shop", titles[self.side])
        self.set_text("#shop", body)

        self.draw_alert()

        lay = self.query_one(Hall).rack_layout()
        lead, racks = f"#{self.cur + 1} {self.site_label(self.cur)}", f" · {sum(self.owned):,} racks"
        dead = " · DECOMMISSIONED" if self.read_only else ""
        pos, short, cues = "", "", ""
        if lay.scrolled and lay.start < lay.end:
            shown = [b.row + 1 for b in lay.blocks[lay.start:lay.end] if b.kind == "rack"]
            if shown:
                pos = f" · rows {shown[0]}-{shown[-1]} of {lay.total_rows} ↑↓"
                short = f" · {shown[0]}-{shown[-1]}/{lay.total_rows}"
            cues = " · ".join(c for c, more in (("▲ more", lay.start > 0),
                                                ("▼ more", lay.end < len(lay.blocks))) if more)
        room = self.query_one(Hall).size.width - 4  # what fits in the border
        title = lead + racks + dead + pos
        if pos and len(title) > room:  # lose, in turn: the rack count, "rows ... ↑↓", the label, the name
            for tail in (dead + pos, dead + short, short):
                title = lead + tail
                if len(title) <= room:
                    break
            else:
                title = lead[:max(1, room - len(short) - 1)] + "…" + short
        self.set_title("#hall", title)
        self.set_subtitle("#hall", f" {cues} " if cues else "")
        self.draw_hall()
        self.sync_clock()

    def row(self, text: Text, index: int, name: str, badge: str, accent: str,
            name_style: str, badge_style: str, pips: Text | None = None) -> None:
        text.append(f" {index % 10} ", f"bold {rgb(self.pal.chip_text)} on {accent}")  # the 10th key is 0
        extra = len(pips) + 1 if pips else 0  # the chip pips and a space, between name and badge
        room = ROW_W - 5 - len(badge) - extra - 1
        if len(name) > room:
            name = name[:room - 1] + "…"
        text.append(f"  {name}", name_style)
        text.append(" " * max(1, ROW_W - 5 - len(name) - len(badge) - extra))
        if pips:
            text.append_text(pips)
            text.append(" ")
        text.append(badge + "\n", badge_style)

    def pips_text(self, tier: int, level: int) -> Text:
        """The chip level as 5 mini bars, one per family, each filling in 4 steps (so it is
        the same picture as the pips under every rack of the tier)."""
        p = self.pal
        colour = p.muted if self.read_only else p.tiers[tier]
        out = Text()
        for step in chip_pips(level):
            out.append(PIP_GLYPHS[step], rgb(colour) if step else rgb(p.faint))
        return out

    def servers_text(self) -> Text:
        p, shop = self.pal, Text()
        top, n = self.window(len(TIERS), self.frontier(self.owned))
        for i in range(top, top + n):
            name = TIERS[i][0]
            cost = cost_of(i, self.owned[i], self.cur)
            ok = self.balance >= cost and not self.read_only
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, f"x{self.owned[i]}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if self.owned[i] else rgb(p.faint))
            each = tier_income(i, 1, self.chips[i], self.cur)
            milestone = next_milestone(self.owned[i])
            tail = f" · x2@{milestone}" if milestone else ""
            cost_s, each_s = fmt(cost), fmt(each)
            for decimals in (2, 1, 0):  # big numbers lose decimals rather than wrap
                cost_s, each_s = fmt(cost, decimals), fmt(each, decimals)
                if len(f"     ${cost_s} · +${each_s}/s{tail}") <= ROW_W:
                    break
            shop.append("     ")
            shop.append(f"${cost_s}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            shop.append(f" · +${each_s}/s", rgb(p.muted))
            shop.append(tail + "\n", rgb(p.warning))
        return shop

    def chips_text(self) -> Text:
        p, shop = self.pal, Text()
        top, n = self.window(len(TIERS), self.frontier(self.owned))
        for i in range(top, top + n):
            tier = TIERS[i][0]
            level = self.chips[i]
            maxed = level >= MAX_CHIP
            name = chip_name(i, min(level, MAX_CHIP - 1))
            cost = 0 if maxed else chip_cost(i, level, self.cur)
            ok = not maxed and self.owned[i] > 0 and self.balance >= cost and not self.read_only
            accent = rgb(p.tiers[i]) if ok else rgb(p.muted)
            self.row(shop, i + 1, name, "MAX" if maxed else f"L{level}", accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.success) if maxed else rgb(p.fg) if level else rgb(p.faint),
                     self.pips_text(i, level))
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
        top, n = self.window(len(STAFF), self.frontier([l + 1 for l in self.staff]))
        for r in range(top, top + n):
            name, _, _, cap, _ = STAFF[r]
            level = self.staff[r]
            maxed = level >= MAX_STAFF
            cost = 0 if maxed else staff_cost(r, level, self.cur)
            ok = not maxed and self.balance >= cost and not self.read_only
            accent = rgb(p.success) if ok else rgb(p.muted)
            badge = "hire" if level < 0 else "MAX" if maxed else f"Lv{level}"
            self.row(shop, r + 1, name, badge, accent,
                     f"bold {accent}" if ok else rgb(p.muted),
                     rgb(p.fg) if level >= 0 else rgb(p.faint))
            shop.append("     ")
            scope = STAFF_SCOPE[cap - 1]
            if maxed:
                shop.append(f"all perks · fixes in {response_secs(r, level)}s\n", rgb(p.success))
                continue
            shop.append(f"${fmt(cost)}", f"bold {rgb(p.success)}" if ok else rgb(p.error))
            if level < 0:
                shop.append(f" · fixes {scope}\n", rgb(p.muted))
            else:  # what the next level of training unlocks
                nxt = next(((lv, text) for lv, text in PERKS if lv > level), None)
                shop.append(f" · Lv{nxt[0]}: {nxt[1]}\n" if nxt else
                            f" · fixes in {response_secs(r, level + 1)}s\n", rgb(p.muted))
        return shop

    def board_text(self) -> Text:
        p, t = self.pal, Text()
        if not ONLINE:
            t.append("Online features are off (DC_ONLINE=0).\n", rgb(p.muted))
            return t
        board = self.board
        me = board.get("me") if board else None
        if self.online_joined:
            if me and me.get("registered"):
                t.append(f"You: #{me['rank']} of {me['total']} · {self.online_name}"[:ROW_W] + "\n",
                         f"bold {rgb(p.success)}")
            else:
                t.append(f"You: {self.online_name} (sending...)\n", f"bold {rgb(p.success)}")
        else:
            t.append("You are not on the board.\n", rgb(p.fg))
            t.append("Press j to join (asks for a name).\n", rgb(p.muted))
        height = max(4, self.query_one("#shop").size.height)
        used = 2 + 1  # header + footer
        if board is None:
            t.append("Loading...\n", rgb(p.muted))
        elif not board["players"] and board.get("error"):
            t.append("Could not reach the server.\n", rgb(p.error))
        elif not board["players"]:
            t.append("Nobody has joined yet. Be the first!\n", rgb(p.muted))
        else:
            if self.online_joined:
                t.append("\n")
            for pl in board["players"][:max(1, height - used)]:
                try:
                    fame, sites = fmt(int(pl["fame"])), int(pl["sites"]) + 1
                    rank, name = int(pl["rank"]), str(pl["name"])
                except (KeyError, ValueError, TypeError):
                    continue
                if not NAME_RE.fullmatch(name):  # a server could send terminal escape codes
                    continue
                mine = self.online_joined and name.lower() == self.online_name.lower()
                row = f"{'▶' if mine else ' '}{rank:>2} {name[:16]:<16} {fame:>8} #{sites}"
                t.append(row[:ROW_W] + "\n", f"bold {rgb(p.success)}" if mine else rgb(p.fg))
        if board and board["at"]:
            age = int(time.time() - board["at"])
            stale = " · offline" if board.get("error") else ""
            t.append(f"updated {age}s ago{stale} · j: {'leave' if self.online_joined else 'join'}",
                     rgb(p.faint))
        return t

    def sites_text(self) -> Text:
        p, t, newest = self.pal, Text(), self.sites
        first = self.cur // 6 * 6  # six per page; the page follows the one you are in
        for row, k in enumerate(range(first, min(first + 6, newest + 1))):  # keys 1-6, oldest first
            here = k == self.cur
            inc = f"${fmt(self.site_income(k))}/s"
            nm, room = f"#{k + 1} {self.site_label(k)}", ROW_W - 6 - len(inc)
            if len(nm) > room:  # only cut what must be cut
                nm = nm[:room - 1] + "…"
            chip = rgb(p.success) if here else rgb(p.muted)
            t.append(f" {row + 1} ", f"bold {rgb(p.chip_text)} on {chip}")
            t.append("▶" if here else " ", f"bold {rgb(p.success)}")  # where you are looking
            t.append("●" if k == newest else " ", rgb(p.success))  # the one that is live
            t.append(nm, f"bold {rgb(p.primary)}" if here else rgb(p.fg))
            t.append(" " * max(1, ROW_W - 5 - len(nm) - len(inc)))
            t.append(inc + "\n", rgb(p.warning) if k == newest else rgb(p.faint))
        if newest > 5:
            t.append(f"     #{first + 1}-{min(first + 6, newest + 1)} of {newest + 1}"
                     f"  ·  [ ] to move\n", rgb(p.faint))
        t.append("● live · the others are decommissioned\n", rgb(p.faint))
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


def main(argv: list[str] | None = None) -> None:
    global ONLINE, ANIM
    parser = argparse.ArgumentParser(
        prog="data-center-tui", description="A pixel-art idle tycoon for your terminal.",
        epilog="Environment: DC_SAVE (save file), DC_ONLINE=0 (no online features), "
               "DC_SERVER (leaderboard server URL), DC_ANIM=0 (no animation), DC_ANIM_FPS (4-30, default 12).")
    parser.add_argument("--version", action="version", version=f"data-center-tui {__version__}")
    parser.add_argument("--no-online", action="store_true",
                        help="never contact the leaderboard server (same as DC_ONLINE=0)")
    parser.add_argument("--no-anim", action="store_true",
                        help="turn off all animation and colour effects (same as DC_ANIM=0)")
    parser.add_argument("--save", metavar="FILE", help="use this save file instead of the default")
    args = parser.parse_args(argv)
    if args.no_online:
        ONLINE = False
    if args.no_anim:
        ANIM = False
    if args.save:
        os.environ["DC_SAVE"] = args.save
    DataCenter().run(mouse=False)  # keyboard-only: don't grab the mouse from tmux


if __name__ == "__main__":
    main()
