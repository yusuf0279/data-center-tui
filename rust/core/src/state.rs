//! The game state machine: purchases, tick, autopilot, crises and relocation.
//!
//! Port of `Game` in `web/core.js` (persistence, online and UI state are out of scope).
//! Randomness goes through [`Rng`] at exactly the same call points as Python and JS.

use crate::data::*;
use crate::econ::*;
use crate::fmt::fmt;
use num_bigint::BigInt;
use num_integer::Integer;
use num_traits::Zero;

/// Random source: the three calls the game makes.
pub trait Rng {
    /// Float in [0, 1).
    fn random(&mut self) -> f64;
    /// Index into `weights`, chosen with those weights (Python's `random.choices`).
    fn weighted(&mut self, weights: &[u32]) -> usize;
    /// Integer in [0, n) (Python's `random.choice` on a list of n).
    fn index(&mut self, n: usize) -> usize;
}

/// Colour class of a log line.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Fg,
    Muted,
    Success,
    Error,
    Warning,
}

impl Kind {
    /// Lower-case name as used by the web port.
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Fg => "fg",
            Kind::Muted => "muted",
            Kind::Success => "success",
            Kind::Error => "error",
            Kind::Warning => "warning",
        }
    }
}

/// One log line.
#[derive(Clone, Debug)]
pub struct LogEntry {
    pub id: u64,
    pub text: String,
    pub kind: Kind,
}

/// An ongoing crisis in the live data center.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Crisis {
    pub title: &'static str,
    pub sev: u8,
    pub fixer: Option<usize>,
    pub eta: Option<i64>,
}

/// The whole game.
pub struct Game<R: Rng> {
    pub rng: R,
    /// Newest (live) data center; the others are decommissioned.
    pub sites: usize,
    /// The one being looked at.
    pub cur: usize,
    pub site_balance: Vec<BigInt>,
    pub site_owned: Vec<Vec<u32>>,
    pub site_chips: Vec<Vec<u32>>,
    pub site_staff: Vec<Vec<i32>>,
    pub site_names: Vec<String>,
    pub fame: BigInt,
    pub autopilot: bool,
    pub crisis: Option<Crisis>,
    pub phase: u64,
    pub log: Vec<LogEntry>,
    pub log_id: u64,
}

impl<R: Rng> Game<R> {
    /// A brand-new game (autopilot on).
    pub fn new(rng: R) -> Self {
        let mut g = Game {
            rng,
            sites: 0,
            cur: 0,
            site_balance: vec![BigInt::from(START_BALANCE)],
            site_owned: vec![vec![0; TIERS.len()]],
            site_chips: vec![vec![0; TIERS.len()]],
            site_staff: vec![vec![-1; STAFF.len()]],
            site_names: vec![String::new()],
            fame: BigInt::zero(),
            autopilot: true,
            crisis: None,
            phase: 0,
            log: Vec::new(),
            log_id: 0,
        };
        g.say("Welcome. Buy servers with keys 1-9 and 0. Press m for the menu.", Kind::Fg);
        g
    }

    // -- derived state ----------------------------------------------------

    /// Balance of the data center being viewed.
    pub fn balance(&self) -> &BigInt {
        &self.site_balance[self.cur]
    }

    /// Viewing a decommissioned data center: nothing earns there.
    pub fn read_only(&self) -> bool {
        self.cur != self.sites
    }

    /// Data center `k`'s income before the crew and Fame bonuses.
    pub fn raw_income(&self, k: usize) -> BigInt {
        (0..TIERS.len())
            .map(|t| {
                tier_income(t, self.site_owned[k][t], self.site_chips[k][t], k)
                    * crew_multiplier(self.site_staff[k][t])
            })
            .sum()
    }

    /// Percent income bonus from data center `k`'s crew.
    pub fn crew_bonus(&self, k: usize) -> u64 {
        STAFF_BONUS as u64
            * self.site_staff[k].iter().map(|&l| if l >= 0 { (l + 1) as u64 } else { 0 }).sum::<u64>()
    }

