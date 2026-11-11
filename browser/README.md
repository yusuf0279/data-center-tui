# My Data Center for Chrome and Firefox

A pixel-art idle tycoon in a browser tab. Click the toolbar icon to open (or jump back to) the game. The icon badge shows `!` while a crisis is eating your income.

## Install (from source)

```
npm run build        # from the repository root; writes browser/dist/chrome and browser/dist/firefox
```

- **Chrome / Edge / Brave:** open `chrome://extensions`, turn on *Developer mode*, choose *Load unpacked* and pick `browser/dist/chrome`.
- **Firefox:** open `about:debugging#/runtime/this-firefox`, choose *Load Temporary Add-on* and pick `browser/dist/firefox/manifest.json`. (A permanent install needs the add-on to be signed by Mozilla.)

`npm run package:browser` also writes `browser/dist/my-data-center-chrome.zip` and `my-data-center-firefox.zip`.

## Notes

- Progress is saved in the extension's own storage. The game only ticks while its tab is open; when you come back you earn 75% of your income for the time you were away.
- The extension asks for the `storage` permission and host access to `https://data-center.openexplorer.xyz/*`. It makes no network request unless you join the leaderboard.
- Leaderboard participation is opt-in and sends only your name, Fame and number of data centers (plus a random token) to `data-center.openexplorer.xyz`. Clearing the extension's storage loses the leaderboard identity token. See PRIVACY.md.
- Firefox needs version 127 or newer (Manifest V3 host permissions are granted at install from there).
- Keys: `1`-`6` pick, `s` `c` `h` `d` switch card, `x` open the next data center, `f` fix a crisis, `[` `]` visit older or newer data centers. Everything is also clickable.
