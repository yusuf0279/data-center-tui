/* My Data Center - UI. Classic script; needs core.js (window.DCCore) first.
 * No inline scripts or handlers (strict CSP in VS Code). Host contract (all optional):
 *   window.DC_HOST = { storage: {load, save}, theme, onStatus, online, api }
 *   online === false  -> no leaderboard at all: no consent dialog, no board card, no fetch.
 *   api(method, path, body) -> Promise<[status, body]>  replaces the built-in fetch client. */
(function () {
  'use strict';
  const C = window.DCCore;
  const { TIERS, STAFF, fmt } = C;
  const host = window.DC_HOST || null;
  const SAVE_KEY = 'dc-tui-save';
  const SERVER = 'https://data-center.openexplorer.xyz';
  const NET_TIMEOUT_MS = 8000;
  const MAX_REPLY_CHARS = 1 << 16;
  const THEMES = ['gruvbox', 'dracula', 'nord', 'tokyo-night', 'solarized-dark',
    'solarized-light', 'catppuccin-mocha', 'vscode'];
  // Same fixed hues as data_center_tui/game.py: a tier looks the same in every theme.
  const TIER_HUES = [340, 140, 300, 95, 262, 32, 175, 55, 215, 8];
  const TIER_SATURATION = 0.72;
  const CREW_INITIALS = C.CREW_INITIALS;
  const VIEW_KEYS = { s: 'servers', c: 'chips', h: 'staff', d: 'sites', b: 'board' };
  const SAVE_EVERY_MS = 1000;
  const OFFLINE_GAP_MS = 10000;
  const SUBMIT_TICKS = 5;
  const BOARD_TICKS = 30;
  const ROW_PX = 46; // a two-line shop row, used to decide how many rows fit
  const SCROLLBAR_PX = 2;
  const FALLBACK_HALL = { w: 210, h: 96 }; // logical pixels when the hall has no layout yet
  const SIDE_TITLES = { servers: 'MARKETPLACE', chips: 'CHIP UPGRADES', staff: 'CREW',
    sites: 'DATA CENTERS', board: 'LEADERBOARD' };
  const SIDE_KEYS = { servers: 's', chips: 'c', staff: 'h', sites: 'd', board: 'b' };
  const ONLINE = !(host && host.online === false);

  const ui = window.DCUI = { game: null, destroy: () => {} };
  const $ = (id) => document.getElementById(id);
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);

  // ------------------------------------------------------------------ colours

  const lum = (c) => (0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]) / 255;
  const mix = (a, b, t) => a.map((v, i) => Math.trunc(v + (b[i] - v) * t));
  const css = (c) => 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')';
  const FALLBACK_DARK = {
    bg: [26, 27, 38], surface: [36, 40, 59], fg: [192, 202, 245], primary: [122, 162, 247],
    success: [158, 206, 106], warning: [224, 175, 104], error: [247, 118, 142],
  };
  const FALLBACK_LIGHT = {
    bg: [233, 233, 237], surface: [222, 222, 228], fg: [52, 59, 88], primary: [52, 84, 138],
    success: [72, 94, 48], warning: [143, 94, 21], error: [140, 67, 81],
  };

  /** colorsys.hls_to_rgb: h, l, s in 0..1 -> [r, g, b] in 0..1. */
  function hlsToRgb(h, l, s) {
    if (s === 0) return [l, l, l];
    const m2 = l <= 0.5 ? l * (1 + s) : l + s - l * s;
    const m1 = 2 * l - m2;
    const v = (hue) => {
      hue = ((hue % 1) + 1) % 1;
      if (hue < 1 / 6) return m1 + (m2 - m1) * hue * 6;
      if (hue < 0.5) return m2;
      if (hue < 2 / 3) return m1 + (m2 - m1) * (2 / 3 - hue) * 6;
      return m1;
    };
    return [v(h + 1 / 3), v(h), v(h - 1 / 3)];
  }

  /** Resolve any CSS colour string to [r,g,b] via the browser; null if unusable. */
  function parseColor(probe, value) {
    probe.style.color = '';
    probe.style.color = value;
    if (!value || !probe.style.color) return null;
    const s = getComputedStyle(probe).color || '';
    const m = s.match(/[\d.]+|\//g);
    if (!m) return null;
    const isSrgb = s.startsWith('color(');
    const nums = m.filter((x) => x !== '/').map((x) => parseFloat(x));
    if (nums.length < 3) return null;
    const alpha = nums.length > 3 ? nums[3] : 1;
    if (alpha < 1) return null;
    const rgb = nums.slice(0, 3).map((x) => Math.round(isSrgb ? x * 255 : x));
    return rgb.every((x) => x >= 0 && x <= 255) ? rgb : null;
  }

  /** Same derivation as game.py's Palette, from the --dc-* custom properties. */
  function readPalette() {
    const probe = document.createElement('span');
    probe.style.display = 'none';
    document.body.appendChild(probe);
    const cs = getComputedStyle(document.documentElement);
    const raw = (name) => parseColor(probe, cs.getPropertyValue('--dc-' + name).trim());
    const bg0 = raw('bg');
    const fallback = lum(bg0 || FALLBACK_DARK.bg) < 0.5 ? FALLBACK_DARK : FALLBACK_LIGHT;
    const get = (name) => raw(name) || fallback[name];
    const p = { bg: get('bg'), surface: get('surface'), fg: get('fg') };
    const base = { primary: get('primary'), success: get('success'), warning: get('warning'),
      error: get('error') };
    probe.remove();
    const visible = (c) => { // keep accents readable on any theme
      for (let i = 0; i < 6; i++) {
        if (Math.abs(lum(c) - lum(p.surface)) >= 0.3) break;
        c = mix(c, p.fg, 0.25);
      }
      return c;
    };
    Object.keys(base).forEach((k) => { p[k] = visible(base[k]); });
    const light = lum(p.surface) < 0.5 ? 0.62 : 0.38; // only lightness follows the theme
    p.tiers = TIER_HUES.map((h) => visible(
      hlsToRgb(h / 360, light, TIER_SATURATION).map((x) => Math.trunc(x * 255))));
    p.muted = mix(p.fg, p.surface, 0.45);
    p.faint = mix(p.fg, p.surface, 0.75);
    p.frame = mix(p.surface, p.fg, 0.2);
    p.shadow = mix(p.bg, [0, 0, 0], 0.5);
    p.ledOn = p.success;
    p.ledOff = mix(p.success, p.bg, 0.8);
    p.alertOn = p.error;
    p.alertOff = mix(p.error, p.bg, 0.8);
    p.key = JSON.stringify(p);
    return p;
  }

  // -------------------------------------------------------------------- state

  let game = null;
  let pal = null;
  let timer = null;
  let lastTick = Date.now();
  let lastSave = 0;
  let dirty = false;
  let destroyed = false;
  let observers = [];
  const cache = {}; // last rendered string per element id
  let logSeen = 0;
  let hallSig = '';
  let hallScroll = null; // first visible rack row, null = follow the newest racks
  let shopTop = null; // first visible row of a scrolled shop card, null = automatic
  let shopNote = '';
  let dlg = null; // the open dialog, if any
  const net = C.newOnlineState();

  const localStore = {
    load() {
      try { return Promise.resolve(window.localStorage.getItem(SAVE_KEY)); } catch (e) { return Promise.resolve(null); }
    },
    save(text) {
      try { window.localStorage.setItem(SAVE_KEY, text); } catch (e) { /* storage blocked */ }
    },
  };
  const store = host && host.storage ? host.storage : localStore;
  const forcedTheme = host && typeof host.theme === 'string' && host.theme ? host.theme : null;

  function save(force) {
    if (!game || !dirty) return;
    const now = Date.now();
    if (!force && now - lastSave < SAVE_EVERY_MS) return;
    lastSave = now;
    dirty = false;
    try {
      const r = store.save(JSON.stringify(game));
      if (r && typeof r.catch === 'function') r.catch(() => {});
    } catch (e) { /* never throw into the host */ }
  }

  function status() {
    if (!host || typeof host.onStatus !== 'function') return;
    try {
      const k = game.sites; // the live data center, wherever you are looking
      const [num, den] = game.crisis ? C.CRISIS_FACTOR[game.crisis.sev] : [1, 1];
      host.onStatus({
        balance: '$' + fmt(game.siteBalance[k]),
        income: '$' + fmt(game.siteIncome(k) * BigInt(num) / BigInt(den)) + '/s',
        site: '#' + (k + 1) + ' ' + game.siteLabel(k),
        crisis: game.crisis !== null,
      });
    } catch (e) { /* host problems stay in the host */ }
  }

  // ---------------------------------------------------------------------- net

  /** Built-in client: fetch with an 8 s timeout. Always resolves to [status, body]. */
  async function fetchApi(method, path, body) {
    const ctl = typeof AbortController === 'function' ? new AbortController() : null;
    const timeout = setTimeout(() => { if (ctl) ctl.abort(); }, NET_TIMEOUT_MS);
    try {
      const init = { method, cache: 'no-store', credentials: 'omit' };
      if (ctl) init.signal = ctl.signal;
      if (body !== undefined) {
        init.headers = { 'Content-Type': 'application/json' };
        init.body = JSON.stringify(body);
      }
      const res = await window.fetch(SERVER + path, init);
      let parsed = {};
      try {
        const text = await res.text();
        const data = text.length <= MAX_REPLY_CHARS ? JSON.parse(text) : null;
        if (data !== null && typeof data === 'object' && !Array.isArray(data)) parsed = data;
      } catch (e) { /* not JSON: keep {} */ }
      return [Number(res.status) || 0, parsed];
    } catch (e) {
      return [0, {}];
    } finally {
      clearTimeout(timeout);
    }
  }

  /** The api the game uses: the host's if given, wrapped so it never rejects or misshapes. */
  function makeApi() {
    if (!(host && typeof host.api === 'function')) return fetchApi;
    return async (method, path, body) => {
      try {
        const res = await host.api(method, path, body);
        return Array.isArray(res) && typeof res[0] === 'number' ? [res[0], res[1] || {}] : [0, {}];
      } catch (e) {
        return [0, {}];
      }
    };
  }
  let api = makeApi();

  const visibleNow = () => typeof document === 'undefined' || document.visibilityState !== 'hidden';

  function submit(force) {
    if (!ONLINE || destroyed) return;
    C.maybeSubmit(game, api, net, game.now(), force).then((r) => {
      if (destroyed || !r) return;
      if (r.kind === 'ok' && game.side === 'board') pullBoard(true);
      else if (r.kind === 'taken') askName(game.online.name, 'That name is taken, pick another', onNameChosen);
      dirty = true;
      render();
      save(false);
    }).catch(() => {});
  }

  function pullBoard(force) {
    if (!ONLINE || destroyed) return;
    C.refreshBoard(game, api, net, game.now(), force).then(() => { if (!destroyed) render(); })
      .catch(() => {});
  }

  // ------------------------------------------------------------------ dialogs

  function showDlg(spec) {
    dlg = spec;
    $('dlgTitle').textContent = spec.title;
    $('dlgBody').textContent = spec.body || '';
    $('dlgError').textContent = spec.error || '';
    const input = $('dlgInput');
    input.hidden = !spec.input;
    if (spec.input) {
      input.value = spec.input.value || '';
      input.maxLength = spec.input.max;
      input.placeholder = spec.input.placeholder;
    }
    const list = $('dlgList');
    list.textContent = '';
    spec.items.forEach((it, i) => {
      const b = document.createElement('button');
      b.className = 'dlg-item' + (it.enabled === false ? ' off' : '');
      b.dataset.dlg = String(i);
      b.textContent = it.label;
      list.appendChild(b);
    });
    $('dlgKeys').textContent = spec.keys;
    $('dlg').hidden = false;
    if (spec.input) { try { input.focus(); } catch (e) { /* no focus in this host */ } }
  }

  /** Close the open dialog and hand its answer to the callback (which may open another). */
  function closeDlg(value) {
    const d = dlg;
    if (!d) return;
    dlg = null;
    $('dlg').hidden = true;
    d.done(value);
    dirty = true;
    render();
    save(false);
  }

  function askYesNo(title, body, done) {
    showDlg({ kind: 'yesno', title, body, keys: '[y] yes    [n] no    [esc] no', done,
      items: [{ label: 'Yes (y)', value: true }, { label: 'No (n)', value: false }] });
  }

  function askMenu(title, items, done) {
    showDlg({ kind: 'menu', title, items, done, keys: '[1-9] choose    [esc] close' });
  }

  /** opts: {value, error, title, rule, max, placeholder, complaint, keys}. done(name|null). */
  function askName(value, error, done, opts = {}) {
    showDlg({
      kind: 'name', title: opts.title || 'Pick a leaderboard name', error,
      input: { value, max: opts.max || 20, placeholder: opts.placeholder || '1-20 letters, digits, space _ . -' },
      rule: opts.rule || C.NAME_RE,
      complaint: opts.complaint || 'Use 1-20 letters, digits, spaces, _ . - (start with a letter or digit)',
      keys: opts.keys || '[enter] join    [esc] cancel', done,
      items: [{ label: 'OK', value: 'ok' }, { label: 'Cancel', value: null }],
    });
  }

  function submitName() {
    const v = $('dlgInput').value.trim();
    if (dlg.rule.test(v)) closeDlg(v);
    else $('dlgError').textContent = dlg.complaint;
  }

  /** Pick item i of the open dialog (a click or a number key). */
  function chooseItem(i) {
    if (!dlg || !(i >= 0 && i < dlg.items.length) || dlg.items[i].enabled === false) return;
    if (dlg.kind === 'name') {
      if (dlg.items[i].value === 'ok') submitName();
      else closeDlg(null);
    } else closeDlg(dlg.items[i].value);
  }

  function dialogKey(e) {
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (k === 'Escape') { closeDlg(dlg.kind === 'yesno' ? false : null); e.preventDefault(); return; }
    if (dlg.kind === 'name') {
      if (k === 'Enter') { submitName(); e.preventDefault(); }
    } else if (dlg.kind === 'yesno') {
      if (k === 'y' || k === 'n') { chooseItem(k === 'y' ? 0 : 1); e.preventDefault(); }
    } else if (k === 'm') {
      closeDlg(null);
      e.preventDefault();
    } else if (/^[1-9]$/.test(k)) {
      chooseItem(Number(k) - 1);
      e.preventDefault();
    }
  }

  // ------------------------------------------------------------- menu & flows

  function openMenu() {
    const joined = game.online.joined;
    const items = [];
    if (ONLINE) {
      items.push({ label: 'Leaderboard: ' + (joined ? 'leave it' : 'join'), value: 'board' });
      items.push({ label: 'Change my leaderboard name', value: 'boardname', enabled: joined });
    }
    items.push({ label: 'Rename data center #' + (game.cur + 1), value: 'rename' });
    items.push({ label: 'Crew autopilot: ' + (game.autopilot ? 'ON' : 'OFF') + ' (switch)', value: 'auto' });
    items.push({ label: 'Change theme', value: 'theme', enabled: forcedTheme === null });
    askMenu('Menu', items, onMenu);
  }

  function onMenu(choice) {
    if (choice === 'board') toggleBoard();
    else if (choice === 'boardname') askName(game.online.name, '', onNameChosen);
    else if (choice === 'rename') openRename();
    else if (choice === 'auto') game.toggleAutopilot();
    else if (choice === 'theme') {
      askMenu('Theme', THEMES.map((t) => ({ label: t + (t === game.theme ? '  (current)' : ''), value: t })),
        (t) => { if (t) setTheme(t); });
    }
  }

  function setTheme(name) {
    game.theme = name;
    applyTheme();
    dirty = true;
    save(true);
  }

  function openRename() {
    const k = game.cur;
    askName(game.siteNames[k], '', (name) => {
      if (name !== null) game.renameSite(k, name);
    }, { title: 'Name data center #' + (k + 1), rule: C.DC_NAME_RE, max: 24,
      placeholder: 'blank = ' + C.siteName(k), complaint: 'Use up to 24 plain characters',
      keys: '[enter] save    [esc] cancel' });
  }

  function askToJoin() {
    askYesNo('Join the online leaderboard?',
      'Compete with other players. If you join, your chosen name, your Fame and your number of ' +
      'data centers are sent to ' + SERVER.split('//')[1] + ' and shown on a public board.\n' +
      'Nothing else is sent. You can leave at any time (press j).', onJoinAnswer);
  }

  function onJoinAnswer(yes) {
    game.online.asked = true;
    if (yes) askName(game.online.name, '', onNameChosen);
    else game.say('Leaderboard off. Press j to join any time.', 'muted');
  }

  function onNameChosen(name) {
    game.online.asked = true;
    if (!name) {
      game.say('Not joined. Press j to join any time.', 'muted');
      return;
    }
    game.online.name = name;
    if (!game.online.token) game.online.token = C.makeToken();
    game.online.joined = true;
    net.lastSent = null;
    game.side = 'board';
    game.say('Joining the leaderboard as ' + name + '...', 'success');
    submit(true);
    pullBoard(true);
  }

  /** j: join the leaderboard, or leave it when already on it. */
  function toggleBoard() {
    if (!ONLINE) return;
    if (!game.online.joined) {
      askName(game.online.name, '', onNameChosen);
      return;
    }
    askYesNo('Leave the leaderboard?',
      'Your entry is deleted from the server. You can join again later.', (yes) => {
        if (!yes) return;
        const token = game.online.token;
        game.online.joined = false;
        net.board = null;
        game.say('Left the leaderboard.', 'muted');
        api('POST', '/api/leave', { token }).catch(() => {});
      });
  }

  // ------------------------------------------------------------------- render

  function setHTML(id, html) {
    if (cache[id] === html) return;
    cache[id] = html;
    $(id).innerHTML = html;
  }

  function setText(id, text) {
    if (cache[id] === text) return;
    cache[id] = text;
    $(id).textContent = text;
  }

  function applyPalette() {
    pal = readPalette();
    const s = $('app').style;
    const names = ['bg', 'surface', 'fg', 'primary', 'success', 'warning', 'error', 'muted', 'faint', 'frame'];
    names.forEach((n) => s.setProperty('--c-' + n, css(pal[n])));
    pal.tiers.forEach((c, i) => s.setProperty('--c-tier' + i, css(c)));
    hallSig = '';
    render();
  }

  function applyTheme() {
    const wanted = forcedTheme || game.theme;
    const name = THEMES.includes(wanted) ? wanted : C.DEFAULT_THEME;
    if (!forcedTheme) game.theme = name;
    document.documentElement.setAttribute('data-theme', name);
    $('theme').value = name;
    applyPalette();
  }

  /** One shop row: hotkey chip (the 10th key is 0), name, badge, then a second line. */
  function rowHTML(i, name, badge, badgeCls, ok, sub, accent, tip) {
    return '<button class="row ' + (ok ? 'ok ' : 'no ') + accent + '" data-i="' + i + '"' +
      (tip ? ' title="' + esc(tip) + '"' : '') +
      '><span class="key">' + ((i + 1) % 10) + '</span><span class="nm">' + esc(name) + '</span>' +
      '<span class="badge ' + badgeCls + '">' + esc(badge) + '</span><span class="sub">' + sub + '</span></button>';
  }

  const costHTML = (cost, ok) => '<span class="cost ' + (ok ? 'ok' : 'no') + '">$' + fmt(cost) + '</span>';

  /** [first row, count] of a two-line-per-row card that fits the card; shows the frontier. */
  function windowOf(count, frontier) {
    const shop = $('shop');
    const rowEl = shop.querySelector ? shop.querySelector('.row') : null;
    const rowPx = rowEl && rowEl.offsetHeight > 0 ? rowEl.offsetHeight : ROW_PX;
    const height = shop.clientHeight > 0 ? shop.clientHeight : rowPx * count;
    const n = Math.max(1, Math.min(count, Math.floor(height / rowPx)));
    let top = Math.max(0, Math.min(count - n, frontier + 3 - n));
    if (shopTop !== null) top = Math.max(0, Math.min(count - n, shopTop));
    shopNote = n < count ? ' · ' + (top + 1) + '-' + (top + n) + '/' + count : '';
    return [top, n];
  }

  const frontierOf = (counts) => counts.reduce((a, n, i) => (n > 0 ? i : a), 0);

  const rowsOf = (top, n, fn) => Array.from({ length: n }, (_, j) => fn(top + j)).join('');

  function serversHTML() {
    const [top, n] = windowOf(TIERS.length, frontierOf(game.owned));
    return rowsOf(top, n, (i) => {
      const cost = C.costOf(i, game.owned[i], game.cur);
      const ok = game.balance >= cost && !game.readOnly;
      const each = C.tierIncome(i, 1, game.chips[i], game.cur);
      const ms = C.nextMilestone(game.owned[i]);
      return rowHTML(i, TIERS[i][0], 'x' + game.owned[i], game.owned[i] ? '' : 'faint', ok,
        costHTML(cost, ok) + ' &middot; +$' + fmt(each) + '/s' +
        (ms ? ' <span class="ms">&middot; x2@' + ms + '</span>' : ''), 't' + i);
    });
  }

  function chipsHTML() {
    const [top, n] = windowOf(TIERS.length, frontierOf(game.owned));
    return rowsOf(top, n, (i) => {
      const tier = TIERS[i][0];
      const level = game.chips[i];
      const maxed = level >= C.MAX_CHIP;
      const cost = maxed ? 0n : C.chipCost(i, level, game.cur);
      const ok = !maxed && game.owned[i] > 0 && game.balance >= cost && !game.readOnly;
      let sub;
      if (maxed) sub = '<span class="good">' + esc(tier) + ' income x' + (C.CHIP_BOOST ** BigInt(C.MAX_CHIP)).toLocaleString('en-US') + '</span>';
      else if (game.owned[i] === 0) sub = '<span class="faint">buy a ' + esc(tier) + ' first</span>';
      else sub = costHTML(cost, ok) + ' &middot; ' + esc(tier) + ' x' + C.CHIP_BOOST;
      return rowHTML(i, C.chipName(i, Math.min(level, C.MAX_CHIP - 1)), maxed ? 'MAX' : 'L' + level,
        maxed ? 'good' : level ? '' : 'faint', ok, sub, 't' + i);
    });
  }

  /** Tooltip listing every crew perk and whether this level has unlocked it. */
  function perkTip(level) {
    return C.PERKS.map(([lv, text]) => 'Lv' + lv + ': ' + text + (level >= lv ? ' (unlocked)' : '')).join('\n');
  }

  function staffSub(r, level, cost, ok) {
    const [, , , cap] = STAFF[r];
    if (level >= C.MAX_STAFF) return '<span class="good">all perks &middot; fixes in ' + C.responseSecs(r, level) + 's</span>';
    if (level < 0) return costHTML(cost, ok) + ' &middot; fixes ' + C.STAFF_SCOPE[cap - 1];
    const next = C.PERKS.find(([lv]) => lv > level); // what the next level of training unlocks
    return costHTML(cost, ok) + ' &middot; ' +
      (next ? 'Lv' + next[0] + ': ' + esc(next[1]) : 'fixes in ' + C.responseSecs(r, level + 1) + 's');
  }

  function staffHTML() {
    const [top, n] = windowOf(STAFF.length, frontierOf(game.staff.map((l) => l + 1)));
    return rowsOf(top, n, (r) => {
      const level = game.staff[r];
      const maxed = level >= C.MAX_STAFF;
      const cost = maxed ? 0n : C.staffCost(r, level, game.cur);
      const ok = !maxed && game.balance >= cost && !game.readOnly;
      return rowHTML(r, STAFF[r][0], level < 0 ? 'hire' : maxed ? 'MAX' : 'Lv' + level,
        level >= 0 ? '' : 'faint', ok, staffSub(r, level, cost, ok), 'crew', perkTip(level));
    });
  }

  function siteRowHTML(k, row) {
    const here = k === game.cur;
    const name = '#' + (k + 1) + ' ' + game.siteLabel(k);
    return '<button class="row site' + (here ? ' here' : '') + (k === game.sites ? ' live' : '') +
      '" data-i="' + row + '"><span class="key">' + (row + 1) + '</span><span class="nm">' +
      '<span class="here-mark">' + (here ? '&#9654;' : '') + '</span>' +
      '<span class="live-mark">' + (k === game.sites ? '&#9679;' : '') + '</span>' + esc(name) +
      '</span><span class="badge">$' + fmt(game.siteIncome(k)) + '/s</span></button>';
  }

  function sitesHTML() {
    const newest = game.sites;
    const first = Math.floor(game.cur / 6) * 6; // six per page; the page follows the one you are in
    let html = '';
    for (let k = first, row = 0; k <= Math.min(first + 5, newest); k++, row++) html += siteRowHTML(k, row);
    if (newest > 5) {
      html += '<div class="more">#' + (first + 1) + '-' + Math.min(first + 6, newest + 1) + ' of ' +
        (newest + 1) + ' &middot; [ ] to move</div>';
    }
    return html + '<div class="more">&#9679; live &middot; the others are decommissioned</div>' + nextSiteHTML();
  }

  function nextSiteHTML() {
    const newest = game.sites;
    if (newest >= C.MAX_SITES) return '<div class="next good">You own the multiverse.</div>';
    const cost = C.expandCost(newest);
    const bal = game.siteBalance[newest];
    const pctBig = bal * 100n / cost;
    const pct = Number(pctBig > 100n ? 100n : pctBig);
    const ready = bal >= cost;
    const filled = Math.floor(pct * 12 / 100);
    const hint = !ready ? '' : game.cur === newest
      ? '  <span class="go">x: relocate +' + fmt(C.fameGain(bal, newest)) + ' Fame</span>'
      : '  <span class="go">] to go there, then x</span>';
    return '<button class="expand" data-act="expand"><div><b>Next: ' + esc(C.siteName(newest + 1)) + '</b></div>' +
      '<div class="need' + (ready ? ' ready' : '') + '">$' + fmt(cost) + ' in #' + (newest + 1) + ' &middot; ' + pct + '%</div>' +
      '<div class="bar"><span class="' + (ready ? 'ready' : 'on') + '">' + '█'.repeat(filled) + '</span>' +
      '<span class="off">' + '░'.repeat(12 - filled) + '</span>' + hint + '</div></button>';
  }

  function boardHeadHTML(board) {
    if (!game.online.joined) {
      return '<div>You are not on the board.</div><div class="muted">Press j to join (asks for a name).</div>';
    }
    const me = board && board.me;
    if (me && me.registered && Number.isInteger(me.rank) && Number.isInteger(me.total)) {
      return '<div class="mine">You: #' + me.rank + ' of ' + me.total + ' &middot; ' + esc(game.online.name) + '</div>';
    }
    return '<div class="mine">You: ' + esc(game.online.name) + ' (sending...)</div>';
  }

  function boardBodyHTML(board) {
    if (board === null) return '<div class="muted">Loading...</div>';
    const rows = C.boardRows(board, game);
    if (!rows.length) {
      return board.error ? '<div class="bad">Could not reach the server.</div>'
        : '<div class="muted">Nobody has joined yet. Be the first!</div>';
    }
    return '<table class="board">' + rows.map((r) => '<tr class="' + (r.mine ? 'mine' : '') + '"><td>' +
      (r.mine ? '&#9654;' : '') + '</td><td class="r">' + r.rank + '</td><td>' + esc(r.name) +
      '</td><td class="r">' + esc(r.fame) + '</td><td>#' + r.sites + '</td></tr>').join('') + '</table>';
  }

  function boardHTML() {
    if (!ONLINE) return '<div class="muted">Online features are off.</div>';
    const board = net.board;
    let html = boardHeadHTML(board) + boardBodyHTML(board);
    if (board && board.at) {
      const age = Math.max(0, Math.floor(game.now() - board.at));
      html += '<div class="more">updated ' + age + 's ago' + (board.error ? ' &middot; offline' : '') +
        ' &middot; j: ' + (game.online.joined ? 'leave' : 'join') + '</div>';
    }
    return html;
  }

  function statsHTML() {
    const crisis = game.crisis !== null;
    const dead = game.readOnly;
    const fleet = game.owned.map((n, i) => '<span class="' + (n ? 't' + i + ' fl' : 'faint') + '">■</span>').join('');
    const crew = game.staff.map((l, r) => '<span class="' + (l >= 0 ? 'lit' : 'off') + '">' + CREW_INITIALS[r] + '</span>').join('');
    const [rank, need] = C.rankOf(game.fame);
    const income = dead
      ? '<span class="lbl">Final</span><span><b class="final">$' + fmt(game.siteIncome(game.cur)) + '/s</b>  <span class="muted">decommissioned</span></span>'
      : '<span class="lbl">Income</span><span><b class="inc' + (crisis ? ' crisis' : '') + '">$' + fmt(game.income) +
        '/s</b>' + (crisis ? '<span class="crisis">  (crisis)</span>' : '') + '</span>';
    return '<span class="lbl">Site</span><span><b class="site">#' + (game.cur + 1) + ' ' + esc(game.siteLabel(game.cur)) + '</b></span>' +
      income +
      '<span class="lbl">Racks</span><span><b class="racks">' + game.racks + '</b>  <span class="lbl">Fame</span> <b class="fame">' +
      fmt(game.fame) + '</b> <span class="muted">(+' + fmt(game.fameBonus) + '%)</span></span>' +
      '<span class="lbl">Fleet</span><span>' + fleet + '</span><span class="lbl">Crew</span><span>' + crew + '</span>' +
      '<span class="lbl">Status</span><span><b class="rank">' + esc(rank) + '</b> <span class="muted">(' +
      fmt(game.fame) + '/' + fmt(need) + ')</span></span>';
  }

  function renderAlert() {
    const c = game.crisis;
    const el = $('alert');
    el.hidden = c === null;
    if (c === null) return;
    const [num, den] = C.CRISIS_FACTOR[c.sev];
    const who = c.fixer !== null ? STAFF[c.fixer][0] + ' responding (' + c.eta + 's)' : 'press F to fix';
    setText('alert', '⚠ ' + c.title + '  ·  income -' + (100 - Math.floor(num * 100 / den)) + '%  ·  ' + who);
  }

  function renderLog() {
    const el = $('log');
    game.log.forEach((e) => {
      if (e.id <= logSeen) return;
      logSeen = e.id;
      const d = document.createElement('div');
      d.className = 'k-' + e.kind;
      d.textContent = e.text;
      el.appendChild(d);
    });
    while (el.childElementCount > game.log.length) el.removeChild(el.firstChild);
    el.scrollTop = el.scrollHeight;
  }

  function shopTitle() {
    const side = game.side;
    const ro = game.readOnly ? ' · view only' : '';
    let t = SIDE_TITLES[side] + ro + shopNote;
    if (side === 'staff' && !game.readOnly) {
      t = 'CREW +' + game.staffBonus + '% · auto ' + (game.autopilot ? 'ON' : 'OFF') + shopNote;
    } else if (side === 'sites' || side === 'board') t = SIDE_TITLES[side];
    return t + '  [' + SIDE_KEYS[side] + ']';
  }

  function render() {
    if (!game || !pal) return;
    if (!ONLINE && game.side === 'board') game.side = 'servers';
    const side = game.side;
    shopNote = '';
    const bodies = { servers: serversHTML, chips: chipsHTML, staff: staffHTML, sites: sitesHTML, board: boardHTML };
    setHTML('shop', bodies[side]());
    setText('shopTitle', shopTitle());
    setHTML('cash', '<span class="dim">$ </span>' + fmt(game.balance));
    setText('title', '◆ MY DATA CENTER  ·  ' + C.rankOf(game.fame)[0]);
    setHTML('stats', statsHTML());
    document.querySelectorAll('.tab').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.view === side)));
    $('app').classList.toggle('dead', game.readOnly);
    renderBanner();
    renderAlert();
    renderLog();
    drawHall();
  }

  function renderBanner() {
    const b = $('banner');
    b.hidden = !game.readOnly;
    if (game.readOnly) {
      setText('banner', 'DECOMMISSIONED · view only · lights off, nothing earns here. Your live data center is #' +
        (game.sites + 1) + ' (press ] to go back).');
    }
  }

  // --------------------------------------------------------------------- hall

  function hallGeom() {
    const wrap = $('hallWrap');
    const dpr = window.devicePixelRatio || 1;
    const devW = Math.floor(wrap.clientWidth * dpr);
    const devH = Math.floor(wrap.clientHeight * dpr);
    if (devW < 8 || devH < 8) return { ok: false, scale: 1, dpr, w: FALLBACK_HALL.w, h: FALLBACK_HALL.h };
    const scale = Math.min(Math.max(Math.floor(devW / (C.CELL_W * 10)), Math.ceil(2 * dpr)), Math.ceil(5 * dpr));
    return { ok: true, scale, dpr, w: Math.floor(devW / scale), h: Math.floor(devH / scale) };
  }

  /** Columns, visible rows, total rows and first visible row of the rack grid. */
  function hallLayout(g) {
    const racks = game.racks;
    const viewRows = Math.max(1, Math.floor(g.h / C.CELL_H));
    let cols = Math.max(1, Math.floor(g.w / C.CELL_W));
    let total = Math.ceil(racks / cols);
    if (total > viewRows) { // a scrollbar needs room of its own
      cols = Math.max(1, Math.floor((g.w - SCROLLBAR_PX) / C.CELL_W));
      total = Math.ceil(racks / cols);
    }
    const maxStart = Math.max(0, total - viewRows);
    const start = hallScroll === null ? maxStart : Math.min(hallScroll, maxStart);
    return { cols, viewRows, total, start, racks };
  }

  function hallTitle(lay) {
    let t = '#' + (game.cur + 1) + ' ' + game.siteLabel(game.cur) + ' · ' + game.racks.toLocaleString('en-US') + ' racks';
    if (game.readOnly) t += ' · DECOMMISSIONED';
    if (lay.total > lay.viewRows) {
      t += ' · rows ' + (lay.start + 1) + '-' + (lay.start + lay.viewRows) + '/' + lay.total + ' ↑↓';
    }
    return t;
  }

  /** Draw the racks to the canvas, but only when something visible changed. */
  function drawHall() {
    const g = hallGeom();
    const lay = hallLayout(g);
    setText('hallTitle', hallTitle(lay));
    $('hallEmpty').hidden = game.racks > 0;
    if (!g.ok) return;
    const sig = [g.w, g.h, g.scale, game.cur, game.owned.join(','), game.crisis !== null, game.readOnly,
      pal.key, lay.start, game.racks ? Math.floor(game.phase / C.LED_PERIOD) : 0].join('|');
    if (sig === hallSig) return;
    hallSig = sig;
    const canvas = $('hall');
    if (canvas.width !== g.w || canvas.height !== g.h) {
      canvas.width = g.w;
      canvas.height = g.h;
    }
    canvas.style.width = (g.w * g.scale / g.dpr) + 'px';
    canvas.style.height = (g.h * g.scale / g.dpr) + 'px';
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(g.w, g.h);
    paintHall(img, g.w, g.h, lay);
    ctx.putImageData(img, 0, 0);
  }

  /** Sprite colours for one tier; a decommissioned data center is washed out to grey. */
  function spriteColours(tier, dead) {
    let base = pal.tiers[tier];
    if (dead) {
      const grey = Math.trunc(lum(base) * 255);
      base = mix([grey, grey, grey], pal.surface, 0.55);
    }
    return { k: pal.frame, c: base, h: mix(base, [255, 255, 255], 0.35),
      d: mix(base, [0, 0, 0], 0.5), w: mix(base, [255, 255, 255], 0.6) };
  }

  function paintHall(img, w, h, lay) {
    const d = img.data;
    const put = (x, y, c) => {
      if (x < 0 || y < 0 || x >= w || y >= h) return;
      const o = (y * w + x) * 4;
      d[o] = c[0]; d[o + 1] = c[1]; d[o + 2] = c[2]; d[o + 3] = 255;
    };
    for (let y = 0; y < h; y++) {
      const c = mix(pal.bg, pal.surface, y / Math.max(1, h - 1));
      for (let x = 0; x < w; x++) put(x, y, c);
    }
    paintRacks(put, lay);
    if (lay.total > lay.viewRows) paintScrollbar(put, w, h, lay);
  }

  function paintRacks(put, lay) {
    const dead = game.readOnly;
    const ends = [];
    game.owned.reduce((a, n) => { ends.push(a + n); return a + n; }, 0);
    let ledOn = game.crisis && !dead ? pal.alertOn : pal.ledOn;
    let ledOff = game.crisis && !dead ? pal.alertOff : pal.ledOff;
    if (dead) ledOn = ledOff = mix(pal.frame, pal.bg, 0.4); // every light is off
    const first = lay.start * lay.cols;
    const shown = Math.min(lay.racks - first, lay.viewRows * lay.cols);
    const step = Math.floor(game.phase / C.LED_PERIOD);
    for (let j = 0; j < shown; j++) {
      const idx = first + j;
      const tier = ends.findIndex((e) => e > idx); // racks are ordered by tier
      const ox = (j % lay.cols) * C.CELL_W;
      const oy = Math.floor(j / lay.cols) * C.CELL_H + 1;
      const colours = spriteColours(tier, dead);
      for (let x = 1; x < 6; x++) put(ox + x, oy + 6, pal.shadow);
      C.SPRITES[tier].forEach((row, y) => {
        for (let x = 0; x < row.length; x++) {
          const ch = row[x];
          if (ch === '.') continue;
          if (ch === 'A' || ch === 'B') put(ox + x, oy + y, (step + idx + y * 2 + x) % 3 === 0 ? ledOn : ledOff);
          else put(ox + x, oy + y, colours[ch]);
        }
      });
    }
  }

  function paintScrollbar(put, w, h, lay) {
    const thumbLen = Math.max(2, Math.round(h * lay.viewRows / lay.total));
    const maxStart = Math.max(1, lay.total - lay.viewRows);
    const thumbPos = Math.round((h - thumbLen) * lay.start / maxStart);
    for (let y = 0; y < h; y++) {
      const c = y >= thumbPos && y < thumbPos + thumbLen ? pal.muted : pal.frame;
      for (let x = w - SCROLLBAR_PX; x < w; x++) put(x, y, c);
    }
  }

  /** Scroll the data hall: up/down one rack row, page, home/end. The bottom follows new racks. */
  function scrollHall(how) {
    const lay = hallLayout(hallGeom());
    const last = Math.max(0, lay.total - lay.viewRows);
    const target = { up: lay.start - 1, down: lay.start + 1, pageup: lay.start - lay.viewRows,
      pagedown: lay.start + lay.viewRows, home: 0, end: last }[how];
    const clamped = Math.max(0, Math.min(last, target));
    hallScroll = clamped >= last ? null : clamped;
  }

  /** , and . scroll the marketplace / chips / crew card when it has more rows than fit. */
  function scrollShop(delta) {
    const side = game.side;
    if (!['servers', 'chips', 'staff'].includes(side)) return;
    const count = side === 'staff' ? STAFF.length : TIERS.length;
    const frontier = side === 'staff' ? frontierOf(game.staff.map((l) => l + 1)) : frontierOf(game.owned);
    const [top] = windowOf(count, frontier);
    shopTop = Math.max(0, top + delta);
  }

  // ------------------------------------------------------------------- inputs

  function act(fn) {
    if (destroyed || !game) return;
    fn();
    dirty = true;
    render();
    save(false);
  }

  function setView(name) {
    if (name === 'board' && !ONLINE) return;
    game.view(name);
    shopTop = null;
    if (name === 'board') pullBoard(false);
  }

  function relocate() {
    const before = game.sites;
    game.relocate();
    if (game.sites !== before) {
      hallScroll = null;
      shopTop = null;
      submit(true);
    }
  }

  const HALL_KEYS = { ArrowUp: 'up', ArrowDown: 'down', PageUp: 'pageup', PageDown: 'pagedown',
    Home: 'home', End: 'end' };

  /** The action for a key, or null. */
  function keyAction(k) {
    if (/^[0-9]$/.test(k)) return () => game.pick(k === '0' ? 9 : Number(k) - 1);
    if (VIEW_KEYS[k] && !(k === 'b' && !ONLINE)) return () => setView(VIEW_KEYS[k]);
    if (HALL_KEYS[k]) return () => scrollHall(HALL_KEYS[k]);
    const simple = {
      x: relocate, f: () => game.fix(), a: () => game.toggleAutopilot(), '[': () => game.prev(),
      ']': () => game.next(), ',': () => scrollShop(-1), '.': () => scrollShop(1),
      n: openRename, m: openMenu, Escape: openMenu, j: toggleBoard,
    };
    return simple[k] || null;
  }

  function onKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || destroyed || !game) return;
    if (dlg) { dialogKey(e); return; }
    const t = e.target;
    if (t && (/^(SELECT|INPUT|TEXTAREA)$/.test(t.tagName) || t.isContentEditable)) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const fn = keyAction(k);
    if (!fn) return;
    e.preventDefault();
    act(fn);
  }

  function onClick(e) {
    const el = e.target.closest ? e.target.closest('[data-i],[data-act],[data-view],[data-dlg]') : null;
    if (!el || destroyed || !game) return;
    if (el.dataset.dlg !== undefined) { chooseItem(Number(el.dataset.dlg)); return; }
    if (dlg) return;
    const a = el.dataset.act;
    if (el.dataset.view) act(() => setView(el.dataset.view));
    else if (a === 'expand') act(relocate);
    else if (a === 'fix') act(() => game.fix());
    else if (a === 'prev') act(() => game.prev());
    else if (a === 'next') act(() => game.next());
    else if (a === 'menu') act(openMenu);
    else if (el.dataset.i !== undefined && el.closest('#shop')) act(() => game.pick(Number(el.dataset.i)));
  }

  function onWheel(e) {
    if (dlg || !game) return;
    e.preventDefault();
    act(() => scrollHall(e.deltaY < 0 ? 'up' : 'down'));
  }

  function onTheme() {
    setTheme($('theme').value);
  }

  // --------------------------------------------------------------------- loop

  /** Per-second online chores: score every 5 ticks, board every 30 while it is open. */
  function onlineChores() {
    if (!ONLINE || !visibleNow()) return;
    if (game.phase % SUBMIT_TICKS === 0) submit(false);
    if (game.side === 'board' && game.phase % BOARD_TICKS === 0) pullBoard(false);
  }

  /** One timer step: tick per elapsed second, or credit a long gap as offline time. */
  function onTimer() {
    if (destroyed || !game) return;
    const now = Date.now();
    const gap = now - lastTick;
    if (gap > OFFLINE_GAP_MS) {
      game.applyOffline(gap / 1000);
      lastTick = now;
    } else {
      const n = Math.floor(gap / 1000);
      if (n < 1) return;
      for (let i = 0; i < n; i++) { game.tick(); onlineChores(); }
      lastTick += n * 1000;
    }
    dirty = true;
    render();
    status();
    save(false);
  }

  function onVisibility() {
    if (document.visibilityState === 'hidden') save(true);
    else onTimer();
  }

  const onHide = () => save(true);

  function destroy() {
    if (destroyed) return;
    save(true);
    destroyed = true;
    clearInterval(timer);
    document.removeEventListener('keydown', onKey);
    document.removeEventListener('click', onClick);
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('pagehide', onHide);
    $('theme').removeEventListener('change', onTheme);
    $('hallWrap').removeEventListener('wheel', onWheel);
    observers.forEach((o) => o.disconnect());
    observers = [];
  }

  function watchTheme() {
    const refresh = () => { if (!destroyed && game) applyPalette(); };
    const opts = { attributes: true, attributeFilter: ['class', 'style', 'data-vscode-theme-id'] };
    if (typeof MutationObserver === 'function') {
      const mo = new MutationObserver(refresh);
      mo.observe(document.documentElement, opts);
      mo.observe(document.body, opts);
      observers.push(mo);
    }
    if (typeof ResizeObserver === 'function') {
      const ro = new ResizeObserver(() => { if (!destroyed && game) { hallSig = ''; render(); } });
      ro.observe($('hallWrap'));
      observers.push(ro);
    }
    if (window.matchMedia) {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      if (mq && mq.addEventListener) mq.addEventListener('change', refresh);
    }
  }

  function setupChrome() {
    const sel = $('theme');
    THEMES.forEach((t) => { const o = document.createElement('option'); o.value = o.textContent = t; sel.appendChild(o); });
    sel.hidden = forcedTheme !== null;
    sel.addEventListener('change', onTheme);
    $('tabBoard').hidden = !ONLINE;
    $('hint').textContent = '1-9, 0 pick  s c h d' + (ONLINE ? ' b' : '') + ' cards  , . scroll card  ↑↓ hall  [ ] site  ' +
      'x relocate  f fix  a autopilot  n name  m menu' + (ONLINE ? '  j board' : '');
    document.addEventListener('keydown', onKey);
    document.addEventListener('click', onClick);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', onHide);
    $('hallWrap').addEventListener('wheel', onWheel, { passive: false });
  }

  function start(text) {
    game = C.Game.fromJSON(text);
    ui.game = game;
    setupChrome();
    watchTheme();
    applyTheme();
    lastTick = Date.now();
    timer = setInterval(onTimer, 1000);
    dirty = true;
    status();
    save(false);
    if (ONLINE && !game.online.asked) askToJoin();
  }

  function boot() {
    ui.destroy = destroy;
    Promise.resolve()
      .then(() => store.load())
      .catch(() => null)
      .then((text) => { if (!destroyed) start(typeof text === 'string' ? text : null); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
