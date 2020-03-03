"""Bounded disposable portfolio scenarios for the local browser workbench."""

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from .instruments import AccountSpec
from .ledger import Ledger, canonical, normalize_event
from .resources import examples_directory
from .valuation import value_portfolio