    /// What data center `k` earns per second while live (two separate floors).
    pub fn site_income(&self, k: usize) -> BigInt {
        let fame_bonus = BigInt::from(FAME_BONUS) * &self.fame;
        let step1 = (self.raw_income(k) * BigInt::from(100 + self.crew_bonus(k))).div_floor(&BigInt::from(100));
        (step1 * (BigInt::from(100) + fame_bonus)).div_floor(&BigInt::from(100))
    }

    /// Income of the viewed data center, ignoring crises.
    pub fn base_income(&self) -> BigInt {
        self.site_income(self.cur)
    }

    /// Income right now, including the crisis multiplier.
    pub fn income(&self) -> BigInt {
        let (num, den) = self.crisis.as_ref().map_or((1, 1), |c| CRISIS_FACTOR[c.sev as usize - 1]);
        (self.base_income() * BigInt::from(num)).div_floor(&BigInt::from(den))
    }

    /// Total servers in the viewed data center.
    pub fn racks(&self) -> u32 {
        self.site_owned[self.cur].iter().sum()
    }

    /// Custom name of data center `k`, or its default.
    pub fn site_label(&self, k: usize) -> String {
        let custom = self.site_names.get(k).map_or("", |s| s.trim());
        if custom.is_empty() { site_name(k) } else { custom.to_string() }
    }

    // -- log --------------------------------------------------------------

    /// Append a log line (the log keeps the newest `LOG_LIMIT`).
    pub fn say(&mut self, text: &str, kind: Kind) {
        self.log_id += 1;
        self.log.push(LogEntry { id: self.log_id, text: text.to_string(), kind });
        if self.log.len() > LOG_LIMIT {
            self.log.remove(0);
        }
    }

    fn guard_read_only(&mut self) -> bool {
        if self.read_only() {
            let msg = format!(
                "#{} is decommissioned: view only (your live data center is #{})",
                self.cur + 1,
                self.sites + 1
            );
            self.say(&msg, Kind::Muted);
        }
        self.read_only()
    }

    // -- game loop --------------------------------------------------------

    /// One second. The live data center works even while an old one is shown.
    pub fn tick(&mut self) {
        let view = self.cur;
        self.cur = self.sites;
        let inc = self.income();
        self.site_balance[self.cur] += inc;
        self.phase += 1;
        self.run_autopilot();
        self.update_crisis();
        self.cur = view;
    }

    /// Each specialist buys for its own tier: servers from Lv2, chips from Lv6.
    fn run_autopilot(&mut self) {
        if !self.autopilot {
            return;
        }
        let cur = self.cur;
        let cheap = self.site_income(cur).div_floor(&BigInt::from(AUTO_AFFORD_DIV));
        for t in 0..STAFF.len() {
            let level = self.site_staff[cur][t];
            if level < AUTO_SERVERS_LEVEL {
                continue;
            }
            for _ in 0..AUTO_BUYS_PER_TICK {
                let cost = cost_of(t, self.site_owned[cur][t], cur);
                if self.site_owned[cur][t] >= MAX_OWNED || self.site_balance[cur] < cost || cost > cheap {
                    break;
                }
                self.site_balance[cur] -= cost;
                self.site_owned[cur][t] += 1;
            }
            if level >= AUTO_CHIPS_LEVEL && self.site_owned[cur][t] > 0 && self.site_chips[cur][t] < MAX_CHIP {
                let cost = chip_cost(t, self.site_chips[cur][t], cur);
                if self.site_balance[cur] >= cost && cost <= cheap {
                    self.site_balance[cur] -= cost;
                    self.site_chips[cur][t] += 1;
                }
            }
        }
    }

    /// Flip autopilot and log it.
    pub fn toggle_autopilot(&mut self) {
        self.autopilot = !self.autopilot;
        if self.autopilot {
            self.say("Autopilot ON: trained specialists buy for their tier", Kind::Success);
        } else {
            self.say("Autopilot OFF: you buy everything yourself", Kind::Muted);
        }
    }

    // -- crises (relative to `cur`, which tick() points at the live site) ----

    /// The hired crew member who can handle `sev` and responds fastest.
    fn fixer_for(&self, sev: u8) -> Option<usize> {
        let staff = &self.site_staff[self.cur];
        let mut best: Option<(usize, f64)> = None;
        for role in 0..STAFF.len() {
            if staff[role] >= 0 && STAFF[role].3 >= sev {
                let t = response_time(role, staff[role]);
                if best.is_none_or(|(_, bt)| t < bt) {
                    best = Some((role, t));
                }
            }
        }
        best.map(|(role, _)| role)
    }

