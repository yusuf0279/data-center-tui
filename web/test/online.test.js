'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

const TOKEN = 'cd'.repeat(16);

function joined(extra = {}) {
  return C.Game.fromJSON(Object.assign({
    sites: 2, fame: '123456', autopilot: false,
    online: { asked: true, joined: true, name: 'Ada', token: TOKEN },
  }, extra), { now: () => 1 });
}

/** Fake api: answers from a queue of [status, body] and records the calls. */
function fakeApi(...answers) {
  const calls = [];
  const api = async (method, path, body) => {
    calls.push({ method, path, body: body === undefined ? undefined : JSON.parse(JSON.stringify(body)) });
    const a = answers.length > 1 ? answers.shift() : answers[0];
    if (a instanceof Error) throw a;
    return a;
  };
  api.calls = calls;
  return api;
}

test('NAME_RE and TOKEN_RE', () => {
  for (const ok of ['A', 'ada', 'Ada Lovelace', 'a_b.c-d', 'x'.repeat(20), '0day']) assert.match(ok, C.NAME_RE);
  for (const bad of ['', ' a', '_a', 'x'.repeat(21), 'a\n', 'café', 'a<b>', '-a']) assert.doesNotMatch(bad, C.NAME_RE);
  assert.match('a'.repeat(32), C.TOKEN_RE);
  assert.match('0123456789abcdef'.repeat(4), C.TOKEN_RE);
  for (const bad of ['a'.repeat(31), 'a'.repeat(65), 'A'.repeat(32), 'g'.repeat(32), '', 'a'.repeat(32) + '\n']) {
    assert.doesNotMatch(bad, C.TOKEN_RE);
  }
  assert.match('', C.DC_NAME_RE);
  assert.doesNotMatch('x'.repeat(25), C.DC_NAME_RE);
});

test('makeToken: injectable source, 32 hex chars; real source works too', () => {
  const bytes = Uint8Array.from([0, 1, 2, 15, 16, 255, 128, 9, 10, 11, 12, 13, 14, 171, 205, 239]);
  let asked = 0;
  const t = C.makeToken((n) => { asked = n; return bytes; });
  assert.equal(asked, 16);
  assert.equal(t, '0001020f10ff80090a0b0c0d0eabcdef');
  assert.match(t, C.TOKEN_RE);
  assert.throws(() => C.makeToken(() => new Uint8Array(8)));
  assert.throws(() => C.makeToken(() => null));
  const real = C.makeToken();
  assert.match(real, C.TOKEN_RE);
  assert.notEqual(real, C.makeToken());
});

test('submitPayload: fame is integer text and the body survives JSON.stringify', () => {
  const g = joined();
  g.fame = 10n ** 12n + 123n; // past 2^53 would break a Number
  const body = C.submitPayload(g);
  assert.deepEqual(body, { token: TOKEN, name: 'Ada', fame: '1000000000123', sites: 2 });
  assert.equal(typeof body.fame, 'string');
  assert.doesNotThrow(() => JSON.stringify(body));
  g.fame = 2n ** 80n;
  assert.equal(C.submitPayload(g).fame, '1208925819614629174706176');
  assert.throws(() => JSON.stringify({ fame: g.fame }), TypeError, 'sanity: BigInt really cannot be stringified');
});

