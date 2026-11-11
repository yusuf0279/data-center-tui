# My Data Center for VS Code

A pixel-art idle tycoon in an editor tab. Buy servers, hire Vibecoders to fix crises, install chip upgrades, and open ever-bigger data centers while you wait on your AI.

## Use

Run **Data Center: Play** from the Command Palette, or click **Data Center** in the status bar. The status bar then shows your balance and income, and turns red during a crisis.

Keys inside the game: `1`-`6` pick, `s` `c` `h` `d` switch card, `x` open the next data center, `f` fix a crisis, `[` `]` visit older or newer data centers. Everything is also clickable.

The game follows your VS Code colour theme. Your progress is saved in VS Code's own storage. Income only ticks while the tab is open (it keeps running in the background); when you reopen it you earn 75% of your income for the time you were away.

## Leaderboard

Joining the online leaderboard is opt-in. If you join, the extension sends only your name, your Fame and your number of data centers (plus a random token proving later updates are yours) to `data-center.openexplorer.xyz`, the only origin the webview may contact. Clearing the extension's storage loses the leaderboard identity token. See PRIVACY.md.

This is the same game as the terminal version; see the repository README.