    fn update_crisis(&mut self) {
        if let Some(mut c) = self.crisis.take() {
            if c.fixer.is_none() {
                c.fixer = self.fixer_for(c.sev);
                if let Some(f) = c.fixer {
                    c.eta = Some(response_secs(f, self.site_staff[self.cur][f]));
                }
            }
            if let Some(f) = c.fixer {
                let eta = c.eta.unwrap_or(0) - 1;
                c.eta = Some(eta);
                if eta <= 0 {
                    self.crisis = Some(c);
                    self.resolve(Some(f));
                    return;
                }
            }
            self.crisis = Some(c);
            return;
        }
        let unit = BigInt::from(INCOME_SCALE).pow(self.cur as u32);
        if self.base_income() >= BigInt::from(CRISIS_MIN_INCOME) * unit
            && self.rng.random() < 1.0 / f64::from(CRISIS_MEAN)
        {
            self.spawn_crisis();
        }
    }

    fn spawn_crisis(&mut self) {
        let mut sevs: Vec<u8> = vec![1];
        if self.racks() >= 5 {
            sevs.push(2);
        }
        let unit = BigInt::from(INCOME_SCALE).pow(self.cur as u32);
        if self.raw_income(self.cur) >= BigInt::from(200u32) * unit {
            sevs.push(3);
        }
        let weights: Vec<u32> = sevs.iter().map(|&s| CRISIS_WEIGHT[s as usize - 1]).collect();
        let sev = sevs[self.rng.weighted(&weights)];
        let list = &CRISES[sev as usize - 1];
        let title = list[self.rng.index(list.len())];
        let fixer = self.fixer_for(sev);
        let eta = fixer.map(|f| response_secs(f, self.site_staff[self.cur][f]));
        self.crisis = Some(Crisis { title, sev, fixer, eta });
        let (num, den) = CRISIS_FACTOR[sev as usize - 1];
        let msg = format!("! {} (income -{}%)", title, 100 - num * 100 / den);
        self.say(&msg, Kind::Error);
    }

    fn resolve(&mut self, fixer: Option<usize>) {
        let Some(c) = self.crisis.take() else { return };
        let who = fixer.map_or("You", |f| STAFF[f].0);
        let quip = FIX_QUIPS[self.rng.index(FIX_QUIPS.len())];
        let msg = format!("\u{2713} {} fixed '{}' {}", who, c.title, quip);
        self.say(&msg, Kind::Success);
    }

    /// Fix the current crisis yourself.
    pub fn fix(&mut self) {
        if self.crisis.is_none() {
            self.say("Nothing to fix. For now.", Kind::Muted);
        } else {
            self.resolve(None);
        }
    }

    // -- actions ----------------------------------------------------------

    /// Buy one server of `tier`.
    pub fn buy(&mut self, tier: usize) {
        if self.guard_read_only() || tier >= TIERS.len() {
            return;
        }
        let cur = self.cur;
        let name = TIERS[tier].0;
        let owned = self.site_owned[cur][tier];
        let cost = cost_of(tier, owned, cur);
        if owned >= MAX_OWNED {
            self.say(&format!("{}: that's enough, truly", name), Kind::Muted);
        } else if self.site_balance[cur] >= cost {
            let msg = format!("+ {}  -${}", name, fmt(&cost));
            self.site_balance[cur] -= cost;
            self.site_owned[cur][tier] += 1;
            self.say(&msg, Kind::Success);
        } else {
            self.say(&format!("! need ${} for {}", fmt(&cost), name), Kind::Error);
        }
    }

