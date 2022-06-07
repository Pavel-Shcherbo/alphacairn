"""Independent cash controls and adversarial decision-versus-execution clocks."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal, Inexact, localcontext
from pathlib import Path

from alphacairn.execution_export import json_data
from alphacairn.market_model import canonical, digest, snapshot_identity
from alphacairn.market_store import MarketCatalog
from alphacairn.strategy_bundle import (
    verify_strategy_bundle,
    write_strategy,
    write_strategy_inputs,
)
from alphacairn.strategy_engine import simulate_strategy
from alphacairn.strategy_inputs import (
    capture_strategy,
    compile_strategy,
    prepare_strategy_inputs,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name):
    return json.loads((EXAMPLES / name).read_text())


def rehash_inputs(document):
    document["sha256"] = digest(
        {key: value for key, value in document.items() if key != "sha256"}
    )


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = MarketCatalog(self.root / "market.sqlite", create=True)
        self.definition = load("strategy-control.json")
        self.bars = load("strategy-bars.json")
        self.members = load("strategy-universe.json")
        self.ingest(self.bars, "bar", "bars")
        self.ingest(self.members, "membership", "members")

    def ingest(self, rows, kind="bar", key="revision"):
        return self.catalog.ingest(
            self.definition["source"], kind, canonical(rows), request_key=key
        )

    def run_study(self, definition=None):
        inputs = capture_strategy(self.catalog, definition or self.definition)
        return inputs, simulate_strategy(inputs)

    def test_hand_calculated_six_fills_cash_positions_and_equity(self):
        inputs, result = self.run_study()
        execution = result["execution"]
        self.assertTrue(result["planning_replayed"])
        self.assertTrue(execution["ledger_audit"]["passed"])
        expected = [
            ("STOCK-A", "buy", "2", "13"),
            ("COIN-C", "buy", "1.0", "23"),
            ("STOCK-A", "sell", "2", "9"),
            ("COIN-C", "buy", "0.5", "25"),
            ("STOCK-A", "buy", "3", "15"),
            ("COIN-C", "sell", "1.5", "20"),
        ]
        self.assertEqual(
            [
                (fill["instrument"], fill["side"], fill["quantity"], fill["price"])
                for fill in execution["fills"]
            ],
            expected,
        )
        # Independent integer cents: 10000-2650-2350+1750-1300-4550+2950.
        self.assertEqual(execution["cash"], {"USD": "38.50"})
        self.assertEqual(execution["valuation"]["equity"], "86.50")
        self.assertEqual(execution["positions"]["STOCK-A"]["quantity"], "3")
        self.assertEqual(execution["fees_by_currency"], {"USD": "3.00"})
        self.assertEqual(prepare_strategy_inputs(inputs).sha256, inputs["sha256"])

    def test_next_decision_sizes_from_partial_fills_instead_of_requested_inventory(
        self,
    ):
        _, result = self.run_study()
        decision = result["decisions"][1]
        self.assertEqual(Decimal(decision["positions_before"]["STOCK-A"]), Decimal(2))
        self.assertEqual(Decimal(decision["positions_before"]["COIN-C"]), Decimal(1))
        actions = {item["instrument"]: item for item in decision["actions"]}
        self.assertEqual(actions["STOCK-A"]["delta_quantity"], "-2")
        self.assertEqual(Decimal(actions["COIN-C"]["delta_quantity"]), Decimal("0.5"))
        self.assertEqual(result["execution"]["orders"][0]["status"], "cancelled")

    def test_future_realization_revision_changes_valuation_not_earlier_signals_or_orders(
        self,
    ):
        _, before = self.run_study()
        revised = copy.deepcopy(
            next(
                row
                for row in self.bars
                if row["instrument"] == "STOCK-A" and row["session"] == "2020-01-06"
            )
        )
        revised.update(close="999", published_at="2020-01-07T12:00:00Z")
        self.ingest([revised])
        _, after = self.run_study()
        self.assertEqual(before["windows"], after["windows"])
        self.assertEqual(before["decisions"], after["decisions"])
        self.assertEqual(before["scenario"]["commands"], after["scenario"]["commands"])
        self.assertEqual(before["execution"]["fills"], after["execution"]["fills"])
        self.assertNotEqual(
            before["execution"]["valuation"]["equity"],
            after["execution"]["valuation"]["equity"],
        )

    def test_future_open_changes_later_balances_without_rewriting_first_decision(self):
        _, before = self.run_study()
        revised = copy.deepcopy(
            next(
                row
                for row in self.bars
                if row["instrument"] == "STOCK-A" and row["session"] == "2020-01-03"
            )
        )
        revised.update(open="100", published_at="2020-01-07T12:00:00Z")
        self.ingest([revised])
        _, after = self.run_study()
        self.assertEqual(before["decisions"][0], after["decisions"][0])
        self.assertEqual(
            before["scenario"]["commands"][:2], after["scenario"]["commands"][:2]
        )
        self.assertEqual(before["windows"], after["windows"])
        self.assertNotEqual(
            before["decisions"][1]["positions_before"],
            after["decisions"][1]["positions_before"],
        )

    def test_late_revision_becomes_available_only_to_later_decisions(self):
        _, before = self.run_study()
        revised = copy.deepcopy(
            next(
                row
                for row in self.bars
                if row["instrument"] == "STOCK-A" and row["session"] == "2020-01-03"
            )
        )
        revised.update(close="30", published_at="2020-01-04T12:00:00Z")
        self.ingest([revised])
        _, after = self.run_study()
        self.assertEqual(before["windows"][:2], after["windows"][:2])
        self.assertEqual(before["decisions"][:2], after["decisions"][:2])
        a = next(
            item
            for item in after["windows"][2]["features"]
            if item["instrument"] == "STOCK-A"
        )
        self.assertFalse(a["above_mean"])
        self.assertEqual(a["mean_close"], "22")
        self.assertNotEqual(
            before["scenario"]["commands"], after["scenario"]["commands"]
        )

    def test_recording_clock_does_not_claim_old_data_was_locally_available(self):
        self.definition["clock"] = "recorded"
        with self.assertRaisesRegex(ValueError, "no matching execution-vintage"):
            self.run_study()

    def test_warmup_produces_explicit_missing_signal_without_fabricated_values(self):
        self.definition["lookback"] = 3
        _, result = self.run_study()
        self.assertEqual(
            result["windows"][0]["features"][0]["reason"], "insufficient_history"
        )
        self.assertTrue(
            all(
                item["outcome"] == "missing_signal_hold"
                for item in result["decisions"][0]["actions"]
            )
        )
        self.assertFalse(
            any(
                command["at"] == result["decisions"][0]["at"]
                for command in result["scenario"]["commands"]
            )
        )

    def test_stale_feature_hold_and_exit_policies_act_on_actual_positions(self):
        self.definition["decisions"][1]["at"] = "2020-01-03T23:00:00Z"
        _, held = self.run_study()
        self.definition["missing_signal_policy"] = "exit"
        _, exited = self.run_study()
        self.assertEqual(
            held["decisions"][1]["actions"][0]["outcome"], "missing_signal_hold"
        )
        self.assertEqual(
            exited["decisions"][1]["actions"][0]["signal_reason"], "stale_history"
        )
        self.assertEqual(exited["decisions"][1]["actions"][0]["delta_quantity"], "-2")
        self.assertEqual(
            exited["decisions"][1]["actions"][0]["outcome"], "order_submitted"
        )

    def test_historical_universe_exit_is_explicit_and_keeps_instrument_evidence(self):
        revision = {
            **self.members[0],
            "valid_until": "2020-01-03",
            "published_at": "2020-01-02T19:00:00Z",
        }
        self.ingest([revision], "membership")
        _, result = self.run_study()
        action = result["decisions"][1]["actions"][0]
        self.assertEqual(action["signal_reason"], "outside_universe")
        self.assertEqual(action["delta_quantity"], "-2")
        self.assertEqual(action["outcome"], "order_submitted")
        self.assertTrue(
            any(
                fill["instrument"] == "STOCK-A" for fill in result["execution"]["fills"]
            )
        )

    def test_undeclared_historical_member_cannot_be_silently_removed(self):
        self.ingest([{**self.members[0], "instrument": "FAILED-COMPANY"}], "membership")
        with self.assertRaisesRegex(ValueError, "missing from the account"):
            self.run_study()

    def test_missing_future_and_unmatched_liquidity_are_rejected(self):
        for mutate in (
            lambda d: d["liquidity"].pop(),
            lambda d: d["liquidity"][0].update(known_at="2020-01-02T10:00:00Z"),
            lambda d: d["liquidity"].append(
                {
                    "instrument": "STOCK-A",
                    "session": "2020-01-07",
                    "quantity": "1",
                    "known_at": "2020-01-07T08:00:00Z",
                }
            ),
        ):
            definition = copy.deepcopy(self.definition)
            mutate(definition)
            with (
                self.subTest(definition=definition["liquidity"]),
                self.assertRaises(ValueError),
            ):
                self.run_study(definition)

    def test_realized_volume_is_never_used_as_pre_open_liquidity(self):
        _, before = self.run_study()
        revisions = [
            {**row, "volume": "0", "published_at": "2020-01-07T12:00:00Z"}
            for row in self.bars
        ]
        self.ingest(revisions)
        _, after = self.run_study()
        self.assertEqual(before["execution"]["fills"], after["execution"]["fills"])
        self.assertEqual(before["scenario"]["commands"], after["scenario"]["commands"])

    def test_declared_allocation_order_controls_competition_for_cash(self):
        self.definition["execution"]["initial_cash"]["USD"] = "30"
        _, stock_first = self.run_study()
        self.definition["allocation_order"].reverse()
        _, coin_first = self.run_study()
        first_time = stock_first["execution"]["fills"][0]["at"]
        self.assertEqual(
            [
                fill["instrument"]
                for fill in stock_first["execution"]["fills"]
                if fill["at"] == first_time
            ],
            ["STOCK-A"],
        )
        self.assertEqual(
            [
                fill["instrument"]
                for fill in coin_first["execution"]["fills"]
                if fill["at"] == first_time
            ],
            ["COIN-C"],
        )
        self.assertTrue(
            all(
                Decimal(value) >= 0
                for value in coin_first["execution"]["cash"].values()
            )
        )

    def test_pending_ioc_waits_for_first_eligible_open_without_duplicate_order(self):
        self.definition["decisions"].insert(
            1, {"at": "2020-01-02T19:00:00Z", "session": "2020-01-02"}
        )
        _, result = self.run_study()
        self.assertTrue(
            all(
                action["outcome"] == "waiting_for_pending_order"
                for action in result["decisions"][1]["actions"]
            )
        )
        self.assertEqual(len(result["scenario"]["commands"]), 6)

    def test_decision_at_open_cannot_fill_at_the_same_open(self):
        self.definition["max_feature_age_seconds"] = 86400
        self.definition["decisions"] = [
            {"at": "2020-01-03T09:00:00Z", "session": "2020-01-02"}
        ]
        _, result = self.run_study()
        self.assertTrue(result["execution"]["fills"])
        self.assertTrue(
            all(
                fill["at"].startswith("2020-01-04")
                for fill in result["execution"]["fills"]
            )
        )

    def test_after_last_open_order_remains_unfilled_instead_of_fake_liquidation(self):
        self.definition["decisions"] = [
            {"at": "2020-01-06T17:00:00Z", "session": "2020-01-06"}
        ]
        _, result = self.run_study()
        self.assertEqual(result["execution"]["fills"], [])
        self.assertEqual(result["execution"]["open_order_count"], 1)
        self.assertEqual(result["execution"]["cash"], {"USD": "100.00"})

    def test_inactive_instrument_is_visible_and_unfilled_exit_expires(self):
        self.definition["execution"]["account"]["instruments"][0][
            "active_until"
        ] = "2020-01-04T09:00:00Z"
        self.definition["execution_sessions"]["end"] = "2020-01-03"
        self.definition["liquidity"] = [
            row
            for row in self.definition["liquidity"]
            if row["session"] <= "2020-01-03"
        ]
        _, result = self.run_study()
        self.assertEqual(
            result["decisions"][2]["actions"][0]["outcome"], "inactive_instrument"
        )
        self.assertEqual(result["execution"]["positions"]["STOCK-A"]["quantity"], "2")
        self.assertEqual(
            next(
                order
                for order in result["execution"]["orders"]
                if order["instrument"] == "STOCK-A" and order["side"] == "sell"
            )["status"],
            "expired",
        )

    def test_input_binding_rejects_missing_unused_duplicate_and_mutated_snapshots(self):
        inputs, _ = self.run_study()
        for mode in ("missing", "unused", "duplicate", "changed"):
            bad = copy.deepcopy(inputs)
            if mode == "missing":
                bad["snapshots"].pop()
            elif mode == "duplicate":
                bad["snapshots"].append(copy.deepcopy(bad["snapshots"][0]))
            elif mode == "unused":
                item = copy.deepcopy(bad["snapshots"][0])
                item["query"]["known_at"] = "2020-02-01T00:00:00.000000+00:00"
                item["sha256"] = snapshot_identity(item)
                bad["snapshots"].append(item)
            else:
                bad["snapshots"][0]["sha256"] = "0" * 64
            rehash_inputs(bad)
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                simulate_strategy(bad)

    def test_cancelled_or_invalid_study_cannot_return_a_completed_report(self):
        inputs, _ = self.run_study()
        with self.assertRaisesRegex(ValueError, "cancelled"):
            simulate_strategy(inputs, should_cancel=lambda: True)
        count = 0

        def cancel():
            nonlocal count
            count += 1
            return count >= 6

        with self.assertRaisesRegex(ValueError, "cancelled"):
            simulate_strategy(inputs, should_cancel=cancel)
        with self.assertRaises(ValueError):
            simulate_strategy(inputs, should_cancel=True)

