"""Sample covariance, declared diagonal shrinkage and explicit rank diagnostics."""

from fractions import Fraction

from .risk_numbers import exact, fixed, root, sqrt_text


def sample_covariance(observations, size):
    count = len(observations)
    if count < 2:
        raise ValueError("sample covariance requires at least two return observations")
    if size * size * count > 600000:
        raise ValueError("covariance workload exceeds 600,000 factor-pair observations")
    means = [
        sum((row["returns"][i] for row in observations), Fraction()) / count
        for i in range(size)
    ]
    covariance = [[Fraction() for _ in range(size)] for _ in range(size)]
    centered = [
        [row["returns"][i] - means[i] for i in range(size)] for row in observations
    ]
    for i in range(size):
        for j in range(i, size):
            value = sum((row[i] * row[j] for row in centered), Fraction()) / (count - 1)
            covariance[i][j] = covariance[j][i] = value
    return means, covariance


def shrink_covariance(matrix, coefficient):
    return [
        [value if i == j else value * (1 - coefficient) for j, value in enumerate(row)]
        for i, row in enumerate(matrix)
    ]


def checked(value):
    if value.numerator.bit_length() > 16384 or value.denominator.bit_length() > 16384:
        raise ValueError("matrix arithmetic exceeds 16,384-bit rational budget")
    return value


def inverse_rank(matrix):
    size = len(matrix)
    work = [
        [fraction for fraction in row] + [Fraction(int(i == j)) for j in range(size)]
        for i, row in enumerate(matrix)
    ]
    pivot_row = 0
    for column in range(size):
        selected = next((i for i in range(pivot_row, size) if work[i][column]), None)
        if selected is None:
            continue
        work[pivot_row], work[selected] = work[selected], work[pivot_row]
        pivot = work[pivot_row][column]
        work[pivot_row] = [checked(value / pivot) for value in work[pivot_row]]
        for i in range(size):
            if i == pivot_row:
                continue
            multiplier = work[i][column]
            if multiplier:
                work[i] = [
                    checked(left - multiplier * right)
                    for left, right in zip(work[i], work[pivot_row])
                ]
        pivot_row += 1
    return pivot_row, [row[size:] for row in work] if pivot_row == size else None


def matrix_diagnostics(matrix):
    size = len(matrix)
    rank, inverse = inverse_rank(matrix)
    norm = lambda value: max(
        (sum((abs(row[j]) for row in value), Fraction()) for j in range(len(value))),
        default=Fraction(),
    )
    condition = norm(matrix) * norm(inverse) if inverse is not None and size else None
    return {
        "factors": size,
        "rank": rank,
        "singular": rank < size,
        "condition_number_one": fixed(condition) if condition is not None else None,
        "ill_conditioned": condition >= 100000000 if condition is not None else None,
        "zero_variance_factors": [i for i in range(size) if matrix[i][i] == 0],
        "condition_threshold": "100000000",
        "inverse_used_for_portfolio_risk": False,
    }


def covariance_report(observations, factors, configuration, equity):
    size = len(factors)
    means, sample = sample_covariance(observations, size)
    coefficient = Fraction(configuration["shrinkage"])
    matrix = shrink_covariance(sample, coefficient)
    values = [factor["base_value"] for factor in factors]
    product = [
        sum((matrix[i][j] * values[j] for j in range(size)), Fraction())
        for i in range(size)
    ]
    contributions = [values[i] * product[i] for i in range(size)]
    variance = sum(contributions, Fraction())
    if variance < 0:
        raise ValueError("negative portfolio variance violates the covariance contract")
    sigma = root(variance)
    rows = []
    for i, factor in enumerate(factors):
        rows.append(
            {
                "id": factor["id"],
                "base_value": fixed(values[i]),
                "mean_return": fixed(means[i]),
                "period_volatility": sqrt_text(matrix[i][i]),
                "variance_contribution": fixed(contributions[i]),
                "variance_contribution_exact": exact(contributions[i]),
                "variance_share": (
                    fixed(contributions[i] / variance) if variance else None
                ),
                "component_volatility_base": (
                    fixed(contributions[i] / Fraction(sigma)) if variance else None
                ),
            }
        )
    correlation = []
    for i in range(size):
        row = []
        for j in range(size):
            denominator = root(matrix[i][i] * matrix[j][j])
            row.append(
                fixed(matrix[i][j] / Fraction(denominator)) if denominator else None
            )
        correlation.append(row)
    frequency = configuration["periods_per_year"]
    return {
        "method": "sample covariance (n-1), then off-diagonal multiplied by (1-shrinkage); unchanged diagonal",
        "shrinkage": configuration["shrinkage"],
        "factor_order": [factor["id"] for factor in factors],
        "sample_covariance": [[fixed(value) for value in row] for row in sample],
        "covariance": [[fixed(value) for value in row] for row in matrix],
        "covariance_exact": [[exact(value) for value in row] for row in matrix],
        "correlation": correlation,
        "sample_diagnostics": matrix_diagnostics(sample),
        "regularized_diagnostics": matrix_diagnostics(matrix),
        "variance_base": fixed(variance),
        "variance_base_exact": exact(variance),
        "period_volatility_base": fixed(Fraction(sigma)),
        "period_volatility_fraction": fixed(Fraction(sigma) / equity),
        "annualized_volatility_fraction": sqrt_text(
            variance * frequency / (equity * equity)
        ),
        "periods_per_year": frequency,
        "components": rows,
        "annualization_assumption": "Square-root-of-time scaling under the declared equal-period/no-serial-correlation approximation; not a forecast",
    }
