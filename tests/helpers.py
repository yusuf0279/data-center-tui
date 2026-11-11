"""Shared test setup: every test gets its own save file and no network, no tmux."""
import contextlib
import json
import logging
import os
import sys
import tempfile
import unittest
from collections.abc import AsyncIterator
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_center_tui import game  # noqa: E402

logging.getLogger("asyncio").setLevel(logging.ERROR)  # no "slow callback" noise from debug mode
for var in ("TMUX", "TMUX_PANE"):
    os.environ.pop(var, None)


class AppCase(unittest.IsolatedAsyncioTestCase):
    """`async with self.run_app(save) as (app, pilot):` runs the real game headlessly."""

    online = False

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.save_path = os.path.join(self.tmp.name, "save.json")
        os.environ["DC_SAVE"] = self.save_path
        self._old = (game.ONLINE, game.SERVER, game.tmux_foreground)
        game.ONLINE = self.online
        game.tmux_foreground = lambda: True
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.restore)

    def restore(self) -> None:
        game.ONLINE, game.SERVER, game.tmux_foreground = self._old

    @contextlib.asynccontextmanager
    async def run_app(self, save: dict[str, Any] | None = None,
                      size: tuple[int, int] = (110, 32)) -> AsyncIterator[tuple[Any, Any]]:
        if save is not None:
            with open(self.save_path, "w") as fh:
                json.dump(save, fh)
        app = game.DataCenter()
        async with app.run_test(size=size) as pilot:
            await pilot.pause(0.1)
            yield app, pilot


def world_save(**extra: Any) -> dict[str, Any]:
    """A three-data-center save: #1 and #2 are decommissioned, #3 is live."""
    n = len(game.TIERS)
    save: dict[str, Any] = {
        "site_balance": [777, 5_000, 123_456], "site_owned": [[5] * n, [3] * n, [2] * n],
        "site_chips": [[1] * n] * 3, "site_staff": [[-1] * n] * 3, "sites": 2, "cur": 2,
        "fame": 2, "autopilot": False, "online": {"asked": True, "joined": False},
    }
    save.update(extra)
    return save
