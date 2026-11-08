"""Tests for the leaderboard server. Run: python3 -m unittest server/test_server.py -v
Uses a throwaway database and a server on a random local port."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from typing import Any, cast

sys.path.insert(0, os.path.dirname(__file__))
import leaderboard as lb  # noqa: E402


def token(n: int) -> str:
    return f"{n:032x}"


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        lb.DB_PATH = os.path.join(cls.tmp.name, "t.db")
        lb.init_db()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), lb.Handler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmp.cleanup()

    def setUp(self) -> None:
        lb._recent_submit.clear()
        lb._ip_hits.clear()
        lb._ip_new.clear()
        with lb.db() as conn:
            conn.execute("DELETE FROM players")

    def call(self, method: str, path: str, body: object = None, raw: bytes | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, dict]:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read() or b"{}")

    def submit(self, n: int, name: str, fame: object = 1, sites: object = 1) -> tuple[int, dict]:
        return self.call("POST", "/api/submit",
                         {"token": token(n), "name": name, "fame": fame, "sites": sites})

    # -- happy path ----------------------------------------------------------
    def test_health(self) -> None:
        self.assertEqual(self.call("GET", "/health"), (200, {"status": "ok"}))

    def test_submit_ranks_and_ordering(self) -> None:
        self.assertEqual(self.submit(1, "Ada", 5, 3)[0], 200)
        self.assertEqual(self.submit(2, "Bob", 9, 4)[1]["rank"], 1)
        self.assertEqual(self.submit(3, "Cyd", 9, 7)[1]["rank"], 1)  # same fame, more data centers
        board = self.call("GET", "/api/leaderboard")[1]
        self.assertEqual([p["name"] for p in board["players"]], ["Cyd", "Bob", "Ada"])
        self.assertEqual(board["total"], 3)
        self.assertEqual(board["players"][0]["fame"], "9")  # fame travels as a string

    def test_update_and_rename_own_row(self) -> None:
        self.submit(1, "Ada", 2, 1)
        lb._recent_submit.clear()
        self.assertEqual(self.submit(1, "Ada2", 8, 2)[0], 200)
        board = self.call("GET", "/api/leaderboard")[1]
        self.assertEqual(board["total"], 1)
        self.assertEqual(board["players"][0]["name"], "Ada2")
        self.assertEqual(board["players"][0]["fame"], "8")

    def test_me_and_leave(self) -> None:
        self.submit(1, "Ada", 5, 2)
        self.submit(2, "Bob", 9, 2)
        status, me = self.call("POST", "/api/me", {"token": token(1)})
        self.assertEqual((me["registered"], me["rank"], me["total"]), (True, 2, 2))
        self.assertEqual(self.call("POST", "/api/me", {"token": token(99)})[1]["registered"], False)
        self.assertEqual(self.call("POST", "/api/leave", {"token": token(1)})[0], 200)
        self.assertEqual(self.call("GET", "/api/leaderboard")[1]["total"], 1)

    def test_limit_parameter(self) -> None:
        for i in range(5):
            self.submit(i + 1, f"P{i}", i + 1, 1)
        self.assertEqual(len(self.call("GET", "/api/leaderboard?limit=2")[1]["players"]), 2)
        self.assertEqual(len(self.call("GET", "/api/leaderboard?limit=abc")[1]["players"]), 5)
        self.assertEqual(len(self.call("GET", "/api/leaderboard?limit=0")[1]["players"]), 1)
        self.assertEqual(len(self.call("GET", "/api/leaderboard?limit=99999")[1]["players"]), 5)

    # -- abuse and validation ------------------------------------------------
    def test_names_are_validated(self) -> None:
        bad = ["", " ", "x" * 21, "<script>", "a;b", "a\nb", "💥", "-lead", "a'b", 'a"b', "../x", None, 5, ["a"]]
        for i, name in enumerate(bad):
            self.assertEqual(self.submit(i + 1, name)[0], 400, repr(name))
        self.assertEqual(self.call("GET", "/api/leaderboard")[1]["total"], 0)

    def test_name_cannot_be_taken_by_someone_else(self) -> None:
        self.assertEqual(self.submit(1, "Ada")[0], 200)
        self.assertEqual(self.submit(2, "ada")[0], 409)  # case-insensitive
        self.assertEqual(self.submit(2, "ADA ")[0], 409)

    def test_other_players_cannot_touch_your_row(self) -> None:
        self.submit(1, "Ada", 5, 2)
        self.call("POST", "/api/leave", {"token": token(2)})  # a different token
        self.assertEqual(self.call("GET", "/api/leaderboard")[1]["total"], 1)

    def test_bad_tokens(self) -> None:
        for tok in ("", "short", "g" * 32, "A" * 32, "0" * 65, None, 7, "0" * 31):
            self.assertEqual(self.call("POST", "/api/submit", {"token": tok, "name": "Ada", "fame": 1, "sites": 1})[0], 400, repr(tok))

    def test_numbers_are_validated(self) -> None:
        cases = [(-1, 1), (1, -1), (1, 61), (True, 1), (1, True), (1.5, 1), ("1e3", 1), ("0x10", 1),
                 (10**13, 1), (None, 1), ([1], 1), ({"a": 1}, 1), ("9" * 19, 1), (float("nan"), 1)]
        for i, (fame, sites) in enumerate(cases):
            self.assertEqual(self.submit(i + 1, f"N{i}", fame, sites)[0], 400, (fame, sites))

    def test_plausibility(self) -> None:
        self.assertEqual(self.submit(1, "Low", 0, 3)[0], 400)            # fame >= sites
        self.assertEqual(self.submit(2, "High", 50_000, 1)[0], 400)      # fame <= (sites+1)*1e4
        self.assertEqual(self.submit(3, "Edge", 20_000, 1)[0], 200)
        self.assertEqual(self.submit(4, "Zero", 0, 0)[0], 200)           # a brand new player

    def test_cooldown(self) -> None:
        self.assertEqual(self.submit(1, "Ada", 1, 1)[0], 200)
        self.assertEqual(self.submit(1, "Ada", 2, 1)[0], 429)
        self.assertEqual(self.submit(2, "")[0], 400)          # a rejected submit does not start a cooldown
        self.assertEqual(self.submit(2, "Bee")[0], 200)

    def test_body_limits_and_garbage(self) -> None:
        self.assertEqual(self.call("POST", "/api/submit", raw=b"x" * 5000)[0], 413)
        self.assertEqual(self.call("POST", "/api/submit", raw=b"{not json")[0], 400)
        self.assertEqual(self.call("POST", "/api/submit", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.call("POST", "/api/submit", raw=b"")[0], 400)
        self.assertEqual(self.call("POST", "/api/nope", {})[0], 404)
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("GET", "/api/submit")[0], 404)  # GET on a POST route

    def test_sql_injection_is_inert(self) -> None:
        self.assertEqual(self.submit(1, "x'); DROP TABLE players;--")[0], 400)
        self.assertEqual(self.call("GET", "/api/leaderboard?limit=1;DROP%20TABLE%20players")[0], 200)
        self.assertEqual(self.submit(2, "Fine")[0], 200)

    def test_ip_rate_limit(self) -> None:
        old = lb.IP_LIMIT
        lb.IP_LIMIT = 5
        try:
            codes = [self.call("GET", "/health", headers={"CF-Connecting-IP": "9.9.9.9"})[0] for _ in range(8)]
            self.assertEqual(codes[:5], [200] * 5)
            self.assertIn(429, codes[5:])
            self.assertEqual(self.call("GET", "/health", headers={"CF-Connecting-IP": "8.8.8.8"})[0], 200)
        finally:
            lb.IP_LIMIT = old

    def test_player_cap(self) -> None:
        old = lb.MAX_PLAYERS
        lb.MAX_PLAYERS = 2
        try:
            self.submit(1, "A1"); self.submit(2, "A2")
            self.assertEqual(self.submit(3, "A3")[0], 503)
            lb._recent_submit.clear()
            self.assertEqual(self.submit(1, "A1", 3, 1)[0], 200)  # existing players can still update
        finally:
            lb.MAX_PLAYERS = old

    def test_unicode_and_huge_limits_do_not_crash(self) -> None:
        self.submit(1, "Ada")
        for raw in ("%C2%B2", "%EF%BC%95", "9" * 5000, "-1", "1.5", "%00", ""):
            self.assertEqual(self.call("GET", f"/api/leaderboard?limit={raw}")[0], 200, raw[:20])

    def test_one_address_cannot_register_unlimited_players(self) -> None:
        for i in range(lb.NEW_PLAYERS_PER_IP):
            self.assertEqual(self.submit(i + 1, f"New{i}")[0], 200)
        self.assertEqual(self.submit(99, "TooMany")[0], 429)
        self.assertEqual(self.call("POST", "/api/submit", {"token": token(100), "name": "Other", "fame": 1, "sites": 1},
                                   headers={"CF-Connecting-IP": "5.5.5.5"})[0], 200)  # a different address is fine
        lb._recent_submit.clear()
        self.assertEqual(self.submit(1, "New0", 2, 1)[0], 200)  # existing players can still update

    def test_headers_are_only_trusted_from_our_own_proxy(self) -> None:
        class Fake:
            def __init__(self, peer: str, headers: dict[str, str]) -> None:
                self.client_address, self.headers = (peer, 1234), headers
        spoof = {"CF-Connecting-IP": "1.2.3.4"}
        self.assertEqual(lb.client_ip(cast(Any, Fake("8.8.8.8", spoof))), "8.8.8.8")        # the internet: ignored
        self.assertEqual(lb.client_ip(cast(Any, Fake("172.17.0.1", spoof))), "1.2.3.4")     # our proxy: trusted
        self.assertEqual(lb.client_ip(cast(Any, Fake("127.0.0.1", {"X-Forwarded-For": "9.9.9.9, 1.1.1.1"}))), "9.9.9.9")
        self.assertEqual(lb.client_ip(cast(Any, Fake("not-an-ip", spoof))), "not-an-ip")

    def test_token_is_never_stored(self) -> None:
        self.submit(1, "Ada")
        with lb.db() as conn:
            dump = json.dumps([tuple(r) for r in conn.execute("SELECT * FROM players")])
        self.assertNotIn(token(1), dump)

    def test_no_internal_errors_leak(self) -> None:
        self.assertEqual(self.submit(1, "Ada")[0], 200)
        good = lb.DB_PATH
        lb.DB_PATH = "/nonexistent-dir/x/leaderboard.db"  # opening it fails
        try:
            status, body = self.call("GET", "/api/leaderboard")
            self.assertEqual((status, body), (500, {"error": "server error"}))
        finally:
            lb.DB_PATH = good


if __name__ == "__main__":
    unittest.main()
