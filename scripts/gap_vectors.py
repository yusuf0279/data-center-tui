#!/usr/bin/env python3
"""Write rust/core/tests/data/gap_vectors.json.gz: expected values for the Rust economy tests
that kill the surviving mutants (fixer tie-break, isqrt fame, 1/120 crisis dice, severity gates).

Everything is computed by the REAL committed Python game (headless, DC_ONLINE=0), taken from
a checkout of the committed tree (default /mnt/bigvolume/dc-e66, override with DC_PY_ROOT).
Run: python3 scripts/gap_vectors.py
"""
import asyncio
import itertools
import importlib
import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

from gzjson import write_gz


def import_game(root: Path) -> Any:
    """Import `game` from the checkout at `root` (new name, or the old one in older commits)."""
    name = "build_a_hyperscaler" if (root / "build_a_hyperscaler").is_dir() else "data_center_tui"
    module = importlib.import_module(f"{name}.game")
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    return module


HERE = Path(__file__).resolve().parent.parent
PY_ROOT = Path(os.environ.get("DC_PY_ROOT", "/mnt/bigvolume/dc-e66"))
OUT = HERE / "rust" / "core" / "tests" / "data" / "gap_vectors.json.gz"
sys.path.insert(0, str(PY_ROOT))
os.environ["DC_ONLINE"] = "0"
os.environ["DC_SAVE"] = str(Path(tempfile.mkdtemp()) / "save.json")

dc = import_game(PY_ROOT)  # noqa: E402


NROLES = len(dc.STAFF)
NTIERS = len(dc.TIERS)


class ScriptedRng:
    """Fake random.Random: kinds r = random(), w = choices -> index, i = choice -> index."""

    def __init__(self) -> None:
        self.queue: list[tuple[str, float | int]] = []
        self.calls: list[list[Any]] = []

    def take(self, kind: str, default: float | int, size: int) -> float | int:
        if self.queue:
            want, value = self.queue.pop(0)
            assert want == kind, (want, kind)
        else:
            value = default
        self.calls.append([kind, value, size])
        return value

    def random(self) -> float:
        return float(self.take("r", 0.5, 0))

    def choices(self, population: list[Any], weights: list[int]) -> list[Any]:
        idx = min(int(self.take("w", 0, len(weights))), len(weights) - 1)  # 99 = last entry
        self.calls[-1][1] = idx
        return [population[idx]]

    def choice(self, seq: list[Any]) -> Any:
        return seq[int(self.take("i", 0, len(seq)))]


# ---------------------------------------------------------------- fame (pure)

def fame_vectors(rng: random.Random) -> list[list[Any]]:
    """[site, balance, expected] with balance // expand_cost around perfect squares."""
    roots = [1, 2, 3, 10, 2**26, 2**26 + 1, 2**27 - 1, 2**27, 2**27 + 1, 94_906_265,
             94_906_266, 2**32, 2**53 - 1, 2**53, 2**53 + 1, 2**64, 2**64 + 1, 2**100 + 1]
    roots += [10**k for k in range(1, 101)] + [10**k + 1 for k in (20, 50, 100)]
    roots += [10**k - 1 for k in (20, 50, 100)]
    roots += [rng.randrange(10**8, 10**rng.randrange(9, 101)) for _ in range(40)]
    out: list[list[Any]] = []
    for site in (0, 1, 5, 30):
        e = dc.expand_cost(site)
        for n in roots:
            for q in (n * n - 1, n * n, n * n + 1):
                for rem in (0, e - 1):  # exact quotient and the largest balance with it
                    b = q * e + rem
                    out.append([site, str(b), str(dc.fame_gain(b, site))])
    for q in (2**53, 2**53 + 1, 2**54 + 3, 2**106 - 1, 2**106):  # above 2^53, not squares
        b = q * dc.expand_cost(0)
        out.append([0, str(b), str(math.isqrt(q))])
    return out


# --------------------------------------------------------------- app plumbing