    /// Buy the next chip level for `tier`.
    pub fn buy_chip(&mut self, tier: usize) {
        if self.guard_read_only() || tier >= TIERS.len() {
            return;
        }
        let cur = self.cur;
        let level = self.site_chips[cur][tier];
        let name = TIERS[tier].0;
        if level >= MAX_CHIP {
            self.say(&format!("{} chips are maxed out", name), Kind::Muted);
            return;
        }
        let cost = chip_cost(tier, level, cur);
        if self.site_owned[cur][tier] == 0 {
            self.say(&format!("! buy a {} first", name), Kind::Error);
        } else if self.site_balance[cur] < cost {
            self.say(&format!("! need ${} for the {}", fmt(&cost), chip_name(tier, level)), Kind::Error);
        } else {
            self.site_balance[cur] -= cost;
            self.site_chips[cur][tier] += 1;
            let msg = format!("+ {}: {} income x{}", chip_name(tier, level), name, CHIP_BOOST);
            self.say(&msg, Kind::Success);
        }
    }

    /// Hire a role (level -1 -> 0) or train it (+1 level).
    pub fn hire(&mut self, role: usize) {
        if self.guard_read_only() || role >= STAFF.len() {
            return;
        }
        let cur = self.cur;
        let level = self.site_staff[cur][role];
        let (name, _, tagline, _, _) = STAFF[role];
        if level >= MAX_STAFF {
            self.say(&format!("{} is already a 10x legend", name), Kind::Muted);
            return;
        }
        let cost = staff_cost(role, level, cur);
        if self.site_balance[cur] < cost {
            self.say(&format!("! need ${} for the {}", fmt(&cost), name), Kind::Error);
            return;
        }
        self.site_balance[cur] -= cost;
        self.site_staff[cur][role] += 1;
        let msg = if level < 0 {
            format!("+ Hired a {}: {} (runs {})", name, tagline, TIERS[role].0)
        } else {
            format!("+ Trained the {} (Lv {})", name, self.site_staff[cur][role])
        };
        self.say(&msg, Kind::Success);
    }

    /// Prestige: freeze the live data center and start the next one; Fame carries over.
    pub fn relocate(&mut self) {
        if self.sites >= MAX_SITES {
            self.say("You own the multiverse. For now.", Kind::Muted);
            return;
        }
        let cost = expand_cost(self.sites);
        if self.cur != self.sites {
            let msg = format!("! relocate from your newest data center (press ] to go to #{})", self.sites + 1);
            self.say(&msg, Kind::Error);
            return;
        }
        if *self.balance() < cost {
            let msg = format!("! need ${} to relocate to {}", fmt(&cost), site_name(self.sites + 1));
            self.say(&msg, Kind::Error);
            return;
        }
        let gain = fame_gain(self.balance(), self.sites);
        let before = rank_of(&self.fame).0;
        self.fame += &gain;
        self.sites += 1;
        self.site_owned.push(vec![0; TIERS.len()]);
        self.site_chips.push(vec![0; TIERS.len()]);
        self.site_balance.push(start_balance(self.sites));
        self.site_staff.push(vec![-1; STAFF.len()]);
        self.site_names.push(String::new());
        self.cur = self.sites;
        self.crisis = None;
        let msg = format!(
            "\u{2605} Relocated to {}! +{} Fame (+{}% income)",
            self.site_label(self.sites),
            fmt(&gain),
            fmt(&(BigInt::from(FAME_BONUS) * &gain))
        );
        self.say(&msg, Kind::Success);
        let after = rank_of(&self.fame).0;
        if after != before {
            self.say(&format!("\u{2605} Promoted: {}!", after), Kind::Warning);
        }
    }

    /// View data center `k` (ignored if out of range or already shown).
    pub fn goto(&mut self, k: i64) {
        if k >= 0 && (k as usize) <= self.sites && k as usize != self.cur {
            let k = k as usize;
            self.cur = k;
            let tail = if k != self.sites { " (decommissioned, view only)" } else { "" };
            let msg = format!("Now at #{} {}{}", k + 1, self.site_label(k), tail);
            self.say(&msg, Kind::Muted);
        }
    }

    /// View the previous data center.
    pub fn prev(&mut self) {
        self.goto(self.cur as i64 - 1);
    }

    /// View the next data center.
    pub fn next(&mut self) {
        self.goto(self.cur as i64 + 1);
    }
}

impl<R: Rng> Game<R> {
    /// Set the viewed data center's balance (test and tooling hook).
    pub fn set_balance(&mut self, v: BigInt) {
        let cur = self.cur;
        self.site_balance[cur] = v;
    }
}

