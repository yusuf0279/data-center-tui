#!/usr/bin/env python3
"""Moderation for the leaderboard (run inside the container: `dokkt exec <app> python admin.py ...`).

  admin.py list [N]          show the top N players
  admin.py delete NAME       remove a player (for abusive names or cheated scores)
  admin.py rename OLD NEW    rename a player
"""
import os
import sqlite3
import sys

DB_PATH = os.environ.get("DC_DB", "/data/leaderboard.db")


def main(argv: list[str]) -> int:
    conn = sqlite3.connect(DB_PATH)
    if len(argv) >= 1 and argv[0] == "list":
        n = int(argv[1]) if len(argv) > 1 else 20
        for i, (name, fame, sites) in enumerate(conn.execute(
                "SELECT name, fame, sites FROM players ORDER BY fame DESC, sites DESC, created LIMIT ?", (n,)), 1):
            print(f"{i:>3}  {name:<20} fame {fame}  data centers {sites + 1}")
    elif len(argv) == 2 and argv[0] == "delete":
        with conn:
            count = conn.execute("DELETE FROM players WHERE name = ? COLLATE NOCASE", (argv[1],)).rowcount
        print(f"deleted {count}")
    elif len(argv) == 3 and argv[0] == "rename":
        with conn:
            count = conn.execute("UPDATE players SET name = ? WHERE name = ? COLLATE NOCASE",
                                 (argv[2], argv[1])).rowcount
        print(f"renamed {count}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
