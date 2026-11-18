//! Exact big-integer port of the My Data Center game model.
//!
//! Mirrors `data_center_tui/game.py` and `web/core.js`. All money maths is
//! `BigInt` with Python floor-division semantics; the only float is the
//! crisis response time.

pub mod color;
pub mod data;
pub mod econ;
pub mod fmt;
pub mod online;
pub mod render;
pub mod save;
pub mod state;
