"""Reconcile current exposures before producing descriptive multi-asset risk."""

from fractions import Fraction

from .market_model import digest
from .risk_history import factor_exposures, history_report, observation_returns
from .risk_inputs import prepare_risk_inputs
from .risk_matrix import covariance_report
from .risk_positions import concentrations, exposures, stress_portfolio
from .risk_tail import historical_tail
from .valuation import value_portfolio


def analyze_risk(inputs):
    prepared = prepare_risk_inputs(inputs)
    spec, state = prepared.spec, prepared.state
    config, quotes = prepared.configuration, prepared.quotes
    valuation = value_portfolio(
        state,
        quotes["marks"],
        quotes["fx"],
        as_of=config["as_of"],
        max_age_seconds=config["max_age_seconds"],
    )
    rows = exposures(state, valuation, spec)
    warnings = [
        {
            "code": "operator_declared_history_basis",
            "source": prepared.history["source"],
        },
        {
            "code": "static_current_exposures",
            "detail": "Historical shocks revalue current marked exposures; these are not realized historical portfolio returns",
        },
    ]
    history = {
        "evaluated": False,
        "source_observation_count": len(prepared.history["observations"]),
        "reason": "baseline_valuation_incomplete",
    }
    statistics = {"complete": False, "reason": "baseline_valuation_incomplete"}
    if valuation["complete"]:
        factors = factor_exposures(rows, spec)
        observations, excluded = observation_returns(
            prepared.history, factors, config, spec
        )
        history = history_report(observations, excluded, factors, config)
        history.update(
            evaluated=True,
            source_observation_count=len(prepared.history["observations"]),
        )
        equity = Fraction(valuation["equity"])
        zero_marked = [
            row["instrument"]
            for row in valuation["positions"]
            if Fraction(row["mark"]) == 0
        ]
        if zero_marked:
            statistics = {
                "complete": False,
                "reason": "zero_marked_positions",
                "instruments": zero_marked,
            }
        elif equity <= 0:
            statistics = {"complete": False, "reason": "nonpositive_equity"}
        elif not factors:
            statistics = {
                "complete": True,
                "method": "deterministic_base_cash_only",
                "period_volatility_base": "0",
                "annualized_volatility_fraction": "0",
                "value_at_risk_base": "0",
                "expected_shortfall_base": "0",
                "history_required": False,
            }
        elif len(observations) < config["min_observations"]:
            statistics = {
                "complete": False,
                "reason": "insufficient_complete_observations",
                "available": len(observations),
                "required": config["min_observations"],
            }
        else:
            covariance = covariance_report(observations, factors, config, equity)
            tail = historical_tail(observations, config["confidence"], equity)
            statistics = {
                "complete": True,
                "covariance": covariance,
                "historical_tail": tail,
            }
            if covariance["sample_diagnostics"]["singular"]:
                warnings.append({"code": "sample_covariance_singular"})
            if covariance["regularized_diagnostics"]["singular"]:
                warnings.append({"code": "regularized_covariance_singular"})
            if covariance["regularized_diagnostics"]["ill_conditioned"]:
                warnings.append({"code": "regularized_covariance_ill_conditioned"})
            if Fraction(tail["tail_observation_mass"]) < 5:
                warnings.append(
                    {
                        "code": "small_empirical_tail",
                        "observation_mass": tail["tail_observation_mass"],
                    }
                )
        if excluded:
            warnings.append(
                {"code": "excluded_history_intervals", "count": len(excluded)}
            )
    concentration = concentrations(
        rows, valuation["equity"], config["concentration_limits"]
    )
    if concentration["breaches"]:
        warnings.append(
            {
                "code": "concentration_limit_breaches",
                "count": len(concentration["breaches"]),
            }
        )
    stresses = stress_portfolio(state, quotes, config, valuation, spec)
    result = {
        "format": "alphacairn.risk-report.v1",
        "inputs_sha256": prepared.sha256,
        "configuration_sha256": digest(config),
        "completed": True,
        "complete": valuation["complete"]
        and statistics["complete"]
        and all(row["complete"] for row in stresses),
        "as_of": config["as_of"],
        "base_currency": spec.base_currency,
        "journal_sequence": state["last_sequence"],
        "journal_replayed": True,
        "valuation": valuation,
        "exposures": rows,
        "concentration": concentration,
        "history": history,
        "statistics": statistics,
        "stresses": stresses,
        "warnings": warnings,
        "scope": "Descriptive long-only equity/spot risk from a replayed journal, operator-declared synchronous price history and explicit shocks; no trading advice, regulatory capital or prediction",
        "rounding_policy": "Journal currency rounding for baseline/stresses; stressed per-unit quotes rounded half-even to 18 places; historical simple returns rounded half-even to 12 places; covariance/tails exact on that grid; displayed diagnostics 18 places",
    }
    result["sha256"] = digest(result)
    return result
