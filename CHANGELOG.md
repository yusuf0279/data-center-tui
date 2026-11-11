# Changelog

## Unreleased

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
