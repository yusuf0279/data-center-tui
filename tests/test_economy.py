import unittest

from helpers import game


class Economy(unittest.TestCase):
    def test_tables_are_consistent(self) -> None:
        n = len(game.TIERS)
        self.assertEqual(n, 10)
        for table in (game.GROWTH_PCT, game.TIER_HUES, game.SPRITES, game.CHIP_FAMILIES, game.STAFF):
            self.assertEqual(len(table), n)
        self.assertEqual(len(game.CREW_INITIALS), n)
        for sprite in game.SPRITES:
            self.assertTrue(len(sprite) == 6 and all(len(row) == 6 for row in sprite))

    def test_costs_and_scaling(self) -> None:
        self.assertEqual(game.cost_of(0, 0), 60)
        self.assertEqual(game.cost_of(0, 1), 64)  # +7%, floored
        self.assertEqual(game.cost_of(0, 0, site=1), 60 * 1250)
        self.assertEqual(game.expand_cost(0), 10**16)
        self.assertEqual(game.expand_cost(2), 10**16 * 1000**2)
        self.assertEqual(game.start_balance(3), 500 * 1250**3)

    def test_milestones_double_income(self) -> None:
        self.assertEqual(game.milestone_mult(24), 1)
        self.assertEqual(game.milestone_mult(25), 2)
        self.assertEqual(game.milestone_mult(50), 4)
        self.assertEqual(game.tier_income(0, 25, 0), 25 * 2 * 2)
        self.assertEqual(game.next_milestone(24), 25)
        self.assertIsNone(game.next_milestone(4000))

    def test_chips(self) -> None:
        names = [game.chip_name(t, level) for t in range(10) for level in range(game.MAX_CHIP)]
        self.assertEqual(len(set(names)), 200)
        self.assertLessEqual(max(map(len, names)), 28)  # must fit the card
        self.assertEqual(game.chip_cost(0, 0), 60 * game.CHIP_BASE)
        self.assertEqual(game.chip_cost(0, 3), 60 * game.CHIP_BASE * game.CHIP_GROWTH**3)

    def test_crew_multiplier(self) -> None:
        self.assertEqual([game.crew_multiplier(lv) for lv in (-1, 0, 3, 4, 7, 8, 10)], [1, 1, 1, 2, 2, 4, 4])

    def test_ranks(self) -> None:
        name = lambda fame: game.rank_of(fame)[0]  # noqa: E731
        self.assertEqual(name(0), "Nobody")
        self.assertEqual(name(1), "Intern")
        self.assertEqual(name(179), "Tech Billionaire")
        self.assertEqual(name(180), "Tech Overlord")
        self.assertEqual(name(359), "Tech Overlord")
        self.assertEqual(name(360), "Tech Overlord II")
        self.assertEqual(name(720), "Tech Overlord III")
        self.assertEqual(game.rank_of(10**50)[0].startswith("Tech Overlord"), True)

    def test_fame_gain(self) -> None:
        threshold = game.expand_cost(0)
        self.assertEqual(game.fame_gain(threshold - 1, 0), 0)
        self.assertEqual(game.fame_gain(threshold, 0), 1)
        self.assertEqual(game.fame_gain(4 * threshold, 0), 2)

    def test_fmt(self) -> None:
        self.assertEqual([game.fmt(n) for n in (0, 999, 1234, 999_995, 10**9)],
                         ["0", "999", "1.23K", "1.00M", "1.00B"])
        self.assertTrue(game.fmt(10**40).endswith("e40"))
        self.assertEqual(game.fmt(10**600).count("e"), 1)

    def test_restore_site_never_exceeds_its_target(self) -> None:
        for site in (0, 1, 5, 40):
            for target in (0, 1, 10**4, 10**9, 10**15, 10**30):
                owned, chips = game.restore_site(site, target, 35)
                got = sum(game.tier_income(t, n, c, site) for t, (n, c) in enumerate(zip(owned, chips)))
                self.assertLessEqual(got * 135, target * 100 + 135)  # got * (100 + bonus) / 100 <= target


if __name__ == "__main__":
    unittest.main()
