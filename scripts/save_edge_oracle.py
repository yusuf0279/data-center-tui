#!/usr/bin/env python3
"""Write rust/core/tests/data/save_edge_oracle.json.gz: the 4300-digit integer limit, as the REAL
committed Python loader (DataCenter.__init__ -> load_save -> json.loads) applies it.

Each case is a save text plus the state Python ended up with. A text that Python rejects
(ValueError from int(): more than 4300 digits, sign not counted) loads as a fresh game.
Game root: $DC_PY_ROOT, default /mnt/bigvolume/dc-e66 (a worktree of the committed code).
Run: python3 scripts/save_edge_oracle.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from gzjson import write_gz

HERE = Path(__file__).resolve().parent.parent
ROOT = Path(os.environ.get("DC_PY_ROOT", "/mnt/bigvolume/dc-e66")).resolve()
OUT = HERE / "rust/core/tests/data/save_edge_oracle.json.gz"
sys.path.insert(0, str(ROOT))
os.environ["DC_ONLINE"] = "0"
os.environ["DC_SAVE"] = str(Path(tempfile.mkdtemp()) / "save.json")
from data_center_tui import game  # noqa: E402

assert Path(game.__file__).resolve().is_relative_to(ROOT), game.__file__
NOW = 1_800_000_000.0
BASE = '"sites": 2, "fame": 5, "theme": "nord"'


def digits(n: int) -> str:
    return ("7" + "0123456789" * (n // 10 + 1))[:n]


def texts() -> list[str]:
    out = []
    for n in (4299, 4300, 4301):
        for sign in ("", "-"):
            d = sign + digits(n)
            out.append("{%s, \"junk\": %s}" % (BASE, d))
            out.append("{\"junk\": %s, %s}" % (d, BASE))
            out.append("{%s, \"junk\": [1, {\"k\": [%s]}]}" % (BASE, d))
            out.append("{\"fame\": %s, %s}" % (d, BASE))  # EARLIER duplicate, last one is 5
            out.append("{%s, \"fame\": %s}" % (BASE, d))  # LAST duplicate
            out.append("{%s, \"junk\": \"%s\"}" % (BASE, d))  # a string is not an integer
            out.append("{%s, \"junk\": %s.5}" % (BASE, d))  # float: no digit limit
            out.append("{%s, \"junk\": %se2}" % (BASE, d))
            out.append("{%s, \"junk\": %s}" % (BASE, d[:-1] + "E+3"))
    out.append("{%s, \"junk\": [%s, %s]}" % (BASE, digits(4300), "-" + digits(4300)))
    out.append("{%s, \"junk\": {\"a\": %s, \"a\": 1}}" % (BASE, "-" + digits(4301)))
    out.append("{%s, \"junk\": \"quote \\\" %s\"}" % (BASE, digits(4301)))
    return out


def run(text: str) -> dict:
    Path(os.environ["DC_SAVE"]).write_text(text, encoding="utf-8")
    with mock.patch("time.time", return_value=NOW):
        app = game.DataCenter()
    return {"sites": app.sites, "cur": app.cur, "balance": [str(b) for b in app.site_balance],
            "owned": app.site_owned, "chips": app.site_chips, "staff": app.site_staff,
            "fame": str(app.fame), "names": app.site_names, "auto": app.autopilot,
            "online": [app.online_asked, app.online_joined, app.online_name, app.online_token],
            "theme": app.saved_theme, "away": [app.away[0], str(app.away[1])]}


def main() -> None:
    cases = [{"text": t, "now": NOW, "want": run(t)} for t in texts()]
    write_gz(OUT, json.dumps(cases, separators=(",", ":")) + "\n")
    loaded = sum(1 for c in cases if c["want"]["sites"] == 2)
    print(f"wrote {OUT} ({len(cases)} cases, {loaded} loaded, {len(cases) - loaded} rejected)")


if __name__ == "__main__":
    main()
