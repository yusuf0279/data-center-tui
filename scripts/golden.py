#!/usr/bin/env python3
"""Write web/test/golden.json: exact results of game.py's pure economy functions, plus
"run": a scripted play-through of the REAL game (DataCenter, headless) that the JS port
replays step by step. The dice are a scripted fake rng; each step records the rng calls
(kind, value, size) so the JS side must make the same calls in the same order.

Big integers are written as decimal strings. Output is deterministic (seeded).
Run: python3 scripts/golden.py
"""
import asyncio
import functools
import itertools
import json
import os
import random
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["DC_ONLINE"] = "0"
os.environ["DC_SAVE"] = str(Path(tempfile.mkdtemp()) / "save.json")

from data_center_tui import game as dc  # noqa: E402  (needs the env setup above)

COST_OWNED = [0, 1, 2, 24, 25, 50, 99, 100, 500, 3999, 4000]
INCOME_OWNED = [0, 1, 2, 24, 25, 26, 49, 50, 99, 100, 199, 200, 300, 400, 500, 999, 1000,
                1500, 2000, 3000, 3999, 4000]
SITES = [0, 1, 2, 5, 30, 59]
TIERS = range(len(dc.TIERS))
ROLES = range(len(dc.STAFF))


def s(n: int) -> str:
    return str(n)


def fmt_values(rng: random.Random) -> list[int]:
    fixed = [0, 1, 7, 999, 1000, 1001, 1234, 999_994, 999_995, 999_996, 10**6 - 1, 10**6,
             1_125_000, 1_005_000, 1_235_000, 999_949_999, 999_950_000,
             10**33 - 1, 10**33, 10**36 - 1, 10**36, 10**36 + 1, 999_995 * 10**30,
             999_994 * 10**30, 999_995 * 10**27, 10**100, 10**599, 10**600 - 1]
    rand = [rng.randrange(10**rng.randrange(1, 40)) for _ in range(20)]
    # exact .xx5 ties and values hugging the 999.995 boundary at every suffix
    ties = [(c * 10 + 5) * 10**(3 * g - 3)
            for g in range(1, 12) for c in (112, 100, 99999, rng.randrange(100, 99999))]
    edges = [999_995 * 10**(3 * g - 3) + d for g in range(1, 12) for d in (-1, 0)]
    return fixed + rand + ties + edges


def fame_cases(rng: random.Random) -> list[tuple[int, int]]:
    """(balance, site) pairs: thresholds, one below, 4x, powers of ten, random."""
    cases: list[tuple[int, int]] = []
    for k in (0, 1, 2, 5, 30, 59):
        e = dc.expand_cost(k)
        for mult in (0, 1, 2, 3, 4, 9, 15, 16, 100, 10**6, 10**12):
            cases += [(e * mult, k), (max(0, e * mult - 1), k), (e * mult + 1, k)]
        cases += [(e * 10**j, k) for j in range(0, 25)]
        cases += [(e * rng.randrange(1, 10**rng.randrange(1, 30)), k) for _ in range(5)]
    return cases


def rank_fames(rng: random.Random) -> list[int]:
    fames = list(range(0, 201))
    for need, _ in dc.RANKS[1:]:
        fames += [need - 1, need, need + 1]
    top = dc.RANKS[-1][0]
    for lv in (1, 2, 3, 5, 10, 50, 100, 500, 1000, 3000, 3997, 3998, 3999, 4000, 5000):
        fames += [top * 2**lv - 1, top * 2**lv, top * 2**lv + 1]
    fames += [10**k for k in range(3, 100, 7)] + [dc.MAX_BIG - 1]
    fames += [rng.randrange(10**rng.randrange(3, 60)) for _ in range(20)]
    return sorted(set(f for f in fames if f >= 0))


# ------------------------------------------------------------- scripted run

@functools.cache
def purchase_mixes() -> list[tuple[int, ...]]:
    """Candidate (a0, a1, a2, a3, h) mixes, fewest purchases first."""
    return sorted(itertools.product(range(30), range(16), range(16), range(24), range(4)),
                  key=sum)


def find_adds(app: Any, want: Any) -> tuple[int, ...]:
    """Fewest extra tier-0..3 servers (a0..a3) and tier-0 specialist trainings (h) as (a0, a1, a2, a3, h)
    after which want(cost, income) holds,
    where cost is tier 0's next price and income the live data center's income per second.
    Evaluated with the real game's own site_income / cost_of, so the numbers are exact."""
    k = app.cur
    base, lv = list(app.site_owned[k]), app.site_staff[k][0]
    combos = purchase_mixes()
    try:
        for adds in combos:
            for t, a in enumerate(adds[:4]):
                app.site_owned[k][t] = base[t] + a
            app.site_staff[k][0] = lv + adds[4]
            if want(dc.cost_of(0, app.site_owned[k][0], k), app.site_income(k)):
                return adds
    finally:
        app.site_owned[k][:] = base
        app.site_staff[k][0] = lv
    raise AssertionError("no purchase mix satisfies the autopilot boundary")


