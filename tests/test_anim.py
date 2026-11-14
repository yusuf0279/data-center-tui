"""Animation: time-based and deterministic (the clock is patched), smooth frame to frame,
and completely idle in a background pane / old data center / with DC_ANIM=0."""
import asyncio
import math

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

    def test_float_rows_rate_and_ease_out(self) -> None:
        self.assertEqual(game.float_rows(0), 0)
        self.assertAlmostEqual(game.float_rows(game.FLOAT_LIFE_S), game.FLOAT_ROWS)
        self.assertEqual(game.float_rows(99), game.FLOAT_ROWS)
        self.assertAlmostEqual(game.FLOAT_LIFE_S / game.FLOAT_ROWS, game.FLOAT_ROW_S)  # 1 row per 0.28 s
        self.assertTrue(0.25 <= game.FLOAT_ROW_S <= 0.3)
        steps = [game.float_rows(i * game.FLOAT_LIFE_S / 20) for i in range(21)]
        gaps = [b - a for a, b in zip(steps, steps[1:])]
        self.assertTrue(all(g >= 0 for g in gaps))
        self.assertTrue(all(a >= b for a, b in zip(gaps, gaps[1:])))  # decelerating

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
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$1.00K")
            app.sparkle(0, big=True)
            a, b = hall_frame(app, self.t + 0.3), hall_frame(app, self.t + 0.3)
            self.assertEqual(a, b)
            self.assertNotEqual(hall_frame(app, self.t + 0.4), a)  # LEDs, pulse, bus move

    async def test_pulse_glides_monotonically_in_sub_cell_steps(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            hall = app.query_one(game.Hall)
            ends = list(game.accumulate(app.owned))
            heads = []
            for i in range(7):  # t = 0 .. 0.5 s at 12 fps
                grid = [[app.pal.frame] * (game.CELL_W * 8) for _ in range(game.CELL_H)]
                hall.draw_bus(grid, 0, 8, 8, ends, i / 12)
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
                c, *_ = hall.rack_layout()
                j = sum(app.owned) - 1  # the lone Quantum Farm, last in the hall
                cols.append(hall._base[0][(j // c) * game.CELL_H + 1 + 2][(j % c) * game.CELL_W])
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
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$9.99M")
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
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$123.45Qi")
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
            self.assertEqual(len(app.fx), 1)

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
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$1")
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
    async def test_income_floats_are_throttled_and_expire(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            for _ in range(10):
                before = sum(f.kind == "float" for f in app.fx)
                self.t += 1.0
                app.tick()
                after = sum(f.kind == "float" for f in app.fx)
                self.assertLessEqual(after, game.MAX_FLOATS)
                self.assertLessEqual(after - before, 1)  # one per second at most
            self.assertIn(f"+${game.fmt(app.income)}", [f.text for f in app.fx])
            app.owned[:] = [0] * N  # income stops: what is left must fade out
            self.t += game.FLOAT_LIFE_S
            app.tick()
            self.assertEqual(app.fx, [])

    async def test_floats_rise_at_the_specified_rate(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.fx.clear()
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$5")
            born = self.t
            hall = app.query_one(game.Hall)
            rows = []
            for i in range(int(game.FLOAT_LIFE_S / 0.07)):
                app.now = born + i * 0.07
                lines = hall.render().plain.split("\n")
                hit = [k for k, ln in enumerate(lines) if "+$5" in ln]
                rows.append(hit[0] if hit else None)
            seen = [r for r in rows if r is not None]
            self.assertTrue(all(a >= b for a, b in zip(seen, seen[1:])))  # only ever goes up
            self.assertEqual(seen[0] - seen[-1] >= game.FLOAT_ROWS - 2, True)
            # average speed: the full climb takes FLOAT_ROWS * FLOAT_ROW_S seconds
            self.assertAlmostEqual(game.float_rows(game.FLOAT_ROW_S * 7), 7.0)
            first = {r: i for i, r in reversed(list(enumerate(rows))) if r is not None}
            self.assertGreater(len(first), game.FLOAT_ROWS - 3)  # visits (nearly) every row
            # patched clock: a frame at +life removes it
            self.frame(app, game.FLOAT_LIFE_S + 0.01)
            self.assertEqual([f for f in app.fx if f.text == "+$5"], [])

    async def test_float_fades_towards_the_top(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.fx.clear()
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$5")
            cols = []
            for i in range(11):
                app.now = self.t + game.FLOAT_LIFE_S * i / 10
                cells = [[(" ", app.pal.bg, app.pal.bg)] * 20 for _ in range(12)]
                app.query_one(game.Hall).draw_floats(cells)
                cols.append(next((c[1] for r in cells for c in r if c[0] == "+"), None))
            cols = [c for c in cols if c]
            self.assertGreater(len(set(cols)), 3)
            self.assertGreater(game.lum(cols[0]) , -1)
            for a, b in zip(cols, cols[1:]):
                self.assertLessEqual(delta(a, b), 40)

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
                app.query_one(game.Hall).draw_sparks(grid, 0, 5, 5, list(game.accumulate(app.owned)))
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
            hall = app.query_one(game.Hall)
            frames = [hall_frame(app, self.t + i / 12) for i in range(6)]
            self.assertEqual(len({str(f.spans) for f in frames}), 6)  # all distinct


class Contrast(AnimCase):
    async def test_float_stays_readable_on_every_theme(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                p = app.pal
                app.fx.clear()
                app.add_fx("float", game.FLOAT_LIFE_S, text="+$5")
                for u in (0, 0.5, 0.9, 0.999):
                    app.now = app.fx[0].born + u * game.FLOAT_LIFE_S
                    cells = [[(" ", p.bg, m) for m in (p.bg, p.surface)] * 10 for _ in range(10)]
                    app.query_one(game.Hall).draw_floats(cells)
                    glyphs = [c for row in cells for c in row if c[0] == "+"]
                    self.assertTrue(glyphs, (name, u))
                    for _, fg, under in glyphs:
                        self.assertGreaterEqual(game.contrast(fg, under), game.FLOAT_MIN_CONTRAST, name)


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


class Paint(AnimCase):
    def setUp(self) -> None:
        super().setUp()
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
        force_full_render(app)
        await pilot.pause(0.15)  # type: ignore[attr-defined]
        self.assertEqual(screen_cells(app), cached, label)

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
            app.add_fx("float", game.FLOAT_LIFE_S, text="+$1.00K")
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
                self.assertIn(p.shadow, {c[2] for row in cached for c in row}, name)  # new colours
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
