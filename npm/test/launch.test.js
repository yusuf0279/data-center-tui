'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const LAUNCH = path.join(__dirname, '..', 'bin', 'launch.js');

/** Make a temp dir of fake executables: {name: exit code}; each logs "name args" to log. */
function fakeBin(spec) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bah-'));
  const log = path.join(dir, 'log.txt');
  for (const [name, code] of Object.entries(spec)) {
    const f = path.join(dir, name);
    fs.writeFileSync(f, `#!/bin/sh\necho "${name} $*" >> "${log}"\nexit ${code}\n`);
    fs.chmodSync(f, 0o755);
  }
  return { dir, log };
}

function launch(dir, args = [], extra = {}) {
  // PATH holds only the fakes plus node's own dir, so real uvx/pipx cannot leak in.
  const env = { PATH: `${dir}${path.delimiter}${path.dirname(process.execPath)}`, ...extra };
  return spawnSync(process.execPath, [LAUNCH, ...args], { env, encoding: 'utf8' });
}
const lines = (log) => (fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n') : []);

test('uvx wins when present, args forwarded, exit code passed', () => {
  const { dir, log } = fakeBin({ uvx: 3, pipx: 0, 'build-a-hyperscaler': 0 });
  const r = launch(dir, ['--no-online', '--save', 'a b.json']);
  assert.strictEqual(r.status, 3);
  assert.deepStrictEqual(lines(log), ['uvx build-a-hyperscaler --no-online --save a b.json']);
});

test('pipx run is second', () => {
  const { dir, log } = fakeBin({ pipx: 0, 'build-a-hyperscaler': 0 });
  const r = launch(dir, ['--version']);
  assert.strictEqual(r.status, 0);
  assert.deepStrictEqual(lines(log), ['pipx run build-a-hyperscaler --version']);
});

test('installed command is third', () => {
  const { dir, log } = fakeBin({ 'build-a-hyperscaler': 7 });
  const r = launch(dir, ['x']);
  assert.strictEqual(r.status, 7);
  assert.deepStrictEqual(lines(log), ['build-a-hyperscaler x']);
});

test('no runner: clear hint on stderr and nonzero exit', () => {
  const { dir } = fakeBin({});
  const r = launch(dir);
  assert.strictEqual(r.status, 127);
  assert.match(r.stderr, /no way to run the game/);
  assert.match(r.stderr, /uv /);
  assert.match(r.stderr, /pipx/);
  assert.match(r.stderr, /python3 -m pip install build-a-hyperscaler/);
});

test('own npm shim on PATH is not run (no self-recursion)', () => {
  const { dir } = fakeBin({});
  fs.symlinkSync(LAUNCH, path.join(dir, 'build-a-hyperscaler')); // what npm i -g creates
  const t = Date.now();
  const r = launch(dir, ['--version']);
  assert.ok(Date.now() - t < 5000, 'must not loop');
  assert.strictEqual(r.status, 127);
  assert.match(r.stderr, /no way to run the game/);
});

test('BAH_LAUNCHER set: bare name is skipped even if it is a real program', () => {
  const { dir, log } = fakeBin({ 'build-a-hyperscaler': 0 });
  const r = launch(dir, [], { BAH_LAUNCHER: '1' });
  assert.strictEqual(r.status, 127);
  assert.deepStrictEqual(lines(log), []);
});

test('the guard does not block a real runner next to our shim', () => {
  const a = fakeBin({});
  fs.symlinkSync(LAUNCH, path.join(a.dir, 'build-a-hyperscaler'));
  const b = fakeBin({ 'build-a-hyperscaler': 5 });
  const r = launch(`${a.dir}${path.delimiter}${b.dir}`, ['go']);
  assert.strictEqual(r.status, 5);
  assert.deepStrictEqual(lines(b.log), ['build-a-hyperscaler go']);
});

test('uvx is run with BAH_LAUNCHER set', () => {
  const { dir, log } = fakeBin({});
  fs.writeFileSync(path.join(dir, 'uvx'), `#!/bin/sh\necho "$BAH_LAUNCHER" > "${log}"\n`, { mode: 0o755 });
  assert.strictEqual(launch(dir).status, 0);
  assert.deepStrictEqual(lines(log), ['1']);
});