def make_site(app: Any, sites: int) -> None:
    """Make the headless app have `sites + 1` data centers with cur = sites."""
    while app.sites < sites:
        app.site_balance.append(0)
        app.site_owned.append([0] * NTIERS)
        app.site_chips.append([0] * NTIERS)
        app.site_staff.append([-1] * NROLES)
        app.site_names.append("")
        app.sites += 1
    app.cur = sites


def reset(app: Any, site: int, owned: list[int], chips: list[int], staff: list[int]) -> None:
    make_site(app, site)
    app.fame = 0
    app.crisis = None
    app.site_owned[site][:] = owned
    app.site_chips[site][:] = chips
    app.site_staff[site][:] = staff


def snap_crisis(c: Any) -> Any:
    return None if c is None else {"title": c["title"], "sev": c["sev"], "fixer": c["fixer"],
                                   "eta": c["eta"]}


def spawn_case(app: Any, rng: ScriptedRng, logs: list[str], site: int, owned: list[int],
               chips: list[int], staff: list[int], script: list[tuple[str, float | int]]) -> dict:
    reset(app, site, owned, chips, staff)
    rng.queue, rng.calls = list(script), []
    logs.clear()
    app.update_crisis()
    return {"site": site, "owned": owned, "chips": chips, "staff": staff, "script": script,
            "racks": sum(owned), "raw": str(app.raw_income(site)), "base": str(app.base_income),
            "calls": rng.calls, "crisis": snap_crisis(app.crisis), "log": list(logs)}


def fixer_case(app: Any, rng: ScriptedRng, logs: list[str], staff: list[int], sev: int) -> dict:
    reset(app, 0, [0] * NTIERS, [0] * NTIERS, staff)
    fixer = app.fixer_for(sev)
    app.crisis = {"title": "T", "sev": sev, "fixer": None, "eta": None}
    rng.queue, rng.calls = [], []
    logs.clear()
    app.update_crisis()
    return {"staff": staff, "sev": sev, "fixer": fixer, "crisis": snap_crisis(app.crisis),
            "calls": rng.calls, "log": list(logs)}


def has_tie(staff: list[int], sev: int) -> bool:
    times = [dc.response_time(r, staff[r]) for r in range(NROLES)
             if staff[r] >= 0 and dc.STAFF[r][3] >= sev]
    return bool(times) and times.count(min(times)) > 1


def fixer_configs(rng: random.Random) -> list[tuple[list[int], int]]:
    cfgs: list[tuple[list[int], int]] = []
    for sev in (1, 2, 3):  # the documented tie, with and without company
        cfgs.append(([1, -1, 0] + [-1] * 7, sev))
        cfgs.append(([1, 0, 0] + [-1] * 7, sev))
        cfgs.append(([1, 3, 0, -1, -1, -1, -1, -1, -1, -1], sev))
    pairs = [(a, la, b, lb) for a in range(NROLES) for b in range(a + 1, NROLES)
             for la in range(11) for lb in range(11)
             if dc.response_time(a, la) == dc.response_time(b, lb)]
    assert pairs, "the game has no response-time ties?"
    while len(cfgs) < 600:
        hire_p = rng.choice((0.0, 0.2, 0.4, 0.6))
        staff = [rng.randrange(0, 11) if rng.random() < hire_p else -1 for _ in range(NROLES)]
        if rng.random() < 0.6:  # force a tie between two roles (either may be the faster of all)
            a, la, b, lb = rng.choice(pairs)
            staff[a], staff[b] = la, lb
        cfgs.append((staff, rng.choice((1, 2, 3))))
    return cfgs


# --------------------------------------------------------- spawn / gates search

def search_incomes(app: Any, site: int) -> list[tuple[list[int], list[int]]]:
    """(owned, chips) layouts whose raw income is exactly 200*unit, and the closest one
    below / above it, for each rack count 3..7 (the sev-2 gate sits at 5 racks)."""
    best: dict[tuple[int, int], tuple[int, list[int], list[int]]] = {}
    unit = dc.INCOME_SCALE**site
    make_site(app, site)
    app.site_staff[site][:] = [-1] * NROLES
    for a in range(0, 12):
        for b in range(0, 8):
            for c in range(0, 6):
                for d in range(0, 3):
                    for chips3 in itertools.product(range(5), range(4), range(4)):
                        owned = [a, b, c, d] + [0] * 6
                        chips = [*chips3, 0] + [0] * 6
                        racks = a + b + c + d
                        if not 3 <= racks <= 7:
                            continue
                        app.site_owned[site][:] = owned
                        app.site_chips[site][:] = chips
                        delta = app.raw_income(site) - 200 * unit
                        key = (racks, (delta > 0) - (delta < 0))
                        if key not in best or abs(delta) < best[key][0]:
                            best[key] = (abs(delta), owned, chips)
    return [(o, c) for _, o, c in best.values()]