test('handleSubmit: 200 ok, 409 name taken, 400 refused, anything else retries', () => {
  const g = joined();
  let st = C.newOnlineState();
  assert.deepEqual(C.handleSubmit(g, st, [200, {}], 'snap'), { kind: 'ok' });
  assert.equal(st.lastSent, 'snap');
  assert.equal(g.online.joined, true);

  st = C.newOnlineState();
  assert.deepEqual(C.handleSubmit(g, st, [409, { error: 'name taken' }], 'snap'), { kind: 'taken' });
  assert.equal(g.online.joined, false);
  assert.equal(st.lastSent, null);
  assert.equal(g.log[g.log.length - 1].text, "! the name 'Ada' is taken");
  assert.equal(g.log[g.log.length - 1].kind, 'error');

  st = C.newOnlineState();
  assert.deepEqual(C.handleSubmit(g, st, [400, { error: 'implausible fame' }], 'snap2'), { kind: 'rejected' });
  assert.equal(st.lastSent, 'snap2', 'a refused score is not resent');
  assert.equal(g.log[g.log.length - 1].text, '! the leaderboard rejected the score (implausible fame)');
  C.handleSubmit(g, st, [400, {}], 's');
  assert.equal(g.log[g.log.length - 1].text, '! the leaderboard rejected the score (bad data)');
  C.handleSubmit(g, st, [400, { error: 7 }], 's');
  assert.equal(g.log[g.log.length - 1].text, '! the leaderboard rejected the score (bad data)');

  for (const status of [0, 429, 500, 503, 404, 201]) {
    st = C.newOnlineState();
    const g2 = joined();
    assert.deepEqual(C.handleSubmit(g2, st, [status, {}], 'x'), { kind: 'retry' }, 'status ' + status);
    assert.equal(st.lastSent, null);
    assert.equal(g2.online.joined, true);
  }
});

test('maybeSubmit: sends once, then only on change, throttled to every 120 s', async () => {
  const g = joined();
  const st = C.newOnlineState();
  const api = fakeApi([200, {}]);
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1000), { kind: 'ok' });
  assert.deepEqual(api.calls, [{ method: 'POST', path: '/api/submit',
    body: { token: TOKEN, name: 'Ada', fame: '123456', sites: 2 } }]);
  assert.equal(st.busy, false);
  assert.equal(await C.maybeSubmit(g, api, st, 5000), null, 'unchanged: nothing sent');
  g.fame += 1n;
  assert.equal(await C.maybeSubmit(g, api, st, 1100), null, 'changed but inside 120 s');
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1120), { kind: 'ok' });
  assert.equal(api.calls.length, 2);
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1121, true), { kind: 'ok' }, 'force skips both checks');
  assert.equal(api.calls.length, 3);
});

test('maybeSubmit: not joined, too much fame or already busy sends nothing', async () => {
  const api = fakeApi([200, {}]);
  const st = C.newOnlineState();
  const out = joined();
  out.online.joined = false;
  assert.equal(await C.maybeSubmit(out, api, st, 1000, true), null);
  const big = joined();
  big.fame = C.MAX_FAME_ONLINE + 1n;
  assert.equal(await C.maybeSubmit(big, api, st, 1000, true), null);
  big.fame = C.MAX_FAME_ONLINE;
  assert.deepEqual(await C.maybeSubmit(big, api, st, 1000, true), { kind: 'ok' });
  const busy = joined();
  st.busy = true;
  assert.equal(await C.maybeSubmit(busy, api, st, 9999, true), null);
  assert.equal(api.calls.length, 1);
});

test('maybeSubmit: failures retry later, 409 leaves the board, a thrown api counts as offline', async () => {
  const g = joined();
  const st = C.newOnlineState();
  const api = fakeApi([0, {}], [500, {}], [200, {}]);
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1000), { kind: 'retry' });
  assert.equal(st.lastSent, null);
  assert.equal(await C.maybeSubmit(g, api, st, 1001), null, 'throttled even after a failure');
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1200), { kind: 'retry' });
  assert.deepEqual(await C.maybeSubmit(g, api, st, 1400), { kind: 'ok' });
  const g2 = joined();
  assert.deepEqual(await C.maybeSubmit(g2, fakeApi(new Error('boom')), C.newOnlineState(), 5), { kind: 'retry' });
  const g3 = joined();
  assert.deepEqual(await C.maybeSubmit(g3, fakeApi([409, {}]), C.newOnlineState(), 5), { kind: 'taken' });
  assert.equal(g3.online.joined, false);
});

