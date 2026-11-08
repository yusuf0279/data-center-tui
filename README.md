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
| `1`-`6` | Buy a server of that tier |
| `ctrl+p` | Command palette, including **Change theme** |
| `q` | Save and quit |

The game is keyboard-only and does not capture the mouse, so it plays nicely inside tmux.

## Features

- **Six server tiers**, each with its own pixel sprite: Budget VPS, Compute Node, GPU Cluster, AI Datacenter, Quantum Farm, Orbital Cloud. Each extra copy of a tier costs 15% more than the last.
- **Pixel data hall** drawn with half-block characters, with blinking LEDs.
- **Themes.** Every colour, panel and sprite follows the active Textual theme. It starts on gruvbox, and your choice is remembered.
- **Saves.** Balance, servers and theme are saved to `~/.local/share/dc-tui/save.json` (or `$XDG_DATA_HOME/dc-tui/save.json`) every second and on quit. Set `DC_SAVE=/path/to/file.json` to use a different file.
- **Offline earnings.** While the game is closed you earn **75%** of your normal income, with no time limit.

## Status

Early prototype. Not yet implemented: managers and upgrades, random crises, multiple data centers, prestige and a leaderboard.

## Credits

The idea, the "buy servers and watch the money roll in" loop and the six-tier cost/income table (with the 15% price scaling) come from [My Data Center](https://github.com/fourtysevencode/My-Data-Center) by fourtysevencode. That project runs as an SSH server with its own accounts.

This repository is a from-scratch rewrite in [Textual](https://textual.textualize.io/). It shares no source code with the original, whose repository has no license file.
