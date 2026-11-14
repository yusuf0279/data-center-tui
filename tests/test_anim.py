"""Animation: deterministic frames, nothing moves in a background pane / old data center /
with DC_ANIM=0, effects expire, and the relocation transition finishes cleanly."""
from helpers import AppCase, game, world_save

N = len(game.TIERS)


def live_save(**extra: object) -> dict[str, object]:
    """One live data center with some racks of the first tiers (so there is income)."""
    save: dict[str, object] = {
        "site_balance": [5_000], "site_owned": [[8, 6, 4, 2, 1] + [0] * (N - 5)],
        "site_chips": [[0] * N], "site_staff": [[-1] * N], "sites": 0, "cur": 0, "fame": 0,
        "autopilot": False, "online": {"asked": True, "joined": False}}
    save.update(extra)
    return save


def hall_text(app: object) -> str:
    return str(app.query_one(game.Hall).render())  # type: ignore[attr-defined]


def hall_frame(app: object, phase: int) -> object:
    app.phase = phase  # type: ignore[attr-defined]
    return app.query_one(game.Hall).render()  # type: ignore[attr-defined]


class AnimCase(AppCase):
    def setUp(self) -> None:
        super().setUp()
        self._anim = game.ANIM
        game.ANIM = True
        self.addCleanup(lambda: setattr(game, "ANIM", self._anim))


