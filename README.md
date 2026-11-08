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
| `s` / `c` / `h` | Open the **s**ervers, **c**hips or crew (**h**ire) card |
| `f` | Fix the current crisis yourself |
| `ctrl+p` | Command palette, including **Change theme** |
| `q` | Save and quit |

The game is keyboard-only and does not capture the mouse, so it plays nicely inside tmux.

## Features

- **Six server tiers**, each with its own pixel sprite: Budget VPS, Compute Node, GPU Cluster, AI Datacenter, Quantum Farm, Orbital Cloud. Each extra copy of a tier costs 15% more than the last.
- **Chip upgrades.** Three levels per tier, each doubling that tier's income, named after some very familiar GPUs and CPUs (RTX 5090 Paper Launch, B200 melts connector, MI325X-ception...).
- **On-call crew.** Vibecoders, Prompt Engineers and Forward Deployed Engineers automatically fix crises of increasing severity. Train them to respond faster.
- **Random crises.** Power cuts, flaky CI, an intern pushing to main on a Friday: they cut your income until fixed, by you (`f`) or by your crew.
- **Pixel data hall** drawn with half-block characters, with blinking LEDs that turn red during a crisis.
- **Quiet redraws.** The screen only repaints when something changed, so it stays calm in a background tmux pane.
- **Themes.** Every colour, panel and sprite follows the active Textual theme. It starts on gruvbox, and your choice is remembered.
- **Saves.** Balance, servers and theme are saved to `~/.local/share/dc-tui/save.json` (or `$XDG_DATA_HOME/dc-tui/save.json`) every second and on quit. Set `DC_SAVE=/path/to/file.json` to use a different file.
- **Offline earnings.** While the game is closed you earn **75%** of your normal income, with no time limit.

## Status

Early prototype. Not yet implemented: multiple data centers, prestige and a leaderboard.

## Credits

The idea, the "buy servers and watch the money roll in" loop and the six-tier cost/income table (with the 15% price scaling) come from [My Data Center](https://github.com/fourtysevencode/My-Data-Center) by fourtysevencode. That project runs as an SSH server with its own accounts.

This repository is a from-scratch rewrite in [Textual](https://textual.textualize.io/). It shares no source code with the original, whose repository has no license file.
