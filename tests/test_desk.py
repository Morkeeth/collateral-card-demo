import sys
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "proof"))
from collateral_card.desk import Book, Limits, view, check_spend, after_reopen, DEMO_BOOK, DEMO_LIMITS

AS_OF = "2026-11-09T00:05:00Z"
WEEKEND = "2026-11-06"


class DeskViewTest(TestCase):
    def test_positions_are_priced_at_both_prices(self):
        desk = view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF)
        nvda = next(p for p in desk["positions"] if p["stock"] == "NVDAc")
        self.assertEqual(nvda["lending_value_usd"], "375.93")
        self.assertEqual(nvda["market_value_usd"], "356.93")
        self.assertEqual(nvda["gap_percent"], "-5.05")
        self.assertEqual(len(desk["positions"]), 3)

    def test_weekend_health_is_lower_than_what_the_lender_sees(self):
        desk = view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF)
        self.assertEqual(desk["health"]["lender_view"], "1.413")
        self.assertEqual(desk["health"]["weekend_view"], "1.358")
        self.assertLess(float(desk["health"]["weekend_view"]), float(desk["health"]["lender_view"]))

    def test_concentration_limit_is_flagged(self):
        desk = view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF)
        self.assertIn("NVDAc", [b["stock"] for b in desk["breaches"]])
        self.assertEqual(desk["exposure"]["largest_stock"], "NVDAc")

    def test_safe_spend_uses_the_weekend_price(self):
        desk = view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF)
        self.assertEqual(desk["spend"]["safe_now_usd"], "16.31")
        self.assertEqual(desk["spend"]["lender_would_allow_usd"], "31.46")


class SpendCheckTest(TestCase):
    def test_small_spend_is_allowed(self):
        d = check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, "5.00")
        self.assertEqual(d["action"], "ALLOW")

    def test_spend_the_frozen_price_allows_is_held_until_repay(self):
        d = check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, "25.00")
        self.assertEqual(d["action"], "REPAY_FIRST")
        self.assertEqual(d["repay_usd"], "8.69")
        self.assertTrue(d["lender_would_allow"])

    def test_spend_without_cash_to_repay_is_refused(self):
        poor = Book(positions=DEMO_BOOK.positions, debt_usd=DEMO_BOOK.debt_usd, cash_usd="2.00",
                    spent_this_week_usd="0")
        d = check_spend(poor, DEMO_LIMITS, WEEKEND, AS_OF, "25.00")
        self.assertEqual(d["action"], "REFUSE")

    def test_weekly_cap_refuses_before_health(self):
        d = check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, "60.00")
        self.assertEqual(d["action"], "REFUSE")
        self.assertIn("weekly", d["reason"])

    def test_bad_amounts_are_refused(self):
        for amount in ("0", "-3", "abc"):
            with self.assertRaises(ValueError):
                check_spend(DEMO_BOOK, DEMO_LIMITS, WEEKEND, AS_OF, amount)

    def test_reopened_feed_is_refused(self):
        with self.assertRaises(ValueError):
            view(DEMO_BOOK, DEMO_LIMITS, WEEKEND, "2026-11-09T02:00:00Z")


class ReopenTest(TestCase):
    def test_reopen_outcome_is_reported_as_measured(self):
        # The real reopen fell less than the weekend pool price. Both paths stay above the
        # floor; the desk path keeps more margin. The test pins the measured numbers.
        r = after_reopen(DEMO_BOOK, DEMO_LIMITS, WEEKEND, "25.00")
        self.assertEqual(r["without_desk"]["health"], "1.303")
        self.assertEqual(r["with_desk"]["health"], "1.334")
        self.assertFalse(r["floor_breached_without_desk"])