class Frames(AnimCase):
    async def test_frames_are_deterministic(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.add_fx("float", game.FLOAT_LIFE, text="+$1.00K")
            app.sparkle(0, big=True)
            a, b = hall_frame(app, 7), hall_frame(app, 7)
            self.assertEqual(a, b)
            self.assertNotEqual(hall_frame(app, 8), a)  # LEDs, pulse and bus move per tick
            self.assertEqual(game.mix32(1, 2, 3), game.mix32(1, 2, 3))
            self.assertEqual(game.wave(0), 0.0)
            self.assertEqual(game.wave(2), 1.0)

    async def test_pulse_targets_the_best_earner(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            self.assertEqual(app.top_tier(), 4)  # 1 Quantum Farm out-earns the cheaper racks
            app.owned[:] = [100, 1, 0, 0, 0] + [0] * (N - 5)
            self.assertEqual(app.top_tier(), 0)
            app.owned[:] = [0] * N
            self.assertIsNone(app.top_tier())

    async def test_every_theme_renders_every_effect(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            app.add_fx("float", game.FLOAT_LIFE, text="+$9.99M")
            app.sparkle(2, big=True)
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                for phase in (0, 1, 2, 3):
                    hall_frame(app, phase)
                    app.redraw()

    async def test_80x24_with_every_effect(self) -> None:
        async with self.run_app(live_save(), size=(80, 24)) as (app, _):
            app.crisis = {"title": "Rogue AI agent deleted prod", "sev": 3, "fixer": None, "eta": None}
            app.add_fx("float", game.FLOAT_LIFE, text="+$123.45Qi")
            app.sparkle(1, big=True)
            hall = app.query_one(game.Hall)
            for phase in range(4):
                app.phase = phase
                app.redraw()
                for line in hall.render().plain.split("\n"):
                    self.assertLessEqual(len(line), hall.size.width)
            app.reloc = {"frame": 3, "gain": 10**9, "rank": "Engineering Manager"}
            for line in hall.render().plain.split("\n"):
                self.assertLessEqual(len(line), hall.size.width)


class Quiet(AnimCase):
    async def test_background_pane_never_animates_or_repaints(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            game.tmux_foreground = lambda: False
            app.foreground = False
            calls: list[int] = []
            orig = game.DataCenter.redraw
            game.DataCenter.redraw = lambda self: (calls.append(self.phase), orig(self))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.DataCenter, "redraw", orig))
            repaints: list[int] = []
            orig_refresh = game.Hall.refresh
            game.Hall.refresh = lambda self, *a, **k: (repaints.append(1), orig_refresh(self, *a, **k))[1]  # type: ignore
            self.addCleanup(lambda: setattr(game.Hall, "refresh", orig_refresh))
            app.phase = 0
            for _ in range(100):
                app.tick()
            self.assertFalse(app.animating)
            self.assertEqual(app.fx, [])
            self.assertIsNone(app._burst)
            self.assertEqual(len(calls), 100 // game.BACKGROUND_REFRESH)  # every Nth tick only
            self.assertLessEqual(len(repaints), 2)  # the hall repaints at most once per redraw
            app.sparkle(0)
            app.start_burst()
            self.assertEqual((app.fx, app._burst), ([], None))
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))  # static frame

    async def test_returning_to_front_animates_on_the_next_tick(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            game.tmux_foreground = lambda: False
            app.tick()
            self.assertEqual(app.fx, [])
            game.tmux_foreground = lambda: True
            app.tick()
            self.assertTrue(app.animating)
            self.assertEqual(len(app.fx), 1)

    async def test_decommissioned_world_stays_washed_out_and_still(self) -> None:
        async with self.run_app(world_save()) as (app, _):
            app.cur = 0
            self.assertTrue(app.read_only)
            for _ in range(3):
                app.tick()
            app.sparkle(0)
            self.assertEqual((app.fx, app._burst, app.animating), ([], None, False))
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))
            app.balance += 1
            app.redraw()
            self.assertEqual(app.cash_flash, 0)

    async def test_effects_are_dropped_when_you_walk_into_an_old_world(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            app.sparkle(0)
            app.add_fx("float", game.FLOAT_LIFE, text="+$1")
            self.assertTrue(app.fx)
            await pilot.press("left_square_bracket")
            self.assertTrue(app.read_only)
            self.assertEqual(app.fx, [])

    async def test_anim_off_is_static(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            game.ANIM = False
            for _ in range(3):
                app.tick()
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            app.redraw()
            self.assertEqual((app.fx, app._burst, app.animating), ([], None, False))
            self.assertEqual(hall_frame(app, 3), hall_frame(app, 4))
            self.assertEqual(str(app._last["#alert"]), "⚠ x  ·  income -50%  ·  press F to fix")
            self.assertEqual(app._last["#alert"].style, "")  # plain: no flicker colours
            self.assertEqual(app.cash_flash, 0)

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
            seen = []
            for _ in range(10):
                before = sum(f.kind == "float" for f in app.fx)
                app.tick()
                after = sum(f.kind == "float" for f in app.fx)
                self.assertLessEqual(after, game.MAX_FLOATS)
                self.assertLessEqual(after - before, 1)  # one per second at most
                seen.append(after)
            self.assertIn(f"+${game.fmt(app.income)}", [f.text for f in app.fx])
            app.owned[:] = [0] * N  # income stops: what is left must fade out
            for _ in range(game.FLOAT_LIFE):
                app.tick()
            self.assertEqual(app.fx, [])

    async def test_sparkle_on_buy_and_big_on_milestone(self) -> None:
        async with self.run_app(live_save(site_owned=[[24] + [0] * (N - 1)])) as (app, pilot):
            await pilot.press("1")  # 25th Budget VPS: x2
            self.assertEqual(app.owned[0], 25)
            self.assertEqual([(f.kind, f.big) for f in app.fx], [("spark", True)])
            app.fx.clear()
            await pilot.press("1")
            self.assertEqual([(f.kind, f.big) for f in app.fx], [("spark", False)])

    async def test_sparks_expire_and_the_frame_timer_stops(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.sparkle(0)
            self.assertIsNotNone(app._burst)
            for _ in range(game.SPARK_LIFE):
                app.anim_frame()
            self.assertEqual([f for f in app.fx if f.kind == "spark"], [])
            self.assertIsNone(app._burst)

    async def test_balance_flash_on_change_only(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.redraw()
            self.assertEqual(app.cash_flash, 0)
            app.balance += 5
            app.redraw()
            self.assertEqual(app.cash_flash, 1)
            self.assertIn("bold", str(app._last["#cash"].spans[-1].style))
            app.anim_frame()
            self.assertEqual(app.cash_flash, 0)
            app.balance -= 5
            app.redraw()
            self.assertEqual(app.cash_flash, -1)

    async def test_crisis_banner_flickers_then_resolves_calmly(self) -> None:
        async with self.run_app(live_save()) as (app, _):
            app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None}
            styles = set()
            for phase in range(4):
                app.phase = phase
                app.redraw()
                styles.add(str(app._last["#alert"].style))
            self.assertEqual(len(styles), 2)  # alternates red / dark
            app.resolve(None)
            self.assertIsNone(app.crisis)
            self.assertEqual(app.resolve_flash, game.RESOLVE_FRAMES)
            app.redraw()
            self.assertTrue(app.query_one("#alert").display)
            self.assertIn("fixed", str(app._last["#alert"]))
            for _ in range(game.RESOLVE_FRAMES):
                app.anim_frame()
            self.assertFalse(app.query_one("#alert").display)
            self.assertIsNone(app._burst)


class Contrast(AnimCase):
    async def test_banner_and_float_stay_readable_on_every_theme(self) -> None:
        async with self.run_app(live_save()) as (app, pilot):
            for name in sorted(app.available_themes):
                app.theme = name
                await pilot.pause()
                app._pal = None
                p = app.pal
                for crisis in (True, False):
                    app.crisis = {"title": "x", "sev": 1, "fixer": None, "eta": None} if crisis else None
                    for flash in ([0] if crisis else range(game.RESOLVE_FRAMES + 1)):
                        for phase in (0, 1):
                            app.phase, app.resolve_flash = phase, flash
                            style = app.alert_banner("fixed").style
                            fg, bg = (tuple(map(int, str(c)[4:-1].split(","))) for c in
                                      str(style).replace("bold ", "").split(" on "))
                            self.assertGreaterEqual(game.contrast(fg, bg), game.BANNER_MIN_CONTRAST,
                                                    (name, crisis, flash, phase))
                app.crisis = None
                app.fx.clear()
                app.add_fx("float", game.FLOAT_LIFE, text="+$5")
                app.fx[0].age = game.FLOAT_LIFE - 1  # last visible frame
                app.owned[:] = [8, 6, 4, 2, 1] + [0] * (N - 5)
                cells = [[(" ", p.bg, mix_) for mix_ in (p.bg, p.surface)] * 10 for _ in range(8)]
                app.query_one(game.Hall).draw_floats(cells)
                glyphs = [c for row in cells for c in row if c[0] == "+"]
                self.assertTrue(glyphs, name)
                for _, fg, under in glyphs:
                    self.assertGreaterEqual(game.contrast(fg, under), game.FLOAT_MIN_CONTRAST, name)


class Relocation(AnimCase):
    async def test_transition_plays_then_the_new_data_center_appears(self) -> None:
        async with self.run_app() as (app, pilot):
            app.site_balance[0] = game.expand_cost(0) * 9  # 3 Fame: Nobody -> Junior Dev
            await pilot.press("x")
            self.assertEqual((app.sites, app.cur, app.fame), (1, 1, 3))  # state changes at once
            self.assertEqual(app.reloc, {"frame": 0, "gain": 3, "rank": "Junior Dev"})
            text = hall_text(app)
            self.assertIn("RELOCATING", text)
            self.assertNotIn("Empty hall", text)
            shots = [app.query_one(game.Hall).render()]
            for _ in range(game.RELOC_FRAMES):
                app.anim_frame()
                shots.append(app.query_one(game.Hall).render())
            frames = [str(t) for t in shots]
            self.assertIn("Fame +3", frames[1])
            self.assertIn("Promoted: Junior Dev!", frames[2])
            self.assertTrue(all(a != b for a, b in zip(shots[:game.RELOC_FRAMES], shots[1:game.RELOC_FRAMES])))  # every frame differs
            self.assertIsNone(app.reloc)
            self.assertIsNone(app._burst)
            self.assertIn("Empty hall", frames[-1])  # the new, empty data center
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
            self.assertNotIn("Promoted", hall_text(app))

    async def test_no_transition_in_background_or_with_anim_off(self) -> None:
        for fg, anim in ((False, True), (True, False)):
            async with self.run_app() as (app, pilot):
                game.ANIM, app.foreground = anim, fg
                app.site_balance[0] = game.expand_cost(0)
                await pilot.press("x")
                self.assertEqual((app.sites, app.reloc, app._burst), (1, None, None))
                game.ANIM = True
