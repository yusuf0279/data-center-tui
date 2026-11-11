'use strict';
// Headless smoke test of web/index.html + ui.js. jsdom is not available offline, so this
// uses a small DOM stub: it knows the element ids and data attributes of index.html, keeps
// innerHTML/textContent as strings, and lets the test dispatch key and click events.
// What it cannot show: real layout, colours on screen, canvas pixels as a human sees them.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const WEB = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(WEB, f), 'utf8');
const HTML = read('index.html');
const CSS = read('dc.css');
const TOKEN = 'ab'.repeat(16);
const T0 = 1_700_000_000_000;

// ------------------------------------------------------------------ DOM stub

class El {
  constructor(tag, id = '') {
    this.tagName = tag.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.listeners = {};
    this.hidden = false;
    this.value = '';
    this.className = '';
    this.classes = new Set();
    this._text = '';
    this._html = '';
    this.scrollTop = 0;
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.offsetHeight = 0;
    this.width = 0;
    this.height = 0;
    this.style = { setProperty: (k, v) => { this.style[k] = v; } };
    this.classList = {
      toggle: (n, force) => { if (force) this.classes.add(n); else this.classes.delete(n); },
      contains: (n) => this.classes.has(n),
    };
  }

  get textContent() { return this._text; }

  set textContent(v) { this._text = String(v); if (v === '') this.children = []; }

  get innerHTML() { return this._html; }

  set innerHTML(v) { this._html = String(v); }

  get childElementCount() { return this.children.length; }

  get firstChild() { return this.children[0] || null; }

  appendChild(c) { this.children.push(c); c.parent = this; return c; }

  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }

  remove() {}

  focus() { this.focused = true; }

  setAttribute(k, v) { this.attrs[k] = v; }

  getAttribute(k) { return this.attrs[k]; }

  querySelector() { return null; }

  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }

  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }

  getContext() {
    const self = this;
    return {
      createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
      putImageData: (img) => { self.painted = img; },
    };
  }
}

