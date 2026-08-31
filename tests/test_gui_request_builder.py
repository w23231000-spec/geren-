from dataclasses import replace
from pathlib import Path

import pytest

from hfss_optimization_agent.ui.main_window import (
    MODEL_ID,
    build_optimization_request,
    budget_summary,
    load_default_request,
    request_to_form_data,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_gui_form_round_trips_to_optimization_request() -> None:
    default = load_default_request(ROOT)
    form = request_to_form_data(default)

    rebuilt = build_optimization_request(
        form,
        tolerance_ghz=default.frequency_plan.tolerance_ghz,
    )

    assert rebuilt.model_id == MODEL_ID
    assert rebuilt.frequency_plan == default.frequency_plan

    rebuilt_semantics = [
        (
            rule.parameter,
            rule.frequency_band,
            rule.operator,
            rule.threshold,
            rule.hard_constraint,
            rule.frequency_unit,
        )
        for rule in rebuilt.rules
    ]

    default_semantics = [
        (
            rule.parameter,
            rule.frequency_band,
            rule.operator,
            rule.threshold,
            rule.hard_constraint,
            rule.frequency_unit,
        )
        for rule in default.rules
    ]

    assert rebuilt_semantics == default_semantics

    assert [rule.rule_id for rule in rebuilt.rules] == [
        "task_core_s21",
        "task_core_s11",
        "task_lower_s21",
        "task_lower_s11",
        "task_upper_s21",
        "task_upper_s11",
    ]

    assert (
        rebuilt.max_optimization_rounds
        == default.max_optimization_rounds
    )


def test_custom_gui_values_bind_to_dynamic_task_and_budget() -> None:
    default = load_default_request(ROOT)
    form = request_to_form_data(default)

    custom = replace(
        form,
        core_s21_threshold="-25",
        core_s11_threshold="-1",
        lower_s21_threshold="-26",
        lower_s11_threshold="-1.5",
        upper_s21_threshold="-27",
        upper_s11_threshold="-2",
        max_optimization_rounds="3",
    )

    request = build_optimization_request(
        custom,
        tolerance_ghz=default.frequency_plan.tolerance_ghz,
    )

    thresholds = {
        rule.rule_id: rule.threshold
        for rule in request.rules
    }

    assert thresholds["task_core_s21"] == -25.0
    assert thresholds["task_core_s11"] == -1.0
    assert thresholds["task_lower_s21"] == -26.0
    assert thresholds["task_lower_s11"] == -1.5
    assert thresholds["task_upper_s21"] == -27.0
    assert thresholds["task_upper_s11"] == -2.0

    assert request.max_optimization_rounds == 3

    assert budget_summary(request) == {
        "max_candidate_hfss_calls": 3,
        "max_hfss_solve_launches": 4,
        "automatic_solve_retries": 0,
    }


def test_gui_request_builder_rejects_invalid_operator() -> None:
    default = load_default_request(ROOT)
    form = request_to_form_data(default)

    invalid = replace(
        form,
        core_s21_operator="==",
    )

    with pytest.raises(ValueError):
        build_optimization_request(
            invalid,
            tolerance_ghz=default.frequency_plan.tolerance_ghz,
        )
