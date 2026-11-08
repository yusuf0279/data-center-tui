> **Inspired by [fourtysevencode/My-Data-Center](https://github.com/fourtysevencode/My-Data-Center)**, an idle tycoon you play over SSH. This is an independent rewrite for the local terminal; see [Credits](#credits).

# My Data Center (TUI)

A pixel-art idle tycoon for your terminal. Buy servers, watch the income roll in, and grow from a budget VPS to an orbital cloud. Built to sit in a tmux pane while you wait on something else.

## Run

```
pip install -r requirements.txt
python3 dc.py
```

Developed and tested on Python 3.13 with Textual 8.2.7. Use a terminal of at least 100×30 for the best view (80×24 works, with a smaller data hall).

## Controls

| Key | Action |
|---|---|
| `1`-`6` | Pick an item in the open card: buy a server, install a chip, or hire/train crew |
| `s` / `c` / `h` / `d` | Open the **s**ervers, **c**hips, crew (**h**ire) or **d**ata centers card |
| `x` | Open the next data center (when you can afford it) |
| `[` / `]` | Visit the older / newer data center (or press `d`, then `1`-`6`) |
| `f` | Fix the current crisis yourself |
| `ctrl+p` | Command palette, including **Change theme** |
| `q` | Save and quit |

The game is keyboard-only and does not capture the mouse, so it plays nicely inside tmux.

## Features

- **Six server tiers**, each with its own pixel sprite: Budget VPS, Compute Node, GPU Cluster, AI Datacenter, Quantum Farm, Orbital Cloud. Each extra copy of a tier costs 15% more than the last.
- **Chip upgrades.** Twenty levels per tier (five chip families, four editions each), every level doubling that tier's income. Named after some very familiar GPUs and CPUs (RTX 5090 Paper, B200 melts, MI325X-ception, Ultra Max...).
- **On-call crew.** Six roles, from Vibecoder up to Chief Hype Officer, each trainable to level 10. They automatically fix crises (bigger crises need more senior people), respond faster as they level up, and every level adds +5% income.
- **Data centers, forever.** Reach $1B and open the next data center (Garage in Palo Alto, Abandoned Mall in Ohio, Decommissioned Missile Silo, ... and on into Parallel Universes). Every data center keeps its own servers and chips and they all earn at once, so you can go back and upgrade an old one any time (`d`, or `[` and `]`). Your crew is shared, and each new data center is bigger and needs 1000x more to move on from. There is no last level.
- **Random crises.** Power cuts, flaky CI, an intern pushing to main on a Friday: they cut your income until fixed, by you (`f`) or by your crew.
- **Pixel data hall** drawn with half-block characters, with blinking LEDs that turn red during a crisis.
- **Tmux friendly.** The screen only repaints when something changed. If the game runs in a tmux pane that isn't the active one, it keeps playing in the background but redraws only every 20 seconds, because every repaint of a background pane makes tmux flick your real cursor over to it.
- **Themes.** Every colour, panel and sprite follows the active Textual theme. It starts on gruvbox, and your choice is remembered.
- **Saves.** Balance, servers and theme are saved to `~/.local/share/dc-tui/save.json` (or `$XDG_DATA_HOME/dc-tui/save.json`) every second and on quit. Set `DC_SAVE=/path/to/file.json` to use a different file.
- **Offline earnings.** While the game is closed you earn **75%** of your normal income, with no time limit.

## Status

Early prototype. Not yet implemented: a leaderboard.

## Credits

The idea, the "buy servers and watch the money roll in" loop and the six-tier cost/income table (with the 15% price scaling) come from [My Data Center](https://github.com/fourtysevencode/My-Data-Center) by fourtysevencode. That project runs as an SSH server with its own accounts.

This repository is a from-scratch rewrite in [Textual](https://textual.textualize.io/). It shares no source code with the original, whose repository has no license file.