class ScriptedRng:
    """Stands in for random.Random. Calls consume the fed script, or a default when empty.
    Kinds: r = random(), w = choices(pop, weights) -> index, i = choice(seq) -> index."""

    def __init__(self) -> None:
        self.queue: list[tuple[str, float | int]] = []
        self.calls: list[list[Any]] = []

    def feed(self, *items: tuple[str, float | int]) -> None:
        self.queue.extend(items)

    def take(self, kind: str, default: float | int, size: int) -> float | int:
        if self.queue:
            want, value = self.queue.pop(0)
            assert want == kind, f"script wanted {want}, game asked for {kind}"
        else:
            value = default
        self.calls.append([kind, value, size])
        return value

    def random(self) -> float:
        return float(self.take("r", 0.5, 0))

    def choices(self, population: list[Any], weights: list[int]) -> list[Any]:
        assert len(population) == len(weights)
        return [population[int(self.take("w", 0, len(weights)))]]

    def choice(self, seq: list[Any]) -> Any:
        return seq[int(self.take("i", 0, len(seq)))]


def snap(app: Any) -> dict[str, Any]:
    crisis = dict(app.crisis) if app.crisis else None
    return json.loads(json.dumps({
        "balance": [s(b) for b in app.site_balance], "owned": app.site_owned,
        "chips": app.site_chips, "staff": app.site_staff, "names": app.site_names,
        "fame": s(app.fame), "sites": app.sites, "cur": app.cur, "readOnly": app.read_only,
        "phase": app.phase, "autopilot": app.autopilot, "crisis": crisis,
        "income": s(app.income), "baseIncome": s(app.base_income),
        "siteIncome": [s(app.site_income(k)) for k in range(app.sites + 1)],
        "rank": dc.rank_of(app.fame)[0],
    }))


def js_save(py: dict[str, Any]) -> dict[str, Any]:
    """A game.py save file in the JS format (big ints as decimal strings)."""
    out = dict(py)
    out["site_balance"] = [s(b) for b in py["site_balance"]]
    out["fame"] = s(py["fame"])
    return out


