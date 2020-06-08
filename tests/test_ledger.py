import sqlite3
from contextlib import closing
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alphacairn.instruments import AccountSpec
from alphacairn.ledger import Ledger
from portfolio_fixtures import account_spec, event, trade, scenario_events


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "ledger.sqlite"
        self.ledger = Ledger(self.path, account_spec())

    def fund(self, amount="10000"):
        return self.ledger.apply(
            event("fund", "deposit", currency="USD", amount=amount)
        )

    def test_fifo_partial_sale_reconciles_hand_calculated_values(self):
        receipts = self.ledger.apply_batch(scenario_events()[:4])
        state = self.ledger.state()
        self.assertEqual(state["cash"]["USD"], "10194.00")
        self.assertEqual(
            state["positions"]["equity:demo-us"], {"quantity": "3", "basis": "360.60"}
        )
        self.assertEqual(
            [match["basis"] for match in receipts[3]["fifo_matches"]],
            ["1002.00", "240.40"],
        )
        self.assertEqual(
            state["accounts"]["USD"]["realized_income:equity:demo-us"], "-554.60"
        )
        self.assertTrue(self.ledger.audit()["passed"])

    def test_full_multi_currency_crypto_and_actions_scenario(self):
        self.ledger.apply_batch(scenario_events())
        state = self.ledger.state()
        self.assertEqual(state["cash"], {"EUR": "399.00", "USD": "7200.00"})
        self.assertEqual(
            state["positions"]["equity:demo-us"], {"quantity": "6", "basis": "360.60"}
        )
        self.assertEqual(
            state["positions"]["equity:demo-eu"], {"quantity": "10", "basis": "501.00"}
        )
        self.assertEqual(
            state["positions"]["crypto:demo"], {"quantity": "0.1", "basis": "2002.00"}
        )
        self.assertEqual(state["accounts"]["USD"]["dividend_income"], "-12.00")
        self.assertEqual(state["accounts"]["USD"]["withholding"], "3.00")
        self.assertTrue(Ledger(self.path).audit()["passed"])

    def test_duplicate_payload_is_idempotent_and_conflict_is_rejected(self):
        receipt = self.fund()
        repeated = self.ledger.apply(
            event("fund", "deposit", currency="USD", amount="10000.00")
        )
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(repeated["sequence"], receipt["sequence"])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.ledger.apply(event("fund", "deposit", currency="USD", amount="9999"))
        self.assertEqual(self.ledger.state()["cash"]["USD"], "10000.00")

    def test_atomic_batch_rolls_back_all_events_after_failure(self):
        with self.assertRaisesRegex(ValueError, "insufficient"):
            self.ledger.apply_batch(
                [
                    event("fund", "deposit", currency="USD", amount="100"),
                    trade("too-large", "buy", "2", "100"),
                ]
            )
        self.assertEqual(self.ledger.state()["last_sequence"], 0)
        self.assertEqual(self.ledger.state()["cash"], {})
        self.assertEqual(self.ledger.events(), [])

    def test_overspending_and_short_sale_leave_no_partial_state(self):
        self.fund("100")
        for item in [
            trade("buy", "buy", "1", "100", "1"),
            trade("sell", "sell", "1", "100"),
        ]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.ledger.apply(item)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "100.00")
        self.assertEqual(self.ledger.state()["positions"], {})
        self.assertEqual(self.ledger.state()["last_sequence"], 1)

    def test_same_cash_cannot_be_spent_twice_by_concurrent_writers(self):
        self.fund("600")

        def buy(number):
            try:
                Ledger(self.path).apply(trade("buy-" + str(number), "buy", "4", "100"))
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(buy, [1, 2]))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "200.00")
        self.assertTrue(self.ledger.audit()["passed"])

    def test_concurrent_duplicate_deliveries_create_one_event(self):
        def deposit(_):
            return Ledger(self.path).apply(
                event("same-fund", "deposit", currency="USD", amount="100")
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            receipts = list(pool.map(deposit, range(12)))
        self.assertEqual(sum(not receipt["duplicate"] for receipt in receipts), 1)
        self.assertEqual(self.ledger.state()["cash"]["USD"], "100.00")

    def test_split_preserves_basis_and_rejects_unrepresentable_fractional_lots(self):
        self.fund()
        self.ledger.apply(trade("buy", "buy", "3", "100", "3"))
        before = self.ledger.state()
        with self.assertRaisesRegex(ValueError, "increment"):
            self.ledger.apply(
                event(
                    "reverse",
                    "split",
                    instrument="equity:demo-us",
                    numerator=1,
                    denominator=2,
                )
            )
        self.assertEqual(self.ledger.state(), before)
        self.ledger.apply(
            event(
                "forward",
                "split",
                instrument="equity:demo-us",
                numerator=2,
                denominator=1,
            )
        )
        self.assertEqual(
            self.ledger.state()["positions"]["equity:demo-us"],
            {"quantity": "6", "basis": "303.00"},
        )

    def test_fifo_rounding_remainder_is_fully_released_on_close(self):
        self.fund("100")
        self.ledger.apply(trade("buy", "buy", "3", "0.01", "0.01"))
        for number in range(3):
            self.ledger.apply(trade("sell-" + str(number), "sell", "1", "0.02"))
        state = self.ledger.state()
        self.assertEqual(state["positions"], {})
        self.assertEqual(state["cash"]["USD"], "100.02")
        self.assertEqual(state["accounts"]["USD"]["inventory:equity:demo-us"], "0.00")
        self.assertTrue(self.ledger.audit()["passed"])

    def test_fx_uses_declared_rounding_and_source_currency_fee(self):
        self.fund("100")
        self.ledger.apply(
            event(
                "fx",
                "fx",
                from_currency="USD",
                to_currency="EUR",
                amount="10",
                rate="0.9005",
                fee="1",
            )
        )
        self.assertEqual(self.ledger.state()["cash"], {"EUR": "9.00", "USD": "89.00"})
        self.assertTrue(self.ledger.audit()["passed"])

