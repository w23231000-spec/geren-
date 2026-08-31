"""Shared deterministic semantics for S-parameter threshold rules."""

from __future__ import annotations

import math


SUPPORTED_OPERATORS = {"<=", ">="}


def margin_to_target(*, operator: str, threshold: float, observed: float) -> float:
    """Return a signed margin where non-negative always means compliant."""

    if operator == "<=":
        return float(threshold) - float(observed)
    if operator == ">=":
        return float(observed) - float(threshold)
    raise ValueError(f"unsupported S-parameter rule operator: {operator!r}")


def violation_from_margin(margin: float | None) -> float:
    if margin is None or not math.isfinite(float(margin)):
        return math.inf
    return max(0.0, -float(margin))


def extremum_metric_name(*, parameter: str, operator: str) -> str:
    """Map a pointwise rule to the worst-case band statistic it constrains."""

    normalized = parameter.strip().lower()
    if normalized not in {"s11", "s21"}:
        raise ValueError(f"unsupported S-parameter: {parameter!r}")
    if operator == "<=":
        return f"maximum_{normalized}_db"
    if operator == ">=":
        return f"minimum_{normalized}_db"
    raise ValueError(f"unsupported S-parameter rule operator: {operator!r}")


def violation_expression(*, parameter: str, operator: str, threshold: float) -> str:
    """Build a vendor expression whose minimum is exactly the rule violation."""

    metric = f"metric.{extremum_metric_name(parameter=parameter, operator=operator)}"
    target = format(float(threshold), ".17g")
    if operator == "<=":
        return f"max(0, {metric} - ({target}))"
    if operator == ">=":
        return f"max(0, ({target}) - {metric})"
    raise ValueError(f"unsupported S-parameter rule operator: {operator!r}")
