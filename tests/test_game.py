import json
import os
import time

from helpers import AppCase, game, world_save


class Basics(AppCase):
    async def test_fresh_game(self) -> None:
        async with self.run_app() as (app, pilot):
            self.assertEqual((app.theme, app.balance, app.fame, app.sites, app.cur), ("gruvbox", 500, 0, 0, 0))
            self.assertTrue(app.autopilot)  # on for a brand-new game
            await pilot.press("1")
            self.assertEqual((app.owned[0], app.balance), (1, 500 - 60))

    async def test_poor_purchase_is_refused(self) -> None:
        async with self.run_app() as (app, pilot):
            await pilot.press("6")
            self.assertEqual((app.owned[5], app.balance), (0, 500))

    async def test_ten_pick_keys_and_chips_and_crew(self) -> None:
        n = len(game.TIERS)
        async with self.run_app({"site_balance": [10**30], "site_owned": [[1] * n], "site_chips": [[0] * n],
                                 "site_staff": [[-1] * n], "sites": 0, "online": {"asked": True}}) as (app, pilot):
            await pilot.press("0")  # key 0 is the tenth item
            self.assertEqual(app.owned[9], 2)
            await pilot.press("c", "0")
            self.assertEqual(app.chips[9], 1)
            await pilot.press("h", "0")
            self.assertEqual(app.staff[9], 0)
            self.assertIn("runs Black Hole Colo", str(app.query_one(game.RichLog).lines[-1].text))

    async def test_save_round_trip_and_old_six_tier_saves(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            await pilot.press("s", "1")  # ignored: #3 is live, so this buys
            app.save()
        with open(self.save_path) as fh:
            saved = json.load(fh)
        self.assertEqual(len(saved["site_owned"]), 3)
        old = {"balance": 5000, "owned": [1, 2, 3, 4, 5, 6], "chips": [1, 0, 0, 0, 0, 0], "staff": [0, 0, 0, -1, -1, -1]}
        async with self.run_app(old) as (app, pilot):
            self.assertEqual(app.owned, [1, 2, 3, 4, 5, 6, 0, 0, 0, 0])
            self.assertEqual(app.staff, [0, 0, 0, -1, -1, -1, -1, -1, -1, -1])
            self.assertFalse(app.autopilot)  # an existing save never starts spending by itself


class Relocation(AppCase):
    async def test_relocating_resets_and_decommissions(self) -> None:
        async with self.run_app() as (app, pilot):
            app.site_balance[0] = game.expand_cost(0) * 9  # sqrt(9) = 3 Fame
            app.owned[0] = 7
            app.staff[0] = 2
            await pilot.press("x")
            self.assertEqual((app.sites, app.cur, app.fame), (1, 1, 3))
            self.assertEqual((app.balance, app.owned, app.staff[0]), (game.start_balance(1), [0] * 10, -1))
            self.assertEqual(app.site_owned[0][0], 7)  # the old data center is frozen as it was
            self.assertEqual(game.rank_of(app.fame)[0], "Senior Dev" if app.fame >= 6 else "Junior Dev")

    async def test_relocating_needs_the_target_and_the_newest(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            await pilot.press("x")  # poor
            self.assertEqual(app.sites, 2)
            app.site_balance[2] = game.expand_cost(2)
            await pilot.press("left_square_bracket", "x")  # visiting an old one
            self.assertEqual(app.sites, 2)
            await pilot.press("right_square_bracket", "x")
            self.assertEqual(app.sites, 3)

    async def test_old_data_centers_are_decommissioned(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            live_before, old_before = app.site_balance[2], app.site_balance[0]
            income = app.site_income(2)
            await pilot.press("d", "1")  # visit #1
            self.assertTrue(app.read_only)
            app.tick()
            self.assertEqual(app.site_balance[2], live_before + income)  # the live one earned
            self.assertEqual(app.site_balance[0], old_before)  # the old one did not
            self.assertEqual(app.cur, 0)
            owned, balance = list(app.owned), app.balance
            await pilot.press("s", "1", "2", "c", "1", "h", "1")
            self.assertEqual((app.owned, app.balance), (owned, balance))  # nothing can be bought
            self.assertIn("DECOMMISSIONED", app._titles["#hall"])
            self.assertIn("view only", app._titles["#shop"])
            self.assertTrue(app._last["#stats"].plain.startswith("Final"))

    async def test_offline_earnings_go_to_the_live_data_center(self) -> None:
        save = world_save(cur=0, saved_at=time.time() - 3600)
        async with self.run_app(save) as (app, pilot):
            self.assertEqual((app.site_balance[0], app.site_balance[1]), (777, 5_000))
            self.assertGreater(app.site_balance[2], 123_456)
            self.assertEqual(app.away[1], app.site_balance[2] - 123_456)

    async def test_visiting_numbers_follow_data_center_numbers(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            for key, expected in (("1", 0), ("2", 1), ("3", 2)):
                await pilot.press("d", key)
                self.assertEqual(app.cur, expected)


class Crew(AppCase):
    def rich_state(self, owned0: int, staff0: int) -> dict:
        n = len(game.TIERS)
        owned = [owned0] + [0] * (n - 1)
        owned[5], owned[6] = 300, 100  # a big income
        return {"site_balance": [10**9], "site_owned": [owned], "site_chips": [[0] * n],
                "site_staff": [[staff0] + [-1] * (n - 1)], "sites": 0, "autopilot": True,
                "online": {"asked": True}}

    async def test_autopilot_buys_only_cheap_things(self) -> None:
        async with self.run_app(self.rich_state(30, 2)) as (app, pilot):
            income = app.site_income(0)
            before, spent_from = app.owned[0], app.balance
            app.run_autopilot()
            self.assertGreater(app.owned[0], before)
            self.assertLessEqual(spent_from - app.balance, income * game.AUTO_BUYS_PER_TICK // game.AUTO_AFFORD_DIV)

    async def test_autopilot_cannot_starve_a_poor_player(self) -> None:
        n = len(game.TIERS)
        poor = {"site_balance": [10**9], "site_owned": [[10] + [0] * (n - 1)], "site_chips": [[0] * n],
                "site_staff": [[2] + [-1] * (n - 1)], "sites": 0, "autopilot": True, "online": {"asked": True}}
        async with self.run_app(poor) as (app, pilot):
            app.run_autopilot()
            self.assertEqual((app.owned[0], app.balance), (10, 10**9))

    async def test_autopilot_off_and_low_level_do_nothing(self) -> None:
        async with self.run_app(self.rich_state(30, 1)) as (app, pilot):
            app.run_autopilot()
            self.assertEqual(app.owned[0], 30)  # Lv1 does not auto-buy
            app.staff[0] = 2
            await pilot.press("a")  # switch autopilot off
            self.assertFalse(app.autopilot)
            app.run_autopilot()
            self.assertEqual(app.owned[0], 30)

    async def test_specialist_doubles_its_tier(self) -> None:
        async with self.run_app(self.rich_state(10, -1)) as (app, pilot):
            base = app.raw_income(0)
            app.staff[0] = 4
            self.assertEqual(app.raw_income(0) - base, game.tier_income(0, 10, 0, 0))  # tier 1 doubled

    async def test_crises_are_fixed_by_the_right_crew(self) -> None:
        async with self.run_app(self.rich_state(10, 0)) as (app, pilot):
            app.crisis = {"title": "x", "sev": 2, "fixer": None, "eta": None}
            app.update_crisis()
            self.assertIsNone(app.crisis["fixer"])  # a Vibecoder cannot fix outages
            app.staff[1] = 0  # a Prompt Engineer can
            app.update_crisis()
            self.assertEqual(app.crisis["fixer"], 1)
            await pilot.press("f")  # or you fix it yourself
            self.assertIsNone(app.crisis)


class Interface(AppCase):
    async def test_cards_never_exceed_their_width_or_height(self) -> None:
        n = len(game.TIERS)
        for size in ((60, 20), (100, 30), (120, 45)):
            async with self.run_app({"site_balance": [10**30], "site_owned": [[400] * n], "site_chips": [[7] * n],
                                     "site_staff": [[5] * n], "sites": 0, "fame": 10**6,
                                     "online": {"asked": True}}, size=size) as (app, pilot):
                for view in "schdb":
                    await pilot.press(view)
                    for top in (None, 0, 3):
                        app.shop_top = top
                        app.redraw()
                        lines = app._last["#shop"].plain.rstrip("\n").split("\n")
                        self.assertLessEqual(max(len(line) for line in lines), 40, (size, view))
                        self.assertLessEqual(len(lines), app.query_one("#shop").size.height, (size, view))

    async def test_hall_scrolls_and_follows_new_racks(self) -> None:
        async with self.run_app(size=(100, 30)) as (app, pilot):
            app.owned[:] = [300] * 10
            app.redraw()
            hall = app.query_one(game.Hall)
            _, view_rows, total_rows, start = hall.rack_layout()
            self.assertGreater(total_rows, view_rows)
            self.assertEqual(start, total_rows - view_rows)  # following the newest racks
            await pilot.press("home")
            self.assertEqual(hall.rack_layout()[3], 0)
            await pilot.press("pagedown")
            self.assertEqual(hall.rack_layout()[3], view_rows)
            await pilot.press("end")
            self.assertIsNone(app.hall_scroll)

    async def test_naming_a_data_center(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            await pilot.press("n")
            await pilot.press(*"Rack Ops 9", "enter")
            self.assertEqual(app.site_names[2], "Rack Ops 9")
            self.assertIn("Rack Ops 9", app._titles["#hall"])
            await pilot.press("n")
            app.screen.query_one(game.Input).value = "Café"  # plain ASCII only
            await pilot.press("enter")
            self.assertEqual(type(app.screen).__name__, "NameInput")
            await pilot.press("escape")
            self.assertEqual(app.site_names[2], "Rack Ops 9")
            await pilot.press("n")
            app.screen.query_one(game.Input).value = ""  # blank goes back to the default
            await pilot.press("enter")
            self.assertEqual(app.site_names[2], "")

    async def test_menu_and_dialogs_block_game_keys(self) -> None:
        async with self.run_app() as (app, pilot):
            await pilot.press("m")
            self.assertEqual(type(app.screen).__name__, "Menu")
            await pilot.press("7", "8", "s", "x", "1")  # 1 chooses menu item 1 (online is off: disabled)
            self.assertEqual(app.owned[0], 0)
            await pilot.press("4")  # autopilot switch
            self.assertFalse(app.autopilot)
            await pilot.press("escape")
            self.assertEqual(type(app.screen).__name__, "Menu")  # escape opens it from the game

    async def test_every_theme_renders(self) -> None:
        async with self.run_app(world_save()) as (app, pilot):
            app.owned[:] = [30] * 10
            for theme in sorted(app.available_themes):
                app.theme = theme
                await pilot.pause(0)
                for view in "schdb":
                    await pilot.press(view)
            # neighbouring tiers stay clearly different colours on every theme
            import math
            for theme in sorted(app.available_themes):
                app.theme = theme
                app._pal = None
                tiers = app.pal.tiers
                self.assertGreater(min(math.dist(tiers[i], tiers[i + 1]) for i in range(9)), 100, theme)

    def test_malformed_saves_load_into_a_sane_state(self) -> None:
        junk = [None, True, "x", -1, 2**70, 1.5, [], [None], {"a": 1}, [[]], "\x1b[2J", 10**700]
        keys = ("site_balance", "site_owned", "site_chips", "site_staff", "site_names", "sites", "cur", "fame",
                "autopilot", "online", "theme", "saved_at", "balance", "owned", "chips", "staff", "legacy")
        n = len(game.TIERS)
        for key in keys:
            for bad in junk:
                with open(self.save_path, "w") as fh:
                    fh.write(json.dumps({key: bad}))
                app = game.DataCenter()  # must never raise
                self.assertEqual(len(app.site_owned), app.sites + 1, (key, bad))
                self.assertTrue(all(len(row) == n for row in app.site_owned + app.site_chips + app.site_staff))
                self.assertEqual(len(app.site_balance), app.sites + 1)
                self.assertEqual(len(app.site_names), app.sites + 1)
                self.assertTrue(0 <= app.cur <= app.sites)
                self.assertTrue(all(isinstance(b, int) and b >= 0 for b in app.site_balance))

    async def test_a_save_full_of_junk_still_plays(self) -> None:
        junk = {key: "\x1b[2J" for key in ("site_balance", "site_owned", "site_chips", "site_staff", "site_names",
                                            "sites", "cur", "fame", "autopilot", "online", "theme", "saved_at")}
        async with self.run_app(junk) as (app, pilot):
            await pilot.press("s", "1", "c", "h", "d", "b", "x", "f", "a", "m", "escape")
            app.tick()


if __name__ == "__main__":
    import unittest
    unittest.main()
