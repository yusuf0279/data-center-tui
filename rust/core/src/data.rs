//! Game tables and constants (copied verbatim from `web/core.js`).

use num_bigint::BigInt;

/// name, base cost, income/sec (for the first data center).
pub const TIERS: [(&str, u64, u64); 10] = [
    ("Budget VPS", 60, 2),
    ("Compute Node", 840, 14),
    ("GPU Cluster", 9_600, 80),
    ("AI Datacenter", 108_000, 450),
    ("Quantum Farm", 1_200_000, 2_500),
    ("Orbital Cloud", 14_400_000, 15_000),
    ("Fusion Campus", 108_000_000, 90_000),
    ("Dyson Swarm", 864_000_000, 540_000),
    ("Neutron Star Farm", 6_400_000_000, 3_200_000),
    ("Black Hole Colo", 47_500_000_000, 19_000_000),
];
/// Each extra copy of a tier costs this many percent of the previous one.
pub const GROWTH_PCT: [u64; 10] = [107, 108, 109, 110, 111, 112, 112, 112, 113, 113];
/// Owning this many of a tier doubles that tier's income.
pub const MILESTONES: [u32; 12] = [25, 50, 100, 200, 300, 400, 500, 1000, 1500, 2000, 3000, 4000];
pub const MAX_OWNED: u32 = 4000;

pub const CHIP_FAMILIES: [[&str; 5]; 10] = [
    ["GeForceless 1030", "Radeoff 6400", "Vague 8 (Hopeful)", "G-Tex 750", "Radeoff HD 7000"],
    ["Rizzen 5 5600", "Rizzen 9 Garden", "Thread-Shred 3990", "Epick Milano", "Rizzen Z Handheld"],
    ["RTZ 3090", "RTZ 4090", "RTZ 5090 (Paper)", "Colossus RTZ", "Leather Jacket Ed."],
    ["A-100", "H-100 (a kidney)", "Bee-200 (melts)", "GB-200 (Rack-ish)", "H-200 (sold out)"],
    ["MX250X", "MX300X (eXpensive)", "MX325-ception", "MX350 Schrödinger", "Insti-Zero"],
    ["Ruby Ultra", "Rizzen Space Ed.", "DGZ Moonbase", "Physicist (TBD)", "Sphere GPU"],
    ["Tokamak TK-1", "Stellarator S7", "ITER Junior", "Cold Fusion (lol)", "Plasma Rack"],
    ["Solar Sail", "Swarm Node", "Mirror Array", "Mercury Strip Mine", "Matrioshka Lite"],
    ["Pulsar Clock", "Magnetar Mk I", "Neutronium Sink", "Quark Fabric", "Strange Matter"],
    ["Event Horizon", "Hawking Cooler", "Singularity Rack", "Penrose Engine", "Info Paradox"],
];
pub const CHIP_EDITIONS: [&str; 4] = ["", " Ti", " Super", " Ultra Max"];
pub const MAX_CHIP: u32 = 20;
/// Level-0 chip costs this many times the tier's base cost.
pub const CHIP_BASE: u64 = 2;
/// Each chip level costs this many times the one before.
pub const CHIP_GROWTH: u64 = 4;
pub const CHIP_BOOST: u64 = 2;

