"""Complete attempt/access metadata and portable replay of a selected trial."""

import json
from pathlib import Path

from .market_model import canonical, digest
from .study_model import declaration, trial_contract, require_window
from .study_runner import compute, summary
from .study_store import decode, trial_meta

MAX_EXPORT = 72 * 1024 * 1024