async def scripted_run() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    rng = ScriptedRng()
    with mock.patch.object(dc.DataCenter, "set_interval", lambda *a, **k: None):
        app = dc.DataCenter()  # brand-new save: autopilot on
        async with app.run_test(size=(110, 32)) as pilot:
            await pilot.pause(0.1)
            app.rng = rng
            p = app.pal
            kinds = {p.success: "success", p.muted: "muted", p.error: "error", p.warning: "warning"}
            assert len(kinds) == 4
            logs: list[list[str]] = []
            app.say = lambda text, colour: logs.append([text, kinds[colour]])  # type: ignore

            def step(op: str, arg: Any = None, feed: tuple[Any, ...] = (), n: int = 1) -> None:
                rng.feed(*feed)  # a script may be consumed on any of the n repeats
                for _ in range(n):
                    rng.calls, logs[:] = [], []
                    if op == "set_balance":
                        app.balance = arg
                    elif op == "buy":
                        app.action_buy(arg)
                    elif op == "chip":
                        app.buy_chip(arg)
                    elif op == "hire":
                        app.hire_staff(arg)
                    elif op == "tick":
                        app.tick()
                    elif op == "fix":
                        app.action_fix()
                    elif op == "relocate":
                        app.action_expand()
                    elif op == "goto":
                        app.goto_site(arg)
                    elif op == "site":
                        app.action_site(arg)
                    elif op == "autopilot":
                        app.action_autopilot()
                    else:
                        raise ValueError(op)
                    steps.append({"op": op, "arg": s(arg) if op == "set_balance" else arg,
                                  "rng": json.loads(json.dumps(rng.calls)), "log": list(logs),
                                  "state": snap(app)})
                assert not rng.queue, f"{op}: unused script {rng.queue}"

            R, W, I = "r", "w", "i"
            step("tick", n=3)                       # no income yet
            step("buy", 0, n=5)
            step("buy", 1)                          # cannot afford
            step("chip", 3)                         # nothing to put a chip in
            step("tick", n=4)                       # income 10/s: crises are possible now
            step("chip", 0)                         # cannot afford yet
            step("set_balance", 10**9)
            step("chip", 0, n=2)
            step("buy", 1, n=3)
            step("buy", 2, n=2)
            step("hire", 0, n=3)                    # hire, train, train: Lv2 buys servers
            step("tick", n=2)
            # crisis A: outage-class, nobody can fix it -> you do it by hand
            step("tick", feed=((R, 0.001), (W, 1), (I, 1)))
            step("tick")
            step("fix", feed=((I, 3),))
            step("fix")                             # nothing to fix
            # crisis B: minor, the Vibecoder fixes it after a countdown
            step("tick", feed=((R, 0.0), (W, 0), (I, 2)))
            step("tick", n=8, feed=((I, 5),))       # the quip is only drawn once it resolves
            # crisis C: needs a fixer nobody has; hire one mid-crisis, it picks it up
            step("tick", feed=((R, 0.0), (W, 2), (I, 0)))
            step("tick", n=2)
            step("hire", 3)
            step("tick", n=8, feed=((I, 1),))
            # autopilot: server buys limited by 1/50th of income, chips from Lv6
            step("hire", 0, n=4)
            step("tick", n=6)
            step("autopilot")                       # off
            step("tick", n=2)
            step("autopilot")                       # on again
            step("tick", n=3)
            step("buy", 3, n=4)
            step("goto", 7)                         # out of range: nothing
            step("relocate")                        # too poor
            # crisis D is running when we relocate: relocating clears it
            step("tick", feed=((R, 0.0), (W, 0), (I, 1)))
            step("set_balance", 7 * 10**16 + 5)
            step("relocate")
            # --- boundaries the autopilot and the crisis dice must get exactly right ---
            step("set_balance", 10**30)
            step("hire", 0, n=3)                    # tier 0's specialist reaches Lv2: autopilot buys tier 0
            step("autopilot")                       # off while the crisis gate is probed
            step("buy", 1, n=4)                     # 4 racks
            step("tick", feed=((R, 0.001), (W, 0), (I, 0)))   # only minor crises (size-1 pool)
            step("fix", feed=((I, 1),))
            step("buy", 1)                          # exactly 5 racks
            step("tick", feed=((R, 0.001), (W, 1), (I, 0)))   # outages are now possible (size-2 pool)
            step("fix", feed=((I, 2),))
            step("autopilot")                       # on again

            def adds_for(want: Any) -> None:
                *servers, hires = find_adds(app, want)
                if hires:
                    step("hire", 0, n=hires)            # +5% income each (Lv5 at most): a finer dial
                for t, n in enumerate(servers):
                    if n:
                        step("buy", t, n=n)

            adds_for(lambda c, i: c == i // 50 + 1)             # 1 above the 1/50 limit
            step("tick")                                        # no purchase
            adds_for(lambda c, i: i // 50 + 2 <= c <= i // 40 and c * 44 >= i)   # between 1/50 and 1/40
            step("tick")                                        # no purchase (1/40 would buy)
            adds_for(lambda c, i: c == i // 50)                 # exactly on the limit
            step("tick")                                        # buys one
            adds_for(lambda c, i: i // 50 - 3 <= c <= i // 50 - 1)   # just under the limit
            step("tick")                                        # buys one
            # income earned in the tick is what makes the purchase affordable: pay first
            adds_for(lambda c, i: c <= i // 50 and c * 2 <= i)
            c0 = dc.cost_of(0, app.owned[0], app.cur)
            step("set_balance", c0 - 1)
            step("tick")                                        # income, then buy
            step("set_balance", dc.start_balance(app.cur))
            step("buy", 0, n=6)                     # new, empty data center #2
            step("buy", 1)
            step("chip", 0)
            step("hire", 0, n=2)
            step("hire", 9)
            step("tick", n=3)
            step("tick", feed=((R, 0.001), (W, 1), (I, 0)))   # an outage at data center #2 (no fixer)
            step("tick", n=2)
            step("site", -1)                        # visit data center #1: read only
            step("buy", 0)
            step("chip", 0)
            step("hire", 0)
            step("relocate")
            step("tick", n=3)                       # the live data center keeps earning
            step("fix", feed=((I, 4),))             # fixes the live one's crisis from afar
            step("tick", feed=((R, 0.001), (W, 1), (I, 2)))
            step("site", -1)                        # already at the oldest: nothing
            step("site", 1)
            step("tick", n=3)
            step("set_balance", 5 * 10**19)
            step("relocate")                        # data center #3: bigger Fame, promotion
            step("hire", 1)
            step("buy", 0, n=5)                     # give the live data center some income
            step("buy", 1)
            step("tick", n=4)
            step("goto", 1)
            step("goto", 0)
            step("goto", 2)
            # offline: reload the saved game 3 h 20 min later
            app.save()
            py_save = json.loads(dc.save_path().read_text())
            states = snap(app)
            offline = []
            for elapsed in (0.5, 3600.9, 12000.4):
                t0 = 1_700_000_000.0
                py_save["saved_at"] = t0
                dc.save_path().write_text(json.dumps(py_save))
                with mock.patch.object(dc.time, "time", lambda e=elapsed: t0 + e):
                    again = dc.DataCenter()
                got = dict(snap(again))
                earned = again.away[1]
                offline.append({
                    "save": js_save(py_save), "saved_at": t0, "now": t0 + elapsed, "state": got,
                    "away": [again.away[0], s(earned), dc.fmt_duration(again.away[0]), dc.fmt(earned)]
                    if earned else None})
            assert states == steps[-1]["state"]
            return steps + [{"op": "offline", "cases": offline}]


def main() -> None:
    rng = random.Random(20260511)
    out: dict[str, object] = {}
    out["expandCost"] = [s(dc.expand_cost(k)) for k in range(dc.MAX_SITES + 1)]
    out["costOf"] = [[t, o, k, s(dc.cost_of(t, o, k))]
                     for t in TIERS for o in COST_OWNED for k in SITES]
    out["chipCost"] = [[t, lv, k, s(dc.chip_cost(t, lv, k))]
                       for t in TIERS for lv in range(0, 21) for k in SITES]
    out["tierIncome"] = [[t, o, lv, k, s(dc.tier_income(t, o, lv, k))]
                         for t in TIERS for o in INCOME_OWNED for lv in (0, 1, 2, 5, 10, 19, 20)
                         for k in SITES]
    out["milestoneMult"] = [[o, s(dc.milestone_mult(o))]
                            for o in sorted(set(INCOME_OWNED + list(range(0, 41))
                                                + [m + d for m in dc.MILESTONES for d in (-1, 0, 1)]))]
    out["staffCost"] = [[r, lv, k, s(dc.staff_cost(r, lv, k))]
                        for r in ROLES for lv in range(-1, dc.MAX_STAFF + 1) for k in SITES]
    out["responseSecs"] = [[r, lv, dc.response_secs(r, lv)]
                           for r in ROLES for lv in range(0, dc.MAX_STAFF + 1)]
    out["crewMultiplier"] = [[lv, s(dc.crew_multiplier(lv))] for lv in range(0, 11)]
    out["fameGain"] = [[s(b), k, s(dc.fame_gain(b, k))] for b, k in fame_cases(rng)]
    out["rankOf"] = [[s(f), *[s(x) if isinstance(x, int) else x for x in dc.rank_of(f)]]
                     for f in rank_fames(rng)]
    out["roman"] = [[n, dc.roman(n)] for n in list(range(0, 201)) + [399, 444, 499, 900, 944,
                                                                       1994, 2024, 3888, 3999]]
    out["startBalance"] = [[k, s(dc.start_balance(k))] for k in range(dc.MAX_SITES + 1)]
    out["siteName"] = [[k, dc.site_name(k)] for k in range(16)]
    out["chipName"] = [[t, lv, dc.chip_name(t, lv)] for t in TIERS for lv in range(0, 20)]
    restore = []
    for _ in range(40):
        site = rng.randrange(0, dc.MAX_SITES)
        income = rng.randrange(10 ** rng.randrange(0, 12 + 4 * site))
        bonus = rng.choice([0, 5, 10, 25, 55, 150, 330])
        restore.append((site, income, bonus))
    restore += [(0, 0, 0), (0, 10**200, 5), (59, 10**260, 330), (3, 10**9 * 7 + 3, 0)]
    out["restoreSite"] = [[k, s(i), b, *dc.restore_site(k, i, b)] for k, i, b in restore]
    out["fmt"] = [[s(n), dc.fmt(n)] for n in fmt_values(rng)]
    out["run"] = asyncio.run(scripted_run())
    path = ROOT / "web" / "test" / "golden.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write("{\n")
        keys = list(out)
        for i, key in enumerate(keys):
            f.write(f"{json.dumps(key)}: {json.dumps(out[key], separators=(',', ':'))}")
            f.write(",\n" if i < len(keys) - 1 else "\n")
        f.write("}\n")
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print({k: len(v) for k, v in out.items()})


if __name__ == "__main__":
    main()
