import hashlib
import io

from .backtest import dataset_digest, parse_bars, simulate
from .analytics import compare, summarize
from .httpapp import serve
from .walkforward import walk_forward
from .resources import examples_directory, state_directory
from .portfolio_web import portfolio_example, evaluate_portfolio


def example():
    return {
        "csv": (examples_directory() / "synthetic.csv").read_text(),
        "source": "Synthetic daily fixture; not market data",
        "portfolio": portfolio_example(),
    }


def evaluate(params):
    if params.get("mode") == "portfolio":
        return evaluate_portfolio(params)
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
    mode = params.get("mode", "fixed")
    periods_per_year = params.get("periods_per_year", 365)
    if mode not in {"fixed", "walk_forward"}:
        raise ValueError("study mode must be fixed or walk_forward")
    lookback = params.get("lookback", 20)
    windows = []
    if mode == "fixed":
        if type(lookback) is not int or lookback >= len(bars):
            raise ValueError(
                "lookback must be an integer smaller than the number of bars"
            )
        strategy = simulate(bars, lookback=lookback, **options)
        baseline = simulate(bars, buy_and_hold=True, **options)
        parameters = {
            "mode": mode,
            "lookback": lookback,
            "periods_per_year": periods_per_year,
            **options,
        }
    else:
        research = walk_forward(
            bars,
            params.get("candidates", [5, 10, 20, 40]),
            train_size=params.get("train_size", 100),
            test_size=params.get("test_size", 40),
            score=params.get("score", "total_return"),
            periods_per_year=periods_per_year,
            **options,
        )
        windows = research["windows"]
        baseline = research["baseline"]
        strategy = {
            "initial_cash": 10000,
            "final_equity": research["equity"][-1]["equity"],
            "total_return": research["metrics"]["total_return"],
            "max_drawdown": research["metrics"]["maximum_drawdown"],
            "fees": research["total_fees"],
            "trade_count": len(research["trades"]),
            "trades": research["trades"],
            "equity": research["equity"],
            "assumptions": research["evaluation_policy"],
        }
        parameters = {"mode": mode, **research["parameters"]}
    return {
        "data_sha256": dataset_digest(bars),
        "input_text_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "digest_policy": "Normalized date/open/close records; input_text_sha256 identifies the received UTF-8 text",
        "bars": len(strategy["equity"]),
        "input_bars": len(bars),
        "start": strategy["equity"][0]["date"],
        "end": strategy["equity"][-1]["date"],
        "strategy": strategy,
        "baseline": baseline,
        "parameters": parameters,
        "windows": windows,
        "strategy_metrics": summarize(strategy["equity"], 10000, periods_per_year),
        "baseline_metrics": summarize(baseline["equity"], 10000, periods_per_year),
        "comparison": (
            compare(strategy["equity"], baseline["equity"], 10000, periods_per_year)
            if len(strategy["equity"]) >= 2
            else None
        ),
    }


if __name__ == "__main__":
    from .research_desk import ResearchDesk

    desk = ResearchDesk(state_directory("alphacairn") / "research.sqlite")
    serve(evaluate, example, 8412, research=desk.dispatch)
