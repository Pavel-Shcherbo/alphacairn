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


