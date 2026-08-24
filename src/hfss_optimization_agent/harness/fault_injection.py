"""Deterministic crash points used by offline reliability/chaos verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from .._compat import StrEnum
from typing import Protocol


class CrashPoint(StrEnum):
    ACTION_AFTER_CLAIM = "action_after_claim"
    ACTION_AFTER_PROVIDER = "action_after_provider"
    ACTION_AFTER_ARTIFACT_FREEZE = "action_after_artifact_freeze"
    ACTION_AFTER_RECEIPT_COMMIT = "action_after_receipt_commit"
    CHECKPOINT_BEFORE_COMMIT = "checkpoint_before_commit"
    CHECKPOINT_AFTER_COMMIT = "checkpoint_after_commit"


class InjectedProcessCrash(BaseException):
    """Represents abrupt host loss; normal exception recovery must not run."""

    def __init__(self, point: CrashPoint) -> None:
        self.point = CrashPoint(point)
        super().__init__(f"injected process crash at {self.point.value}")


class FaultInjector(Protocol):
    def hit(self, point: CrashPoint) -> None: ...


class NoFaultInjector:
    def hit(self, point: CrashPoint) -> None:
        del point


@dataclass(slots=True)
class ArmedFaultInjector:
    """Fire selected crash points once, then remain inert for deterministic resume."""

    armed: set[CrashPoint]
    fired: list[CrashPoint] = field(default_factory=list)

    def hit(self, point: CrashPoint) -> None:
        normalized = CrashPoint(point)
        if normalized not in self.armed:
            return
        self.armed.remove(normalized)
        self.fired.append(normalized)
        raise InjectedProcessCrash(normalized)
