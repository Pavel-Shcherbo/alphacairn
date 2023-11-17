"""Current marked exposures, concentration groups and exactly reconciled stresses."""

import copy
from decimal import Decimal
from fractions import Fraction

from .money import arithmetic, rounded, text, decimal_value
from .risk_numbers import fixed
from .valuation import value_portfolio