# ---------------------------------------------------------------------- driver

async def python_cases(rng: random.Random) -> dict[str, Any]:
    scripted = ScriptedRng()
    out: dict[str, Any] = {}
    with mock.patch.object(dc.DataCenter, "set_interval", lambda *a, **k: None):
        app = dc.DataCenter()
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause(0.1)
            app.rng = scripted
            logs: list[str] = []
            app.say = lambda text, colour: logs.append(text)  # type: ignore
            out["fixer"] = [fixer_case(app, scripted, logs, s, v) for s, v in fixer_configs(rng)]

            nodice = 1 / dc.CRISIS_MEAN
            dice = [nodice, math.nextafter(nodice, 0.0), math.nextafter(nodice, 1.0),
                    1 / (dc.CRISIS_MEAN + 1), 1 / (dc.CRISIS_MEAN - 1), 0.0, 0.5, 0.99]
            spawn: list[dict] = []
            for site in (0, 1):
                z = [0] * NTIERS
                unit = dc.INCOME_SCALE**site
                # base income threshold: income exactly 10*unit, one below, one above
                need = 10 * unit
                for owned in ([5] + [0] * 9, [4] + [0] * 9, [6] + [0] * 9, [0, 1] + [0] * 8):
                    reset(app, site, owned, z, [-1] * NROLES)
                    for v in dice:
                        spawn.append(spawn_case(app, scripted, logs, site, owned, z, [-1] * NROLES,
                                                [("r", v), ("w", 0), ("i", 0)]))
                if site:  # income exactly at / around 10 * 1000 on the scaled site
                    for a in range(3, 9):
                        owned = [a] + [0] * 9
                        for v in (nodice, math.nextafter(nodice, 0.0)):
                            spawn.append(spawn_case(app, scripted, logs, site, owned, z,
                                                    [-1] * NROLES, [("r", v), ("w", 0), ("i", 0)]))
                del need
            out["spawn"] = spawn

            gates: list[dict] = []
            for site in (0, 1):
                for owned, chips in search_incomes(app, site):
                    for w in (0, 1, 99):  # first / second / last entry of the severity pool
                        gates.append(spawn_case(app, scripted, logs, site, owned, chips,
                                                [-1] * NROLES,
                                                [("r", 0.0), ("w", w), ("i", 0)]))
            out["gates"] = gates
    return out


def main() -> None:
    rng = random.Random(20261118)
    data = asyncio.run(python_cases(rng))
    data["fame"] = fame_vectors(rng)
    data["meta"] = {"python_root": str(PY_ROOT), "crisis_mean": dc.CRISIS_MEAN}
    write_gz(OUT, json.dumps(data))
    fixers = data["fixer"]
    ties = sum(has_tie(c["staff"], c["sev"]) for c in fixers)
    spawned = sum(c["crisis"] is not None for c in data["spawn"])
    gate_pools = {}
    for g in data["gates"]:
        gate_pools.setdefault(g["calls"][1][2] if len(g["calls"]) > 1 else 0, 0)
        gate_pools[g["calls"][1][2] if len(g["calls"]) > 1 else 0] += 1
    print(f"wrote {OUT}")
    print(f"fixer configs: {len(fixers)} ({ties} with a response-time tie among eligible roles)")
    print(f"fame vectors: {len(data['fame'])}")
    print(f"spawn cases: {len(data['spawn'])} ({spawned} spawned a crisis)")
    print(f"gate cases: {len(data['gates'])}; severity pool sizes seen: {gate_pools}")


if __name__ == "__main__":
    main()
