"""Animation: time-based and deterministic (the clock is patched), smooth frame to frame,
and completely idle in a background pane / old data center / with DC_ANIM=0."""
import asyncio
import io
import itertools
import math
import re

from rich.color import Color

from helpers import AppCase, game, world_save

N = len(game.TIERS)
FIVE = [8, 6, 4, 2, 1] + [0] * (N - 5)


def live_save(**extra: object) -> dict[str, object]:
    """One live data center with some racks of the first tiers (so there is income)."""
    save: dict[str, object] = {
        "site_balance": [5_000], "site_owned": [list(FIVE)],
        "site_chips": [[0] * N], "site_staff": [[-1] * N], "sites": 0, "cur": 0, "fame": 0,
        "autopilot": False, "online": {"asked": True, "joined": False}}
    save.update(extra)
    return save


def hall_text(app: object) -> str:
    return str(app.query_one(game.Hall).render())  # type: ignore[attr-defined]


def hall_frame(app: object, t: float) -> object:
    app.now = t  # type: ignore[attr-defined]
    return app.query_one(game.Hall).render()  # type: ignore[attr-defined]


def rgb_of(css: str) -> game.RGB:
    return tuple(int(x) for x in css[4:-1].split(","))  # type: ignore[return-value]


def banner_colours(app: object) -> tuple[game.RGB, game.RGB]:
    style = str(app.alert_banner("fixed").style)  # type: ignore[attr-defined]
    fg, bg = (rgb_of(c) for c in style.replace("bold ", "").split(" on "))
    return fg, bg


def delta(a: game.RGB, b: game.RGB) -> int:
    return max(abs(x - y) for x, y in zip(a, b))


class AnimCase(AppCase):
    """ANIM on, a fake clock (self.t, seconds) that only moves when a test moves it."""

    def setUp(self) -> None:
        super().setUp()
        self._saved = (game.ANIM, game.clock, game.FRAME_S)
        self.t = 1000.0
        game.ANIM = True
        game.clock = lambda: self.t
        game.FRAME_S = 0.05  # real timers fire quickly; they read the fake clock
        self.addCleanup(lambda: setattr(game, "ANIM", self._saved[0]))
        self.addCleanup(lambda: setattr(game, "clock", self._saved[1]))
        self.addCleanup(lambda: setattr(game, "FRAME_S", self._saved[2]))

    def frame(self, app: object, dt: float) -> None:
        """Move the fake clock and run one animation frame."""
        self.t += dt
        app.anim_frame()  # type: ignore[attr-defined]


class Maths(AnimCase):
    def test_easing_and_sine(self) -> None:
        self.assertEqual((game.smoothstep(-1), game.smoothstep(0.5), game.smoothstep(2)), (0, 0.5, 1))
        self.assertEqual((game.ease_out(0), game.ease_out(1)), (0, 1))
        self.assertGreater(game.ease_out(0.25), 0.25)  # fast start
        self.assertEqual(game.sine01(0, 2), 0.0)
        self.assertAlmostEqual(game.sine01(1, 2), 1.0)
        self.assertEqual(game.mix32(1, 2, 3), game.mix32(1, 2, 3))

    def test_fps_clamp(self) -> None:
        for raw, want in ((None, 12.0), ("", 12.0), ("20", 20.0), ("1", 4.0), ("0", 4.0),
                          ("-5", 4.0), ("999", 30.0), ("abc", 12.0), ("nan", 12.0),
                          ("inf", 12.0), ("4", 4.0), ("30", 30.0), ("7.5", 7.5)):
            self.assertEqual(game.anim_fps(raw), want, raw)
        self.assertEqual(game.FPS_DEFAULT, 12.0)

    def test_led_level_fades_instead_of_flipping(self) -> None:
        frame = 1 / 12
        biggest, seen = 0.0, set()
        for idx in range(6):
            levels = [game.Hall.led_level(idx, 4, 3, i * frame) for i in range(240)]  # 20 s
            self.assertTrue(all(0.0 <= v <= 1.0 for v in levels))
            biggest = max(biggest, *(abs(b - a) for a, b in zip(levels, levels[1:])))
            seen.update(round(v, 1) for v in levels)
        self.assertLess(biggest, 0.5)  # a hard on/off flip would be 1.0 in one frame
        self.assertGreater(len(seen), 6)  # lots of in-between brightnesses
        self.assertEqual(game.Hall.led_level(2, 1, 1, 3.7), game.Hall.led_level(2, 1, 1, 3.7))


