# Leaderboard server

The optional online leaderboard for My Data Center. It is a single standard-library Python file
(`leaderboard.py`) with an SQLite database, no dependencies. The game only talks to it if the
player opts in (see the main README).

## API

| Request | What it does |
|---|---|
| `GET /health` | `{"status":"ok"}` (also checks the database) |
| `GET /api/leaderboard?limit=N` | top players, best first (`N` 1-100, default 20) |
| `POST /api/submit` | `{token, name, fame, sites}`: create or update your own row |
| `POST /api/me` | `{token}`: your rank, or `registered: false` |
| `POST /api/leave` | `{token}`: delete your row |

Players are identified by a random **token** that only their game knows. The server stores a hash of
it and never the token itself, so nobody else can change or delete your row. Names are unique
(case-insensitive), 1-20 characters of letters, digits, space, `_`, `.`, `-`. Players are ranked by
Fame, then by number of data centers, then by who got there first.

**This is an honour-system board.** The game runs on the player's machine, so the server can only
sanity-check a score (Fame is at least the number of relocations, and not absurdly large). It cannot
prove a score is real. The application writes no request logs and holds IP addresses in memory only
briefly for rate limiting. (The reverse proxy and Cloudflare in front of it may keep their own access
logs: see [PRIVACY.md](../PRIVACY.md).)

Limits: 2 KB request bodies, 10 s between updates per player, 120 requests per minute per IP,
5 new players per address per hour, 20,000 players. The rate limit trusts the `CF-Connecting-IP` /
`X-Forwarded-For` headers only from a private or loopback peer (our own reverse proxy), so they cannot
be spoofed by connecting directly.

## Run it locally

```
DC_DB=/tmp/leaderboard.db PORT=8080 python3 leaderboard.py
python3 -m unittest discover -s . -p test_server.py        # the tests
DC_SERVER=http://127.0.0.1:8080 python3 -m data_center_tui   # (from the repo root) point the game at it
```

## Deploy (dokkt)

`dokkt.yml` describes the app: one public web service on container port 8080, health check on
`/health`, a persistent volume for `/data`, resource limits (128 MB, 0.25 CPU, set under a top-level
`resources:` block: dokkt ignores `--memory`/`--cpus` flags when a `dokkt.yml` exists), and the domain
`data-center.openexplorer.xyz`.

```
cd server
dokkt up --yes
```

The domain also needs a DNS record (an `A` record to the server, proxied by Cloudflare like the other
apps). The database lives in the `leaderboard-data` volume, so it survives restarts and redeploys.

## Moderation

```
dokkt exec data-center-leaderboard -- python admin.py list 20
dokkt exec data-center-leaderboard -- python admin.py delete SomeName
dokkt exec data-center-leaderboard -- python admin.py rename OldName NewName
dokkt logs data-center-leaderboard
```
