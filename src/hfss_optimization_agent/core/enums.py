"""Shared workflow statuses and route actions."""

from enum import StrEnum


class WorkflowStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NextAction(StrEnum):
    RUN_HFSS = "run_hfss"
    PASS = "pass"
    STOP = "stop"
