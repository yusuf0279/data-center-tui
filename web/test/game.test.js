'use strict';
// Replays scripts/golden.py's scripted play-through of the real Python game and asserts
// that the JS Game is in the same state, writes the same log and makes the same rng calls.
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');
const golden = require('./golden.json');

const B = BigInt;

/** rng that replays one step's recorded calls [kind, value, size]; strict about order. */
function scriptedRng() {
  const rng = {
    queue: [],
    calls: [],
    take(kind, size) {
      assert.ok(rng.queue.length > 0, 'JS made an rng call (' + kind + ') the Python game did not');
      const [want, value, n] = rng.queue.shift();
      assert.equal(kind, want, 'rng call kind');
      assert.equal(size, n, 'rng call size for ' + kind);
      rng.calls.push([kind, value, size]);
      return value;
    },
    random() { return rng.take('r', 0); },
    weighted(ws) { return rng.take('w', ws.length); },
    index(n) { return rng.take('i', n); },
  };
  return rng;
}

function view(g) {
  return {
    balance: g.siteBalance.map(String), owned: g.siteOwned, chips: g.siteChips,
    staff: g.siteStaff, names: g.siteNames, fame: String(g.fame), sites: g.sites, cur: g.cur,
    readOnly: g.readOnly, phase: g.phase, autopilot: g.autopilot,
    crisis: g.crisis ? Object.assign({}, g.crisis) : null,
    income: String(g.income), baseIncome: String(g.baseIncome),
    siteIncome: g.siteIncome ? Array.from({ length: g.sites + 1 }, (_, k) => String(g.siteIncome(k))) : [],
    rank: C.rankOf(g.fame)[0],
  };
}

const OPS = {
  set_balance: (g, a) => { g.balance = B(a); },
  buy: (g, a) => g.buy(a),
  chip: (g, a) => g.buyChip(a),
  hire: (g, a) => g.hire(a),
  tick: (g) => g.tick(),
  fix: (g) => g.fix(),
  relocate: (g) => g.relocate(),
  goto: (g, a) => g.goto(a),
  site: (g, a) => (a < 0 ? g.prev() : g.next()),
  autopilot: (g) => g.toggleAutopilot(),
};

test('golden run: scripted play-through matches the Python game step by step', () => {
  const steps = golden.run.filter((s) => s.op !== 'offline');
  assert.ok(steps.length > 100);
  const rng = scriptedRng();
  const g = new C.Game({ rng, now: () => 0 });
  assert.equal(g.autopilot, true, 'a brand-new game has autopilot on');
  const seen = new Set();
  steps.forEach((st, i) => {
    seen.add(st.op);
    rng.queue = st.rng.map((c) => c.slice());
    rng.calls = [];
    const logFrom = g.logId;
    assert.ok(OPS[st.op], 'unknown op ' + st.op);
    OPS[st.op](g, st.arg);
    const label = 'step ' + i + ' ' + st.op + ' ' + st.arg;
    assert.deepEqual(rng.queue, [], label + ': the game skipped rng calls Python made');
    assert.deepEqual(rng.calls, st.rng, label + ': rng calls');
    const log = g.log.filter((e) => e.id > logFrom).map((e) => [e.text, e.kind]);
    assert.deepEqual(log, st.log, label + ': log');
    assert.deepEqual(view(g), st.state, label + ': state');
  });
  // the script must really have covered the interesting paths
  for (const op of ['buy', 'chip', 'hire', 'tick', 'fix', 'relocate', 'goto', 'site', 'autopilot']) {
    assert.ok(seen.has(op), 'run covers ' + op);
  }
  const text = steps.flatMap((s) => s.log.map((l) => l[0])).join('\n');
  for (const needle of ['decommissioned: view only', 'Promoted', 'Relocated to', 'fixed',
    'income -100%', 'income -75%', 'income -50%', 'Hired a']) {
    assert.ok(text.includes(needle), 'run exercises: ' + needle);
  }
});

test('golden run: offline gain on load (75%, live data center only)', () => {
  const last = golden.run[golden.run.length - 1];
  assert.equal(last.op, 'offline');
  assert.equal(last.cases.length, 3);
  let credited = 0;
  for (const c of last.cases) {
    const g = C.Game.fromJSON(c.save, { now: () => c.now, rng: scriptedRng() });
    assert.deepEqual(view(g), c.state, 'offline ' + (c.now - c.saved_at));
    if (c.away === null) {
      assert.equal(g.away, null);
      continue;
    }
    credited++;
    assert.equal(g.away.seconds, c.away[0]);
    assert.equal(String(g.away.earned), c.away[1]);
    const msg = g.log[g.log.length - 1];
    assert.equal(msg.text, 'Welcome back! Away ' + c.away[2] + ', earned $' + c.away[3] +
      ' (75% offline rate)');
  }
  assert.equal(credited, 2);
});
