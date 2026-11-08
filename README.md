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
| `x` | **Relocate** to the next data center (when your newest one reaches its target) |
| `[` / `]` | Visit the older / newer data center (or press `d`, then `1`-`6`) |
| `f` | Fix the current crisis yourself |
| `ctrl+p` | Command palette, including **Change theme** |
| `q` | Save and quit |

The game is keyboard-only and does not capture the mouse, so it plays nicely inside tmux.

## Features

- **Six server tiers**, each with its own pixel sprite: Budget VPS, Compute Node, GPU Cluster, AI Datacenter, Quantum Farm, Orbital Cloud. Cheap tiers pay back in about 30 seconds, the biggest in about 16 minutes, so each tier has its moment. Every extra copy costs a little more than the last (+7% on the cheapest up to +12% on the biggest).
- **Milestones.** Owning 25, 50, 100, 200, 300, 400 ... of a tier doubles that tier's income, and the shop shows the next one (`x2@25`).
- **Chip upgrades.** Twenty levels per tier (five chip families, four editions each), every level doubling that tier's income and costing 4x the last. Named after some very familiar GPUs and CPUs (RTX 5090 Paper, B200 melts, MI325X-ception, Ultra Max...).
- **On-call crew.** Six roles, from Vibecoder up to Chief Hype Officer, each trainable to level 10. They automatically fix crises (bigger crises need more senior people), respond faster as they level up, and every level adds +5% income.
- **Relocate, forever.** Reach $10T in your newest data center and you can relocate to the next one (Garage in Palo Alto, Abandoned Mall in Ohio, Decommissioned Missile Silo, ... and on into Parallel Universes). You **start from scratch** there: money, servers, chips and crew all reset. The old data center is frozen as you left it: you can visit it (`d`, or `[` and `]`), but only the one you are in earns. Each new data center has bigger numbers and a target 1000x higher, and takes a little longer than the last. There is no last level.
- **Fame and status.** Every relocation earns **Fame** (more if you waited past the target): each point is +2% income in every data center, forever. Fame also climbs your status ladder: Nobody, Intern, Junior Dev, Senior Dev, Tech Lead, Engineering Manager, Director, VP of Engineering, CTO, Tech CEO, Tech Billionaire, Tech Overlord, and then Tech Overlord II, III, ... without end.
- **Random crises.** Power cuts, flaky CI, an intern pushing to main on a Friday: they cut your income until fixed, by you (`f`) or by your crew.
- **Pixel data hall** drawn with half-block characters, with blinking LEDs that turn red during a crisis.
- **Tmux friendly.** The screen only repaints when something changed. If the game runs in a tmux pane that isn't the active one, it keeps playing in the background but redraws only every 20 seconds, because every repaint of a background pane makes tmux flick your real cursor over to it.
- **Themes.** Every colour, panel and sprite follows the active Textual theme. It starts on gruvbox, and your choice is remembered.
- **Saves.** Every data center's money, servers, chips and crew, plus your Fame and theme, are saved to `~/.local/share/dc-tui/save.json` (or `$XDG_DATA_HOME/dc-tui/save.json`) every second and on quit. Set `DC_SAVE=/path/to/file.json` to use a different file. Older saves are converted automatically.
- **Offline earnings.** While the game is closed the data center you were in earns **75%** of its normal income, with no time limit.

## Status

Early prototype. Not yet implemented: a leaderboard.

## Credits

The idea, the "buy servers and watch the money roll in" loop and the six tiers' income figures come from [My Data Center](https://github.com/fourtysevencode/My-Data-Center) by fourtysevencode. That project runs as an SSH server with its own accounts. The prices, price scaling, milestones, chips, crew, crises and everything after the first version are this repository's own.

The reset-and-Fame loop and the milestone doublings are inspired by mobile idle tycoons such as [Cash, Inc.](https://apps.apple.com/us/app/cash-inc-fame-fortune-game/id1270598321) and AdVenture Capitalist. The numbers here are tuned with a simulated player and are not copied from any of them.

This repository is a from-scratch rewrite in [Textual](https://textual.textualize.io/). It shares no source code with the original, whose repository has no license file.