/// name, hire cost, tagline, highest crisis severity handled, base response (s).
pub const STAFF: [(&str, u64, &str, u8, f64); 10] = [
    ("Vibecoder", 5_000, "ships it without reading the diff", 1, 10.0),
    ("Prompt Engineer", 60_000, "negotiates with the model for you", 2, 9.0),
    ("Forward Deployed Engineer", 750_000, "lives on-site, expenses everything", 3, 8.0),
    ("Site Reliability Engineer", 10_000_000, "has seen things", 3, 6.0),
    ("10x Engineer", 150_000_000, "does not exist, allegedly", 3, 4.0),
    ("Chief Hype Officer", 2_500_000_000, "raises a round to fix it", 3, 3.0),
    ("Distinguished Engineer", 40_000_000_000, "has opinions about your architecture", 3, 2.5),
    ("Chief AI Officer", 700_000_000_000, "puts AI in the press release", 3, 2.0),
    ("Head of Synergy", 12_000_000_000_000, "aligns stakeholders at light speed", 3, 1.5),
    ("Founder Mode CEO", 200_000_000_000_000, "is personally in the weeds", 3, 1.0),
];
pub const CREW_INITIALS: &str = "VPFSXCDAHO";
pub const AUTO_SERVERS_LEVEL: i32 = 2;
pub const DOUBLE_LEVELS: [i32; 2] = [4, 8];
pub const AUTO_CHIPS_LEVEL: i32 = 6;
pub const AUTO_BUYS_PER_TICK: u32 = 10;
pub const AUTO_AFFORD_DIV: u64 = 50;
pub const PERKS: [(i32, &str); 4] = [
    (AUTO_SERVERS_LEVEL, "buys cheap servers"),
    (DOUBLE_LEVELS[0], "x2 its income"),
    (AUTO_CHIPS_LEVEL, "buys cheap chips"),
    (DOUBLE_LEVELS[1], "x2 its income"),
];
pub const STAFF_SCOPE: [&str; 3] = ["minor incidents", "outages and below", "everything"];
pub const MAX_STAFF: i32 = 10;
pub const RESPONSE_DECAY: f64 = 0.8;
pub const STAFF_BONUS: i64 = 5;

pub const SITE_NAMES: [&str; 10] = [
    "Garage in Palo Alto",
    "Abandoned Mall in Ohio",
    "Decommissioned Missile Silo",
    "Arctic Bunker (free cooling)",
    "Undersea Pod off Iceland",
    "Lunar Regolith Campus",
    "Dyson Swarm Annex",
    "Pocket Universe",
    "Heat Death Colo",
    "The Cloud (Actually Water Vapor)",
];
/// `EXPAND_BASE` is 10^16.
pub const EXPAND_BASE: u64 = 10_000_000_000_000_000;
pub const EXPAND_SCALE: u64 = 1000;
pub const INCOME_SCALE: u64 = 1000;
pub const COST_SCALE: u64 = 1250;
pub const START_BALANCE: u64 = 500;
pub const MAX_SITES: usize = 60;
/// Percent income per Fame point.
pub const FAME_BONUS: u64 = 2;
/// Lifetime Fame needed for each title; past the last, each numeral level doubles it.
pub const RANKS: [(u64, &str); 12] = [
    (0, "Nobody"),
    (1, "Intern"),
    (3, "Junior Dev"),
    (6, "Senior Dev"),
    (10, "Tech Lead"),
    (15, "Engineering Manager"),
    (25, "Director"),
    (40, "VP of Engineering"),
    (60, "CTO"),
    (90, "Tech CEO"),
    (130, "Tech Billionaire"),
    (180, "Tech Overlord"),
];
/// Exclusive upper bound for stored amounts: 10^600.
pub fn max_big() -> BigInt {
    BigInt::from(10u32).pow(600)
}

/// Crisis titles by severity (index 0 = severity 1).
pub const CRISES: [[&str; 3]; 3] = [
    [
        "CI is stuck on a flaky test",
        "Janitor unplugged a rack to vacuum",
        "Someone pasted the API key into Slack",
    ],
    [
        "Power outage: the grid is down",
        "Cooling failed: the AC is a fan and a prayer",
        "Cloud bill spiked 40x overnight",
    ],
    [
        "GPU shortage: scalpers bought every one",
        "Intern force-pushed to main on a Friday",
        "Solar flare fried the Orbital Cloud",
    ],
];
/// Income multiplier (num, den) by severity (index 0 = severity 1).
pub const CRISIS_FACTOR: [(u64, u64); 3] = [(1, 2), (1, 4), (0, 1)];
/// Spawn weight by severity (index 0 = severity 1).
pub const CRISIS_WEIGHT: [u32; 3] = [5, 3, 2];
pub const CRISIS_MEAN: u32 = 120;
pub const CRISIS_MIN_INCOME: u64 = 10;
pub const FIX_QUIPS: [&str; 6] = [
    "by turning it off and on again",
    "with one prompt and zero tests",
    "by rewriting it in Rust",
    "by blaming the intern",
    "with a hotfix straight to prod",
    "by asking the model nicely",
];
pub const OFFLINE_NUM: u64 = 3;
pub const OFFLINE_DEN: u64 = 4;
pub const LOG_LIMIT: usize = 300;
