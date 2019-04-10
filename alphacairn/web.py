import hashlib
import io
from pathlib import Path

from .backtest import parse_bars, simulate
from .httpapp import serve

ROOT = Path(__file__).resolve().parents[1]


def example():
    return {
        "csv": (ROOT / "examples/synthetic.csv").read_text(),
        "source": "Synthetic daily fixture; not market data",
    }


def evaluate(params):
    content = params.get("csv", example()["csv"])
    if not isinstance(content, str):
        raise ValueError("csv must be text")
    bars = parse_bars(io.StringIO(content))
    if len(bars) > 20000:
        raise ValueError("The local workbench supports at most 20,000 bars per run")
    options = {
        "fee_bps": float(params.get("fee_bps", 10)),
        "slippage_bps": float(params.get("slippage_bps", 5)),
    }
    lookback = params.get("lookback", 20)
    if type(lookback) is not int or lookback >= len(bars):
        raise ValueError("lookback must be an integer smaller than the number of bars")
    return {
        "data_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "bars": len(bars),
        "start": bars[0]["date"],
        "end": bars[-1]["date"],
        "strategy": simulate(bars, lookback=lookback, **options),
        "baseline": simulate(bars, buy_and_hold=True, **options),
        "parameters": {"lookback": lookback, **options},
    }


if __name__ == "__main__":
    serve(evaluate, example, 8412)
