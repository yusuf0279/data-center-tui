'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');
const golden = require('./golden.json');

const { TIERS, STAFF, MAX_SITES } = C;
const B = BigInt;

// ------------------------------------------------------------ golden vectors

test('golden: expandCost', () => {
  golden.expandCost.forEach((v, k) => assert.equal(C.expandCost(k), B(v), 'site ' + k));
  assert.equal(golden.expandCost.length, MAX_SITES + 1);
});

test('golden: costOf', () => {
  for (const [t, o, k, v] of golden.costOf) assert.equal(C.costOf(t, o, k), B(v), [t, o, k] + '');
});

test('golden: chipCost', () => {
  for (const [t, lv, k, v] of golden.chipCost) assert.equal(C.chipCost(t, lv, k), B(v), [t, lv, k] + '');
});

test('golden: tierIncome', () => {
  for (const [t, o, lv, k, v] of golden.tierIncome) {
    assert.equal(C.tierIncome(t, o, lv, k), B(v), [t, o, lv, k] + '');
  }
});

test('golden: staffCost', () => {
  for (const [r, lv, k, v] of golden.staffCost) assert.equal(C.staffCost(r, lv, k), B(v), [r, lv, k] + '');
});

test('golden: responseSecs', () => {
  for (const [r, lv, v] of golden.responseSecs) assert.equal(C.responseSecs(r, lv), v, [r, lv] + '');
});

test('golden: milestoneMult', () => {
  for (const [o, v] of golden.milestoneMult) assert.equal(C.milestoneMult(o), B(v), 'owned ' + o);
});

test('golden: crewMultiplier', () => {
  for (const [lv, v] of golden.crewMultiplier) assert.equal(C.crewMultiplier(lv), B(v), 'lv ' + lv);
});

test('golden: fameGain', () => {
  for (const [bal, k, v] of golden.fameGain) assert.equal(C.fameGain(B(bal), k), B(v), [bal, k] + '');
});

test('golden: rankOf', () => {
  for (const [fame, title, need, next] of golden.rankOf) {
    assert.deepEqual(C.rankOf(B(fame)), [title, B(need), next], 'fame ' + fame);
  }
});

test('golden: roman', () => {
  for (const [n, v] of golden.roman) assert.equal(C.roman(n), v, 'roman ' + n);
});

test('golden: startBalance', () => {
  for (const [k, v] of golden.startBalance) assert.equal(C.startBalance(k), B(v), 'site ' + k);
});

test('golden: siteName', () => {
  for (const [k, v] of golden.siteName) assert.equal(C.siteName(k), v, 'site ' + k);
});

test('golden: chipName', () => {
  for (const [t, lv, v] of golden.chipName) assert.equal(C.chipName(t, lv), v, [t, lv] + '');
});

test('golden: restoreSite', () => {
  assert.ok(golden.restoreSite.length >= 40);
  for (const [k, inc, bonus, owned, chips] of golden.restoreSite) {
    const [o, c] = C.restoreSite(k, B(inc), bonus);
    assert.deepEqual(o, owned, 'owned ' + [k, inc, bonus]);
    assert.deepEqual(c, chips, 'chips ' + [k, inc, bonus]);
  }
});

test('golden: fmt', () => {
  assert.ok(golden.fmt.length >= 60);
  for (const [n, text] of golden.fmt) assert.equal(C.fmt(B(n)), text, 'fmt(' + n + ')');
});

test('fmt: spot checks and number input', () => {
  assert.equal(C.fmt(0n), '0');
  assert.equal(C.fmt(999n), '999');
  assert.equal(C.fmt(999995n), '1.00M');
  assert.equal(C.fmt(999994n), '999.99K');
  assert.equal(C.fmt(10n ** 36n), '1.00e36');
  assert.equal(C.fmt(12), '12');
  assert.equal(C.fmt(-5n), '0');
});

test('fmtDuration', () => {
  assert.equal(C.fmtDuration(59), '0m');
  assert.equal(C.fmtDuration(3 * 3600 + 125), '3h 2m');
  assert.equal(C.fmtDuration(90061), '1d 1h');
});

test('constants and names', () => {
  assert.equal(C.siteName(0), 'Garage in Palo Alto');
  assert.equal(C.siteName(10), 'Parallel Universe #1');
  assert.equal(C.siteName(59), 'Parallel Universe #50');
  assert.equal(C.chipName(0, 0), 'GeForceless 1030');
  assert.equal(C.chipName(0, 5), 'Radeoff 6400 Ti');
  assert.equal(C.chipName(9, 19), 'Info Paradox Ultra Max');
  assert.equal(TIERS.length, 10);
  assert.equal(STAFF.length, 10);
  assert.equal(C.COST_SCALE, 1250n);
  assert.equal(C.INCOME_SCALE, 1000n);
  assert.equal(C.EXPAND_BASE, 10n ** 16n);
  assert.equal(C.MAX_CHIP, 20);
  assert.equal(C.CRISIS_MEAN, 120);
  assert.equal(C.CRISIS_MIN_INCOME, 10n);
  assert.equal(C.SPRITES.length, 10);
  assert.ok(C.SPRITES.every((s) => s.length === 6 && s.every((r) => r.length === 6)));
});
