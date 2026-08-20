"""Versioned Production Evaluation Contract loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.config import EvaluationConfig
from ..core.models import FrequencyPlan
from .evaluator import SParameterRule


PRODUCTION_CONTRACT_ID = "production-evaluation-v1"


def load_production_evaluation_config(path: Path) -> EvaluationConfig:
    """Load Production Contract v1 into the existing EvaluationConfig model."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("contract_id") != PRODUCTION_CONTRACT_ID:
        raise ValueError(f"Expected Production Evaluation Contract {PRODUCTION_CONTRACT_ID}")
    if payload.get("schema_version") != "1.0":
        raise ValueError("Unsupported Production Evaluation Contract schema version")
    if payload.get("value_unit") != "dB" or payload.get("frequency_unit") != "GHz":
        raise ValueError("Production Evaluation Contract v1 requires dB values and GHz frequencies")

    plan_value = payload.get("frequency_plan")
    if not isinstance(plan_value, dict):
        raise ValueError("Production Evaluation Contract requires a frequency_plan mapping")
    plan = FrequencyPlan.from_mapping(plan_value)
    if not plan.is_valid:
        raise ValueError(plan.validation_error or "Invalid Production FrequencyPlan")

    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or len(raw_rules) != 6:
        raise ValueError("Production Evaluation Contract v1 requires exactly six rules")
    parsed = tuple(SParameterRule.from_mapping(value) for value in raw_rules)
    if len({rule.rule_id for rule in parsed}) != len(parsed):
        raise ValueError("Production Evaluation Contract rule IDs must be unique")
    if any(rule.parameter not in {"S11", "S21"} for rule in parsed):
        raise ValueError("Production Evaluation Contract supports only S11 and S21 rules")
    if any(rule.frequency_unit != "GHz" for rule in parsed):
        raise ValueError("Production Evaluation Contract rule frequencies must use GHz")

    core = [rule for rule in parsed if rule.hard_constraint]
    soft = [rule for rule in parsed if not rule.hard_constraint]
    if len(core) != 2 or len(soft) != 4:
        raise ValueError("Production Evaluation Contract v1 requires two HARD and four SOFT rules")
    if any(rule.frequency_band != plan.core_band for rule in core):
        raise ValueError("All Production HARD rules must use the Core Band")
    margin_bands = [rule.frequency_band for rule in soft]
    if margin_bands.count(plan.lower_margin_band) != 2 or margin_bands.count(plan.upper_margin_band) != 2:
        raise ValueError("Production SOFT rules must cover both Margin bands")

    normalized_rules: tuple[dict[str, Any], ...] = tuple(
        {
            "rule_id": rule.rule_id,
            "parameter": rule.parameter,
            "frequency_band": rule.frequency_band,
            "operator": rule.operator,
            "threshold": rule.threshold,
            "hard_constraint": rule.hard_constraint,
            "frequency_unit": rule.frequency_unit,
        }
        for rule in parsed
    )
    return EvaluationConfig(rules=normalized_rules, frequency_plan=plan)
