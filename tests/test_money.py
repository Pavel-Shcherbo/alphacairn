import unittest
from decimal import Decimal, localcontext

from alphacairn.instruments import AccountSpec, timestamp
from alphacairn.money import aligned, decimal_value, exact_amount, rounded
from portfolio_fixtures import account_spec


class MoneyContractTests(unittest.TestCase):
    def test_helpers_do_not_depend_on_callers_decimal_precision(self):
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(exact_amount("123456789.12", 2), Decimal("123456789.12"))
            self.assertEqual(
                aligned("123456789.125", Decimal("0.001"), "quantity"),
                Decimal("123456789.125"),
            )
            self.assertEqual(
                rounded(Decimal("123456789.125"), 2), Decimal("123456789.12")
            )

    def test_invalid_or_unbounded_money_is_rejected(self):
        for value in [True, 0.1, "NaN", "Infinity", "1e999", "0" * 1000, "-1"]:
            with self.subTest(value=str(value)[:30]), self.assertRaises(ValueError):
                decimal_value(value, positive=True)
        with self.assertRaises(ValueError):
            exact_amount("1.001", 2)
        with self.assertRaises(ValueError):
            aligned("0.03", Decimal("0.02"), "quantity")

    def test_instrument_identity_is_distinct_from_symbol(self):
        spec = AccountSpec.compile(account_spec())
        self.assertEqual(
            spec.instrument("equity:demo-us").symbol,
            spec.instrument("equity:demo-eu").symbol,
        )
        self.assertNotEqual(
            spec.instrument("equity:demo-us").quote_currency,
            spec.instrument("equity:demo-eu").quote_currency,
        )
        self.assertEqual(AccountSpec.compile(spec.definition()), spec)

    def test_naive_and_out_of_range_timestamps_fail(self):
        for value in ["2026-01-01T00:00:00", "0001-01-01T00:00:00+23:59", "not-a-date"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                timestamp(value)
