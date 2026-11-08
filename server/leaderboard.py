#!/usr/bin/env python3
"""Leaderboard server for My Data Center. Standard library only.

Players are identified by a secret token that only their game knows. The server keeps
a hash of it, never the token itself, so nobody else can overwrite or delete your row.

  GET  /health                 -> {"status": "ok"}
  GET  /api/leaderboard?limit= -> top players, best first
  POST /api/submit             -> {token, name, fame, sites}   create or update your row
  POST /api/me                 -> {token}                      your rank
  POST /api/leave              -> {token}                      delete your row

This is an honour-system board: the game runs on the player's machine, so the server
only does sanity checks (see check_plausible), it cannot prove a score is real.
"""
import hashlib
import ipaddress
import json
import os
import re
import signal
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

DB_PATH = os.environ.get("DC_DB", "/data/leaderboard.db")
PORT = int(os.environ.get("PORT", "8080"))
MAX_BODY = 2048
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,19}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{32,64}$")
MAX_SITES = 60
MAX_FAME = 10**12  # also keeps every value inside SQLite's 64-bit integers
MAX_PLAYERS = 20000  # no new players beyond this; existing ones can still update
SUBMIT_COOLDOWN = 10.0  # seconds between updates from one player
IP_LIMIT, IP_WINDOW = 120, 60.0  # requests per IP per window
NEW_PLAYERS_PER_IP = 5  # new players one address may register per hour
FAME_PER_RELOCATION = 10**4  # generous: a real relocation gains about sqrt(how far past the target)
MAX_TRACKED = 20000  # entries kept in the in-memory rate limit tables

_write_lock = threading.Lock()
_recent_submit: dict[str, float] = {}
_ip_hits: dict[str, list[float]] = {}
_ip_new: dict[str, list[float]] = {}
_state_lock = threading.Lock()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error and is always closed.
    (`with sqlite3.connect()` alone never closes it, which would leak one per request.)"""
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                pid TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                fame INTEGER NOT NULL,
                sites INTEGER NOT NULL,
                created REAL NOT NULL,
                updated REAL NOT NULL
            )""")
        conn.execute("CREATE INDEX IF NOT EXISTS rank_idx ON players (fame DESC, sites DESC, created)")


def pid_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


class Bad(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


def check_plausible(fame: int, sites: int) -> None:
    """Fame only comes from relocating, at least 1 per relocation, and the gain per
    relocation is the square root of how far past the target you were."""
    if not 0 <= sites <= MAX_SITES:
        raise Bad(400, "bad sites")
    if not sites <= fame <= min(MAX_FAME, (sites + 1) * FAME_PER_RELOCATION):
        raise Bad(400, "implausible fame")


def parse_number(value: object, low: int, high: int, what: str) -> int:
    if isinstance(value, bool):
        raise Bad(400, f"bad {what}")
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        value = int(value)
    if not isinstance(value, int) or not low <= value <= high:
        raise Bad(400, f"bad {what}")
    return value


def rank_of(conn: sqlite3.Connection, row: sqlite3.Row) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM players WHERE fame > ? OR (fame = ? AND sites > ?) "
        "OR (fame = ? AND sites = ? AND created < ?)",
        (row["fame"], row["fame"], row["sites"], row["fame"], row["sites"], row["created"]),
    ).fetchone()[0] + 1


def leaderboard(limit: int) -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT name, fame, sites FROM players "
            "ORDER BY fame DESC, sites DESC, created ASC LIMIT ?", (limit,)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    return {"total": total, "players": [
        {"rank": i + 1, "name": r["name"], "fame": str(r["fame"]), "sites": r["sites"]}
        for i, r in enumerate(rows)]}


def submit(body: dict, ip: str = "") -> dict:
    token = body.get("token")
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise Bad(400, "bad token")
    name = body.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name.strip()):
        raise Bad(400, "bad name: 1-20 letters, digits, spaces, _ . -")
    name = name.strip()
    fame = parse_number(body.get("fame"), 0, MAX_FAME, "fame")
    sites = parse_number(body.get("sites"), 0, MAX_SITES, "sites")
    check_plausible(fame, sites)
    pid, now = pid_of(token), time.time()
    with _state_lock:
        if now - _recent_submit.get(pid, 0) < SUBMIT_COOLDOWN:
            raise Bad(429, "slow down")
    with _write_lock, db() as conn:
        mine = conn.execute("SELECT * FROM players WHERE pid = ?", (pid,)).fetchone()
        clash = conn.execute("SELECT pid FROM players WHERE name = ? COLLATE NOCASE",
                             (name,)).fetchone()
        if clash and clash["pid"] != pid:
            raise Bad(409, "name taken")
        if mine:
            conn.execute("UPDATE players SET name=?, fame=?, sites=?, updated=? WHERE pid=?",
                         (name, fame, sites, now, pid))
        else:
            if conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] >= MAX_PLAYERS:
                raise Bad(503, "leaderboard is full")
            with _state_lock:  # one address cannot fill the board with fake players
                recent = [t for t in _ip_new.get(ip, []) if now - t < 3600]
                if ip and len(recent) >= NEW_PLAYERS_PER_IP:
                    raise Bad(429, "too many new players from this address")
                recent.append(now)
                _ip_new[ip] = recent
                if len(_ip_new) > MAX_TRACKED:
                    _ip_new.clear()
            conn.execute("INSERT INTO players (pid, name, fame, sites, created, updated) "
                         "VALUES (?,?,?,?,?,?)", (pid, name, fame, sites, now, now))
        row = conn.execute("SELECT * FROM players WHERE pid = ?", (pid,)).fetchone()
        result = {"ok": True, "rank": rank_of(conn, row), "name": row["name"]}
    with _state_lock:  # the cooldown only starts after a successful update
        _recent_submit[pid] = now
        if len(_recent_submit) > 50000:
            for key in [k for k, t in _recent_submit.items() if now - t > 3600]:
                del _recent_submit[key]
    return result


