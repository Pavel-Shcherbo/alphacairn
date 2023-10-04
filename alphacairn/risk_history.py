"""Complete-case adjacent shock observations without bridging missing inputs."""

from datetime import timedelta
from fractions import Fraction

from .instruments import timestamp
from .risk_model import MAX_FACTORS
from .risk_numbers import fixed, quantized_return


