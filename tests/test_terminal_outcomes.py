"""Offline tests for Phase-0 authoritative terminal outcomes and exit codes."""

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.agent.terminal_policy import classify_terminal_outcome
from hfss_optimization_agent.core.enums import WorkflowStatus, workflow_exit_code
from hfss_optimization_agent.core.models import HFSSResult
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
)


def test_missing_baseline_evaluation_is_invalid_not_success():
    state = create_comparison_state(
        task_id="terminal-invalid",
        baseline_parameters=supplied_baseline_candidate(),
    )

    outcome = classify_terminal_outcome(state)

    assert outcome.status is WorkflowStatus.INVALID
    assert outcome.reason_code == "baseline_evaluation_invalid"
    assert outcome.successful is False


def test_failed_candidate_provider_is_failed_not_rejected():
    candidate = supplied_baseline_candidate()
    state = create_comparison_state(
        task_id="terminal-failed",
        baseline_parameters=candidate,
    )
    state["current_candidate_id"] = candidate.candidate_id
    state["hfss_results"] = (
        HFSSResult(
            candidate_id=candidate.candidate_id,
            success=False,
            error="offline injected provider failure",
        ),
    )

    outcome = classify_terminal_outcome(state)

    assert outcome.status is WorkflowStatus.FAILED
    assert outcome.reason_code == "candidate_hfss_failed"
    assert outcome.successful is False


def test_authoritative_statuses_have_distinct_process_exit_codes():
    assert workflow_exit_code(WorkflowStatus.SUCCEEDED_BASELINE) == 0
    assert workflow_exit_code(WorkflowStatus.SUCCEEDED_CANDIDATE) == 0
    assert workflow_exit_code(WorkflowStatus.INVALID) == 2
    assert workflow_exit_code(WorkflowStatus.REJECTED) == 3
    assert workflow_exit_code(WorkflowStatus.CANCELLED) == 4
    assert workflow_exit_code(WorkflowStatus.FAILED) == 1
    assert workflow_exit_code(WorkflowStatus.COMPLETED) == 1
    assert workflow_exit_code("unknown") == 1
    assert workflow_exit_code(None) == 1
