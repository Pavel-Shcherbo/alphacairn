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