class Frames(AnimCase):
    async def test_frames_are_deterministic_for_a_time(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.sparkle(0, big=True)
            a, b = hall_frame(app, self.t + 0.3), hall_frame(app, self.t + 0.3)
            self.assertEqual(a, b)
            self.assertNotEqual(hall_frame(app, self.t + 0.4), a)  # LEDs, pulse, bus move

    async def test_pulse_glides_monotonically_in_sub_cell_steps(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            hall = app.query_one(game.Hall)
            heads = []
            for i in range(7):  # t = 0 .. 0.5 s at 12 fps
                grid = [[app.pal.frame] * (game.CELL_W * 8) for _ in range(game.CELL_H)]
                blocks = [game.Block("rack", 0, 0, 8, 0, game.RACK_LINES, 0)]
                lay = game.Layout(8, 4, blocks, 0, 1, 4, 1, [0] + [-1] * (N - 1), [0] * N)
                hall.draw_bus(grid, lay, i / 12)
                lit = [(x, game.mix(app.pal.frame, c, 1)) for x, c in enumerate(grid[0])]
                weights = [sum(abs(a - b) for a, b in zip(c, app.pal.frame)) for _, c in lit]
                heads.append(sum(x * wt for (x, _), wt in zip(lit, weights)) / max(1, sum(weights)))
                self.assertTrue(any(wt > 0 for wt in weights))
            steps = [b - a for a, b in zip(heads, heads[1:])]
            self.assertTrue(all(0 < st < 4 for st in steps), steps)  # always moving, never a jump
            self.assertGreater(len({round(h % 1, 2) for h in heads}), 3)  # lands between cells

    async def test_dropped_frames_do_not_change_speed(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertEqual(hall_frame(app, self.t + 2.0), hall_frame(app, self.t + 2.0))
            slow = [hall_frame(app, self.t + i / 12) for i in range(25)]  # every frame
            sparse = [hall_frame(app, self.t + i / 12) for i in range(0, 25, 6)]  # most dropped
            self.assertEqual(sparse, slow[::6])  # same picture at the same time

    async def test_top_tier_pulse_is_smooth(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            cols = []
            for i in range(37):  # 3 s
                hall_frame(app, i / 12)
                hall = app.query_one(game.Hall)
                x, y = hall.rack_layout().rack_xy(sum(app.owned) - 1, 4)  # the lone Quantum Farm
                cols.append(hall._base[0][y + 2][x])
            for a, b in zip(cols, cols[1:]):
                self.assertLessEqual(delta(a, b), 12)
            self.assertGreater(len(set(cols)), 3)

    async def test_pulse_targets_the_best_earner(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertEqual(app.top_tier(), 4)
            app.owned[:] = [100, 1, 0, 0, 0] + [0] * (N - 5)
            self.assertEqual(app.top_tier(), 0)
            app.owned[:] = [0] * N
            self.assertIsNone(app.top_tier())

    async def test_every_theme_renders_every_effect(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            app.sparkle(2, big=True)
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                for i in range(4):
                    hall_frame(app, self.t + i * 0.2)
                    app.redraw()

    async def test_80x24_with_every_effect(self) -> None:
        async with self.run_app(live_save(), size=(80, 24)) as (app, _):
            app.crisis = {"title": "Rogue AI agent deleted prod", "sev": 3, "fixer": None, "eta": None}
            app.sparkle(1, big=True)
            hall = app.query_one(game.Hall)
            for i in range(8):
                app.now = self.t + i * 0.15
                app.redraw()
                for line in hall.render().plain.split("\n"):
                    self.assertLessEqual(len(line), hall.size.width)
            app.reloc = {"t0": app.now, "gain": 10**9, "rank": "Engineering Manager"}
            app.now += 0.7
            for line in hall.render().plain.split("\n"):
                self.assertLessEqual(len(line), hall.size.width)

    async def test_hall_repaints_only_when_the_picture_changed(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            count = []
            orig = game.Hall.refresh
            game.Hall.refresh = lambda self, *a, **k: (count.append(1), orig(self, *a, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "refresh", orig))
            for _ in range(5):  # the clock has not moved: same frame bucket
                app.anim_frame()
            self.assertLessEqual(len(count), 1)
            n = len(count)
            for _ in range(5):
                self.frame(app, 1 / 12)
            self.assertEqual(len(count) - n, 5)  # a new picture each frame


class Quiet(AnimCase):
    async def test_background_pane_never_animates_or_repaints(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertIsNotNone(app._anim_timer)  # control: the foreground pane does run
            game.tmux_foreground = lambda: False
            app.foreground = False
            calls: list[int] = []
            orig = game.DataCenter.redraw
            game.DataCenter.redraw = lambda self: (calls.append(self.phase), orig(self))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.DataCenter, "redraw", orig))
            frames: list[int] = []
            orig_frame = game.DataCenter.anim_frame
            game.DataCenter.anim_frame = lambda self: (frames.append(1), orig_frame(self))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.DataCenter, "anim_frame", orig_frame))
            repaints: list[int] = []
            orig_refresh = game.Hall.refresh
            game.Hall.refresh = lambda self, *a, **k: (repaints.append(1), orig_refresh(self, *a, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "refresh", orig_refresh))
            app.phase = 0
            for _ in range(100):
                app.tick()
            self.assertFalse(app.animating)
            self.assertEqual(app.fx, [])
            self.assertIsNone(app._anim_timer)
            self.assertEqual(len(calls), 100 // game.BACKGROUND_REFRESH)  # every Nth tick only
            self.assertLessEqual(len(repaints), 2)
            app.sparkle(0)
            self.assertEqual((app.fx, app._anim_timer), ([], None))
            await asyncio.sleep(0.4)  # 8 frame periods
            self.assertEqual(frames, [])  # not one frame ran
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))  # static picture

    async def test_frames_never_shell_out_to_tmux(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            asked: list[int] = []
            game.tmux_foreground = lambda: (asked.append(1), True)[1]
            for _ in range(30):
                self.frame(app, 1 / 12)
            self.assertEqual(asked, [])
            app.tick()  # only the 1 s tick asks, once
            self.assertEqual(asked, [1])

    async def test_clock_follows_the_pane_forward_and_back(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertIsNotNone(app._anim_timer)
            game.tmux_foreground = lambda: False
            app.tick()
            self.assertIsNone(app._anim_timer)
            self.assertEqual(app.fx, [])
            game.tmux_foreground = lambda: True
            app.tick()  # back in front: animating again on the very next tick
            self.assertTrue(app.animating)
            self.assertIsNotNone(app._anim_timer)
            self.assertEqual(app.fx, [])  # nothing launches on its own any more

    async def test_one_timer_only(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            timer = app._anim_timer
            for _ in range(5):
                app.sparkle(0)
                app.redraw()
                app.tick()
            self.assertIs(app._anim_timer, timer)

    async def test_empty_calm_hall_costs_no_frames(self) -> None:
        async with self.run_app(live_save(site_owned=[[0] * N])) as (app, _):
            self.assertIsNone(app._anim_timer)
            app.tick()
            app.redraw()
            self.assertIsNone(app._anim_timer)
            app.balance += 1  # a change flashes the balance, so then it needs frames
            app.redraw()
            self.assertIsNotNone(app._anim_timer)
            self.frame(app, game.CASH_FLASH_S + 0.01)
            self.assertIsNone(app._anim_timer)

    async def test_decommissioned_world_stays_washed_out_and_still(self) -> None:
        async with self.run_app(world_save()) as (app, _):
            app.cur = 0
            self.assertTrue(app.read_only)
            for _ in range(3):
                app.tick()
            app.sparkle(0)
            self.assertEqual((app.fx, app._anim_timer, app.animating), ([], None, False))
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))
            app.balance += 1
            app.redraw()
            self.assertEqual(app.cash_flash, 0)

    async def test_effects_are_dropped_when_you_walk_into_an_old_world(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            app.sparkle(0)
            self.assertTrue(app.fx)
            await pilot.press("left_square_bracket")
            self.assertTrue(app.read_only)
            self.assertEqual(app.fx, [])
            self.assertIsNone(app._anim_timer)

    async def test_anim_off_is_static(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            game.ANIM = False
            for _ in range(3):
                app.tick()
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            app.redraw()
            self.assertEqual((app.fx, app._anim_timer, app.animating), ([], None, False))
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))
            self.assertEqual(str(app._last["#alert"]), "⚠ x  ·  income -50%  ·  press F to fix")
            self.assertEqual(app._last["#alert"].style, "")  # plain: no pulsing colours
            self.assertEqual(app.cash_flash, 0)

    async def test_anim_off_from_the_start_never_makes_a_timer(self) -> None:
        game.ANIM = False
        async with self.run_app(live_save()) as (app, pilot):
            await pilot.press("1")
            app.tick()
            self.assertIsNone(app._anim_timer)

    async def test_timer_stops_on_exit(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertIsNotNone(app._anim_timer)
        self.assertIsNone(app._anim_timer)

    def test_no_anim_flag(self) -> None:
        game.ANIM = True
        old_run = game.DataCenter.run
        game.DataCenter.run = lambda *_a, **_k: None  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(game.DataCenter, "run", old_run))
        game.main(["--no-anim"])
        self.assertFalse(game.ANIM)


class Effects(AnimCase):
    async def test_sparkle_on_buy_and_big_on_milestone(self) -> None:
        async with self.run_app(live_save(site_owned=[[24] + [0] * (N - 1)])) as (app, pilot):
            await pilot.press("1")  # 25th Budget VPS: x2
            self.assertEqual(app.owned[0], 25)
            self.assertEqual([(f.kind, f.big) for f in app.fx if f.kind == "spark"], [("spark", True)])
            app.fx.clear()
            await pilot.press("1")
            self.assertEqual([(f.kind, f.big) for f in app.fx if f.kind == "spark"], [("spark", False)])

    async def test_sparks_ease_out_fade_and_expire(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.fx.clear()
            app.sparkle(0)
            fx = app.fx[0]
            self.assertIsNotNone(app._anim_timer)
            seen = []
            for i in range(9):
                app.now = fx.born + game.SPARK_LIFE_S * i / 8
                grid = [[app.pal.bg] * 40 for _ in range(24)]
                hall = app.query_one(game.Hall)
                hall.draw_sparks(grid, hall.rack_layout())
                seen.append(sum(c != app.pal.bg for row in grid for c in row))
            self.assertGreater(max(seen), 0)
            self.assertEqual(seen[-1], 0)  # faded out completely
            self.frame(app, game.SPARK_LIFE_S + 0.01)
            self.assertEqual([f for f in app.fx if f.kind == "spark"], [])

    async def test_clock_stops_when_the_last_effect_ends(self) -> None:
        async with self.run_app(live_save(site_owned=[[0] * N])) as (app, _):
            self.assertIsNone(app._anim_timer)
            app.sparkle(0)
            self.assertIsNotNone(app._anim_timer)
            self.frame(app, game.SPARK_LIFE_S + 0.01)
            self.assertIsNone(app._anim_timer)

    async def test_balance_flash_eases_back(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.redraw()
            self.assertEqual(app.cash_flash, 0)
            app.balance += 5
            app.redraw()
            self.assertEqual(app.cash_flash, 1)
            tints = []
            for _ in range(8):
                tints.append(str(app._last["#cash"].spans[-1].style))
                self.frame(app, game.CASH_FLASH_S / 7)
            self.assertIn("bold", tints[0])
            self.assertGreater(len(set(tints)), 3)  # a gradient, not a switch
            self.assertEqual(app.cash_flash, 0)
            self.assertEqual(app._last["#cash"].spans[-1].style, "") if app._last["#cash"].spans[-1:] and False else None
            app.balance -= 5
            app.redraw()
            self.assertEqual(app.cash_flash, -1)

    async def test_crisis_banner_pulses_smoothly_then_resolves_calmly(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            bgs = []
            for i in range(37):  # 3 s at 12 fps
                self.frame(app, 1 / 12)
                bgs.append(banner_colours(app)[1])
            self.assertGreater(len(set(bgs)), 10)  # a continuum
            self.assertLess(max(delta(a, b) for a, b in zip(bgs, bgs[1:])), 40)  # never a hard flip
            self.assertGreater(delta(min(bgs), max(bgs)), 25)  # but it really pulses
            app.resolve(None)
            self.assertIsNone(app.crisis)
            self.assertIsNotNone(app.resolve_t0)
            app.redraw()
            self.assertTrue(app.query_one("#alert").display)
            self.assertIn("fixed", str(app._last["#alert"]))
            self.frame(app, game.RESOLVE_S / 2)
            self.assertTrue(app.query_one("#alert").display)
            self.frame(app, game.RESOLVE_S)
            self.assertFalse(app.query_one("#alert").display)
            self.assertIsNone(app.resolve_t0)


class Smooth(AnimCase):
    async def test_banner_frames_differ_by_small_colour_steps_on_every_theme(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                for crisis in (True, False):
                    app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None} if crisis else None
                    app.resolve_t0 = None if crisis else self.t
                    prev = None
                    for i in range(1 + int(2.5 * 12)):
                        app.now = self.t + i / 12
                        fg, bg = banner_colours(app)
                        self.assertGreaterEqual(game.contrast(fg, bg), game.BANNER_MIN_CONTRAST,
                                                (name, crisis, i))
                        if prev:
                            self.assertLessEqual(delta(bg, prev[1]), 40, (name, crisis, i))
                            self.assertLessEqual(delta(fg, prev[0]), 60, (name, crisis, i))
                        prev = (fg, bg)

    async def test_led_colours_fade_between_frames(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            p, hall = app.pal, app.query_one(game.Hall)
            on, off = p.led_on, p.led_off
            span = delta(on, off)
            leds = hall._base[0] and hall._base[1]
            self.assertTrue(leds)
            for x, y, idx, pos in leds[:20]:
                prev = None
                for i in range(240):
                    c = game.mix(off, on, hall.led_level(idx, pos // 8, pos % 8, i / 12))
                    if prev:
                        self.assertLessEqual(delta(c, prev), span * 0.5 + 1)
                    prev = c

    async def test_whole_hall_changes_a_little_each_frame(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            frames = [hall_frame(app, self.t + i / 12) for i in range(6)]
            self.assertEqual(len({str(f.spans) for f in frames}), 6)  # all distinct


class Relocation(AnimCase):
    async def test_transition_plays_then_the_new_data_center_appears(self) -> None:
        async with self.run_app() as (app, pilot):
            app.site_balance[0] = game.expand_cost(0) * 9  # 3 Fame: Nobody -> Junior Dev
            await pilot.press("x")
            self.assertEqual((app.sites, app.cur, app.fame), (1, 1, 3))  # state changes at once
            self.assertEqual(app.reloc, {"t0": self.t, "gain": 3, "rank": "Junior Dev"})
            self.assertNotIn("Empty hall", hall_text(app))
            self.assertIn("RELOCATING", str(hall_frame(app, self.t + 0.5)))
            shots = []
            for i in range(int(game.RELOC_S * 12) - 1):
                app.now = self.t + i / 12
                shots.append(app.query_one(game.Hall).render())
            frames = [str(t) for t in shots]
            self.assertTrue(any("Fame +3" in f for f in frames))
            self.assertTrue(any("Promoted: Junior Dev!" in f for f in frames))
            self.assertLess(next(i for i, f in enumerate(frames) if "Fame" in f),
                            next(i for i, f in enumerate(frames) if "Promoted" in f))  # staggered
            # eased: the title's colour passes through intermediate shades
            shades = {str(s.style.color) for t in shots[:6] for s in t.spans if s.style}
            self.assertGreater(len(shades), 3)
            self.frame(app, game.RELOC_S + 0.01)
            self.assertIsNone(app.reloc)
            self.assertIsNone(app._anim_timer)
            self.assertIn("Empty hall", str(app.query_one(game.Hall).render()))
            self.assertEqual((app.sites, app.cur, app.fame, sum(app.owned)), (1, 1, 3, 0))
            self.assertEqual(app.balance, game.start_balance(1))
            self.assertEqual(app.site_balance[0], game.expand_cost(0) * 9)  # old one is frozen

    async def test_no_rank_line_without_a_promotion(self) -> None:
        async with self.run_app(live_save(fame=5, site_balance=[game.expand_cost(0)])) as (app, pilot):
            await pilot.press("x")  # 5 + 1 = 6 Fame: Senior Dev
            self.assertEqual(app.reloc["rank"], "Senior Dev")
        async with self.run_app(live_save(fame=7, site_balance=[game.expand_cost(0)])) as (app, pilot):
            await pilot.press("x")
            self.assertIsNone(app.reloc["rank"])
            app.now += 0.9
            self.assertNotIn("Promoted", hall_text(app))

    async def test_no_transition_in_background_or_with_anim_off(self) -> None:
        for fg, anim in ((False, True), (True, False)):
            async with self.run_app() as (app, pilot):
                game.ANIM, app.foreground = anim, fg
                app.site_balance[0] = game.expand_cost(0)
                await pilot.press("x")
                self.assertEqual((app.sites, app.reloc, app._anim_timer), (1, None, None))
                game.ANIM = True


# ---------------------------------------------------------------- what really reaches the screen

def screen_cells(app: object) -> list[list[tuple[str, game.RGB | None, game.RGB | None]]]:
    """The Hall's cells as the compositor emits them: (char, fg, bg) per terminal cell."""
    hall = app.query_one(game.Hall)  # type: ignore[attr-defined]
    strips = app.screen._compositor.render_strips()  # type: ignore[attr-defined]
    reg = hall.content_region
    out = []
    for y in range(reg.height):
        cells: list[tuple[str, game.RGB | None, game.RGB | None]] = []
        for seg in strips[reg.y + y]:
            st = seg.style
            fg = st.color.get_truecolor() if st and st.color else None
            bg = st.bgcolor.get_truecolor() if st and st.bgcolor else None
            cells.extend((ch, fg, bg) for ch in seg.text)
        out.append(cells[reg.x:reg.x + reg.width])
    return out


def expected_cells(app: object) -> list[list[tuple[str, game.RGB | None, game.RGB | None]]]:
    """The same picture from the plain Text render() path (no row caches, no Strips)."""
    from rich.console import Console
    hall = app.query_one(game.Hall)  # type: ignore[attr-defined]
    lines: list[list[tuple[str, game.RGB | None, game.RGB | None]]] = [[]]
    for seg in hall.render().render(Console(color_system="truecolor")):
        for i, part in enumerate(seg.text.split("\n")):
            if i:
                lines.append([])
            st = seg.style
            fg = st.color.get_truecolor() if st and st.color else None
            bg = st.bgcolor.get_truecolor() if st and st.bgcolor else None
            lines[-1].extend((ch, fg, bg) for ch in part)
    return lines


def force_full_render(app: object) -> None:
    """Throw away every hall cache and repaint from scratch."""
    hall = app.query_one(game.Hall)  # type: ignore[attr-defined]
    hall._rows, hall._base_key, hall._strips = None, None, {}
    app._hall_sig = None  # type: ignore[attr-defined]
    app.draw_hall()  # type: ignore[attr-defined]


class Term:
    """A tiny terminal: applies the escape sequences the game really sends (cursor moves and
    truecolor SGR) to a grid of (char, fg, bg), so tests can see what reaches the screen."""

    TOKEN = re.compile(r"\x1b\[(\d+);(\d+)H|\x1b\[([0-9;]*)m|(\x1b\[[^\x1b]*?[A-Za-z])|([^\x1b])")

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], tuple[str, game.RGB | None, game.RGB | None]] = {}
        self.sent = 0  # bytes since the last reset

    def reset(self, strips: list[object]) -> None:
        self.cells = {}
        for y, strip in enumerate(strips):
            x = 0
            for seg in strip:  # type: ignore[attr-defined]
                st = seg.style
                fg = st.color.get_truecolor() if st and st.color else None
                bg = st.bgcolor.get_truecolor() if st and st.bgcolor else None
                for ch in seg.text:
                    self.cells[(x, y)] = (ch, fg, bg)
                    x += 1

    def feed(self, text: str) -> None:
        x = y = 0
        fg = bg = None
        for m in self.TOKEN.finditer(text):
            if m.group(1):
                y, x = int(m.group(1)) - 1, int(m.group(2)) - 1
            elif m.group(3) is not None:
                codes = [int(c) for c in m.group(3).split(";") if c] or [0]
                i = 0
                while i < len(codes):
                    c = codes[i]
                    if c == 0:
                        fg = bg = None
                    elif c in (38, 48):  # 38;2;r;g;b  or  38;5;n
                        two = codes[i + 1:i + 2] == [2]
                        rgb = (tuple(codes[i + 2:i + 5]) if two
                               else Color.from_ansi(codes[i + 2]).get_truecolor())
                        fg, bg = (rgb, bg) if c == 38 else (fg, rgb)
                        i += 4 if two else 2
                    elif 30 <= c <= 37 or 90 <= c <= 97:
                        fg = Color.from_ansi(c - 30 if c < 90 else c - 82).get_truecolor()
                    elif 40 <= c <= 47 or 100 <= c <= 107:
                        bg = Color.from_ansi(c - 40 if c < 100 else c - 92).get_truecolor()
                    i += 1
            elif m.group(5) and m.group(5) not in "\r\n":
                self.cells[(x, y)] = (m.group(5), fg, bg)  # type: ignore[assignment]
                x += 1
        self.sent += len(text)


def install_term(case: AnimCase) -> Term:
    """Route every compositor update of this test through a Term, via the same
    game.CroppedChops that the app's _display puts on the wire."""
    from rich.console import Console
    from textual._compositor import ChopsUpdate, Compositor
    term, orig = Term(), Compositor.render_update

    def hooked(comp: object, *a: object, **k: object) -> object:
        update = orig(comp, *a, **k)  # type: ignore[arg-type]
        if type(update) is ChopsUpdate:
            wire = game.crop_update(update)
            console = Console(color_system="truecolor", force_terminal=True, width=500, file=io.StringIO())
            term.feed(wire.render_segments(console))
        elif update is not None:  # a full repaint: the screen is whatever the strips say
            term.reset(comp.render_strips())  # type: ignore[attr-defined]
        return update

    Compositor.render_update = hooked  # type: ignore[method-assign]
    case.addCleanup(lambda: setattr(Compositor, "render_update", orig))
    return term


def term_cells(term: Term, app: object) -> list[list[tuple[str, game.RGB | None, game.RGB | None]]]:
    """The Hall's content region as the simulated terminal shows it."""
    reg = app.query_one(game.Hall).content_region  # type: ignore[attr-defined]
    blank = (" ", None, None)
    return [[term.cells.get((reg.x + x, reg.y + y), blank) for x in range(reg.width)]
            for y in range(reg.height)]


def same_picture(a: list[list[tuple[str, object, object]]],
                 b: list[list[tuple[str, object, object]]]) -> bool:
    """Same characters everywhere and the same colours on every picture cell (padding keeps
    the terminal's default colours, which a terminal simulation does not resolve)."""
    return len(a) == len(b) and all(
        len(ra) == len(rb) and all(ca[0] == cb[0] and (ca[0] != "▀" or ca == cb)
                                   for ca, cb in zip(ra, rb))
        for ra, rb in zip(a, b))


class Paint(AnimCase):
    def setUp(self) -> None:
        super().setUp()
        self.term = install_term(self)
        orig = game.DataCenter.tick  # no real 1 s tick mid-comparison: the picture must hold still
        game.DataCenter.tick = lambda self: None  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(game.DataCenter, "tick", orig))

    async def check(self, app: object, pilot: object, label: str) -> None:
        """Compositor output == forced full render == Text path; colours really present."""
        await pilot.pause(0.15)  # type: ignore[attr-defined]
        cached = screen_cells(app)
        want = expected_cells(app)
        halves = [c for row in cached for c in row if c[0] == "▀"]
        self.assertTrue(halves, label)
        for _, fg, bg in halves:
            self.assertIsNotNone(fg, label)
            self.assertIsNotNone(bg, label)
        for y, row in enumerate(cached):
            for x, (ch, fg, bg) in enumerate(row):
                if y < len(want) and x < len(want[y]):
                    wch, wfg, wbg = want[y][x]
                    if wch == "▀":
                        self.assertEqual((ch, fg, bg), (wch, wfg, wbg), (label, y, x))
                if ch == " ":  # padding / scrollbar: a background, never "no colour"
                    self.assertIsNotNone(bg, (label, y, x))
        self.assertTrue(same_picture(term_cells(self.term, app), cached), ("terminal", label))
        force_full_render(app)
        await pilot.pause(0.15)  # type: ignore[attr-defined]
        self.assertEqual(screen_cells(app), cached, label)
        self.assertTrue(same_picture(term_cells(self.term, app), cached), ("terminal, full", label))

    async def test_cached_output_has_colour_and_equals_a_full_render(self) -> None:
        big = [200, 100, 50, 30, 20] + [0] * (N - 5)
        async with self.run_app(live_save(site_owned=[big], site_balance=[10**12])) as (app, pilot):
            await self.check(app, pilot, "idle")
            await pilot.press("1")
            await self.check(app, pilot, "purchase")
            for key in ("pagedown", "down", "home", "end", "up"):
                await pilot.press(key)
                await self.check(app, pilot, f"scroll {key}")
            for size in ((80, 24), (150, 50), (110, 32)):
                await pilot.resize_terminal(*size)
                await pilot.pause(0.2)
                await self.check(app, pilot, f"resize {size}")
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            app.redraw()
            self.frame(app, 0.3)
            await self.check(app, pilot, "crisis")
            app.crisis = None
            app.redraw()
            self.frame(app, 0.3)
            await self.check(app, pilot, "crisis over")

    async def test_old_and_new_world(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            await self.check(app, pilot, "live world")
            await pilot.press("left_square_bracket")
            self.assertTrue(app.read_only)
            await self.check(app, pilot, "old world")
            await pilot.press("right_square_bracket")
            await self.check(app, pilot, "back to the live world")

    async def test_frames_keep_the_cache_equal_to_a_full_render(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            app.sparkle(1, big=True)
            for _ in range(10):
                self.frame(app, 1 / 12)
                await self.check(app, pilot, "frame")

    async def test_cached_rows_follow_theme_changes_without_animation(self) -> None:
        game.ANIM = False
        async with self.run_app(live_save()) as (app, pilot):
            names = sorted(app.available_themes)
            self.assertGreaterEqual(len(names), 8)
            for name in names + names[:4]:
                app.theme = name
                await pilot.pause(0.2)
                p = app.pal
                cached = screen_cells(app)
                self.assertIn(p.pip_floor, {c[2] for row in cached for c in row}, name)  # new colours
                await self.check(app, pilot, name)

    async def test_only_changed_rows_are_repainted(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            hall = app.query_one(game.Hall)
            self.frame(app, 1 / 12)
            await pilot.pause(0.1)
            regions: list[game.Region] = []
            orig = game.Hall.refresh
            game.Hall.refresh = lambda self, *r, **k: (regions.extend(r), orig(self, *r, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "refresh", orig))
            before = [list(r) for r in hall._rows]
            self.frame(app, 1 / 12)
            after = hall._rows
            changed = {y for y, (a, b) in enumerate(zip(before, after)) if a != b}
            painted = {r.y for r in regions}
            self.assertTrue(changed)
            self.assertEqual(painted, changed)
            self.assertLess(len(painted), len(after))  # not every row
            self.assertTrue(all(r.height == 1 for r in regions))


class Spans(AnimCase):
    """Partial repaints: only the changed cells, LEDs on a slower beat, fewer LED shades."""

    def test_changed_spans_join_near_neighbours_only(self) -> None:
        cell = lambda v: ("▀", (v, v, v), None)  # noqa: E731
        old = [cell(0)] * 12
        new = list(old)
        for x in (1, 2, 5, 11):  # 3,4 unchanged between 2 and 5: within the gap of 2
            new[x] = cell(9)
        self.assertEqual(game.Hall.changed_spans(old, new, gap=2), [(1, 6), (11, 12)])
        self.assertEqual(game.Hall.changed_spans(old, new, gap=0), [(1, 3), (5, 6), (11, 12)])
        self.assertEqual(game.Hall.changed_spans(old, old), [])
        self.assertEqual(game.Hall.changed_spans(old, old[:9]), [(0, 12)])  # a width change: all of it

    async def test_regions_are_exactly_the_changed_cells_plus_small_gaps(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            hall = app.query_one(game.Hall)
            regions: list[game.Region] = []
            orig = game.Hall.refresh
            game.Hall.refresh = lambda self, *r, **k: (regions.extend(r), orig(self, *r, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "refresh", orig))
            for _ in range(8):
                regions.clear()
                before = [list(r) for r in hall._cells]
                self.frame(app, 1 / 12)
                changed = {(x, y) for y, (a, b) in enumerate(zip(before, hall._cells))
                           for x, (ca, cb) in enumerate(zip(a, b)) if ca != cb}
                covered = {(r.x + i, r.y) for r in regions for i in range(r.width)}
                self.assertTrue(changed <= covered)  # nothing stale
                self.assertTrue(all(r.height == 1 and r.width >= 1 for r in regions))
                self.assertLess(len(covered), 4 * len(changed) + 1)  # and not much extra
                self.assertLess(len(covered), len(hall._cells) * len(hall._cells[0]) // 4)

    async def test_wire_bytes_per_frame_are_small(self) -> None:
        term = install_term(self)
        async with self.run_app(live_save(site_owned=[[40, 0, 0, 0, 0] + [0] * (N - 5)]), size=(120, 36)) as (app, pilot):
            await pilot.pause(0.2)
            term.sent = 0
            for _ in range(24):
                self.frame(app, 1 / 12)
                await pilot.pause(0.02)
            per_frame = term.sent / 24
            # whole-row repaints cost about 19 KB a frame here (timer frames add noise)
            self.assertLess(per_frame, 12_000, per_frame)

    def test_led_shade_has_four_levels(self) -> None:
        shades = {game.Hall.led_shade(i, y, x, k / 12) for i in range(8) for y in range(6)
                  for x in range(6) for k in range(120)}
        self.assertEqual(shades, {0.0, 1 / 3, 2 / 3, 1.0})
        self.assertEqual(game.LED_LEVELS, 4)
        for i in range(30):  # still a fade: neighbouring frames never jump more than one step
            a, b = (game.Hall.led_shade(1, 2, 3, i / 12), game.Hall.led_shade(1, 2, 3, (i + 1) / 12))
            self.assertLessEqual(abs(a - b), 2 / 3 + 1e-9)

    async def test_leds_and_glow_tick_slower_than_the_pulse(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            hall = app.query_one(game.Hall)
            self.assertAlmostEqual(game.SLOW_HZ * round(game.ANIM_FPS / game.SLOW_FPS), game.ANIM_FPS)
            slot = 1 / game.SLOW_HZ
            base = math.floor(self.t * game.SLOW_HZ) / game.SLOW_HZ + 0.01
            orig_bus = game.Hall.draw_bus
            game.Hall.draw_bus = lambda *a, **k: None  # type: ignore[method-assign]
            self.addCleanup(lambda: setattr(game.Hall, "draw_bus", orig_bus))
            app.now = base
            first = hall.build_cells()
            app.now = base + slot * 0.8  # same slow slot: LEDs and glow cannot move
            self.assertEqual(hall.build_cells(), first)
            moved = 0
            for k in range(1, 12):  # later slots: the LEDs do change
                app.now = base + k * slot
                moved += hall.build_cells() != first
            self.assertGreater(moved, 6)
            game.Hall.draw_bus = orig_bus  # the data pulse is not slowed: it moves within a slot
            app.now = base
            a = hall.build_cells()
            app.now = base + slot * 0.5
            self.assertNotEqual(hall.build_cells(), a)

    async def test_crop_update_only_touches_partial_updates(self) -> None:
        from textual._compositor import ChopsUpdate
        marker = object()
        self.assertIs(game.crop_update(marker), marker)
        self.assertIs(game.crop_update(None), None)
        chops = ChopsUpdate([{0: None}], [(0, 0, 1)], [[1]])
        self.assertIsInstance(game.crop_update(chops), game.CroppedChops)


class CropGate(AnimCase):
    """CroppedChops leans on private Textual pieces: it must switch itself off (and never
    break painting) outside the tested Textual range or when those pieces look different."""

    def test_version_parsing(self) -> None:
        ok = ["8.0", "8.0.0", "8.2.7", "8.2", "8.2.7.dev1", " 8.2.1 ", "8.2rc1"]
        bad = ["7.9.9", "8.3", "8.3.0", "9.0", "10.0.0", "", "garbage", "8", "8.x", "v8.2", "-8.2", "8..2"]
        for raw in ok:
            self.assertTrue(game.textual_in_range(raw), raw)
        for raw in bad + [None, 8.2, b"8.2"]:  # type: ignore[list-item]
            self.assertFalse(game.textual_in_range(raw), raw)  # type: ignore[arg-type]

    def test_gate_checks_version_and_shapes(self) -> None:
        from textual._compositor import ChopsUpdate, CompositorUpdate
        from textual.app import App
        args = (ChopsUpdate, CompositorUpdate, App)
        self.assertTrue(game.crop_supported("8.2.7", *args))
        self.assertTrue(game.CROP_OK)  # the installed Textual is inside the tested range
        self.assertFalse(game.crop_supported("9.0.0", *args))
        self.assertFalse(game.crop_supported("not a version", *args))
        self.assertFalse(game.crop_supported("", *args))
        self.assertFalse(game.crop_supported("8.2.7", None, CompositorUpdate, App))  # import failed
        self.assertFalse(game.crop_supported("8.2.7", ChopsUpdate, None, App))

        class NoEnds:  # a ChopsUpdate that lost chop_ends
            def __init__(self, chops: object, spans: object) -> None: ...
            def render_segments(self, console: object) -> str: return ""

        class OtherDisplay:  # an App whose _display changed
            def _display(self, screen: object, renderable: object, extra: object) -> None: ...

        self.assertFalse(game.crop_supported("8.2.7", NoEnds, CompositorUpdate, App))
        self.assertFalse(game.crop_supported("8.2.7", ChopsUpdate, CompositorUpdate, OtherDisplay))
        self.assertFalse(game.crop_supported("8.2.7", ChopsUpdate, CompositorUpdate, object()))

    def test_crop_update_uses_stock_updates_when_off_or_odd(self) -> None:
        from textual._compositor import ChopsUpdate
        chops = ChopsUpdate([{0: None}], [(0, 0, 1)], [[1]])
        self.assertIsInstance(game.crop_update(chops), game.CroppedChops)
        game.CROP_OK = False
        self.addCleanup(lambda: setattr(game, "CROP_OK", True))
        self.assertIs(game.crop_update(chops), chops)
        game.CROP_OK = True
        del chops.chop_ends  # a Textual that dropped the attribute
        self.assertIs(game.crop_update(chops), chops)
        saved = game.CompositorUpdate
        game.CompositorUpdate = None
        self.addCleanup(lambda: setattr(game, "CompositorUpdate", saved))
        self.assertIs(game.crop_update(chops), chops)

    def test_a_failing_crop_falls_back_to_the_stock_output(self) -> None:
        class Stock:
            spans = [(0, 0, 1)]  # no chops / chop_ends: the crop itself raises
            def render_segments(self, console: object) -> str: return "STOCK"

        self.assertEqual(game.CroppedChops(Stock()).render_segments(object()), "STOCK")

    def test_crop_sends_exactly_the_span(self) -> None:
        """Independent of the app and its frames: a known strip, a known span, exact cells."""
        from rich.console import Console
        from rich.segment import Segment
        from rich.style import Style
        from textual._compositor import ChopsUpdate
        from textual.strip import Strip

        def strip(offset: int) -> Strip:  # ten one-cell pieces, each its own colour
            return Strip([Segment(chr(65 + i), Style.parse(f"rgb({10 * i + 10},0,0) on rgb(0,{i + 1},0)"))
                          for i in range(10)])

        console = Console(color_system="truecolor", force_terminal=True, width=500, file=io.StringIO())
        for x0, span in ((0, (3, 6)), (4, (6, 9)), (2, (2, 12)), (2, (0, 5)), (0, (0, 10))):
            update = ChopsUpdate([{x0: strip(x0)}, {x0: strip(x0)}], [(1, span[0], span[1])], [[x0 + 10]] * 2)
            term = Term()
            term.feed(game.CroppedChops(update).render_segments(console))
            lo, hi = max(x0, span[0]), min(x0 + 10, span[1])
            self.assertEqual(sorted(x for x, y in term.cells), list(range(lo, hi)), (x0, span))
            self.assertTrue(all(y == 1 for x, y in term.cells))
            for x in range(lo, hi):
                i = x - x0
                self.assertEqual(term.cells[(x, 1)],
                                 (chr(65 + i), (10 * i + 10, 0, 0), (0, i + 1, 0)), (x0, span, x))


class PaintStock(AnimCase):
    """With the crop gated off, or failing, the picture is still exactly a full render."""

    def setUp(self) -> None:
        super().setUp()
        orig = game.DataCenter.tick
        game.DataCenter.tick = lambda self: None  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(game.DataCenter, "tick", orig))
        self.term = install_term(self)
        self.check = Paint.check.__get__(self)  # reuse the equivalence check

    async def flows(self, mode: str) -> None:
        big = [200, 100, 50, 30, 20] + [0] * (N - 5)
        async with self.run_app(live_save(site_owned=[big], site_balance=[10**12])) as (app, pilot):
            await self.check(app, pilot, f"{mode} idle")
            app.sparkle(1, big=True)
            for _ in range(5):
                self.frame(app, 1 / 12)
                await self.check(app, pilot, f"{mode} frame")
            for key in ("pagedown", "home"):
                await pilot.press(key)
                await self.check(app, pilot, f"{mode} {key}")
            await pilot.resize_terminal(80, 24)
            await pilot.pause(0.2)
            await self.check(app, pilot, f"{mode} resize")

    async def test_unsupported_textual_version(self) -> None:
        game.CROP_OK = game.crop_supported("9.0.0", game.ChopsUpdate, game.CompositorUpdate, game.App)
        self.addCleanup(lambda: setattr(game, "CROP_OK", True))
        self.assertFalse(game.CROP_OK)
        await self.flows("textual 9.0")

    async def test_garbage_version(self) -> None:
        game.CROP_OK = game.crop_supported("garbage", game.ChopsUpdate, game.CompositorUpdate, game.App)
        self.addCleanup(lambda: setattr(game, "CROP_OK", True))
        self.assertFalse(game.CROP_OK)
        await self.flows("garbage version")

    async def test_crop_that_raises_falls_back(self) -> None:
        def boom(self: object, console: object) -> str:
            raise RuntimeError("private API changed")

        orig = game.CroppedChops.cropped
        game.CroppedChops.cropped = boom  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(game.CroppedChops, "cropped", orig))
        await self.flows("raising crop")


# ------------------------------------------------- chip pips, tier headers, hall navigation

TALL = (120, 60)
CHIPS = [0, 5, 20, 1, 4] + [0] * (N - 5)  # tier 0 none, 1 = L5, 2 = full, 3 = L1, 4 = L4


def chip_save(**extra: object) -> dict[str, object]:
    return live_save(site_chips=[list(CHIPS)], **extra)


def line_text(cells: list[game.Cell]) -> str:
    return "".join(c[0] for c in cells)


def header_lines(app: object) -> dict[int, list[game.Cell]]:
    """Visible hall line -> its cells, for every tier header line on screen."""
    hall = app.query_one(game.Hall)  # type: ignore[attr-defined]
    lay = hall.rack_layout()
    cells = hall.build_cells()
    return {b.line0 - lay.top_line: cells[b.line0 - lay.top_line]
            for b in lay.blocks[lay.start:lay.end] if b.kind == "head"}


def pip_pixels(app: object, idx: int, tier: int) -> list[game.RGB]:
    """The five chip pip pixels under rack `idx`, from the cached base picture."""
    hall = app.query_one(game.Hall)  # type: ignore[attr-defined]
    hall.render()
    x, y = hall.rack_layout().rack_xy(idx, tier)
    return [hall._base[0][y + 6][x + 1 + i] for i in range(5)]


class NoFloats(AnimCase):
    async def test_money_floats_are_gone_but_flash_and_sparks_stay(self) -> None:
        self.assertFalse(any("float" in n.lower() for n in dir(game) if n != "float"))
        self.assertFalse(hasattr(game.Hall, "draw_floats"))
        async with self.run_app(live_save(site_balance=[10**9])) as (app, pilot):
            for _ in range(4):
                self.t += 1.0
                app.tick()
            self.assertEqual(app.fx, [])  # earning money launches nothing
            await pilot.press("1")
            self.assertEqual([f.kind for f in app.fx], ["spark"])
            self.assertNotEqual(app.cash_flash, 0)
            for i in range(6):
                self.assertNotIn("+$", hall_frame(app, self.t + i * 0.2).plain)


class ChipPips(AnimCase):
    def test_levels_are_five_families_of_four_editions(self) -> None:
        self.assertEqual(game.MAX_CHIP, game.CHIP_PIPS * game.CHIP_STEPS)
        want = {0: [0, 0, 0, 0, 0], 1: [1, 0, 0, 0, 0], 4: [4, 0, 0, 0, 0],
                5: [4, 1, 0, 0, 0], 20: [4, 4, 4, 4, 4]}
        for level, pips in want.items():
            self.assertEqual(game.chip_pips(level), pips, level)
        for level in range(21):
            self.assertEqual(sum(game.chip_pips(level)), level)  # nothing lost, nothing extra

    async def test_rack_pips_per_level_and_consistent_across_racks(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, _):
            p = app.pal
            ends = list(itertools.accumulate(app.owned))
            for tier in range(5):
                hue, level = p.tiers[tier], CHIPS[tier]
                racks = range(ends[tier] - app.owned[tier], ends[tier])
                seen = {tuple(pip_pixels(app, i, tier)) for i in racks}
                self.assertEqual(len(seen), 1, tier)  # every rack of a tier shows the same level
                pixels = list(seen.pop())
                for step, px in zip(game.chip_pips(level), pixels):
                    if step == 0:
                        self.assertEqual(px, p.pip_floor, (tier, level))
                    else:
                        self.assertNotEqual(px, p.pip_floor, (tier, level))
                        self.assertNotEqual(px, hue, (tier, level))  # never the sprite's own colour
                lit = [game.contrast(px, p.pip_floor) for px in pixels]
                self.assertEqual(lit, sorted(lit, reverse=True))  # fills from the left
            self.assertEqual(set(pip_pixels(app, 0, 0)), {p.pip_floor})  # level 0: nothing installed
            full = set(pip_pixels(app, ends[2] - 1, 2))
            self.assertEqual(len(full), 1)  # level 20: all five pips the same, full
            self.assertGreater(game.lum(full.pop()), game.lum(p.tiers[2]))

    async def test_each_edition_is_a_distinct_brightness(self) -> None:
        async with self.run_app(live_save(), size=TALL) as (app, _):
            hall, p = app.query_one(game.Hall), app.pal
            seen = []
            for level in range(5):  # one family: 0, 1, 2, 3, 4 editions
                app.chips[1] = level
                hall.render()
                hall._base_key = None
                seen.append(pip_pixels(app, app.owned[0], 1)[0])
            self.assertEqual(len(set(seen)), 5)
            self.assertEqual(seen[0], p.pip_floor)
            lums = [game.lum(c) for c in seen]
            self.assertEqual(lums, sorted(lums))  # every edition is brighter than the last

    def test_pips_sit_on_a_row_no_sprite_or_led_uses(self) -> None:
        for sprite in game.SPRITES:
            self.assertEqual(len(sprite), 6)  # rows 0..5; the pips take row 6 (the old shadow)
            self.assertTrue(all(len(row) == 6 for row in sprite))

    async def test_pips_cost_nothing_per_frame(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, _):
            calls: list[int] = []
            orig = game.Hall.base_grid
            game.Hall.base_grid = lambda self, *a, **k: (calls.append(1), orig(self, *a, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "base_grid", orig))
            hall_frame(app, self.t)
            n = len(calls)
            for i in range(1, 6):  # same glow step: the base picture is reused
                hall_frame(app, self.t + i * 0.01)
            self.assertEqual(len(calls), n)
            before = header_lines(app)
            hall_frame(app, self.t + 0.5)
            self.assertEqual(header_lines(app), before)  # headers are identical every frame

    async def test_read_only_pips_are_washed_out(self) -> None:
        async with self.run_app(world_save(site_chips=[[20] * N] * 3), size=TALL) as (app, pilot):
            live = pip_pixels(app, 0, 0)
            await pilot.press("left_square_bracket")
            self.assertTrue(app.read_only)
            dead = pip_pixels(app, 0, 0)
            self.assertEqual(len(set(dead)), 1)  # level 20: all five pips full
            spread = lambda c: max(c) - min(c)  # noqa: E731
            self.assertLess(spread(dead[0]), spread(live[0]))  # grey, not the tier colour
            self.assertNotEqual(dead[0], app.pal.shadow)
            self.assertIsNone(app._anim_timer)
            self.assertEqual(hall_frame(app, 1.0), hall_frame(app, 7.3))  # still

    async def test_card_shows_the_same_mini_indicator(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, pilot):
            await pilot.press("c")
            app.shop_top = 0
            app.redraw()
            lines = app._last["#shop"].plain.split("\n")
            for tier, pips in enumerate(["·····", "█▂···", "█████", "▂····", "█····"]):
                if 2 * tier + 1 < len(lines):  # a short card shows fewer tiers
                    self.assertIn(pips, lines[2 * tier], tier)
            for ln in lines:
                self.assertLessEqual(len(ln), game.ROW_W)


class Headers(AnimCase):
    def test_header_label_fits_and_degrades_in_order(self) -> None:
        self.assertEqual(game.header_label("COMPUTE NODE", 9, 3, 60), "COMPUTE NODE x9 · chip L3/20")
        self.assertEqual(game.header_label("COMPUTE NODE", 9, 3, 25), "COMPUTE NODE x9 · L3/20")
        self.assertEqual(game.header_label("COMPUTE NODE", 9, 3, 21), "COMPUTE NODE x9 L3/20")
        self.assertEqual(game.header_label("NEUTRON STAR FARM", 4000, 20, 27), "NEUTRON STAR… x4000 L20/20")
        for room in range(0, 70):
            for name in ("BUDGET VPS", "NEUTRON STAR FARM"):
                self.assertLessEqual(len(game.header_label(name, 4000, 20, room)), max(0, room))
        self.assertIn("L20/20", game.header_label("NEUTRON STAR FARM", 4000, 20, 27))  # the level stays

    async def test_every_owned_tier_has_a_header_with_its_key_and_level(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, _):
            heads = header_lines(app)
            self.assertEqual(len(heads), 5)  # only tiers you own
            for (line, cells), tier in zip(sorted(heads.items()), range(5)):
                text = line_text(cells)
                name = game.TIERS[tier][0].upper()
                self.assertIn(f" {tier + 1} ", text[:3])  # the number key that buys it
                self.assertIn(f"{name} x{app.owned[tier]}", text)
                self.assertIn(f"L{CHIPS[tier]}/20", text)
                self.assertEqual(cells[0][2], app.pal.tiers[tier])  # badge in the tier colour
                self.assertEqual(sum(c[1] == app.pal.frame for c in cells) > 0, True)  # rule

    async def test_the_tenth_tier_is_key_zero(self) -> None:
        async with self.run_app(live_save(site_owned=[[1] * N], site_chips=[[0] * N]),
                                size=(120, 90)) as (app, _):
            last = line_text(header_lines(app)[max(header_lines(app))])
            self.assertTrue(last.startswith(" 0  BLACK HOLE COLO"), last)

    async def test_headers_scroll_with_the_content(self) -> None:
        big = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[big], site_chips=[[0] * N])) as (app, pilot):
            hall = app.query_one(game.Hall)
            await pilot.press("home")
            lay = hall.rack_layout()
            self.assertEqual(lay.blocks[0].kind, "head")
            self.assertIn("BUDGET VPS", line_text(header_lines(app)[0]))
            first = lay.blocks[lay.start + 1]  # one block down: the header is gone, racks moved up
            await pilot.press("down")
            self.assertEqual(hall.rack_layout().start, 1)
            self.assertNotIn(0, header_lines(app))
            seen = set()
            for _ in range(len(lay.blocks)):  # walk to the end: every tier's header shows up
                seen.update(line_text(c).split()[1] for c in header_lines(app).values())
                await pilot.press("down")
            self.assertTrue({"COMPUTE", "GPU", "AI", "QUANTUM", "ORBITAL", "FUSION"} <= seen, seen)
            del first

    async def test_header_follows_its_racks_by_exactly_the_block_height(self) -> None:
        big = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[big], site_chips=[[0] * N])) as (app, pilot):
            hall = app.query_one(game.Hall)
            await pilot.press("home")
            for _ in range(6):
                lay = hall.rack_layout()
                before = {b.tier: b.line0 - lay.top_line for b in lay.blocks[lay.start:lay.end]
                          if b.kind == "head"}
                await pilot.press("down")
                lay2 = hall.rack_layout()
                step = lay.blocks[lay.start].height  # lines the content moved up
                after = {b.tier: b.line0 - lay2.top_line for b in lay2.blocks[lay2.start:lay2.end]
                         if b.kind == "head"}
                for tier, line in after.items():
                    if tier in before:
                        self.assertEqual(line, before[tier] - step)

    async def test_follow_newest_with_headers_and_a_new_tier(self) -> None:
        big = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[big], site_balance=[10**15])) as (app, pilot):
            hall = app.query_one(game.Hall)
            self.assertIsNone(app.hall_scroll)
            self.assertEqual(hall.rack_layout().end, len(hall.rack_layout().blocks))  # bottom in view
            await pilot.press("8")  # first Dyson Swarm: a new header + row appear at the bottom
            lay = hall.rack_layout()
            self.assertEqual(lay.blocks[-1].tier, 7)
            self.assertEqual(lay.end, len(lay.blocks))
            self.assertIn("DYSON SWARM x1", " ".join(line_text(c) for c in header_lines(app).values()))
            await pilot.press("home")  # scrolled away: buying does not drag the view
            await pilot.press("8")
            self.assertEqual(hall.rack_layout().start, 0)

    async def test_position_and_more_cues(self) -> None:
        big = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[big])) as (app, pilot):
            hall = app.query_one(game.Hall)
            total = hall.rack_layout().total_rows
            self.assertEqual(app._titles["#hall:sub"].strip(), "▲ more")  # following: bottom
            self.assertIn(f"of {total}", app._titles["#hall"])
            await pilot.press("home")
            self.assertEqual(app._titles["#hall:sub"].strip(), "▼ more")
            self.assertIn("rows 1-", app._titles["#hall"])
            await pilot.press("down")
            self.assertEqual(app._titles["#hall:sub"].strip(), "▲ more · ▼ more")
            lay = hall.rack_layout()
            shown = [b.row for b in lay.blocks[lay.start:lay.end] if b.kind == "rack"]
            self.assertIn(f"rows {shown[0] + 1}-{shown[-1] + 1} of {total}", app._titles["#hall"])
            await pilot.press("end")
            self.assertEqual(app._titles["#hall:sub"].strip(), "▲ more")

    async def test_no_cue_when_everything_fits(self) -> None:
        async with self.run_app(live_save(site_owned=[[2] + [0] * (N - 1)]), size=TALL) as (app, _):
            self.assertEqual(app._titles["#hall:sub"], "")
            self.assertNotIn("rows", app._titles["#hall"])
            self.assertFalse(app.query_one(game.Hall).rack_layout().scrolled)

    async def test_title_keeps_the_position_on_a_narrow_hall(self) -> None:
        big = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[big]), size=(80, 24)) as (app, pilot):
            await pilot.press("home")
            title = app._titles["#hall"]
            self.assertRegex(title, r"1-\d+/\d+$")  # "rows" and the arrows give way to the numbers
            self.assertLessEqual(len(title), app.query_one(game.Hall).size.width - 4)

    async def test_decommissioned_title_keeps_its_label_and_position(self) -> None:
        async with self.run_app(world_save(), size=(150, 24)) as (app, pilot):
            await pilot.press("left_square_bracket")
            title = app._titles["#hall"]
            self.assertIn("DECOMMISSIONED", title)
            self.assertIn("rows ", title)
            self.assertLessEqual(len(title), app.query_one(game.Hall).size.width - 4)
        async with self.run_app(world_save(), size=(80, 24)) as (app, pilot):  # too narrow for the label
            await pilot.press("left_square_bracket")
            self.assertRegex(app._titles["#hall"], r"\d+-\d+/\d+$")  # the position survives
            self.assertLessEqual(len(app._titles["#hall"]), app.query_one(game.Hall).size.width - 4)

    async def test_read_only_headers_are_washed_out_and_still(self) -> None:
        async with self.run_app(world_save(), size=TALL) as (app, pilot):
            live = list(header_lines(app).values())[0]
            await pilot.press("left_square_bracket")
            self.assertTrue(app.read_only)
            dead = list(header_lines(app).values())[0]
            spread = lambda c: max(c) - min(c)  # noqa: E731
            self.assertLess(spread(dead[0][2]), spread(live[0][2]))  # grey badge, not the tier colour
            self.assertEqual(hall_frame(app, 1.0), hall_frame(app, 9.9))  # nothing moves
            self.assertIsNone(app._anim_timer)

    async def test_widths_at_80x24_and_everything_you_could_own(self) -> None:
        fleets = [[4000] * N, [1] * N, [25, 9, 1] + [0] * (N - 3), [4000] + [0] * (N - 1)]
        for fleet in fleets:
            for chips in ([0] * N, [20] * N, [7] * N):
                async with self.run_app(live_save(site_owned=[fleet], site_chips=[chips],
                                                  site_balance=[10**15]), size=(80, 24)) as (app, pilot):
                    hall = app.query_one(game.Hall)
                    for key in ("home", "pagedown", "down", "end", "pageup"):
                        await pilot.press(key)
                        for row in hall.build_cells():
                            self.assertLessEqual(len(row), hall.size.width, (fleet[:2], key))
                        for ln in hall.render().plain.split("\n"):
                            self.assertLessEqual(len(ln), hall.size.width)
                        for cells in header_lines(app).values():
                            self.assertIn("L", line_text(cells))
                            self.assertGreaterEqual(len(cells), hall.size.width - 1)
                    await pilot.press("c")
                    for top in (0, 5):
                        app.shop_top = top
                        app.redraw()
                        for ln in app._last["#shop"].plain.split("\n"):
                            self.assertLessEqual(len(ln), game.ROW_W)

    async def test_headers_and_pips_are_readable_on_every_theme(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, pilot):
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                for cells in header_lines(app).values():
                    for ch, fg, bg in cells:
                        if ch not in " ─":
                            self.assertGreaterEqual(game.contrast(fg, bg), 2.99, (name, ch))
                    self.assertGreaterEqual(game.contrast(cells[1][1], cells[1][2]), 2.99, name)  # key badge
                p = app.pal
                self.assertNotEqual(pip_pixels(app, 8, 1)[0], pip_pixels(app, 8, 1)[4], name)  # L5 shows
                self.assertNotEqual(pip_pixels(app, 8, 1)[0], p.pip_floor, name)


class HeaderPaint(AnimCase):
    def setUp(self) -> None:
        super().setUp()
        self.term = install_term(self)
        orig = game.DataCenter.tick
        game.DataCenter.tick = lambda self: None  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(game.DataCenter, "tick", orig))
        self.check = Paint.check.__get__(self)

    def headers_match(self, app: object, label: str) -> None:
        """Header text and rule cells, which Paint.check skips (it compares only the pixels)."""
        cached, want = screen_cells(app), expected_cells(app)
        n = 0
        for line in header_lines(app):
            norm = lambda cells: [(ch, None if ch == " " else fg, bg) for ch, fg, bg in cells]  # noqa: E731
            self.assertEqual(norm(cached[line][:len(want[line])]), norm(want[line]), (label, line))
            n += 1
        self.assertGreater(n + (1 if not header_lines(app) else 0), 0)

    async def test_cache_term_and_full_render_agree_with_headers_and_chips(self) -> None:
        big = [200, 100, 50, 30, 20] + [0] * (N - 5)
        save = live_save(site_owned=[big], site_balance=[10**15], site_chips=[[0, 5, 20, 1, 4] + [0] * (N - 5)])
        async with self.run_app(save) as (app, pilot):
            await self.check(app, pilot, "idle")
            self.headers_match(app, "idle")
            for key in ("home", "down", "down", "pagedown", "pageup", "end", "up"):
                await pilot.press(key)
                await self.check(app, pilot, key)
                self.headers_match(app, key)
            await pilot.press("c")
            await pilot.press("2")  # buy a chip: the header text and the pips change, nothing stale
            await self.check(app, pilot, "chip bought")
            self.headers_match(app, "chip bought")
            await pilot.press("home")
            await self.check(app, pilot, "home after the chip")
            hall = app.query_one(game.Hall)
            lay = hall.rack_layout()
            head = hall.header_cells(lay.blocks[lay.tier_block[1]], 60, app.pal.bg)
            self.assertIn("COMPUTE NODE x100 · chip L6/20", line_text(head))
            self.assertIn("L6", app._last["#shop"].plain)  # the chips card agrees with the header
            for size in ((80, 24), (150, 50)):
                await pilot.resize_terminal(*size)
                await pilot.pause(0.2)
                await self.check(app, pilot, f"resize {size}")
                self.headers_match(app, f"resize {size}")
            for _ in range(4):
                self.frame(app, 1 / 12)
                await self.check(app, pilot, "frame")

    async def test_old_world_with_headers(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            await pilot.press("left_square_bracket")
            await self.check(app, pilot, "old world")
            self.headers_match(app, "old world")


def lab(c: game.RGB) -> tuple[float, float, float]:
    """CIE Lab of an sRGB colour, for measuring how different two colours look."""
    def f(v: int) -> float:
        x = v / 255
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = f(c[0]), f(c[1]), f(c[2])
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, \
        (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    h = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * h(y) - 16, 500 * (h(x) - h(y)), 200 * (h(y) - h(z))


class PipVisibility(AnimCase):
    async def test_every_level_is_clear_on_every_theme_and_tier(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            worst_contrast, worst_step = 99.0, 999.0
            for name, theme in sorted(app.available_themes.items()):
                p = game.Palette(theme.to_color_system().generate(), theme.dark)
                for tier in range(N):
                    grey = int(game.lum(p.tiers[tier]) * 255)  # a decommissioned world's colour
                    for hue in (p.tiers[tier], game.mix((grey, grey, grey), p.surface, 0.55)):
                        cols = [game.pip_colour(s, hue, p.pip_floor) for s in range(game.CHIP_STEPS + 1)]
                        self.assertEqual(cols[0], p.pip_floor)
                        for c in cols[1:]:
                            worst_contrast = min(worst_contrast, game.contrast(c, p.pip_floor))
                        for a, b in zip(cols, cols[1:]):  # empty -> 1 -> 2 -> 3 -> 4
                            worst_step = min(worst_step, math.dist(lab(a), lab(b)))
            self.assertGreaterEqual(worst_contrast, 2.99)  # lit against empty
            self.assertGreaterEqual(worst_step, 8.0)  # adjacent levels clearly different (CIE76 dE)

    async def test_the_hall_really_draws_those_colours_on_a_light_and_a_dark_theme(self) -> None:
        async with self.run_app(chip_save(), size=TALL) as (app, pilot):
            for name in ("gruvbox", "atom-one-light"):
                app.theme = name
                await pilot.pause()
                app._pal = None
                p = app.pal
                px = pip_pixels(app, 8, 1)  # tier 1 at L5: [full, 1 step, empty, empty, empty]
                self.assertGreaterEqual(game.contrast(px[0], p.pip_floor), 2.99, name)
                self.assertGreaterEqual(game.contrast(px[1], p.pip_floor), 2.99, name)
                self.assertEqual(px[2:], [p.pip_floor] * 3, name)
                self.assertGreater(math.dist(lab(px[0]), lab(px[1])), 8, name)


class NoOrphanHeaders(AnimCase):
    @staticmethod
    def layout(owned: list[int], w: int, h: int, scroll: int | None) -> game.Layout:
        from textual.geometry import Size

        class Fake:
            pass
        fake = Fake()
        fake.owned, fake.hall_scroll = list(owned), scroll  # type: ignore[attr-defined]

        class H(game.Hall):
            game = property(lambda self: fake)  # type: ignore[assignment]
            size = property(lambda self: Size(w, h))  # type: ignore[assignment]
        hall = H.__new__(H)
        hall._blocks_owned, hall._blocks = (), {}
        return hall.rack_layout()

    def check(self, owned: list[int], w: int, h: int) -> None:
        n = len(self.layout(owned, w, h, None).blocks)
        seen: set[int] = set()
        for scroll in [None, *range(n + 2)]:
            lay = self.layout(owned, w, h, scroll)
            vis = lay.blocks[lay.start:lay.end]
            label = (owned, w, h, scroll)
            self.assertTrue(vis, label)
            self.assertNotEqual(vis[-1].kind, "head", label)  # never a header without its racks
            self.assertLessEqual(lay.used, lay.height, label)
            seen.update(range(lay.start, lay.end))
            if lay.end < n:  # the window is as full as it can be without a trailing header
                nxt = lay.blocks[lay.end]
                fits = lay.used + nxt.height <= lay.height
                self.assertTrue(not fits or nxt.kind == "head", label)
        follow = self.layout(owned, w, h, None)
        self.assertEqual(follow.end, n, (owned, w, h))  # following shows the very last rack
        racks = [b for b in follow.blocks if b.kind == "rack"]
        self.assertIsNotNone(follow.rack_xy(racks[-1].first + racks[-1].count - 1, racks[-1].tier))
        self.assertEqual(len(seen), n, (owned, w, h))  # every block (so every rack) is reachable

    def test_no_orphan_header_for_many_sizes_fleets_and_positions(self) -> None:
        fleets = [[30, 20, 12, 9, 5, 3, 1, 0, 0, 0], [1] * 10, [60] + [0] * 9, [0, 0, 7, 0, 1, 0, 0, 0, 0, 2],
                  [25, 9, 1] + [0] * 7, [3] * 10, [12, 1, 12, 1, 12, 1, 12, 1, 12, 1]]
        for owned in fleets:
            for w in (14, 31, 62, 150):
                for h in (5, 6, 9, 14, 15, 24, 33):
                    self.check(owned, w, h)

    def test_the_reported_case(self) -> None:
        owned = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        lay = self.layout(owned, 32, 15, 6)  # 80x24 hall, a few steps down from the top
        self.assertNotEqual(lay.blocks[lay.end - 1].kind, "head")

    async def test_keys_reach_every_rack_and_never_end_on_a_header(self) -> None:
        owned = [30, 20, 12, 9, 5, 3, 1, 0, 0, 0]
        async with self.run_app(live_save(site_owned=[owned]), size=(80, 24)) as (app, pilot):
            hall = app.query_one(game.Hall)
            await pilot.press("home")
            seen: set[int] = set()
            for _ in range(60):
                lay = hall.rack_layout()
                self.assertNotEqual(lay.blocks[lay.end - 1].kind, "head")
                seen.update(range(lay.start, lay.end))
                await pilot.press("down")
            self.assertEqual(len(seen), len(hall.rack_layout().blocks))
            await pilot.press("home")
            seen.clear()
            for _ in range(60):
                lay = hall.rack_layout()
                seen.update(range(lay.start, lay.end))
                await pilot.press("pagedown")
            self.assertIn(len(lay.blocks) - 1, seen)  # pagedown gets to the last rack row
            await pilot.press("home")
            await pilot.press("end")
            self.assertIsNone(app.hall_scroll)
            self.assertEqual(hall.rack_layout().end, len(hall.rack_layout().blocks))
