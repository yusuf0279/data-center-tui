# build-a-hyperscaler (npm launcher)

A tiny launcher for [Build a Hyperscaler / My Data Center](https://github.com/yusuf0279/data-center-tui), a pixel-art idle tycoon for your terminal. The game itself is a Python program on PyPI; this package only starts it.

```
npx build-a-hyperscaler
```

It tries, in order: `uvx build-a-hyperscaler`, `pipx run build-a-hyperscaler`, then a `build-a-hyperscaler` already on your PATH. Arguments (for example `--no-online`) and the exit code are passed through, and the terminal is handed over unchanged. If none is available it prints how to install one. The launcher has no dependencies and makes no network requests itself (uvx and pipx download the game from PyPI the first time).

If the bare `build-a-hyperscaler` on your PATH turns out to be this launcher itself (after `npm i -g`), it is skipped, so a launcher never runs itself. On Windows, or when starting a program fails for a reason other than "not found", that check is not done and the plain behaviour applies.

Needs Node 18 or newer. MIT licensed.