test('boardFromResults: ok, kept-but-stale, and first-failure boards', () => {
  const players = [{ rank: 1, name: 'Ada', fame: '5', sites: 0 }];
  const me = { registered: true, rank: 1, total: 1, name: 'Ada', fame: '5', sites: 0 };
  const ok = C.boardFromResults(null, [200, { players, total: 9 }], [200, me], 50);
  assert.deepEqual(ok, { players, total: 9, at: 50, me, error: false });
  assert.equal(C.boardFromResults(null, [200, { players }], [500, {}], 1).me, null);
  assert.equal(C.boardFromResults(null, [200, { players }], [0, {}], 1).total, 0);
  const stale = C.boardFromResults(ok, [0, {}], [0, {}], 80);
  assert.equal(stale.error, true);
  assert.equal(stale.at, 50, 'keeps the old data and time');
  assert.deepEqual(stale.players, players);
  assert.equal(ok.error, false, 'does not mutate the previous board');
  assert.deepEqual(C.boardFromResults(null, [0, {}], [0, {}], 80),
    { players: [], total: 0, at: 0, me: null, error: true });
  assert.equal(C.boardFromResults(null, [200, { players: 'x' }], [0, {}], 1).error, true);
});

test('refreshBoard: fetches top 30 then our rank, throttled to 5 s unless forced', async () => {
  const g = joined();
  const st = C.newOnlineState();
  const players = [{ rank: 1, name: 'Ada', fame: '5', sites: 0 }];
  const api = async (method, path, body) => {
    api.calls.push([method, path, body]);
    return path.startsWith('/api/leaderboard') ? [200, { players, total: 1 }]
      : [200, { registered: true, rank: 1, total: 1 }];
  };
  api.calls = [];
  const b = await C.refreshBoard(g, api, st, 100);
  assert.deepEqual(api.calls, [['GET', '/api/leaderboard?limit=30', undefined],
    ['POST', '/api/me', { token: TOKEN }]]);
  assert.equal(b.me.rank, 1);
  assert.equal(st.board, b);
  assert.equal(await C.refreshBoard(g, api, st, 102), b);
  assert.equal(api.calls.length, 2, 'inside 5 s: no request');
  await C.refreshBoard(g, api, st, 102, true);
  assert.equal(api.calls.length, 4);
  g.online.joined = false;
  const before = api.calls.length;
  await C.refreshBoard(g, api, st, 200);
  assert.equal(api.calls.length, before + 1, 'not joined: no /api/me');
  assert.equal(st.board.me, null);
  st.boardBusy = true;
  await C.refreshBoard(g, api, st, 999, true);
  assert.equal(api.calls.length, before + 1, 'one fetch at a time');
});

test('refreshBoard: an unreachable server gives an error board; a throwing api is survived', async () => {
  const g = joined();
  const st = C.newOnlineState();
  const b = await C.refreshBoard(g, fakeApi([0, {}]), st, 10);
  assert.deepEqual(b, { players: [], total: 0, at: 0, me: null, error: true });
  assert.equal(st.boardBusy, false);
  const b2 = await C.refreshBoard(g, fakeApi(new Error('x')), C.newOnlineState(), 10);
  assert.equal(b2.error, true);
});

test('boardRows: formats Fame, skips bad rows and names a server must not be able to send', () => {
  const g = joined();
  const board = { players: [
    { rank: 1, name: 'Ada', fame: '1234567', sites: 3 },
    { rank: 2, name: 'bob', fame: '12', sites: 0 },
    { rank: 3, name: '\u001b[31mred', fame: '5', sites: 0 },
    { rank: 4, name: 'x'.repeat(21), fame: '5', sites: 0 },
    { rank: 5, name: 'ok', fame: 'NaN', sites: 0 },
    { rank: '6', name: 'ok', fame: '5', sites: 0 },
    { rank: 7, name: 'ok', fame: '5', sites: -1 },
    { rank: 8, name: 'ok', fame: '5', sites: 1.5 },
    null, 'str', [],
    { rank: 9, name: 'ADA', fame: '5', sites: 1 },
  ] };
  const rows = C.boardRows(board, g);
  assert.deepEqual(rows.map((r) => r.rank), [1, 2, 9]);
  assert.deepEqual(rows[0], { rank: 1, name: 'Ada', fame: '1.23M', sites: 4, mine: true });
  assert.equal(rows[1].mine, false);
  assert.equal(rows[2].mine, true, 'names compare case-insensitively like Python');
  g.online.joined = false;
  assert.equal(C.boardRows(board, g)[0].mine, false);
  assert.equal(C.boardRows(board, g, 1).length, 1);
  assert.deepEqual(C.boardRows(null, g), []);
  assert.deepEqual(C.boardRows({ players: 'x' }, g), []);
});
