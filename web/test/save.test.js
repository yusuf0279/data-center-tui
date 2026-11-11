'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

const B = BigInt;
const TOKEN = 'ab'.repeat(16);
const opts = (now = () => 1000) => ({ now, rng: C.makeRng(() => 0.5) });
const load = (raw, now) => C.Game.fromJSON(raw, opts(now));

/** Invariants every loaded game must satisfy, whatever it was fed. */
function assertSane(g) {
  const n = g.sites + 1;
  assert.ok(Number.isInteger(g.sites) && g.sites >= 0 && g.sites <= 60);
  assert.ok(g.cur >= 0 && g.cur <= g.sites);
  for (const arr of [g.siteBalance, g.siteOwned, g.siteChips, g.siteStaff, g.siteNames]) {
    assert.equal(arr.length, n);
  }
  g.siteBalance.forEach((b) => assert.ok(typeof b === 'bigint' && b >= 0n && b < C.MAX_BIG));
  g.siteOwned.forEach((a) => {
    assert.equal(a.length, 10);
    a.forEach((v) => assert.ok(Number.isInteger(v) && v >= 0 && v <= 4000));
  });
  g.siteChips.forEach((a) => a.forEach((v) => assert.ok(Number.isInteger(v) && v >= 0 && v <= 20)));
  g.siteStaff.forEach((a) => {
    assert.equal(a.length, 10);
    a.forEach((v) => assert.ok(Number.isInteger(v) && v >= -1 && v <= 10));
  });
  g.siteNames.forEach((s) => assert.match(s, C.DC_NAME_RE));
  assert.ok(typeof g.fame === 'bigint' && g.fame >= 0n && g.fame < C.MAX_BIG);
  assert.equal(typeof g.autopilot, 'boolean');
  assert.ok(g.theme.length > 0);
  g.income; // must not throw
}

test('garbage saves fall back to a fresh game with autopilot on', () => {
  const junk = [undefined, null, 0, 1, true, 'garbage', '', '{', '[]', '[1,2]', '"x"', 'null',
    '{}', [], 42, Symbol.iterator && 'NaN'];
  for (const raw of junk) {
    const g = load(raw);
    assertSane(g);
    assert.equal(g.sites, 0, String(raw));
    assert.equal(g.siteBalance[0], 500n);
    assert.equal(g.fame, 0n);
    assert.equal(g.autopilot, true, 'brand-new save: ' + String(raw));
    assert.deepEqual(g.online, { asked: false, joined: false, name: '', token: '' });
    assert.equal(g.theme, 'gruvbox');
  }
});

test('autopilot: default on only for a brand-new save', () => {
  assert.equal(load({}).autopilot, true);
  assert.equal(load({ sites: 0 }).autopilot, false, 'an existing save without the key');
  assert.equal(load({ autopilot: false }).autopilot, false);
  assert.equal(load({ autopilot: true }).autopilot, true);
  assert.equal(load({ autopilot: 'yes' }).autopilot, false);
  assert.equal(load({ autopilot: 1 }).autopilot, false);
});

test('sites bounds 0..60', () => {
  for (const [v, want] of [[0, 0], [1, 1], [60, 60], [61, 0], [-1, 0], [1.5, 0], ['3', 0],
    [true, 0], [null, 0], [1e300, 0], [NaN, 0]]) {
    const g = load({ sites: v, autopilot: false });
    assertSane(g);
    assert.equal(g.sites, want, 'sites=' + String(v));
  }
  assert.equal(load({ sites: 60 }).siteOwned.length, 61);
});

