/* My Data Center - game model. Port of data_center_tui/game.py (no DOM access).
 * Works as a classic <script> (window.DCCore) and as CommonJS.
 * All money maths is exact BigInt; Numbers are only used for tiny values. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.DCCore = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ---------------------------------------------------------------- game data
  // Mirrors data_center_tui/game.py exactly.

  // name, base cost, income/sec (for the first data center)
  const TIERS = [
    ['Budget VPS', 60n, 2n],
    ['Compute Node', 840n, 14n],
    ['GPU Cluster', 9600n, 80n],
    ['AI Datacenter', 108000n, 450n],
    ['Quantum Farm', 1200000n, 2500n],
    ['Orbital Cloud', 14400000n, 15000n],
    ['Fusion Campus', 108000000n, 90000n],
    ['Dyson Swarm', 864000000n, 540000n],
    ['Neutron Star Farm', 6400000000n, 3200000n],
    ['Black Hole Colo', 47500000000n, 19000000n],
  ];
  // Each extra copy of a tier costs this many percent of the previous one.
  const GROWTH_PCT = [107n, 108n, 109n, 110n, 111n, 112n, 112n, 112n, 113n, 113n];
  // Owning this many of a tier doubles that tier's income.
  const MILESTONES = [25, 50, 100, 200, 300, 400, 500, 1000, 1500, 2000, 3000, 4000];
  const MAX_OWNED = 4000;

  const CHIP_FAMILIES = [
    ['GeForceless 1030', 'Radeoff 6400', 'Vague 8 (Hopeful)', 'G-Tex 750', 'Radeoff HD 7000'],
    ['Rizzen 5 5600', 'Rizzen 9 Garden', 'Thread-Shred 3990', 'Epick Milano', 'Rizzen Z Handheld'],
    ['RTZ 3090', 'RTZ 4090', 'RTZ 5090 (Paper)', 'Colossus RTZ', 'Leather Jacket Ed.'],
    ['A-100', 'H-100 (a kidney)', 'Bee-200 (melts)', 'GB-200 (Rack-ish)', 'H-200 (sold out)'],
    ['MX250X', 'MX300X (eXpensive)', 'MX325-ception', 'MX350 Schrödinger', 'Insti-Zero'],
    ['Ruby Ultra', 'Rizzen Space Ed.', 'DGZ Moonbase', 'Physicist (TBD)', 'Sphere GPU'],
    ['Tokamak TK-1', 'Stellarator S7', 'ITER Junior', 'Cold Fusion (lol)', 'Plasma Rack'],
    ['Solar Sail', 'Swarm Node', 'Mirror Array', 'Mercury Strip Mine', 'Matrioshka Lite'],
    ['Pulsar Clock', 'Magnetar Mk I', 'Neutronium Sink', 'Quark Fabric', 'Strange Matter'],
    ['Event Horizon', 'Hawking Cooler', 'Singularity Rack', 'Penrose Engine', 'Info Paradox'],
  ];
  const CHIP_EDITIONS = ['', ' Ti', ' Super', ' Ultra Max'];
  const MAX_CHIP = 20;
  const CHIP_BASE = 2n; // level-0 chip costs this many times the tier's base cost
  const CHIP_GROWTH = 4n; // each level costs 4x the one before
  const CHIP_BOOST = 2n;

  // name, hire cost, tagline, highest crisis severity handled, base response (s).
  // Perks: Lv0 fixes crises, Lv2 auto-buys servers, Lv4 x2 income, Lv6 auto-buys chips,
  // Lv8 x2 again (and every level adds +5% income).
  const STAFF = [
    ['Vibecoder', 5000n, 'ships it without reading the diff', 1, 10.0],
    ['Prompt Engineer', 60000n, 'negotiates with the model for you', 2, 9.0],
    ['Forward Deployed Engineer', 750000n, 'lives on-site, expenses everything', 3, 8.0],
    ['Site Reliability Engineer', 10000000n, 'has seen things', 3, 6.0],
    ['10x Engineer', 150000000n, 'does not exist, allegedly', 3, 4.0],
    ['Chief Hype Officer', 2500000000n, 'raises a round to fix it', 3, 3.0],
    ['Distinguished Engineer', 40000000000n, 'has opinions about your architecture', 3, 2.5],
    ['Chief AI Officer', 700000000000n, 'puts AI in the press release', 3, 2.0],
    ['Head of Synergy', 12000000000000n, 'aligns stakeholders at light speed', 3, 1.5],
    ['Founder Mode CEO', 200000000000000n, 'is personally in the weeds', 3, 1.0],
  ];
  const CREW_INITIALS = 'VPFSXCDAHO';
  const AUTO_SERVERS_LEVEL = 2;
  const DOUBLE_LEVELS = [4, 8];
  const AUTO_CHIPS_LEVEL = 6;
  const AUTO_BUYS_PER_TICK = 10;
  const AUTO_AFFORD_DIV = 50n;
  const PERKS = [[AUTO_SERVERS_LEVEL, 'buys cheap servers'], [DOUBLE_LEVELS[0], 'x2 its income'],
    [AUTO_CHIPS_LEVEL, 'buys cheap chips'], [DOUBLE_LEVELS[1], 'x2 its income']];
  const STAFF_SCOPE = ['minor incidents', 'outages and below', 'everything'];
  const MAX_STAFF = 10;
  const RESPONSE_DECAY = 0.8;
  const STAFF_BONUS = 5;

  const SITE_NAMES = [
    'Garage in Palo Alto', 'Abandoned Mall in Ohio', 'Decommissioned Missile Silo',
    'Arctic Bunker (free cooling)', 'Undersea Pod off Iceland', 'Lunar Regolith Campus',
    'Dyson Swarm Annex', 'Pocket Universe', 'Heat Death Colo',
    'The Cloud (Actually Water Vapor)',
  ];
  const EXPAND_BASE = 10n ** 16n;
  const EXPAND_SCALE = 1000n;
  const INCOME_SCALE = 1000n;
  const COST_SCALE = 1250n;
  const START_BALANCE = 500n;
  const MAX_SITES = 60;
  const FAME_BONUS = 2; // percent income per Fame point
  // Lifetime Fame needed for each title; past the last, each numeral level doubles it.
  const RANKS = [
    [0n, 'Nobody'], [1n, 'Intern'], [3n, 'Junior Dev'], [6n, 'Senior Dev'], [10n, 'Tech Lead'],
    [15n, 'Engineering Manager'], [25n, 'Director'], [40n, 'VP of Engineering'], [60n, 'CTO'],
    [90n, 'Tech CEO'], [130n, 'Tech Billionaire'], [180n, 'Tech Overlord'],
  ];
  const MAX_BIG = 10n ** 600n;

  const CRISES = {
    1: ['CI is stuck on a flaky test', 'Janitor unplugged a rack to vacuum',
      'Someone pasted the API key into Slack'],
    2: ['Power outage: the grid is down', 'Cooling failed: the AC is a fan and a prayer',
      'Cloud bill spiked 40x overnight'],
    3: ['GPU shortage: scalpers bought every one', 'Intern force-pushed to main on a Friday',
      'Solar flare fried the Orbital Cloud'],
  };
  const CRISIS_FACTOR = { 1: [1, 2], 2: [1, 4], 3: [0, 1] }; // income multiplier num/den
  const CRISIS_WEIGHT = { 1: 5, 2: 3, 3: 2 };
  const CRISIS_MEAN = 120;
  const CRISIS_MIN_INCOME = 10n;
  const FIX_QUIPS = [
    'by turning it off and on again', 'with one prompt and zero tests',
    'by rewriting it in Rust', 'by blaming the intern',
    'with a hotfix straight to prod', 'by asking the model nicely',
  ];

  const DEFAULT_THEME = 'gruvbox';
  const OFFLINE_NUM = 3n;
  const OFFLINE_DEN = 4n;
  const LED_PERIOD = 2;
  const CELL_W = 7;
  const CELL_H = 8;
  const LOG_LIMIT = 300;

  // k frame, c tier colour, h highlight, d dark, w pale window/fan, A/B blinking LEDs
  const SPRITES = [
    ['......', '......', '.cccc.', 'chhhhc', 'cddAdc', 'kkkkkk'],
    ['......', 'cccccc', 'chhhAc', 'kkkkkk', 'chhhBc', 'cccccc'],
    ['cccccc', 'cwdwAc', 'cddddc', 'cwdwBc', 'cddddc', 'kkkkkk'],
    ['..hh..', 'cccccc', 'cwcwcc', 'cccccc', 'cwcAwc', 'dddddd'],
    ['..hh..', '.hwwh.', 'chwwhc', '.cwwc.', '..cc..', '..dd..'],
    ['..hA..', 'cckkcc', 'cchhcc', 'cckkcc', '..kk..', '..dd..'],
    ['..cc..', '.chhc.', 'chwwhc', 'cwAAwc', 'cddddc', 'kkkkkk'],
    ['c....c', '.hhhh.', 'hwAAwh', 'hwwwwh', '.hhhh.', 'c....c'],
    ['......', '..cc..', 'cwhhwc', '.cwwc.', '..cc..', '..dd..'],
    ['.cccc.', 'chddhc', 'cdAAdc', 'chddhc', '.cccc.', '..dd..'],
  ];

  // ------------------------------------------------------------------ economy

  function powCache(base) {
    const cache = [1n];
    return (k) => {
      while (cache.length <= k) cache.push(cache[cache.length - 1] * base);
      return cache[k];
    };
  }
  const incomePow = powCache(INCOME_SCALE);
  const costPow = powCache(COST_SCALE);
  const expandPow = powCache(EXPAND_SCALE);

  function siteName(k) {
    return k < SITE_NAMES.length ? SITE_NAMES[k]
      : 'Parallel Universe #' + (k - SITE_NAMES.length + 1);
  }

  /** Cost to leave data center `site` and open the next one. */
  function expandCost(site) {
    return EXPAND_BASE * expandPow(site);
  }

  function costOf(tier, owned, site = 0) {
    return TIERS[tier][1] * costPow(site) * GROWTH_PCT[tier] ** BigInt(owned) / 100n ** BigInt(owned);
  }

  /** Income multiplier from owning enough of a tier (x2 per milestone passed). */
  function milestoneMult(owned) {
    let n = 0n;
    for (const m of MILESTONES) if (owned >= m) n += 1n;
    return 2n ** n;
  }

  function nextMilestone(owned) {
    const m = MILESTONES.find((x) => owned < x);
    return m === undefined ? null : m;
  }

  function tierIncome(tier, owned, chip, site = 0) {
    return BigInt(owned) * TIERS[tier][2] * incomePow(site) * CHIP_BOOST ** BigInt(chip) *
      milestoneMult(owned);
  }

  /** A tier's specialist doubles its income at each milestone level (Lv4, Lv8). */
  function crewMultiplier(level) {
    let n = 0n;
    for (const m of DOUBLE_LEVELS) if (level >= m) n += 1n;
    return 2n ** n;
  }

  function startBalance(site) {
    return START_BALANCE * costPow(site);
  }

  /** floor(sqrt(n)) for a non-negative BigInt. */
  function isqrt(n) {
    if (n < 2n) return n;
    let x = 1n << BigInt((n.toString(2).length + 1) >> 1); // >= sqrt(n)
    for (;;) {
      const y = (x + n / x) >> 1n;
      if (y >= x) return x;
      x = y;
    }
  }

  /** Fame for relocating out of data center `site` holding `balance`. */
  function fameGain(balance, site) {
    return isqrt(balance / expandCost(site));
  }

  function roman(n) {
    const table = [[1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
      [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
    let out = '';
    for (const [value, symbol] of table) {
      while (n >= value) { out += symbol; n -= value; }
    }
    return out;
  }

  /** [current title, Fame needed for the next title (BigInt), next title]. */
  function rankOf(fame) {
    fame = BigInt(fame);
    let i = 0;
    for (let j = 0; j < RANKS.length; j++) if (fame >= RANKS[j][0]) i = j;
    if (i + 1 < RANKS.length) return [RANKS[i][1], RANKS[i + 1][0], RANKS[i + 1][1]];
    const [top, name] = RANKS[RANKS.length - 1];
    let level = 1; // the last title is level 1; each doubling of Fame adds one
    while (fame >= top * 2n ** BigInt(level) && level < 3999) level++;
    const title = level === 1 ? name : name + ' ' + roman(level);
    return [title, top * 2n ** BigInt(level), name + ' ' + roman(level + 1)];
  }

  function chipName(tier, level) {
    return CHIP_FAMILIES[tier][Math.floor(level / 4)] + CHIP_EDITIONS[level % 4];
  }

  function chipCost(tier, level, site = 0) {
    return TIERS[tier][1] * CHIP_BASE * CHIP_GROWTH ** BigInt(level) * costPow(site);
  }

  /** Cost to hire (level -1) or to train from `level` to level+1. */
  function staffCost(role, level, site = 0) {
    const hire = STAFF[role][1] * costPow(site);
    return level < 0 ? hire : hire * 3n * 9n ** BigInt(level) / 5n ** BigInt(level);
  }

  function responseTime(role, level) {
    return STAFF[role][4] * Math.pow(RESPONSE_DECAY, level);
  }

  function responseSecs(role, level) {
    return Math.max(1, Math.ceil(responseTime(role, level)));
  }

  /** Rebuild a [owned, chips] layout worth about `income` (legacy saves). */
  function restoreSite(site, income, bonusPct) {
    const owned = new Array(TIERS.length).fill(0);
    const chips = new Array(TIERS.length).fill(0);
    let remaining = BigInt(income) * 100n / (100n + BigInt(bonusPct));
    for (let t = TIERS.length - 1; t >= 0; t--) {
      let level = 0;
      for (level = 0; level <= MAX_CHIP; level++) { // fewest chips that keep the count in range
        if (tierIncome(t, MAX_OWNED, level, site) > remaining) break;
      }
      if (level > MAX_CHIP) level = MAX_CHIP; // Python's range() leaves the last value
      let lo = 0;
      let hi = MAX_OWNED; // largest count whose income does not exceed what is left
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (tierIncome(t, mid, level, site) <= remaining) lo = mid;
        else hi = mid - 1;
      }
      if (lo) {
        owned[t] = lo;
        chips[t] = level;
        remaining -= tierIncome(t, lo, level, site);
      }
    }
    return [owned, chips];
  }

  // --------------------------------------------------------------- formatting

  const SUFFIXES = ['', 'K', 'M', 'B', 'T', 'Qa', 'Qi', 'Sx', 'Sp', 'Oc', 'No', 'Dc'];

  function bitLen(x) {
    return x.toString(2).length;
  }

  function divRoundEven(a, b) {
    const q = a / b;
    const twice = (a % b) * 2n;
    return twice > b || (twice === b && (q & 1n) === 1n) ? q + 1n : q;
  }

  /**
   * n / d formatted like Python's f"{n / d:.2f}": the quotient is first rounded to
   * the nearest double (as true division does), then printed half-to-even.
   * Returns {value, text}; value is that double.
   */
  function quot2(n, d) {
    const sh = 55 - (bitLen(n) - bitLen(d));
    const num = n << BigInt(sh);
    const t = num / d;
    const sticky = num % d !== 0n;
    const extra = BigInt(bitLen(t) - 53);
    let m = t >> extra;
    const rem = t & ((1n << extra) - 1n);
    const half = 1n << (extra - 1n);
    if (rem > half || (rem === half && (sticky || (m & 1n) === 1n))) m += 1n;
    const s = sh - Number(extra); // value = m / 2^s
    const cents = divRoundEven(m * 100n, 1n << BigInt(s));
    return {
      value: Number(m) / Math.pow(2, s),
      text: (cents / 100n) + '.' + String(cents % 100n).padStart(2, '0'),
    };
  }

  function fmt(n) {
    let v = typeof n === 'bigint' ? n : BigInt(Math.trunc(Number(n)) || 0);
    if (v < 0n) v = 0n;
    if (v < 1000n) return v.toString();
    const s = v.toString();
    const digits = s.length;
    const group = Math.floor((digits - 1) / 3);
    if (group < SUFFIXES.length) {
      const q = quot2(v, 10n ** BigInt(3 * group));
      if (q.value < 999.995) return q.text + SUFFIXES[group];
      if (group + 1 < SUFFIXES.length) { // would round up to "1000.00": next unit
        return quot2(v, 10n ** BigInt(3 * (group + 1))).text + SUFFIXES[group + 1];
      }
    }
    return s[0] + '.' + s.slice(1, 3) + 'e' + (digits - 1);
  }

  function fmtDuration(seconds) {
    const total = Math.floor(seconds);
    const d = Math.floor(total / 86400);
    const h = Math.floor((total % 86400) / 3600);
    const m = Math.floor((total % 3600) / 60);
    if (d) return d + 'd ' + h + 'h';
    return h ? h + 'h ' + m + 'm' : m + 'm';
  }

  // ------------------------------------------------------------ save helpers

  /** Decimal string (or safe non-negative integer) -> BigInt in [0, MAX_BIG), else null. */
  function parseBig(v) {
    let b = null;
    if (typeof v === 'string' && /^[0-9]{1,601}$/.test(v)) b = BigInt(v);
    else if (typeof v === 'number' && Number.isSafeInteger(v) && v >= 0) b = BigInt(v);
    return b !== null && b < MAX_BIG ? b : null;
  }

  /** A list of n ints in [lo, hi]; anything invalid falls back to def. */
  function cleanLevels(raw, n, lo, hi, def) {
    const out = new Array(n).fill(def);
    if (Array.isArray(raw)) {
      for (let i = 0; i < n && i < raw.length; i++) {
        const v = raw[i];
        if (typeof v === 'number' && Number.isInteger(v) && v >= lo && v <= hi) out[i] = v;
      }
    }
    return out;
  }

  const isObject = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);

  // ---------------------------------------------------------------------- rng

  /**
   * Random source used by the game. Anything with these three methods works, which is
   * how tests script the dice:
   *   random()        -> float in [0, 1)
   *   weighted(ws)    -> index into ws, chosen with those weights (Python's random.choices)
   *   index(n)        -> integer in [0, n) (Python's random.choice on a list of n)
   */
  function makeRng(random = Math.random) {
    return {
      random,
      weighted(weights) {
        let total = 0;
        const cum = weights.map((w) => (total += w));
        const x = random() * total;
        for (let i = 0; i < cum.length - 1; i++) if (x < cum[i]) return i; // bisect_right
        return cum.length - 1;
      },
      index(n) { return Math.min(n - 1, Math.floor(random() * n)); },
    };
  }

  // ------------------------------------------------------------------ online
  // Pure helpers for the leaderboard client. The network is an injected `api(method,
  // path, body) -> Promise<[status, body]>` that never rejects (status 0 = unreachable).

  const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,19}$/;
  const TOKEN_RE = /^[0-9a-f]{32,64}$/;
  const DC_NAME_RE = /^[ -~]{0,24}$/; // what you may call a data center: plain printable text
  const MAX_FAME_ONLINE = 10n ** 12n; // the server rejects anything above this
  const SUBMIT_EVERY = 120; // seconds between score updates when something changed
  const BOARD_EVERY = 5; // seconds between board fetches unless forced

  /** 32 lowercase hex chars from 16 random bytes. `randomBytes(n)` is injectable. */
  function makeToken(randomBytes) {
    const get = randomBytes || ((n) => globalThis.crypto.getRandomValues(new Uint8Array(n)));
    const bytes = get(16);
    if (!bytes || bytes.length !== 16) throw new Error('token source must return 16 bytes');
    const token = Array.from(bytes, (b) => (b & 255).toString(16).padStart(2, '0')).join('');
    if (!TOKEN_RE.test(token)) throw new Error('bad token');
    return token;
  }

  /** JSON-safe body for POST /api/submit. Fame is integer text (BigInt can't be stringified). */
  function submitPayload(game) {
    return {
      token: game.online.token, name: game.online.name,
      fame: game.fame.toString(), sites: game.sites,
    };
  }

  /** Mutable client state for the leaderboard (what Python keeps on the app). */
  function newOnlineState() {
    return { busy: false, lastSent: null, lastAttempt: -Infinity, boardBusy: false,
      boardAt: -Infinity, board: null };
  }

  function snapshotOf(game) {
    return game.fame.toString() + '|' + game.sites + '|' + game.online.name;
  }

  /**
   * React to the server's answer to a submit.
   * 200 ok; 409 name taken (leave the board); 400 refused (mark sent, never resend);
   * anything else (0 offline, 429, 5xx): retry later. Returns {kind}.
   */
  function handleSubmit(game, st, res, snapshot) {
    const [status, body] = res;
    if (status === 200) {
      st.lastSent = snapshot;
      return { kind: 'ok' };
    }
    if (status === 409) {
      game.online.joined = false;
      game.say("! the name '" + game.online.name + "' is taken", 'error');
      return { kind: 'taken' };
    }
    if (status === 400) {
      st.lastSent = snapshot;
      const why = body && typeof body.error === 'string' ? body.error.slice(0, 60) : 'bad data';
      game.say('! the leaderboard rejected the score (' + why + ')', 'error');
      return { kind: 'rejected' };
    }
    return { kind: 'retry' };
  }

  /**
   * Send the score if joined and something changed (or `force`). `now` is unix seconds.
   * Resolves to the handleSubmit result, or null when nothing was sent.
   */
  async function maybeSubmit(game, api, st, now, force = false) {
    if (!game.online.joined || st.busy || game.fame > MAX_FAME_ONLINE) return null;
    const snapshot = snapshotOf(game);
    if (!force && (snapshot === st.lastSent || now - st.lastAttempt < SUBMIT_EVERY)) return null;
    st.busy = true;
    st.lastAttempt = now;
    let res;
    try { res = await api('POST', '/api/submit', submitPayload(game)); } catch (e) { res = [0, {}]; }
    st.busy = false;
    return handleSubmit(game, st, res, snapshot);
  }

  /** Board model after a fetch (Python's on_board). `prev` is the previous board or null. */
  function boardFromResults(prev, top, me, now) {
    const [status, topBody] = top;
    const [meStatus, meBody] = me;
    if (status === 200 && topBody && Array.isArray(topBody.players)) {
      return { players: topBody.players, total: topBody.total === undefined ? 0 : topBody.total,
        at: now, me: meStatus === 200 ? meBody : null, error: false };
    }
    if (prev !== null) return Object.assign({}, prev, { error: true });
    return { players: [], total: 0, at: 0, me: null, error: true };
  }

  /** Fetch top 30 and (when joined) our own rank, then store st.board. Resolves to the board. */
  async function refreshBoard(game, api, st, now, force = false) {
    if (st.boardBusy || (!force && now - st.boardAt < BOARD_EVERY)) return st.board;
    st.boardAt = now;
    st.boardBusy = true;
    const token = game.online.joined ? game.online.token : '';
    let top;
    let me = [0, {}];
    try {
      top = await api('GET', '/api/leaderboard?limit=30');
      if (token) me = await api('POST', '/api/me', { token });
    } catch (e) { top = top || [0, {}]; }
    st.boardBusy = false;
    st.board = boardFromResults(st.board, top, me, now);
    return st.board;
  }

  /**
   * Display rows of a board: skips malformed entries and names that fail NAME_RE (a
   * server must not be able to inject markup or control characters).
   */
  function boardRows(board, game, limit = 30) {
    const rows = [];
    if (!board || !Array.isArray(board.players)) return rows;
    const mineName = game.online.name.toLowerCase();
    for (const pl of board.players) {
      if (rows.length >= limit) break;
      if (!isObject(pl)) continue;
      const fame = parseBig(pl.fame);
      const sites = pl.sites;
      const rank = pl.rank;
      const name = pl.name;
      if (fame === null || !Number.isInteger(sites) || sites < 0 || !Number.isInteger(rank) ||
        typeof name !== 'string' || !NAME_RE.test(name)) continue;
      rows.push({ rank, name, fame: fmt(fame), sites: sites + 1,
        mine: game.online.joined && name.toLowerCase() === mineName });
    }
    return rows;
  }

  // --------------------------------------------------------------------- game

  const SIDES = ['servers', 'chips', 'staff', 'sites', 'board'];

  const isInt = (v) => typeof v === 'number' && Number.isInteger(v);

  class Game {
    /**
     * @param {{rng?: object|function, now?: function(): number}} [opts]
     *   rng: {random, weighted, index} (see makeRng) or a plain random() function;
     *   now returns unix seconds.
     */
    constructor(opts = {}) {
      const r = opts.rng;
      this.rng = typeof r === 'function' ? makeRng(r) : (r || makeRng());
      this.now = opts.now || (() => Date.now() / 1000);
      this.sites = 0; // newest (live) data center; the others are decommissioned
      this.cur = 0; // the one you are looking at
      this.siteBalance = [START_BALANCE];
      this.siteOwned = [new Array(TIERS.length).fill(0)];
      this.siteChips = [new Array(TIERS.length).fill(0)];
      this.siteStaff = [new Array(STAFF.length).fill(-1)];
      this.siteNames = [''];
      this.fame = 0n;
      this.autopilot = true; // on for a brand-new game only (see load)
      this.online = { asked: false, joined: false, name: '', token: '' };
      this.theme = DEFAULT_THEME;
      this.crisis = null; // {title, sev, fixer, eta}
      this.phase = 0;
      this.side = 'servers'; // UI card: servers | chips | staff | sites | board
      this.log = [];
      this.logId = 0;
      this.away = null; // {seconds, earned} from the last offline credit
      this.say('Welcome. Buy servers with keys 1-9 and 0. Press m for the menu.', 'fg');
    }

    // -- derived state (the data center you are in, `cur`) -----------------

    get balance() { return this.siteBalance[this.cur]; }

    set balance(v) { this.siteBalance[this.cur] = v; }

    get owned() { return this.siteOwned[this.cur]; }

    get chips() { return this.siteChips[this.cur]; }

    get staff() { return this.siteStaff[this.cur]; }

    /** You are looking at a decommissioned data center: view only, nothing earns there. */
    get readOnly() { return this.cur !== this.sites; }

    /** Data center k's income before the crew and Fame bonuses. */
    rawIncome(k) {
      let sum = 0n;
      for (let t = 0; t < TIERS.length; t++) {
        sum += tierIncome(t, this.siteOwned[k][t], this.siteChips[k][t], k) *
          crewMultiplier(this.siteStaff[k][t]);
      }
      return sum;
    }

    /** Percent income bonus from data center k's crew. */
    crewBonus(k) {
      return STAFF_BONUS * this.siteStaff[k].reduce((a, l) => a + (l >= 0 ? l + 1 : 0), 0);
    }

    get staffBonus() { return this.crewBonus(this.cur); }

    get fameBonus() { return BigInt(FAME_BONUS) * this.fame; }

    /** What data center k earns per second while you are in it (two separate floors). */
    siteIncome(k) {
      return this.rawIncome(k) * BigInt(100 + this.crewBonus(k)) / 100n *
        (100n + this.fameBonus) / 100n;
    }

    /** What you earn right now (the data center you are in), ignoring crises. */
    get baseIncome() { return this.siteIncome(this.cur); }

    get income() {
      const [num, den] = this.crisis ? CRISIS_FACTOR[this.crisis.sev] : [1, 1];
      return this.baseIncome * BigInt(num) / BigInt(den);
    }

    get racks() { return this.owned.reduce((a, b) => a + b, 0); }

    siteLabel(k) {
      return (k < this.siteNames.length ? this.siteNames[k].trim() : '') || siteName(k);
    }

    // -- log ----------------------------------------------------------------

    /** kind: fg | muted | success | error | warning (maps to a palette colour). */
    say(text, kind) {
      this.log.push({ id: ++this.logId, text, kind });
      if (this.log.length > LOG_LIMIT) this.log.shift();
    }

    guardReadOnly() {
      if (this.readOnly) {
        this.say('#' + (this.cur + 1) + ' is decommissioned: view only (your live data center is #' +
          (this.sites + 1) + ')', 'muted');
      }
      return this.readOnly;
    }

    // -- game loop ----------------------------------------------------------

    /** One second. The live data center works even while you look at an old one. */
    tick() {
      const view = this.cur;
      this.cur = this.sites;
      try {
        this.balance += this.income;
        this.phase += 1;
        this.runAutopilot();
        this.updateCrisis();
      } finally {
        this.cur = view;
      }
    }

    /** Each specialist buys for its own tier: servers from Lv2, chips from Lv6. */
    runAutopilot() {
      if (!this.autopilot) return;
      const cheap = this.siteIncome(this.cur) / AUTO_AFFORD_DIV; // most one purchase may cost
      for (let t = 0; t < this.staff.length; t++) {
        const level = this.staff[t];
        if (level < AUTO_SERVERS_LEVEL) continue;
        for (let i = 0; i < AUTO_BUYS_PER_TICK; i++) {
          const cost = costOf(t, this.owned[t], this.cur);
          if (this.owned[t] >= MAX_OWNED || this.balance < cost || cost > cheap) break;
          this.balance -= cost;
          this.owned[t] += 1;
        }
        if (level >= AUTO_CHIPS_LEVEL && this.owned[t] > 0 && this.chips[t] < MAX_CHIP) {
          const cost = chipCost(t, this.chips[t], this.cur);
          if (this.balance >= cost && cost <= cheap) {
            this.balance -= cost;
            this.chips[t] += 1;
          }
        }
      }
    }

    toggleAutopilot() {
      this.autopilot = !this.autopilot;
      this.say(this.autopilot ? 'Autopilot ON: trained specialists buy for their tier'
        : 'Autopilot OFF: you buy everything yourself', this.autopilot ? 'success' : 'muted');
    }

    /** Credit 75% of the live data center's income for `seconds` away (whole seconds). */
    applyOffline(seconds) {
      const whole = Math.floor(seconds);
      if (!(whole > 0)) return 0n;
      const earned = BigInt(whole) * this.siteIncome(this.sites) * OFFLINE_NUM / OFFLINE_DEN;
      if (earned > 0n) {
        this.siteBalance[this.sites] += earned;
        this.away = { seconds, earned };
        this.say('Welcome back! Away ' + fmtDuration(seconds) + ', earned $' + fmt(earned) +
          ' (' + (OFFLINE_NUM * 100n / OFFLINE_DEN) + '% offline rate)', 'warning');
      }
      return earned;
    }

    // -- crises (all relative to `cur`, which tick() points at the live site) -----------

    /** The hired crew member who can handle this severity and responds fastest. */
    fixerFor(sev) {
      let best = null;
      let bestTime = 0;
      for (let role = 0; role < STAFF.length; role++) {
        if (this.staff[role] >= 0 && STAFF[role][3] >= sev) {
          const t = responseTime(role, this.staff[role]);
          if (best === null || t < bestTime) { best = role; bestTime = t; }
        }
      }
      return best;
    }

    updateCrisis() {
      const c = this.crisis;
      if (c !== null) {
        if (c.fixer === null) { // someone may have been hired since it started
          c.fixer = this.fixerFor(c.sev);
          if (c.fixer !== null) c.eta = responseSecs(c.fixer, this.staff[c.fixer]);
        }
        if (c.fixer !== null) {
          c.eta -= 1;
          if (c.eta <= 0) this.resolve(c.fixer);
        }
        return;
      }
      const unit = INCOME_SCALE ** BigInt(this.cur); // relative to this data center's size
      if (this.baseIncome >= CRISIS_MIN_INCOME * unit && this.rng.random() < 1 / CRISIS_MEAN) {
        this.spawnCrisis();
      }
    }

    spawnCrisis() {
      const sevs = [1];
      if (this.racks >= 5) sevs.push(2);
      if (this.rawIncome(this.cur) >= 200n * INCOME_SCALE ** BigInt(this.cur)) sevs.push(3);
      const sev = sevs[this.rng.weighted(sevs.map((s) => CRISIS_WEIGHT[s]))];
      const list = CRISES[sev];
      const title = list[this.rng.index(list.length)];
      const fixer = this.fixerFor(sev);
      const eta = fixer !== null ? responseSecs(fixer, this.staff[fixer]) : null;
      this.crisis = { title, sev, fixer, eta };
      const [num, den] = CRISIS_FACTOR[sev];
      this.say('! ' + title + ' (income -' + (100 - Math.floor(num * 100 / den)) + '%)', 'error');
    }

    resolve(fixer) {
      if (this.crisis === null) return;
      const title = this.crisis.title;
      this.crisis = null;
      const who = fixer === null ? 'You' : STAFF[fixer][0];
      const quip = FIX_QUIPS[this.rng.index(FIX_QUIPS.length)];
      this.say('✓ ' + who + " fixed '" + title + "' " + quip, 'success');
    }

    fix() {
      if (this.crisis === null) this.say('Nothing to fix. For now.', 'muted');
      else this.resolve(null);
    }

    // -- actions ------------------------------------------------------------

    view(name) {
      if (SIDES.includes(name)) this.side = name;
    }

    /** Number key i (0-based) on whichever card is showing. */
    pick(i) {
      if (this.side === 'servers') this.buy(i);
      else if (this.side === 'sites') { // six per page; the page follows the one you are in
        const k = Math.floor(this.cur / 6) * 6 + i;
        if (i >= 0 && i < 6 && k <= this.sites) {
          this.side = 'servers';
          this.goto(k);
        }
      } else if (this.side === 'chips') this.buyChip(i);
      else if (this.side === 'staff' && i < STAFF.length) this.hire(i);
    }

    buy(tier) {
      if (this.guardReadOnly()) return;
      if (!(tier >= 0 && tier < TIERS.length)) return;
      const name = TIERS[tier][0];
      const cost = costOf(tier, this.owned[tier], this.cur);
      if (this.owned[tier] >= MAX_OWNED) {
        this.say(name + ": that's enough, truly", 'muted');
      } else if (this.balance >= cost) {
        this.balance -= cost;
        this.owned[tier] += 1;
        this.say('+ ' + name + '  -$' + fmt(cost), 'success');
      } else {
        this.say('! need $' + fmt(cost) + ' for ' + name, 'error');
      }
    }

    buyChip(tier) {
      if (this.guardReadOnly()) return;
      if (!(tier >= 0 && tier < TIERS.length)) return;
      const level = this.chips[tier];
      const name = TIERS[tier][0];
      if (level >= MAX_CHIP) {
        this.say(name + ' chips are maxed out', 'muted');
        return;
      }
      const cost = chipCost(tier, level, this.cur);
      if (this.owned[tier] === 0) {
        this.say('! buy a ' + name + ' first', 'error');
      } else if (this.balance < cost) {
        this.say('! need $' + fmt(cost) + ' for the ' + chipName(tier, level), 'error');
      } else {
        this.balance -= cost;
        this.chips[tier] += 1;
        this.say('+ ' + chipName(tier, level) + ': ' + name + ' income x' + CHIP_BOOST, 'success');
      }
    }

    /** Hire a role (level -1 -> 0) or train it (+1 level): the same key does both. */
    hire(role) {
      if (this.guardReadOnly()) return;
      if (!(role >= 0 && role < STAFF.length)) return;
      const level = this.staff[role];
      const [name, , tagline] = STAFF[role];
      if (level >= MAX_STAFF) {
        this.say(name + ' is already a 10x legend', 'muted');
        return;
      }
      const cost = staffCost(role, level, this.cur);
      if (this.balance < cost) {
        this.say('! need $' + fmt(cost) + ' for the ' + name, 'error');
        return;
      }
      this.balance -= cost;
      this.staff[role] += 1;
      if (level < 0) {
        this.say('+ Hired a ' + name + ': ' + tagline + ' (runs ' + TIERS[role][0] + ')', 'success');
      } else {
        this.say('+ Trained the ' + name + ' (Lv ' + this.staff[role] + ')', 'success');
      }
    }

    train(role) { this.hire(role); }

    /**
     * Prestige: the live data center is frozen as it is (its money stays in it) and the
     * next one starts from scratch. Fame and status carry over.
     */
    relocate() {
      if (this.sites >= MAX_SITES) {
        this.say('You own the multiverse. For now.', 'muted');
        return;
      }
      const cost = expandCost(this.sites);
      if (this.cur !== this.sites) {
        this.say('! relocate from your newest data center (press ] to go to #' +
          (this.sites + 1) + ')', 'error');
        return;
      }
      if (this.balance < cost) {
        this.say('! need $' + fmt(cost) + ' to relocate to ' + siteName(this.sites + 1), 'error');
        return;
      }
      const gain = fameGain(this.balance, this.sites);
      const before = rankOf(this.fame)[0];
      this.fame += gain;
      this.sites += 1;
      this.siteOwned.push(new Array(TIERS.length).fill(0));
      this.siteChips.push(new Array(TIERS.length).fill(0));
      this.siteBalance.push(startBalance(this.sites));
      this.siteStaff.push(new Array(STAFF.length).fill(-1));
      this.siteNames.push('');
      this.cur = this.sites;
      this.crisis = null;
      this.side = 'servers';
      this.say('★ Relocated to ' + this.siteLabel(this.sites) + '! +' + fmt(gain) + ' Fame (+' +
        fmt(BigInt(FAME_BONUS) * gain) + '% income)', 'success');
      const after = rankOf(this.fame)[0];
      if (after !== before) this.say('★ Promoted: ' + after + '!', 'warning');
    }

    goto(k) {
      if (isInt(k) && k >= 0 && k <= this.sites && k !== this.cur) {
        this.cur = k;
        this.say('Now at #' + (k + 1) + ' ' + this.siteLabel(k) +
          (k !== this.sites ? ' (decommissioned, view only)' : ''), 'muted');
      }
    }

    prev() { this.goto(this.cur - 1); }

    next() { this.goto(this.cur + 1); }

    /** Give data center k your own name (blank = the default). False if the name is refused. */
    renameSite(k, name) {
      if (!isInt(k) || k < 0 || k > this.sites) return false;
      if (typeof name !== 'string' || !DC_NAME_RE.test(name)) return false;
      this.siteNames[k] = name;
      this.say('Data center #' + (k + 1) + " is now '" + this.siteLabel(k) + "'", 'success');
      return true;
    }

    // Names the UI of the first web port used.
    buyServer(tier) { this.buy(tier); }

    hireStaff(role) { this.hire(role); }

    expand() { this.relocate(); }

    gotoSite(k) { this.goto(k); }

    stepSite(delta) { this.goto(this.cur + delta); }

    // -- persistence --------------------------------------------------------

    /** Plain object for JSON.stringify (same keys as game.py); BigInts become decimal strings. */
    toJSON() {
      return {
        site_balance: this.siteBalance.map((b) => b.toString()),
        site_owned: this.siteOwned.map((a) => a.slice()),
        site_chips: this.siteChips.map((a) => a.slice()),
        site_staff: this.siteStaff.map((a) => a.slice()),
        fame: this.fame.toString(),
        sites: this.sites,
        cur: this.cur,
        autopilot: this.autopilot,
        site_names: this.siteNames.slice(),
        online: { asked: this.online.asked, joined: this.online.joined,
          name: this.online.name, token: this.online.token },
        theme: this.theme,
        saved_at: this.now(),
      };
    }

    /**
     * Build a game from a parsed save, a JSON string, or garbage. Never throws: anything
     * invalid falls back to the defaults. Applies offline earnings.
     */
    static fromJSON(raw, opts = {}) {
      let game;
      try {
        game = new Game(opts);
        let data = raw;
        if (typeof raw === 'string') {
          try { data = JSON.parse(raw); } catch (e) { data = null; }
        }
        game.load(isObject(data) ? data : {});
      } catch (e) {
        game = new Game(opts);
      }
      return game;
    }

    load(data) {
      const n = TIERS.length;
      const s = data.sites;
      this.sites = isInt(s) && s >= 0 && s <= MAX_SITES ? s : 0;
      const list = (x) => (Array.isArray(x) ? x : []);
      const so = list(data.site_owned);
      const sc = list(data.site_chips);
      const sb = list(data.site_balance);
      const ss = list(data.site_staff);
      const names = list(data.site_names);
      this.siteOwned = [];
      this.siteChips = [];
      this.siteBalance = [];
      this.siteStaff = [];
      this.siteNames = [];
      for (let k = 0; k <= this.sites; k++) {
        this.siteOwned.push(cleanLevels(so[k], n, 0, MAX_OWNED, 0));
        this.siteChips.push(cleanLevels(sc[k], n, 0, MAX_CHIP, 0));
        const b = parseBig(sb[k]);
        this.siteBalance.push(b !== null ? b : startBalance(k));
        this.siteStaff.push(cleanLevels(ss[k], STAFF.length, -1, MAX_STAFF, -1));
        const label = names[k];
        this.siteNames.push(typeof label === 'string' && DC_NAME_RE.test(label) ? label : '');
      }
      const fame = parseBig(data.fame);
      this.fame = fame !== null ? fame : 0n;
      const cur = data.cur;
      this.cur = isInt(cur) && cur >= 0 && cur <= this.sites ? cur : this.sites;
      const theme = data.theme;
      this.theme = typeof theme === 'string' && theme.length > 0 && theme.length <= 64
        ? theme : DEFAULT_THEME;
      // Autopilot is on for a brand-new game, off for an existing save.
      this.autopilot = typeof data.autopilot === 'boolean' ? data.autopilot
        : Object.keys(data).length === 0;
      const on = isObject(data.online) ? data.online : {};
      const valid = typeof on.name === 'string' && NAME_RE.test(on.name) &&
        typeof on.token === 'string' && TOKEN_RE.test(on.token);
      this.online = {
        asked: on.asked === true,
        joined: valid && on.joined === true,
        name: valid ? on.name : '',
        token: valid ? on.token : '',
      };
      const at = data.saved_at;
      if (typeof at === 'number' && Number.isFinite(at) && at > 0) {
        this.applyOffline(Math.max(0, this.now() - at));
      }
    }
  }

  return {
    TIERS, GROWTH_PCT, MILESTONES, CHIP_FAMILIES, CHIP_EDITIONS, MAX_CHIP, CHIP_BASE,
    CHIP_GROWTH, CHIP_BOOST, STAFF, CREW_INITIALS, AUTO_SERVERS_LEVEL, DOUBLE_LEVELS,
    AUTO_CHIPS_LEVEL, AUTO_BUYS_PER_TICK, AUTO_AFFORD_DIV, PERKS, STAFF_SCOPE, MAX_STAFF,
    RESPONSE_DECAY, STAFF_BONUS, SITE_NAMES, EXPAND_BASE, EXPAND_SCALE, INCOME_SCALE,
    COST_SCALE, START_BALANCE, MAX_SITES, MAX_OWNED, MAX_BIG, FAME_BONUS, RANKS, CRISES,
    CRISIS_FACTOR, CRISIS_WEIGHT, CRISIS_MEAN, CRISIS_MIN_INCOME, FIX_QUIPS, OFFLINE_NUM,
    OFFLINE_DEN, DEFAULT_THEME, LED_PERIOD, CELL_W, CELL_H, SPRITES, SUFFIXES,
    siteName, expandCost, costOf, milestoneMult, nextMilestone, tierIncome, crewMultiplier,
    startBalance, isqrt, fameGain, roman, rankOf, chipName, chipCost, staffCost,
    responseTime, responseSecs, restoreSite, fmt, fmtDuration, parseBig, cleanLevels, Game,
    makeRng, NAME_RE, TOKEN_RE, DC_NAME_RE, MAX_FAME_ONLINE, SUBMIT_EVERY, BOARD_EVERY,
    makeToken, submitPayload, newOnlineState, snapshotOf, handleSubmit, maybeSubmit,
    boardFromResults, refreshBoard, boardRows,
  };
});
