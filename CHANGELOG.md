# Changelog

## Unreleased

- Much less terminal output while animating (about 10x less at 120x36; matters over SSH): a repaint sends only the cells that changed, LEDs and the top-tier glow tick at 6 Hz and the LED fade has four brightness levels. The cell-level trim relies on private Textual internals, so it switches itself on only for Textual 8.0 up to (not including) 8.3 and falls back to Textual's own, wider repaints on any other version (or if it ever fails); `textual>=8.2` in the requirements is deliberately left open
- Animation and colour: blinking LEDs, data pulses and a pulsing top tier in the hall, floating `+$X`, balance flash and sparkles, a flickering crisis banner and a relocation transition. Only in a front pane and a live data center; `--no-anim` or `DC_ANIM=0` turns it all off
- Web port of the game (`web/`), shared by the VS Code extension and the Chrome/Firefox extensions (`npm run build`)
- Extensions can use the optional leaderboard: opt-in, sends only name, Fame and number of data centers to `data-center.openexplorer.xyz` (webview CSP and extension host permission restricted to that origin). Clearing extension storage loses the leaderboard identity token
- Firefox extension now requires Firefox 127 or newer, so the host permission is granted at install

## 0.1.0

First release.

- Ten server tiers with pixel sprites, a scrollable data hall, 20 chip levels per tier and milestone doublings
- On-call crew: one specialist per tier with autopilot for cheap purchases, income doublings, crisis fixing
- Random crises, offline earnings (75%), themes that follow your Textual theme
- Relocate to endless new data centers: reset, Fame, a status ladder from Nobody to Tech Overlord II, III, ...
- Decommissioned old data centers you can visit, and your own names for data centers
- A menu (`m`), and an optional online leaderboard
