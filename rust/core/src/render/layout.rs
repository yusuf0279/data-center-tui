//! Hall layout: tier headers and rack rows laid end to end, which blocks are on screen,
//! and the scroll rules. Pure functions with explicit inputs; a port of `Block`, `Layout`,
//! `Hall.make_blocks`, `Hall.rack_layout` and `DataCenter.action_hall` (commit edf443e, with the crew margin).

use crate::data::MAX_OWNED;

/// Pixel columns per rack: 6x6 sprite plus one gap column.
pub const CELL_W: usize = 7;
/// Pixel rows per rack: sprite plus the shadow row.
pub const CELL_H: usize = 8;
/// Terminal lines per tier header.
pub const HEADER_LINES: usize = 1;
/// Terminal lines per rack row.
pub const RACK_LINES: usize = CELL_H / 2;
/// A crew sprite: 5x6 pixels.
pub const CREW_W: usize = 5;
/// Pixel columns reserved right of the racks for the crew: the sprite plus a gap column.
pub const CREW_MARGIN: usize = CREW_W + 1;

/// What a block of the hall is.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    /// A tier header line.
    Head,
    /// One row of racks.
    Rack,
}

impl Kind {
    /// The name the Python game uses ("head" / "rack").
    pub fn as_str(self) -> &'static str {
        match self {
            Kind::Head => "head",
            Kind::Rack => "rack",
        }
    }
}

/// One stretch of the hall: a tier header line or one row of racks.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Block {
    pub kind: Kind,
    pub tier: usize,
    /// Index of the first rack (racks are numbered cheapest tier first).
    pub first: usize,
    /// Racks in this row (0 for a header).
    pub count: usize,
    /// Terminal line the block starts on, from the top of the whole hall.
    pub line0: usize,
    pub height: usize,
    /// Rack-row number (0-based); a header takes the number of the row below it.
    pub row: usize,
}

/// Every block of the whole hall for one column count.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Blocks {
    pub blocks: Vec<Block>,
    pub total_lines: usize,
    /// Index of each tier's header block (-1: none owned).
    pub tier_block: Vec<i64>,
    /// Index of each tier's first rack.
    pub tier_first: Vec<usize>,
}

/// Which blocks are visible: `blocks[start..end]`, all fully on screen.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    pub cols: usize,
    /// Terminal lines available.
    pub height: usize,
    pub blocks: Vec<Block>,
    pub start: usize,
    pub end: usize,
    pub total_lines: usize,
    pub total_rows: usize,
    pub tier_block: Vec<i64>,
    pub tier_first: Vec<usize>,
    /// Pixel columns kept free right of the racks for the crew sprites.
    pub reserve: usize,
}

/// A scroll key of the hall.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScrollKey {
    Up,
    Down,
    PageUp,
    PageDown,
    Home,
    End,
}

/// Every block of the hall for `cols` racks per row: headers and rack rows per tier.
pub fn make_blocks(owned: &[u64], cols: usize) -> Blocks {
    let cols = cols.max(1);
    let mut blocks = Vec::new();
    let mut tier_block = vec![-1_i64; owned.len()];
    let mut tier_first = vec![0_usize; owned.len()];
    let (mut line, mut row, mut first) = (0_usize, 0_usize, 0_usize);
    for (tier, &n) in owned.iter().enumerate() {
        tier_first[tier] = first;
        if n == 0 {
            continue;
        }
        let n = n as usize;
        tier_block[tier] = blocks.len() as i64;
        blocks.push(Block { kind: Kind::Head, tier, first, count: 0, line0: line,
                            height: HEADER_LINES, row });
        line += HEADER_LINES;
        for k in 0..n.div_ceil(cols) {
            blocks.push(Block { kind: Kind::Rack, tier, first: first + k * cols,
                                count: cols.min(n - k * cols), line0: line,
                                height: RACK_LINES, row });
            line += RACK_LINES;
            row += 1;
        }
        first += n;
    }
    Blocks { blocks, total_lines: line, tier_block, tier_first }
}

/// Place the hall in a `width` x `height` view and pick the visible blocks. `scroll` is the
/// player's block number; `None` follows the newest racks at the bottom. `staff` holds the
/// training level per tier (-1: not hired): once somebody who owns racks is hired a right
/// margin holds the crew, unless the hall is too narrow for a rack beside it. Rack counts above
/// `MAX_OWNED` (a value no save or game can hold) are clamped to it, so an out-of-domain
/// view cannot ask for gigabytes of picture.
pub fn rack_layout(owned: &[u64], staff: &[i32], width: usize, height: usize,
                   scroll: Option<usize>) -> Layout {
    let owned: Vec<u64> = owned.iter().map(|&n| n.min(u64::from(MAX_OWNED))).collect();
    let owned = owned.as_slice();
    let height = height.max(HEADER_LINES + RACK_LINES);
    let hired = owned.iter().zip(staff).any(|(&n, &s)| s >= 0 && n > 0);
    let mut reserve = if hired { CREW_MARGIN } else { 0 };
    if width < reserve + CELL_W {
        reserve = 0;
    }
    let mut cols = (width.saturating_sub(reserve) / CELL_W).max(1);
    let mut b = make_blocks(owned, cols);
    if b.total_lines > height {
        // a scrollbar needs one column of its own
        if reserve > 0 && width < reserve + 1 + CELL_W {
            reserve = 0; // no room for rack + margin + bar
        }
        cols = (width.saturating_sub(reserve + 1) / CELL_W).max(1);
        b = make_blocks(owned, cols);
    }
    let total_rows = b.blocks.iter().filter(|x| x.kind == Kind::Rack).count();
    let mut lay = Layout { cols, height, blocks: b.blocks, start: 0, end: 0,
                           total_lines: b.total_lines, total_rows,
                           tier_block: b.tier_block, tier_first: b.tier_first, reserve };
    lay.start = scroll.map_or(lay.max_start(), |s| s.min(lay.max_start()));
    lay.end = lay.start;
    let mut used = 0;
    while lay.end < lay.blocks.len() && used + lay.blocks[lay.end].height <= height {
        used += lay.blocks[lay.end].height;
        lay.end += 1;
    }
    // a header never ends the screen without a rack row under it
    if lay.end >= 1 && lay.end - 1 > lay.start && lay.blocks[lay.end - 1].kind == Kind::Head {
        lay.end -= 1;
    }
    lay
}