function themeVars() {
  const out = {};
  for (const m of CSS.matchAll(/:root(?:, :root)?\[data-theme="([\w-]+)"\]\s*\{([^}]*)\}/g)) {
    out[m[1]] = Object.fromEntries([...m[2].matchAll(/--dc-(\w+):\s*(#[0-9a-fA-F]{6})/g)].map((x) => [x[1], x[2]]));
  }
  out.gruvbox = out.gruvbox || {};
  return out;
}

/** A browser-ish world running core.js and ui.js on index.html. */
function makeWorld({ save = null, host = {}, fetchImpl = null } = {}) {
  const clock = { t: T0 };
  class FakeDate extends Date {
    constructor(...a) { if (a.length) super(...a); else super(clock.t); }

    static now() { return clock.t; }
  }
  const els = {};
  for (const m of HTML.matchAll(/<(\w+)([^>]*\bid="(\w+)"[^>]*)>/g)) {
    const el = new El(m[1], m[3]);
    el.hidden = /\shidden(\s|$|>)/.test(m[2]);
    els[m[3]] = el;
  }
  const tabs = [...HTML.matchAll(/<button class="tab"[^>]*data-view="(\w+)"/g)].map((m) => {
    const el = els[`tab_${m[1]}`] = new El('button');
    el.dataset.view = m[1];
    return el;
  });
  els.tabBoard = tabs.find((t) => t.dataset.view === 'board');
  const docListeners = {};
  const themes = themeVars();
  const root = new El('html');
  const document = {
    readyState: 'complete', visibilityState: 'visible', body: new El('body'), documentElement: root,
    getElementById: (id) => els[id] || null,
    createElement: (tag) => new El(tag),
    querySelectorAll: (sel) => (sel === '.tab' ? tabs : []),
    addEventListener: (t, fn) => { (docListeners[t] = docListeners[t] || []).push(fn); },
    removeEventListener: (t, fn) => { docListeners[t] = (docListeners[t] || []).filter((f) => f !== fn); },
  };
  const timers = [];
  const intervals = [];
  const saves = [];
  const calls = [];
  const ctx = vm.createContext({
    document, console, Date: FakeDate, crypto: require('node:crypto').webcrypto, Promise, setImmediate, AbortController,
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    clearInterval: () => {},
    setTimeout: (fn, ms) => { const t = { fn, ms, live: true }; timers.push(t); return t; },
    clearTimeout: (t) => { if (t) t.live = false; },
    getComputedStyle: (el) => {
      if (el === root) {
        const t = themes[root.attrs['data-theme']] || {};
        return { getPropertyValue: (n) => t[n.replace('--dc-', '')] || '' };
      }
      const c = String(el.style.color || '');
      const m = c.match(/^#(..)(..)(..)$/);
      return { color: m ? `rgb(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)})` : '' };
    },
    DC_HOST: Object.assign({
      storage: { load: async () => save, save: (t) => { saves.push(t); } },
    }, host),
  });
  ctx.window = ctx;
  ctx.window.addEventListener = () => {};
  ctx.window.removeEventListener = () => {};
  ctx.window.devicePixelRatio = 1;
  ctx.window.fetch = fetchImpl ? (url, init) => { calls.push({ url, init }); return fetchImpl(url, init); }
    : (url) => { calls.push({ url }); return Promise.reject(new Error('no network in test')); };
  vm.runInContext(read('core.js'), ctx);
  vm.runInContext(read('ui.js'), ctx);
  const w = {
    ctx, els, calls, saves, timers, clock, docListeners,
    get game() { return ctx.DCUI.game; },
    C: ctx.DCCore,
    async settle() { for (let i = 0; i < 12; i++) await new Promise((r) => setImmediate(r)); },
    key(k, target = { tagName: 'BODY' }) {
      const e = { key: k, ctrlKey: false, metaKey: false, altKey: false, target, defaultPrevented: false,
        preventDefault() { this.defaultPrevented = true; } };
      (docListeners.keydown || []).forEach((f) => f(e));
      return e;
    },
    click(dataset, inShop = false) {
      const el = { dataset, closest: (s) => (s === '#shop' ? (inShop ? {} : null) : el) };
      (docListeners.click || []).forEach((f) => f({ target: el }));
    },
    async tick(n = 1) {
      for (let i = 0; i < n; i++) { clock.t += 1000; intervals.forEach((f) => f()); }
      await w.settle();
    },
    dialogOpen: () => !els.dlg.hidden,
    type(text) { els.dlgInput.value = text; },
    stripped: (id) => els[id].innerHTML.replace(/<[^>]+>/g, '').replace(/&middot;/g, '.'),
  };
  return w;
}

async function boot(opts = {}) {
  const w = makeWorld(opts);
  await w.settle();
  return w;
}

/** A save that has already answered the consent question. */
const saved = (extra = {}) => JSON.stringify(Object.assign({
  sites: 0, cur: 0, fame: '0', autopilot: false, site_balance: ['500'],
  online: { asked: true, joined: false, name: '', token: '' }, saved_at: T0 / 1000,
}, extra));

const reply = (status, body) => async () => ({ status, text: async () => JSON.stringify(body) });

// --------------------------------------------------------------------- tests

test('markup: no inline scripts or handlers, required ids exist', () => {
  assert.equal(/<script(?![^>]*\bsrc=)/i.test(HTML), false, 'inline <script>');
  assert.equal(/\son[a-z]+\s*=/i.test(HTML), false, 'inline on* handler');
  const ui = read('ui.js');
  assert.equal(/\.on[a-z]+\s*=(?!=)|setAttribute\(\s*['"]on|javascript:|eval\(|new Function/.test(ui), false);
  for (const id of ['title', 'cash', 'stats', 'shop', 'shopTitle', 'hall', 'hallTitle', 'log', 'banner',
    'dlg', 'dlgTitle', 'dlgBody', 'dlgInput', 'dlgError', 'dlgList', 'dlgKeys', 'tabBoard', 'hint']) {
    assert.ok(new RegExp(`id="${id}"`).test(HTML), id);
  }
});

test('first run: consent dialog says what is sent; no fetch until you agree', async () => {
  const w = await boot();
  assert.ok(w.dialogOpen());
  assert.match(w.els.dlgTitle.textContent, /Join the online leaderboard/);
  const body = w.els.dlgBody.textContent;
  assert.match(body, /name/);
  assert.match(body, /Fame/);
  assert.match(body, /number of data centers/);
  assert.match(body, /Nothing else is sent/);
  w.key('1'); // keys do nothing while a dialog is open
  assert.equal(w.game.owned[0], 0);
  w.key('n');
  assert.equal(w.dialogOpen(), false);
  assert.equal(w.game.online.asked, true);
  assert.equal(w.game.online.joined, false);
  await w.tick(10);
  assert.equal(w.calls.length, 0);
});

test('palette: ten tier colours, hue fixed, lighter on dark themes than on light ones', async () => {
  const w = await boot({ save: saved() });
  const tier = (i) => w.els.app.style[`--c-tier${i}`];
  const rgb = (s) => s.match(/\d+/g).map(Number);
  const colours = Array.from({ length: 10 }, (_, i) => tier(i));
  assert.equal(new Set(colours).size, 10);
  assert.ok(colours.every((c) => /^rgb\(\d+,\d+,\d+\)$/.test(c)));
  const lum = (c) => 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2];
  const dark = lum(rgb(tier(0)));
  w.els.theme.value = 'solarized-light';
  w.els.theme.listeners.change.forEach((f) => f());
  assert.equal(w.ctx.document.documentElement.attrs['data-theme'], 'solarized-light');
  assert.ok(lum(rgb(tier(0))) < dark, 'light theme tiers are darker');
  assert.equal(w.game.theme, 'solarized-light');
});

test('keys: 1-9 and 0 pick, view keys switch cards, overview shows rank/Fame/crew', async () => {
  const w = await boot({ save: saved({ site_balance: ['1' + '0'.repeat(30)] }) });
  const g = w.game;
  for (const k of '1234567890') w.key(k);
  assert.deepEqual(Array.from(g.owned), new Array(10).fill(1));
  assert.match(w.els.shop.innerHTML, /data-i="9"/);
  assert.match(w.els.shop.innerHTML, /<span class="key">0<\/span>/);
  w.key('c');
  assert.equal(g.side, 'chips');
  assert.match(w.els.shopTitle.textContent, /CHIP UPGRADES/);
  w.key('1');
  assert.equal(g.chips[0], 1);
  w.key('h');
  assert.equal(g.side, 'staff');
  w.key('1');
  w.key('0');
  assert.equal(g.staff[0], 0);
  assert.equal(g.staff[9], 0);
  assert.match(w.els.shopTitle.textContent, /^CREW \+\d+% · auto OFF/);
  assert.match(w.els.shop.innerHTML, /Lv2: buys cheap servers/);
  assert.match(w.els.shop.innerHTML, /title="Lv2: buys cheap servers/);
  w.key('d');
  assert.equal(g.side, 'sites');
  w.key('b');
  assert.equal(g.side, 'board');
  w.key('s');
  const stats = w.stripped('stats');
  assert.match(stats, /VPFSXCDAHO/);
  assert.match(stats, /Fame\s*0/);
  assert.match(stats, /Status\s*Nobody/);
  assert.match(stats, /#1 Garage in Palo Alto/);
  assert.match(w.els.title.textContent, /MY DATA CENTER.*Nobody/);
  assert.match(w.els.cash.innerHTML, /\$/);
  const hint = w.els.hint.textContent;
  for (const bit of ['1-9, 0', 'b', ', .', 'x relocate', 'f fix', 'a autopilot', 'n name', 'm menu', 'j board']) {
    assert.ok(hint.includes(bit), bit);
  }
  assert.ok(w.saves.length >= 1);
});

test('mouse: tabs, rows, prev/next and fix buttons work through delegation', async () => {
  const w = await boot({ save: saved() });
  w.click({ view: 'chips' });
  assert.equal(w.game.side, 'chips');
  w.click({ view: 'servers' });
  w.click({ i: '0' }, true);
  assert.equal(w.game.owned[0], 1);
  w.click({ act: 'fix' });
  assert.ok(w.game.log.some((l) => /Nothing to fix/.test(l.text)));
  w.click({ act: 'menu' });
  assert.ok(w.dialogOpen());
});

test('card scrolling with , and . when rows do not fit', async () => {
  const w = await boot({ save: saved() });
  w.els.shop.clientHeight = 46 * 4;
  w.key('s');
  assert.match(w.els.shopTitle.textContent, /MARKETPLACE · 1-4\/10  \[s\]/);
  assert.equal((w.els.shop.innerHTML.match(/data-i=/g) || []).length, 4);
  w.key('.');
  assert.match(w.els.shopTitle.textContent, /2-5\/10/);
  w.key('.'); w.key('.'); w.key('.'); w.key('.'); w.key('.'); w.key('.'); w.key('.');
  assert.match(w.els.shopTitle.textContent, /7-10\/10/);
  w.key(',');
  assert.match(w.els.shopTitle.textContent, /6-9\/10/);
  w.key('c');
  assert.match(w.els.shopTitle.textContent, /CHIP UPGRADES · 1-4\/10/, 'switching cards resets the scroll');
});

test('relocate (x), visiting an old world is read-only and washed out, ] returns', async () => {
  const w = await boot({ save: saved({ site_balance: ['20000000000000000'] }) });
  const g = w.game;
  w.key('1');
  w.key('x');
  assert.equal(g.sites, 1);
  assert.equal(g.cur, 1);
  assert.equal(g.fame, 1n);
  assert.equal(w.els.banner.hidden, true);
  assert.equal(w.els.app.classes.has('dead'), false);
  w.key('d');
  assert.match(w.els.shop.innerHTML, /#1 Garage in Palo Alto/);
  assert.match(w.els.shop.innerHTML, /#2 Abandoned Mall in Ohio/);
  w.key('1'); // sites card: key 1 opens data center #1
  assert.equal(g.cur, 0);
  assert.equal(g.side, 'servers');
  assert.equal(w.els.banner.hidden, false);
  assert.match(w.els.banner.textContent, /DECOMMISSIONED/);
  assert.equal(w.els.app.classes.has('dead'), true);
  assert.match(w.els.hallTitle.textContent, /DECOMMISSIONED/);
  assert.match(w.els.shopTitle.textContent, /view only/);
  assert.match(w.stripped('stats'), /Final.*decommissioned/);
  const before = g.siteBalance[0];
  w.key('2');
  assert.equal(g.siteBalance[0], before);
  assert.ok(g.log.some((l) => /decommissioned: view only/.test(l.text)));
  await w.tick(3); // the old world earns nothing, the live one does
  assert.equal(g.siteBalance[0], before);
  w.key(']');
  assert.equal(g.cur, 1);
  assert.equal(w.els.app.classes.has('dead'), false);
  w.key('[');
  assert.equal(g.cur, 0);
  w.key('x'); // relocating from an old world is refused
  assert.equal(g.sites, 1);
});

test('data centers card pages by six and follows the one you are in', async () => {
  const n = 9;
  const save = saved({
    sites: n, cur: n,
    site_balance: Array.from({ length: n + 1 }, () => '5'),
    site_owned: Array.from({ length: n + 1 }, () => new Array(10).fill(0)),
    site_names: Array.from({ length: n + 1 }, (_, k) => (k === 7 ? 'Cool Lab' : '')),
  });
  const w = await boot({ save });
  w.key('d');
  let html = w.els.shop.innerHTML;
  assert.match(html, /#7 /);
  assert.match(html, /#10 /);
  assert.doesNotMatch(html, /#1 /);
  assert.match(html, /#7-10 of 10/);
  w.key('[');
  w.key('[');
  w.key('[');
  w.key('[');
  assert.equal(w.game.cur, 5);
  assert.match(w.els.shop.innerHTML, /#1 /);
  assert.match(w.els.shop.innerHTML, /Cool Lab|#6 /);
  w.key('2'); // second row of page 1 -> data center #2
  assert.equal(w.game.cur, 1);
  w.key('d');
  w.key('9'); // beyond six: ignored
  assert.equal(w.game.cur, 1);
  w.key('d');
  w.click({ act: 'expand' });
  assert.ok(w.game.log.some((l) => /relocate from your newest/.test(l.text)));
});

test('data hall scrolls with arrows, wheel, home/end and follows the newest racks', async () => {
  const w = await boot({ save: saved({ site_owned: [[300, 0, 0, 0, 0, 0, 0, 0, 0, 0]] }) });
  w.els.hallWrap.clientWidth = 700;
  w.els.hallWrap.clientHeight = 320;
  w.key('Home');
  assert.match(w.els.hallTitle.textContent, /300 racks · rows 1-\d+\/\d+ ↑↓/);
  const first = w.els.hallTitle.textContent;
  w.key('ArrowDown');
  assert.notEqual(w.els.hallTitle.textContent, first);
  w.key('PageDown');
  w.key('ArrowUp');
  w.key('End');
  const m = w.els.hallTitle.textContent.match(/rows (\d+)-(\d+)\/(\d+)/);
  assert.equal(m[2], m[3], 'End shows the last rows');
  const e = w.key('ArrowUp');
  assert.ok(e.defaultPrevented);
  assert.ok(w.els.hall.painted, 'canvas was painted');
  assert.ok(w.els.hall.painted.data.some((v) => v !== 0));
  w.key('s', { tagName: 'INPUT' }); // typing in a field never plays the game
  assert.equal(w.game.side, 'servers');
});

test('decommissioned hall is painted grey with its lights off', async () => {
  const w = await boot({ save: saved({
    sites: 1, cur: 1, site_balance: ['5', '5'],
    site_owned: [[5, 0, 0, 0, 0, 0, 0, 0, 0, 0], [5, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
  }) });
  w.els.hallWrap.clientWidth = 700;
  w.els.hallWrap.clientHeight = 320;
  w.key('x'); // refused, but forces a redraw at this size
  const live = Uint8ClampedArray.from(w.els.hall.painted.data);
  w.key('[');
  const dead = w.els.hall.painted.data;
  assert.notDeepEqual(Array.from(dead), Array.from(live));
  const chroma = (d, e) => { // colour of the pixels that differ between the two halls
    let sum = 0;
    for (let i = 0; i < d.length; i += 4) {
      if (d[i] === e[i] && d[i + 1] === e[i + 1] && d[i + 2] === e[i + 2]) continue;
      sum += Math.max(d[i], d[i + 1], d[i + 2]) - Math.min(d[i], d[i + 1], d[i + 2]);
    }
    return sum;
  };
  assert.ok(chroma(dead, live) < chroma(live, dead) * 0.6, 'washed-out hall has far less colour');
});

test('rename (n): validated with DC_NAME_RE, blank restores the default', async () => {
  const w = await boot({ save: saved() });
  w.key('n');
  assert.ok(w.dialogOpen());
  assert.match(w.els.dlgTitle.textContent, /Name data center #1/);
  assert.equal(w.els.dlgInput.maxLength, 24);
  w.type('Café');
  w.key('Enter', w.els.dlgInput);
  assert.ok(w.dialogOpen());
  assert.match(w.els.dlgError.textContent, /24 plain characters/);
  w.type('My Lab');
  w.key('Enter', w.els.dlgInput);
  assert.equal(w.dialogOpen(), false);
  assert.equal(w.game.siteLabel(0), 'My Lab');
  assert.match(w.stripped('stats'), /#1 My Lab/);
  w.key('n');
  w.type('');
  w.key('Enter', w.els.dlgInput);
  assert.equal(w.game.siteLabel(0), 'Garage in Palo Alto');
  w.key('n');
  w.key('Escape', w.els.dlgInput);
  assert.equal(w.dialogOpen(), false);
});

test('menu: m and Esc, autopilot, theme, rename; digits choose', async () => {
  const w = await boot({ save: saved() });
  w.key('Escape');
  assert.ok(w.dialogOpen());
  assert.equal(w.els.dlgTitle.textContent, 'Menu');
  const labels = () => w.els.dlgList.children.map((c) => c.textContent);
  assert.deepEqual(labels().slice(0, 2), ['Leaderboard: join', 'Change my leaderboard name']);
  assert.equal(w.els.dlgList.children[1].className.includes('off'), true);
  w.key('2'); // disabled while not joined
  assert.ok(w.dialogOpen());
  w.key('m');
  assert.equal(w.dialogOpen(), false);
  w.key('m');
  w.key('4'); // autopilot
  assert.equal(w.game.autopilot, true);
  w.key('m');
  assert.ok(labels().includes('Crew autopilot: ON (switch)'));
  w.key('5'); // theme submenu
  assert.equal(w.els.dlgTitle.textContent, 'Theme');
  w.key('2');
  assert.equal(w.game.theme, 'dracula');
  assert.equal(w.dialogOpen(), false);
  w.key('m');
  w.key('3');
  assert.match(w.els.dlgTitle.textContent, /Name data center/);
});

test('join flow: consent -> name -> submit + board; leave deletes; name taken re-asks', async () => {
  const seen = [];
  const fetchImpl = async (url, init) => {
    seen.push(`${init.method} ${url.replace('https://data-center.openexplorer.xyz', '')}`);
    if (url.endsWith('/api/submit')) return reply(200, { ok: true })();
    if (url.includes('/api/leaderboard')) {
      return reply(200, { total: 2, players: [
        { rank: 1, name: 'Ann', fame: '1500', sites: 3 },
        { rank: 2, name: '<img src=x>', fame: '10', sites: 0 },
        { rank: 3, name: 'Bob', fame: '5', sites: 0 },
      ] })();
    }
    if (url.endsWith('/api/me')) return reply(200, { registered: true, rank: 3, total: 2 })();
    return reply(200, {})();
  };
  const w = await boot({ fetchImpl });
  w.key('y'); // consent
  assert.ok(w.dialogOpen());
  assert.match(w.els.dlgTitle.textContent, /leaderboard name/);
  w.type('-bad');
  w.key('Enter', w.els.dlgInput);
  assert.match(w.els.dlgError.textContent, /1-20 letters/);
  assert.equal(w.calls.length, 0);
  w.type('Bob');
  w.key('Enter', w.els.dlgInput);
  await w.settle();
  const g = w.game;
  assert.equal(g.online.joined, true);
  assert.equal(g.online.name, 'Bob');
  assert.match(g.online.token, /^[0-9a-f]{32}$/);
  assert.equal(g.side, 'board');
  assert.ok(seen.includes('POST /api/submit'));
  assert.ok(seen.includes('GET /api/leaderboard?limit=30'));
  assert.ok(seen.includes('POST /api/me'));
  const submit = w.calls.find((c) => c.url.endsWith('/api/submit'));
  assert.deepEqual(JSON.parse(submit.init.body), { token: g.online.token, name: 'Bob', fame: '0', sites: 0 });
  assert.ok(submit.init.signal, 'AbortController signal');
  assert.equal(w.timers.some((t) => t.ms === 8000), true, '8 s timeout armed');
  assert.match(w.els.shop.innerHTML, /You: #3 of 2 &middot; Bob/);
  assert.match(w.els.shop.innerHTML, /Ann/);
  assert.doesNotMatch(w.els.shop.innerHTML, /<img/, 'server names that fail NAME_RE are dropped');
  assert.match(w.els.shop.innerHTML, /<tr class="mine">/);
  assert.equal(w.els.shopTitle.textContent, 'LEADERBOARD  [b]');

  // periodic: nothing changed -> no resubmit; a Fame change after 2 min is sent
  const submits = () => seen.filter((s) => s === 'POST /api/submit').length;
  await w.tick(130);
  assert.equal(submits(), 1);
  g.fame += 1n;
  await w.tick(125);
  assert.equal(submits(), 2);
  // board refreshes while open (every 30 ticks, min 5 s)
  const boards = () => seen.filter((s) => s.startsWith('GET /api/leaderboard')).length;
  const b0 = boards();
  await w.tick(31);
  assert.ok(boards() > b0);
  w.key('s'); // board closed: no more refreshes
  const b1 = boards();
  await w.tick(65);
  assert.equal(boards(), b1);

  // leave
  w.key('j');
  assert.match(w.els.dlgTitle.textContent, /Leave the leaderboard/);
  w.key('y');
  await w.settle();
  assert.equal(g.online.joined, false);
  assert.ok(seen.includes('POST /api/leave'));
  const leave = w.calls.find((c) => c.url.endsWith('/api/leave'));
  assert.deepEqual(JSON.parse(leave.init.body), { token: g.online.token });
  const n = w.calls.length;
  await w.tick(130);
  assert.equal(w.calls.length, n, 'a left player is never submitted');
});

test('409 on submit: tells you and asks for another name', async () => {
  const fetchImpl = async (url) => (url.endsWith('/api/submit') ? reply(409, {})() : reply(200, { players: [], total: 0 })());
  const w = await boot({ fetchImpl, save: saved() });
  w.key('j');
  w.type('Taken');
  w.key('Enter', w.els.dlgInput);
  await w.settle();
  assert.equal(w.game.online.joined, false);
  assert.ok(w.dialogOpen());
  assert.match(w.els.dlgError.textContent, /taken/);
});

test('network failure and 8 s timeout show an offline board and never throw', async () => {
  const fetchImpl = (url, init) => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new Error('aborted')));
  });
  const w = await boot({ fetchImpl, save: saved() });
  w.key('b');
  await w.settle();
  const t = w.timers.find((x) => x.ms === 8000 && x.live);
  assert.ok(t, 'timeout armed');
  t.fn(); // the 8 s are up
  await w.settle();
  assert.match(w.els.shop.innerHTML, /Could not reach the server/);
});

test('an injected DC_HOST.api is adapted and may not reject', async () => {
  const seen = [];
  const host = { api: async (m, p) => { seen.push(`${m} ${p}`); if (p.includes('leaderboard')) throw new Error('boom'); return [200, {}]; } };
  const w = await boot({ host, save: saved() });
  w.key('b');
  await w.settle();
  assert.deepEqual(seen, ['GET /api/leaderboard?limit=30']);
  assert.equal(w.calls.length, 0, 'host api replaces fetch');
  assert.match(w.els.shop.innerHTML, /Could not reach/);
});

test('DC_HOST.online === false: no consent, no board card, no fetch at all', async () => {
  const w = await boot({ host: { online: false } });
  assert.equal(w.dialogOpen(), false);
  assert.equal(w.els.tabBoard.hidden, true);
  assert.doesNotMatch(w.els.hint.textContent, /\bb\b.*cards|j board/);
  w.key('b');
  assert.equal(w.game.side, 'servers');
  w.key('j');
  assert.equal(w.dialogOpen(), false);
  w.key('m');
  const labels = w.els.dlgList.children.map((c) => c.textContent);
  assert.equal(labels.some((l) => /eaderboard/.test(l)), false);
  assert.ok(labels.some((l) => /autopilot/.test(l)));
  w.key('Escape');
  w.game.online.joined = true; // even a save that says joined must not fetch
  w.game.online.name = 'Zed';
  w.game.online.token = TOKEN;
  w.game.fame = 5n;
  await w.tick(300);
  assert.equal(w.calls.length, 0);
});

test('welcome back: an offline gap is credited and logged', async () => {
  const save = saved({ site_owned: [[10, 0, 0, 0, 0, 0, 0, 0, 0, 0]], saved_at: T0 / 1000 - 3600 });
  const w = await boot({ save });
  const text = w.els.log.children.map((c) => c.textContent).join('\n');
  assert.match(text, /Welcome back! Away 1h 0m, earned \$/);
  assert.match(text, /75% offline rate/);
  assert.ok(w.game.away.earned > 0n);
});

test('status callback reports the live data center, saves are throttled, destroy stops', async () => {
  const statuses = [];
  const w = await boot({ save: saved(), host: { onStatus: (s) => statuses.push(s) } });
  await w.tick(2);
  const last = statuses[statuses.length - 1];
  assert.match(last.site, /^#1 /);
  assert.equal(last.crisis, false);
  assert.match(last.balance, /^\$/);
  w.ctx.DCUI.destroy();
  const n = w.saves.length;
  w.key('1');
  await w.tick(5);
  assert.equal(w.game.owned[0], 0);
  assert.ok(w.saves.length >= n);
});

test('crisis banner and fix', async () => {
  const w = await boot({ save: saved() });
  w.game.crisis = { title: 'Janitor unplugged a rack to vacuum', sev: 1, fixer: null, eta: null };
  w.key('f');
  assert.equal(w.game.crisis, null);
  assert.equal(w.els.alert.hidden, true);
});
