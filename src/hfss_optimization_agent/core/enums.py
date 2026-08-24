"""Shared workflow statuses and route actions."""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED_BASELINE = "succeeded_baseline"
    SUCCEEDED_CANDIDATE = "succeeded_candidate"
    NO_SOLUTION = "no_solution"
    REJECTED = "rejected"
    INVALID = "invalid"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_RECONCILIATION = "waiting_reconciliation"


class NextAction(StrEnum):
    RUN_HFSS = "run_hfss"
    PASS = "pass"
    STOP = "stop"


SUCCESS_WORKFLOW_STATUSES = frozenset(
    {WorkflowStatus.SUCCEEDED_BASELINE, WorkflowStatus.SUCCEEDED_CANDIDATE}
)


def workflow_exit_code(status: str | WorkflowStatus) -> int:
    """Map the authoritative workflow terminal status to a process exit code."""

    try:
        normalized = WorkflowStatus(status)
    except (TypeError, ValueError):
        return 1
    if normalized in SUCCESS_WORKFLOW_STATUSES:
        return 0
    if normalized is WorkflowStatus.INVALID:
        return 2
    if normalized is WorkflowStatus.REJECTED:
        return 3
    if normalized is WorkflowStatus.CANCELLED:
        return 4
    if normalized is WorkflowStatus.WAITING_RECONCILIATION:
        return 5
    if normalized is WorkflowStatus.NO_SOLUTION:
        return 6
    return 1
