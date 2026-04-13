"""Forecasting Engine — regression modeler.

Builds linear and polynomial (degree 2) regression models using
ordinary least squares. Computes R-squared for model comparison and
selects the best-fit model.

Model: Mistral for contextual interpretation of regression results.

Pure Python — no numpy.
"""
from __future__ import annotations

import math
from typing import Any

from .trend_analyzer import least_squares, r_squared


def build_regression(
    cleaned_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build linear and polynomial regression models.

    Args:
        cleaned_data: List of CleanedPoint dicts (date, value).

    Returns:
        Structured dict with RegressionResult fields.
    """
    try:
        if not cleaned_data:
            return {
                "status": "error",
                "regression": _empty_regression(),
                "error": "No data for regression modeling",
            }

        values = [p["value"] for p in cleaned_data]
        n = len(values)

        if n < 3:
            return {
                "status": "success",
                "regression": _empty_regression(
                    note="Insufficient data for regression (need >= 3 points)",
                ),
            }

        x = list(range(n))

        # ---- Linear regression ----
        lin_slope, lin_intercept = least_squares(x, values)
        lin_r2 = r_squared(x, values, lin_slope, lin_intercept)

        # ---- Polynomial regression (degree 2): y = a*x^2 + b*x + c ----
        poly_coeffs, poly_r2 = _poly_regression_deg2(x, values)

        # ---- Select best model ----
        # Prefer linear unless polynomial improves R-squared by at least 0.05
        if poly_r2 > lin_r2 + 0.05:
            best_model = "polynomial"
        else:
            best_model = "linear"

        return {
            "status": "success",
            "regression": {
                "linear_slope": round(lin_slope, 6),
                "linear_intercept": round(lin_intercept, 4),
                "linear_r_squared": round(lin_r2, 4),
                "poly_coefficients": [round(c, 8) for c in poly_coeffs],
                "poly_r_squared": round(poly_r2, 4),
                "best_model": best_model,
                "model_note": "Mistral: regression model interpretation",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "regression": _empty_regression(),
            "error": f"Regression modeling failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Polynomial regression (degree 2) via normal equations
# ---------------------------------------------------------------------------

def _poly_regression_deg2(
    x: list[int | float],
    y: list[float],
) -> tuple[list[float], float]:
    """Fit y = a*x^2 + b*x + c using the normal equations.

    Normal equations: (X^T X) beta = X^T y
    where X = [[x_i^2, x_i, 1], ...], beta = [a, b, c].

    Returns (coefficients [a, b, c], r_squared).
    """
    n = len(x)
    if n < 3:
        return [0.0, 0.0, 0.0], 0.0

    # Build sums for X^T X and X^T y
    # X^T X is 3x3 symmetric:
    #   [[sum(x^4), sum(x^3), sum(x^2)],
    #    [sum(x^3), sum(x^2), sum(x)  ],
    #    [sum(x^2), sum(x),   n        ]]
    sx1 = sum(xi for xi in x)
    sx2 = sum(xi ** 2 for xi in x)
    sx3 = sum(xi ** 3 for xi in x)
    sx4 = sum(xi ** 4 for xi in x)

    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sx2y = sum((xi ** 2) * yi for xi, yi in zip(x, y))

    # Solve 3x3 system via Cramer's rule
    # | sx4  sx3  sx2 | | a |   | sx2y |
    # | sx3  sx2  sx1 | | b | = | sxy  |
    # | sx2  sx1  n   | | c |   | sy   |
    matrix = [
        [sx4, sx3, sx2],
        [sx3, sx2, sx1],
        [sx2, sx1, float(n)],
    ]
    rhs = [sx2y, sxy, sy]

    det = _det3(matrix)
    if abs(det) < 1e-12:
        # Singular matrix — fall back to linear
        slope, intercept = least_squares(x, y)
        r2 = r_squared(x, y, slope, intercept)
        return [0.0, slope, intercept], r2

    a = _det3([
        [rhs[0], matrix[0][1], matrix[0][2]],
        [rhs[1], matrix[1][1], matrix[1][2]],
        [rhs[2], matrix[2][1], matrix[2][2]],
    ]) / det

    b = _det3([
        [matrix[0][0], rhs[0], matrix[0][2]],
        [matrix[1][0], rhs[1], matrix[1][2]],
        [matrix[2][0], rhs[2], matrix[2][2]],
    ]) / det

    c = _det3([
        [matrix[0][0], matrix[0][1], rhs[0]],
        [matrix[1][0], matrix[1][1], rhs[1]],
        [matrix[2][0], matrix[2][1], rhs[2]],
    ]) / det

    # Compute R-squared for polynomial
    mean_y = sy / n
    ss_tot = sum((yi - mean_y) ** 2 for yi in y)
    ss_res = sum((yi - (a * xi ** 2 + b * xi + c)) ** 2 for xi, yi in zip(x, y))

    if abs(ss_tot) < 1e-12:
        poly_r2 = 1.0
    else:
        poly_r2 = max(0.0, 1.0 - ss_res / ss_tot)

    return [a, b, c], poly_r2


def _det3(m: list[list[float]]) -> float:
    """Compute the determinant of a 3x3 matrix."""
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


# ---------------------------------------------------------------------------
# Empty result
# ---------------------------------------------------------------------------

def _empty_regression(note: str = "") -> dict[str, Any]:
    """Return an empty regression result."""
    return {
        "linear_slope": 0.0,
        "linear_intercept": 0.0,
        "linear_r_squared": 0.0,
        "poly_coefficients": [0.0, 0.0, 0.0],
        "poly_r_squared": 0.0,
        "best_model": "none",
        "model_note": note,
    }
