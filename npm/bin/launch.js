#!/usr/bin/env node
'use strict';
// Launcher for the Python game `build-a-hyperscaler`. Makes no network requests itself:
// it only starts one of uvx / pipx / an installed copy, with stdio inherited.
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const NAME = 'build-a-hyperscaler';
const args = process.argv.slice(2);

/** Candidate commands in priority order. */
const RUNNERS = [
  { cmd: 'uvx', args: [NAME] },
  { cmd: 'pipx', args: ['run', NAME] },
  { cmd: NAME, args: [] },
];

/** Real path of this script, to recognise our own npm shim on PATH. */
function self() {
  try { return fs.realpathSync(__filename); } catch (e) { return __filename; }
}

/** First `cmd` on PATH that is not this launcher (after npm i -g the bare name may be us). */
function resolveOther(cmd) {
  if (process.platform === 'win32') return cmd; // .cmd shims: keep the plain behaviour
  const me = self();
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    const f = path.join(dir, cmd);
    try {
      fs.accessSync(f, fs.constants.X_OK);
      if (fs.statSync(f).isDirectory()) continue;
      if (fs.realpathSync(f) !== me) return f;
    } catch (e) { /* not here */ }
  }
  return null;
}

function run(runner) {
  let cmd = runner.cmd;
  if (cmd === NAME) {
    if (process.env.BAH_LAUNCHER) return null; // we were started by a launcher: never loop
    cmd = resolveOther(NAME);
    if (cmd === null) return null;
  }
  const env = { ...process.env, BAH_LAUNCHER: '1' };
  const res = spawnSync(cmd, [...runner.args, ...args], { stdio: 'inherit', env });
  if (res.error && res.error.code === 'ENOENT') return null; // not installed: try the next one
  if (res.error) {
    console.error(`${NAME}: could not start ${runner.cmd}: ${res.error.message}`);
    return 1;
  }
  if (res.signal) return 128 + (require('node:os').constants.signals[res.signal] || 0);
  return res.status === null ? 1 : res.status;
}

function main() {
  for (const runner of RUNNERS) {
    const code = run(runner);
    if (code !== null) return code;
  }
  console.error(
    `${NAME}: no way to run the game was found.\n` +
    `The game is a Python program; install one of these and run this again:\n` +
    `  uv    https://docs.astral.sh/uv/   (then: uvx ${NAME})\n` +
    `  pipx  https://pipx.pypa.io/        (then: pipx install ${NAME})\n` +
    `  or:   python3 -m pip install ${NAME}   (Python 3.10 or newer)`
  );
  return 127;
}

process.exit(main());