def me(body: dict) -> dict:
    token = body.get("token")
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise Bad(400, "bad token")
    with db() as conn:
        row = conn.execute("SELECT * FROM players WHERE pid = ?", (pid_of(token),)).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        if not row:
            return {"registered": False, "total": total}
        return {"registered": True, "rank": rank_of(conn, row), "total": total,
                "name": row["name"], "fame": str(row["fame"]), "sites": row["sites"]}


def leave(body: dict) -> dict:
    token = body.get("token")
    if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
        raise Bad(400, "bad token")
    with _write_lock, db() as conn:
        conn.execute("DELETE FROM players WHERE pid = ?", (pid_of(token),))
    return {"ok": True}


def from_proxy(peer: str) -> bool:
    """Only a private or loopback peer (our own reverse proxy) may tell us who the real
    client is. A direct connection from the internet cannot spoof it."""
    try:
        ip = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback


def client_ip(handler: BaseHTTPRequestHandler) -> str:
    """The address used for rate limiting (never logged)."""
    peer = handler.client_address[0]
    if from_proxy(peer):
        forwarded = handler.headers.get("CF-Connecting-IP") or handler.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",")[0].strip() or peer)[:64]
    return peer


def over_limit(ip: str) -> bool:
    now = time.time()
    with _state_lock:
        hits = [t for t in _ip_hits.get(ip, []) if now - t < IP_WINDOW]
        hits.append(now)
        _ip_hits[ip] = hits
        if len(_ip_hits) > MAX_TRACKED:
            for key in [k for k, v in _ip_hits.items() if not v or now - v[-1] > IP_WINDOW]:
                del _ip_hits[key]
            if len(_ip_hits) > MAX_TRACKED:  # still too many live keys: start over
                _ip_hits.clear()
        return len(hits) > IP_LIMIT


class Handler(BaseHTTPRequestHandler):
    server_version = "dc-leaderboard"
    timeout = 10  # slow clients can't hold a thread forever

    def log_message(self, format: str, *args: Any) -> None:  # no per-request logs: no IPs on disk
        pass

    def send_json(self, status: int, payload: object, cache: str = "no-store") -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")  # the board is public
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def guarded(self, fn) -> None:  # type: ignore[no-untyped-def]
        try:
            if over_limit(client_ip(self)):
                raise Bad(429, "too many requests")
            fn()
        except Bad as exc:
            self.send_json(exc.status, {"error": exc.message})
        except Exception:  # never leak internals
            self.send_json(500, {"error": "server error"})

    def do_GET(self) -> None:
        def run() -> None:
            url = urlparse(self.path)
            if url.path == "/health":
                with db() as conn:
                    conn.execute("SELECT 1")
                self.send_json(200, {"status": "ok"})
            elif url.path == "/api/leaderboard":
                raw = parse_qs(url.query).get("limit", ["20"])[0]
                limit = int(raw) if raw.isascii() and raw.isdigit() and len(raw) <= 6 else 20
                self.send_json(200, leaderboard(max(1, min(limit, 100))), cache="public, max-age=10")
            else:
                raise Bad(404, "not found")
        self.guarded(run)

    def do_POST(self) -> None:
        def run() -> None:
            routes = {"/api/submit": lambda b: submit(b, client_ip(self)), "/api/me": me,
                      "/api/leave": leave}
            fn = routes.get(urlparse(self.path).path)
            if fn is None:
                raise Bad(404, "not found")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise Bad(400, "bad length")
            if not 0 < length <= MAX_BODY:
                raise Bad(413 if length > MAX_BODY else 400, "bad body size")
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                raise Bad(400, "bad json")
            if not isinstance(body, dict):
                raise Bad(400, "bad json")
            self.send_json(200, fn(body))
        self.guarded(run)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main() -> None:
    init_db()
    ThreadingHTTPServer.request_queue_size = 64  # the default of 5 resets bursts of connections
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    print(f"leaderboard listening on :{PORT}, db {DB_PATH}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
