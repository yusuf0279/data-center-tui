"""The online client against a real local leaderboard server (never the production one)."""
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from helpers import AppCase, game

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import leaderboard as lb  # noqa: E402  # pyright: ignore[reportMissingImports]


class Online(AppCase):
    online = True

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = tempfile.TemporaryDirectory()
        lb.DB_PATH = os.path.join(cls.db.name, "t.db")
        lb.init_db()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), lb.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.db.cleanup()

    def setUp(self) -> None:
        super().setUp()
        game.SERVER = self.url
        lb._recent_submit.clear()
        lb._ip_hits.clear()
        lb._ip_new.clear()
        with lb.db() as conn:
            conn.execute("DELETE FROM players")

    @staticmethod
    def names() -> list[str]:
        return [row["name"] for row in lb.leaderboard(50)["players"]]

    @staticmethod
    def screen(app: game.DataCenter) -> str:
        return type(app.screen).__name__

    async def test_first_run_question_and_declining(self) -> None:
        async with self.run_app() as (app, pilot):
            self.assertEqual(self.screen(app), "YesNo")
            await pilot.press("1", "2", "s")  # game keys do nothing behind the dialog
            self.assertEqual(app.owned[0], 0)
            await pilot.press("n")
            self.assertTrue(app.online_asked and not app.online_joined)
            await pilot.press("1")
            self.assertEqual(app.owned[0], 1)
        self.assertEqual(self.names(), [])  # nothing was sent

    async def test_joining_renaming_and_leaving(self) -> None:
        async with self.run_app() as (app, pilot):
            await pilot.press("y")
            self.assertEqual(self.screen(app), "NameInput")
            await pilot.press("enter")  # empty: refused
            self.assertEqual(self.screen(app), "NameInput")
            await pilot.press(*"Alice 1 sxfq", "enter")  # typing letters must not trigger game keys
            await pilot.pause(1.5)
            self.assertTrue(app.online_joined)
            self.assertEqual(self.names(), ["Alice 1 sxfq"])
            self.assertIn("You: #1 of 1", app._last["#shop"].plain)
            self.assertEqual(len(app.online_token), 32)
            lb._recent_submit.clear()
            await pilot.press("j")  # leave
            self.assertEqual(self.screen(app), "YesNo")
            await pilot.press("y")
            await pilot.pause(1.0)
            self.assertFalse(app.online_joined)
            self.assertEqual(self.names(), [])

    async def test_a_taken_name_asks_again(self) -> None:
        other = {"token": "a" * 32, "name": "Taken", "fame": 1, "sites": 0}
        self.assertEqual(lb.submit(other)["ok"], True)
        async with self.run_app() as (app, pilot):
            await pilot.press("y")
            await pilot.press(*"taken", "enter")
            await pilot.pause(1.5)
            self.assertFalse(app.online_joined)
            self.assertEqual(self.screen(app), "NameInput")
            await pilot.press("escape")
        self.assertEqual(self.names(), ["Taken"])

    async def test_relocating_sends_the_new_fame(self) -> None:
        save = {"fame": 0, "online": {"asked": True, "joined": True, "name": "Bob", "token": "b" * 32}}
        async with self.run_app(save) as (app, pilot):
            app.site_balance[0] = game.expand_cost(0) * 9
            await pilot.press("x")
            await pilot.pause(1.5)
            row = next(r for r in lb.leaderboard(50)["players"] if r["name"] == "Bob")
            self.assertEqual((row["fame"], row["sites"]), (str(app.fame), 1))

    async def test_hostile_player_names_are_never_drawn(self) -> None:
        async with self.run_app() as (app, pilot):
            await pilot.press("n")  # decline politely
            app.board = {"players": [
                {"rank": 1, "name": "\x1b]0;PWNED\x07evil", "fame": "5", "sites": 1},
                {"rank": 2, "name": "Good Name", "fame": "4", "sites": 0},
                {"rank": 3, "name": "\x1b[2Jx", "fame": "3", "sites": 0}], "total": 3, "at": time.time(), "me": None}
            text = app.board_text().plain
            self.assertNotIn("\x1b", text)
            self.assertIn("Good Name", text)

    async def test_an_unreachable_server_never_breaks_the_game(self) -> None:
        save = {"fame": 2, "sites": 1, "online": {"asked": True, "joined": True, "name": "Carl", "token": "c" * 32}}
        dead = socket.socket()
        dead.bind(("127.0.0.1", 0))
        port = dead.getsockname()[1]
        dead.close()
        game.SERVER = f"http://127.0.0.1:{port}"
        async with self.run_app(save) as (app, pilot):
            await pilot.press("b")
            await pilot.pause(1.5)
            self.assertIn("Could not reach the server", app._last["#shop"].plain)
            app.tick()
            self.assertTrue(app.is_running)

    def test_a_slow_drip_server_is_cut_off(self) -> None:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)

        def serve() -> None:
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    return
                conn.recv(4096)
                try:
                    for byte in b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n" * 5:
                        conn.sendall(bytes([byte]))
                        time.sleep(1)
                except OSError:
                    return

        threading.Thread(target=serve, daemon=True).start()
        game.SERVER = f"http://127.0.0.1:{srv.getsockname()[1]}"
        started = time.monotonic()
        self.assertEqual(game.api("GET", "/api/leaderboard"), (0, {}))
        self.assertLess(time.monotonic() - started, 12)
        srv.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