impl Layout {
    /// Does the hall need scrolling?
    pub fn scrolled(&self) -> bool {
        self.total_lines > self.height
    }

    /// Pixels across the whole picture: the racks plus the crew margin.
    pub fn grid_w(&self) -> usize {
        self.cols * CELL_W + self.reserve
    }

    /// Left pixel column of the crew sprites (the last rack's gap column is their gap).
    pub fn crew_x(&self) -> usize {
        self.cols * CELL_W
    }

    /// Terminal line of the first visible block (0 for an empty hall).
    pub fn top_line(&self) -> usize {
        self.blocks.get(self.start).map_or(0, |b| b.line0)
    }

    /// Terminal lines the visible blocks take.
    pub fn used(&self) -> usize {
        self.blocks[self.start..self.end].iter().map(|b| b.height).sum()
    }

    /// The first block of the last full screen (what the hall shows while following).
    pub fn max_start(&self) -> usize {
        let Some(mut s) = self.blocks.len().checked_sub(1) else { return 0 };
        while s > 0 && self.total_lines - self.blocks[s - 1].line0 <= self.height {
            s -= 1;
        }
        s
    }

    /// Pixel (x, y) of the top left of rack `idx` of `tier`, `None` if it is off screen.
    pub fn rack_xy(&self, idx: usize, tier: usize) -> Option<(usize, usize)> {
        let tb = *self.tier_block.get(tier)?;
        if tb < 0 {
            return None;
        }
        let rel = idx as i64 - self.tier_first[tier] as i64;
        let cols = self.cols as i64;
        let (k, c) = (rel.div_euclid(cols), rel.rem_euclid(cols)); // Python divmod
        let bi = tb + 1 + k;
        if bi < self.start as i64 || bi >= self.end as i64 {
            return None;
        }
        let line0 = self.blocks[bi as usize].line0;
        Some((c as usize * CELL_W, (line0 - self.top_line()) * 2 + 1))
    }

    /// The new `hall_scroll` after a scroll key (`None` = follow the newest racks): the
    /// target is clamped to `0..=max_start` and reaching `max_start` means follow.
    pub fn scroll_target(&self, key: ScrollKey) -> Option<usize> {
        let last = self.max_start() as i64;
        let start = self.start as i64;
        let floor = self.top_line() as i64 - self.height as i64;
        let back = self.blocks.iter().position(|b| b.line0 as i64 >= floor).unwrap_or(0) as i64;
        let target = match key {
            ScrollKey::Up => start - 1,
            ScrollKey::Down => start + 1,
            ScrollKey::PageUp => back.min(start - 1),
            ScrollKey::PageDown => (self.end as i64).max(start + 1),
            ScrollKey::Home => 0,
            ScrollKey::End => last,
        };
        let target = target.clamp(0, last);
        (target < last).then_some(target as usize)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_hall() {
        let lay = rack_layout(&[0; 10], &[-1; 10], 80, 24, None);
        assert!(lay.blocks.is_empty());
        assert_eq!((lay.start, lay.end, lay.max_start(), lay.used(), lay.top_line()), (0, 0, 0, 0, 0));
        assert_eq!(lay.tier_block, vec![-1; 10]);
        assert_eq!(lay.scroll_target(ScrollKey::Down), None);
    }

    #[test]
    fn rows_wrap_at_cols() {
        let b = make_blocks(&[9], 4);
        let counts: Vec<usize> = b.blocks.iter().map(|x| x.count).collect();
        assert_eq!(counts, vec![0, 4, 4, 1]);
        assert_eq!(b.total_lines, 1 + 3 * RACK_LINES);
    }

    #[test]
    fn follow_and_scroll_keys() {
        let lay = rack_layout(&[30, 20], &[-1; 10], 80, 10, None);
        assert_eq!(lay.start, lay.max_start());
        assert_eq!(lay.scroll_target(ScrollKey::End), None);
        let up = lay.scroll_target(ScrollKey::Up).expect("scrolled off the end");
        assert_eq!(up, lay.start - 1);
        assert_eq!(lay.scroll_target(ScrollKey::Home), Some(0));
        let top = rack_layout(&[30, 20], &[-1; 10], 80, 10, Some(0));
        assert_eq!(top.scroll_target(ScrollKey::Up), Some(0));
        assert_eq!(top.rack_xy(0, 0), Some((0, 3))); // under the header line: (1 - 0) * 2 + 1
        assert_eq!(top.rack_xy(0, 5), None);
    }
}
