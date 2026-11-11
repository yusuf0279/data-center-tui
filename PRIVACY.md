# Privacy

My Data Center works fully offline. The online leaderboard is **optional and off until you say yes**.

## What stays on your computer

Your save file (default `~/.local/share/dc-tui/save.json`, or the file in `DC_SAVE`) holds your progress,
your theme, your data center names and, if you joined the leaderboard, your leaderboard name and a random
private token. Nothing else is stored.

## If you join the leaderboard

The game sends this to `https://data-center.openexplorer.xyz` (and nothing else):

| Sent | Why |
|---|---|
| your chosen leaderboard name | shown on the public board |
| your Fame and how many data centers you have opened | your score |
| a random token your game generated | proves a later update comes from you; the server stores only a hash of it |

The server keeps the name, Fame, data center count, the token's hash and two timestamps. It is a public
board: anyone can read the names and scores. You can **leave at any time** (menu `m`, or `j`), which deletes
your entry from the server. Pick a name that is not your real name.

The leaderboard application itself does not write request logs. Web traffic to it passes through a reverse
proxy and through Cloudflare, which may keep their own standard access logs (including IP addresses) under
their own policies. The application briefly holds IP addresses in memory only to rate limit requests.

## In the VS Code and browser extensions

The web game inside the extensions follows the same rules: joining is opt-in, and only the name, Fame and number of
data centers (plus the token) go to `data-center.openexplorer.xyz`, which is the only origin the extensions may
contact. The save, including the leaderboard name and token, lives in the extension's own storage (VS Code's
extension storage, or the browser's `storage.local`). **Clearing that storage loses the leaderboard identity
token**: you can no longer update or remove your old entry from this install, and joining again creates a new entry.
Ask for the old one to be removed via the contact below.

## Turning it off

`data-center-tui --no-online`, or set `DC_ONLINE=0`. With it off the game never makes a network request.
If you decline the first-run question, nothing about you is ever sent. Opening the leaderboard view still downloads the public top list (a plain GET that carries no data from you, though the server and proxy see your IP address as for any request).

## Contact

Open an issue at https://github.com/yusuf0279/data-center-tui/issues to ask for your entry to be removed.
