"""Strict controller contracts for the real-HFSS production closed-loop Agent."""

from __future__ import annotations

from dataclasses import dataclass
from .._compat import StrEnum
import hashlib
from typing import Any

from ..domain.canonical_json import canonical_dumps, require_exact_fields


CLOSED_LOOP_WORKFLOW_ID = "closed-loop-agent-v2"
PRODUCTION_CLOSED_LOOP_POLICY_ID = "bounded-production-policy-v1"


class ControllerAction(StrEnum):
    PREPARE_OPTIMIZATION = "prepare_optimization"
    OPTIMIZE = "optimize"
    SELECT_NEXT_CANDIDATE = "select_next_candidate"
    SCREEN_CANDIDATE = "screen_candidate"
    RUN_CANDIDATE_HFSS = "run_candidate_hfss"
    NEXT_CANDIDATE = "next_candidate"
    REOPTIMIZE = "reoptimize"
    RETRY_SAFE = "retry_safe"
    RECONCILE = "reconcile"
    FINALIZE = "finalize"


@dataclass(frozen=True, slots=True)
class ClosedLoopBudget:
    max_controller_iterations: int = 64
    max_optimizer_calls: int = 2
    max_candidate_screenings: int = 16
    max_candidate_hfss_calls: int = 8
    max_reoptimizations: int = 1
    max_safe_retries: int = 1
    max_stagnation: int = 4

    def __post_init__(self) -> None:
        for name in (
            "max_controller_iterations",
            "max_optimizer_calls",
            "max_candidate_screenings",
            "max_candidate_hfss_calls",
        ):
            if not isinstance(getattr(self, name), int) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("max_reoptimizations", "max_safe_retries", "max_stagnation"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @classmethod
    def production_canary(cls) -> "ClosedLoopBudget":
        """Bound Production to baseline plus one candidate physical solve."""

        return cls(
            max_controller_iterations=64,
            max_optimizer_calls=2,
            max_candidate_screenings=16,
            max_candidate_hfss_calls=1,
            max_reoptimizations=1,
            max_safe_retries=0,
            max_stagnation=4,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "ClosedLoopBudget":
        data = require_exact_fields(
            value,
            {
                "max_controller_iterations",
                "max_optimizer_calls",
                "max_candidate_screenings",
                "max_candidate_hfss_calls",
                "max_reoptimizations",
                "max_safe_retries",
                "max_stagnation",
            },
            context="ClosedLoopBudget",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ControllerDecision:
    decision_id: str
    iteration: int
    action: ControllerAction
    reason_code: str
    reason: str
    candidate_id: str | None = None

    def __post_init__(self) -> None:
        if not self.decision_id or not self.reason_code or not self.reason:
            raise ValueError("controller decision identity and reason are required")
        if not isinstance(self.iteration, int) or self.iteration <= 0:
            raise ValueError("controller decision iteration must be positive")
        object.__setattr__(self, "action", ControllerAction(self.action))

    @classmethod
    def from_dict(cls, value: Any) -> "ControllerDecision":
        data = require_exact_fields(
            value,
            {"decision_id", "iteration", "action", "reason_code", "reason", "candidate_id"},
            context="ControllerDecision",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class ClosedLoopControllerState:
    policy_id: str
    budget: ClosedLoopBudget
    controller_iterations: int = 0
    optimizer_calls: int = 0
    candidate_screenings: int = 0
    candidate_hfss_calls: int = 0
    reoptimizations: int = 0
    safe_retries: int = 0
    stagnation_count: int = 0
    prepared_optimizer_iteration: int | None = None
    consumed_candidate_ids: tuple[str, ...] = ()
    pending_action: ControllerAction | None = None
    decisions: tuple[ControllerDecision, ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("controller policy_id is required")
        for name in (
            "controller_iterations",
            "optimizer_calls",
            "candidate_screenings",
            "candidate_hfss_calls",
            "reoptimizations",
            "safe_retries",
            "stagnation_count",
        ):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.controller_iterations != len(self.decisions):
            raise ValueError("controller iteration count must equal decision history length")
        if self.controller_iterations > self.budget.max_controller_iterations:
            raise ValueError("controller iteration budget exceeded")
        for current, maximum, label in (
            (self.optimizer_calls, self.budget.max_optimizer_calls, "optimizer"),
            (self.candidate_screenings, self.budget.max_candidate_screenings, "screening"),
            (self.candidate_hfss_calls, self.budget.max_candidate_hfss_calls, "candidate HFSS"),
            (self.reoptimizations, self.budget.max_reoptimizations, "reoptimization"),
            (self.safe_retries, self.budget.max_safe_retries, "safe retry"),
        ):
            if current > maximum:
                raise ValueError(f"{label} budget exceeded")
        if len(self.consumed_candidate_ids) != len(set(self.consumed_candidate_ids)):
            raise ValueError("consumed candidate IDs must be unique")
        if self.prepared_optimizer_iteration is not None and (
            not isinstance(self.prepared_optimizer_iteration, int)
            or self.prepared_optimizer_iteration < 0
        ):
            raise ValueError("prepared optimizer iteration must be non-negative")
        if self.pending_action is not None:
            object.__setattr__(self, "pending_action", ControllerAction(self.pending_action))

    @classmethod
    def production_canary(cls) -> "ClosedLoopControllerState":
        return cls(
            policy_id=PRODUCTION_CLOSED_LOOP_POLICY_ID,
            budget=ClosedLoopBudget.production_canary(),
        )

    @classmethod
    def from_dict(cls, value: Any) -> "ClosedLoopControllerState":
        data = require_exact_fields(
            value,
            {
                "policy_id",
                "budget",
                "controller_iterations",
                "optimizer_calls",
                "candidate_screenings",
                "candidate_hfss_calls",
                "reoptimizations",
                "safe_retries",
                "stagnation_count",
                "prepared_optimizer_iteration",
                "consumed_candidate_ids",
                "pending_action",
                "decisions",
            },
            context="ClosedLoopControllerState",
        )
        return cls(
            **{
                **data,
                "budget": ClosedLoopBudget.from_dict(data["budget"]),
                "consumed_candidate_ids": tuple(data["consumed_candidate_ids"]),
                "decisions": tuple(ControllerDecision.from_dict(item) for item in data["decisions"]),
            }
        )

    def replace(self, **changes: Any) -> "ClosedLoopControllerState":
        values = {
            "policy_id": self.policy_id,
            "budget": self.budget,
            "controller_iterations": self.controller_iterations,
            "optimizer_calls": self.optimizer_calls,
            "candidate_screenings": self.candidate_screenings,
            "candidate_hfss_calls": self.candidate_hfss_calls,
            "reoptimizations": self.reoptimizations,
            "safe_retries": self.safe_retries,
            "stagnation_count": self.stagnation_count,
            "prepared_optimizer_iteration": self.prepared_optimizer_iteration,
            "consumed_candidate_ids": self.consumed_candidate_ids,
            "pending_action": self.pending_action,
            "decisions": self.decisions,
        }
        values.update(changes)
        return ClosedLoopControllerState(**values)


def production_policy_sha256() -> str:
    controller = ClosedLoopControllerState.production_canary()
    return hashlib.sha256(
        canonical_dumps(
            {"policy_id": controller.policy_id, "budget": controller.budget}
        ).encode("utf-8")
    ).hexdigest()