test('owned 0..4000, chips 0..20, staff -1..10: out-of-range entries reset individually', () => {
  const g = load({
    sites: 1,
    site_owned: [[4000, 4001, -1, 1.5, '5', null, 7, true, 0, 3999], 'nope'],
    site_chips: [[20, 21, -1, 0, 5, 1e9, 'x', null, 2, 3], null],
    site_staff: [[10, 11, -2, -1, 0, 5, 0.5, '3', null, 9], { 0: 1 }],
  });
  assertSane(g);
  assert.deepEqual(g.siteOwned[0], [4000, 0, 0, 0, 0, 0, 7, 0, 0, 3999]);
  assert.deepEqual(g.siteChips[0], [20, 0, 0, 0, 5, 0, 0, 0, 2, 3]);
  assert.deepEqual(g.siteStaff[0], [10, -1, -1, -1, 0, 5, -1, -1, -1, 9]);
  assert.deepEqual(g.siteOwned[1], new Array(10).fill(0));
  assert.deepEqual(g.siteStaff[1], new Array(10).fill(-1));
  // too long / too short lists
  const h = load({ sites: 0, site_owned: [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]], site_chips: [[1]] });
  assert.deepEqual(h.siteOwned[0], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.deepEqual(h.siteChips[0], [1, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
});

test('balances: decimal strings below MAX_BIG; anything else becomes the start balance', () => {
  const big = (10n ** 600n - 1n).toString();
  const g = load({
    sites: 5,
    site_balance: [big, '10' + '0'.repeat(600), '-5', '12.5', 'abc', 123456789, -3, 1e30, null, {}],
    cur: 0,
  });
  assertSane(g);
  assert.equal(g.siteBalance[0], 10n ** 600n - 1n);
  assert.equal(g.siteBalance[1], C.startBalance(1), '10^601 is too big');
  assert.equal(g.siteBalance[2], C.startBalance(2));
  assert.equal(g.siteBalance[3], C.startBalance(3));
  assert.equal(g.siteBalance[4], C.startBalance(4));
  assert.equal(g.siteBalance[5], 123456789n, 'safe integers are accepted');
  assert.equal(load({ site_balance: [10 ** 600 + ''] }).siteBalance[0], 500n, 'MAX_BIG itself is out');
  assert.equal(load({ site_balance: ['1' + '0'.repeat(600)] }).siteBalance[0], 500n);
  assert.equal(load({ site_balance: [1e30] }).siteBalance[0], 500n, 'unsafe numbers lose digits: refused');
  assert.equal(load({ site_balance: 'not a list' }).siteBalance[0], 500n);
});

test('fame: decimal string below MAX_BIG, else 0', () => {
  assert.equal(load({ fame: '12345678901234567890' }).fame, 12345678901234567890n);
  assert.equal(load({ fame: 7 }).fame, 7n);
  for (const bad of ['-1', '1e3', '', 'x', null, -1, 1.5, '1' + '0'.repeat(600), [], {}]) {
    assert.equal(load({ fame: bad }).fame, 0n, String(bad));
  }
});

test('cur: in range or the newest', () => {
  assert.equal(load({ sites: 3, cur: 1 }).cur, 1);
  assert.equal(load({ sites: 3, cur: 4 }).cur, 3);
  assert.equal(load({ sites: 3, cur: -1 }).cur, 3);
  assert.equal(load({ sites: 3, cur: 'x' }).cur, 3);
  assert.equal(load({ sites: 3, cur: 0.5 }).cur, 3);
});

test('site names: only up to 24 printable ASCII characters', () => {
  const g = load({ sites: 5, site_names: ['Home', 'x'.repeat(24), 'x'.repeat(25), 'tab\there', 'café', 7] });
  assert.deepEqual(g.siteNames, ['Home', 'x'.repeat(24), '', '', '', '']);
  assert.equal(g.siteLabel(0), 'Home');
  assert.equal(g.siteLabel(2), C.siteName(2));
  assert.equal(load({ sites: 0, site_names: ['   '] }).siteLabel(0), C.siteName(0), 'blank = default');
});

test('online block: name and token must both be valid to count as joined', () => {
  const ok = load({ online: { asked: true, joined: true, name: 'Ada_1', token: TOKEN } });
  assert.deepEqual(ok.online, { asked: true, joined: true, name: 'Ada_1', token: TOKEN });
  const badName = load({ online: { asked: true, joined: true, name: '_bad', token: TOKEN } });
  assert.deepEqual(badName.online, { asked: true, joined: false, name: '', token: '' });
  const badToken = load({ online: { asked: true, joined: true, name: 'Ada', token: 'XYZ' } });
  assert.deepEqual(badToken.online, { asked: true, joined: false, name: '', token: '' });
  const notJoined = load({ online: { asked: 'yes', joined: 'true', name: 'Ada', token: TOKEN } });
  assert.deepEqual(notJoined.online, { asked: false, joined: false, name: 'Ada', token: TOKEN });
  assert.equal(load({ online: 'x' }).online.joined, false);
  assert.equal(load({ online: [] }).online.asked, false);
  assert.equal(load({ online: { name: 'a'.repeat(21), token: TOKEN, joined: true } }).online.joined, false);
});

test('theme must be a short non-empty string', () => {
  assert.equal(load({ theme: 'nord' }).theme, 'nord');
  for (const bad of ['', 5, null, 'x'.repeat(65), {}]) assert.equal(load({ theme: bad }).theme, 'gruvbox');
});

test('save round trip keeps everything, through JSON text', () => {
  const g = load(undefined, () => 5000);
  g.balance = 123456789012345678901234567890n;
  g.owned[2] = 40;
  g.chips[2] = 3;
  g.staff[1] = 4;
  g.fame = 99999999999999999999n;
  g.sites = 1;
  g.siteOwned.push(new Array(10).fill(1));
  g.siteChips.push(new Array(10).fill(0));
  g.siteBalance.push(777n);
  g.siteStaff.push(new Array(10).fill(-1));
  g.siteNames = ['Home', ''];
  g.cur = 0;
  g.autopilot = false;
  g.online = { asked: true, joined: true, name: 'Zed', token: TOKEN };
  g.theme = 'nord';
  const text = JSON.stringify(g);
  const data = JSON.parse(text);
  assert.deepEqual(Object.keys(data).sort(), ['autopilot', 'cur', 'fame', 'online', 'saved_at',
    'site_balance', 'site_chips', 'site_names', 'site_owned', 'site_staff', 'sites', 'theme']);
  assert.equal(data.site_balance[0], '123456789012345678901234567890');
  assert.equal(data.fame, '99999999999999999999');
  const h = C.Game.fromJSON(text, opts(() => 5000)); // saved_at == now: nothing earned
  assert.deepEqual(JSON.parse(JSON.stringify(h)), data);
  assert.equal(h.away, null);
});

// ------------------------------------------------------------------ offline

function offlineSave(extra = {}) {
  return Object.assign({
    sites: 1, cur: 0, autopilot: false, fame: '3',
    site_balance: ['1000', '2000'],
    site_owned: [[9, 9, 9, 9, 9, 9, 9, 9, 9, 9], [10, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
    saved_at: 100,
  }, extra);
}

test('offline: 75% of the live data center only, whole seconds, floors like site_income', () => {
  const g = load(offlineSave(), () => 100 + 3600.9);
  // live site #2: 10 Budget VPS at x1000 income = 20000/s, +6% Fame, floor
  const live = g.siteIncome(1);
  assert.equal(live, 21200n);
  assert.equal(g.siteBalance[1], 2000n + 3600n * live * 3n / 4n);
  assert.equal(g.siteBalance[0], 1000n, 'decommissioned data centers do not earn');
  assert.equal(g.away.seconds, 3600.9);
  assert.equal(g.away.earned, 3600n * live * 3n / 4n);
  assert.match(g.log[g.log.length - 1].text, /^Welcome back! Away 1h 0m, earned \$.* \(75% offline rate\)$/);
  assert.equal(g.cur, 0, 'the view is kept');
});

test('offline: saved_at that is missing, non-finite, non-positive or in the future is ignored', () => {
  const want = (extra) => {
    const g = load(offlineSave(extra), () => 100 + 5000);
    assert.equal(g.siteBalance[1], 2000n, JSON.stringify(extra));
    assert.equal(g.away, null);
  };
  for (const bad of [0, -5, NaN, Infinity, -Infinity, '100', null, true, [], {}]) want({ saved_at: bad });
  const noKey = offlineSave();
  delete noKey.saved_at;
  assert.equal(load(noKey, () => 99999).siteBalance[1], 2000n);
  const future = load(offlineSave({ saved_at: 10000 }), () => 100);
  assert.equal(future.siteBalance[1], 2000n, 'clock went backwards: no gain, no negative');
});

test('offline: nothing earned under one second or with no income', () => {
  assert.equal(load(offlineSave(), () => 100.99).siteBalance[1], 2000n);
  const idle = load(offlineSave({ site_owned: [[0], [0]] }), () => 1e9);
  assert.equal(idle.siteBalance[1], 2000n);
  assert.equal(idle.away, null);
});

test('offline: absurd elapsed times stay exact and do not throw', () => {
  const g = load(offlineSave({ saved_at: 1e-300 }), () => 1e300);
  assertSane(g);
  assert.ok(g.siteBalance[1] > 10n ** 300n);
  const edge = load(offlineSave({ saved_at: Number.MAX_VALUE }), () => 1);
  assert.equal(edge.siteBalance[1], 2000n);
});

// ------------------------------------------------------------------ actions

test('read-only guards: a decommissioned data center cannot be changed', () => {
  const g = load(offlineSave({ saved_at: undefined, site_balance: ['10000000', '10000000'] }));
  assert.equal(g.readOnly, true);
  const before = JSON.stringify(g.toJSON());
  for (const act of [() => g.buy(0), () => g.buyChip(0), () => g.hire(0), () => g.train(0)]) {
    act();
    assert.match(g.log[g.log.length - 1].text, /^#1 is decommissioned: view only \(your live data center is #2\)$/);
  }
  assert.equal(JSON.stringify(g.toJSON()), before);
  g.relocate();
  assert.match(g.log[g.log.length - 1].text, /^! relocate from your newest data center/);
  g.next();
  assert.equal(g.readOnly, false);
  g.buy(0);
  assert.equal(g.siteOwned[1][0], 11);
});

test('relocate: needs the cost, adds an empty site, keeps the old balance, clears the crisis', () => {
  const g = load({ sites: 0, autopilot: false, site_balance: [String(C.expandCost(0) * 9n + 7n)] });
  g.crisis = { title: 't', sev: 1, fixer: null, eta: null };
  g.relocate();
  assert.equal(g.sites, 1);
  assert.equal(g.cur, 1);
  assert.equal(g.fame, 3n);
  assert.equal(g.crisis, null);
  assert.equal(g.siteBalance[0], C.expandCost(0) * 9n + 7n, 'the frozen data center keeps its money');
  assert.equal(g.siteBalance[1], C.startBalance(1));
  assert.deepEqual(g.siteOwned[1], new Array(10).fill(0));
  assert.deepEqual(g.siteStaff[1], new Array(10).fill(-1));
  assert.equal(g.siteNames[1], '');
  const texts = g.log.map((e) => e.text);
  assert.ok(texts.includes('★ Relocated to Abandoned Mall in Ohio! +3 Fame (+6% income)'));
  assert.ok(texts.includes('★ Promoted: Junior Dev!'));
  const poor = load({ sites: 0, site_balance: ['5'] });
  poor.relocate();
  assert.equal(poor.sites, 0);
  assert.match(poor.log[poor.log.length - 1].text, /^! need \$10\.00Qa to relocate to Abandoned Mall in Ohio$/);
  const top = load({ sites: 60, site_balance: [String(10n ** 599n)] });
  top.cur = 60;
  top.relocate();
  assert.equal(top.sites, 60);
  assert.equal(top.log[top.log.length - 1].text, 'You own the multiverse. For now.');
});

test('renameSite validates with DC_NAME_RE', () => {
  const g = load({ sites: 1 });
  assert.equal(g.renameSite(0, 'Home Sweet Home'), true);
  assert.equal(g.siteLabel(0), 'Home Sweet Home');
  assert.equal(g.renameSite(1, 'x'.repeat(24)), true);
  assert.equal(g.renameSite(1, 'x'.repeat(25)), false);
  assert.equal(g.renameSite(1, 'café'), false);
  assert.equal(g.renameSite(1, 'line\nbreak'), false);
  assert.equal(g.renameSite(2, 'x'), false);
  assert.equal(g.renameSite(-1, 'x'), false);
  assert.equal(g.renameSite(0, 5), false);
  assert.equal(g.siteLabel(1), 'x'.repeat(24));
  assert.equal(g.renameSite(1, ''), true);
  assert.equal(g.siteLabel(1), C.siteName(1), 'blank resets to the default');
  assert.equal(g.siteLabel(0), 'Home Sweet Home');
});

test('goto / prev / next stay in range', () => {
  const g = load({ sites: 2 });
  assert.equal(g.cur, 2);
  g.next();
  assert.equal(g.cur, 2);
  g.prev();
  g.prev();
  g.prev();
  assert.equal(g.cur, 0);
  g.goto(1.5);
  g.goto('1');
  g.goto(3);
  g.goto(-1);
  assert.equal(g.cur, 0);
  g.goto(2);
  assert.equal(g.cur, 2);
});

test('makeRng: weighted follows bisect_right on cumulative weights, index stays in range', () => {
  const at = (x) => C.makeRng(() => x);
  assert.equal(at(0).weighted([5, 3, 2]), 0);
  assert.equal(at(0.4999).weighted([5, 3, 2]), 0);
  assert.equal(at(0.5).weighted([5, 3, 2]), 1);
  assert.equal(at(0.7999).weighted([5, 3, 2]), 1);
  assert.equal(at(0.8).weighted([5, 3, 2]), 2);
  assert.equal(at(0.99999).weighted([5, 3, 2]), 2);
  assert.equal(at(0.99).weighted([7]), 0);
  assert.equal(at(0.99999999).index(6), 5);
  assert.equal(at(0).index(6), 0);
});

test('crew multiplier, crew bonus then Fame bonus are two separate floors', () => {
  const g = load({ sites: 0, autopilot: false, fame: '11',
    site_owned: [[3, 0, 0, 0, 0, 0, 0, 0, 0, 0]], site_staff: [[4, -1, -1, -1, -1, -1, -1, -1, -1, 0]] });
  // raw = 3 VPS * 2/s * crew x2 (Lv4) = 12; crew bonus 5*(5+1) = 30%; Fame 22%
  assert.equal(g.rawIncome(0), 12n);
  assert.equal(g.crewBonus(0), 30);
  assert.equal(g.siteIncome(0), 18n); // 15, then 18.3 -> 18
  assert.equal(12n * 130n * 122n / 10000n, 19n, 'a single floor would give 19');
});
