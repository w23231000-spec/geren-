"""Runtime task contract for the real-HFSS closed loop.

Optimization targets are runtime data. They should normally be stored under
``runs/requests`` so changing one task never dirties the Git working tree.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .core.config import EvaluationConfig
from .core.models import FrequencyPlan
from .domain.canonical_json import canonical_dumps, require_exact_fields


OPTIMIZATION_REQUEST_SCHEMA_VERSION = "optimization-request/1.0"
OPTIMIZATION_REQUEST_ENV = "HFSS_OPTIMIZATION_REQUEST"
SUPPORTED_MODEL_ID = "interposer_temple4"


@dataclass(frozen=True, slots=True)
class OptimizationRuleRequest:
    rule_id: str
    parameter: str
    frequency_band: tuple[float, float]
    operator: str
    threshold: float
    hard_constraint: bool
    frequency_unit: str = "GHz"

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not self.rule_id.strip():
            raise ValueError("optimization rule_id must be non-empty")
        parameter = str(self.parameter).upper()
        if parameter not in {"S11", "S21"}:
            raise ValueError("optimization rules currently support only S11/S21")
        object.__setattr__(self, "parameter", parameter)
        if self.operator not in {"<=", ">="}:
            raise ValueError("optimization rule operator must be <= or >=")

        try:
            band = tuple(float(value) for value in self.frequency_band)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "optimization rule frequency_band must be numeric"
            ) from exc
        if (
            len(band) != 2
            or not all(math.isfinite(value) for value in band)
            or band[0] >= band[1]
        ):
            raise ValueError(
                "optimization rule frequency_band requires finite start < stop"
            )
        object.__setattr__(self, "frequency_band", band)

        threshold = float(self.threshold)
        if not math.isfinite(threshold):
            raise ValueError("optimization rule threshold must be finite")
        object.__setattr__(self, "threshold", threshold)

        if not isinstance(self.hard_constraint, bool):
            raise ValueError("optimization rule hard_constraint must be boolean")
        if self.frequency_unit != "GHz":
            raise ValueError("optimization request v1 requires GHz")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "parameter": self.parameter,
            "frequency_band": list(self.frequency_band),
            "operator": self.operator,
            "threshold": self.threshold,
            "hard_constraint": self.hard_constraint,
            "frequency_unit": self.frequency_unit,
        }

    @classmethod
    def from_dict(
        cls, value: Mapping[str, Any]
    ) -> "OptimizationRuleRequest":
        data = require_exact_fields(
            value,
            {
                "rule_id",
                "parameter",
                "frequency_band",
                "operator",
                "threshold",
                "hard_constraint",
                "frequency_unit",
            },
            context="OptimizationRuleRequest",
        )
        return cls(**data)


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    schema_version: str
    model_id: str
    frequency_plan: FrequencyPlan
    rules: tuple[OptimizationRuleRequest, ...]
    max_optimization_rounds: int

    def __post_init__(self) -> None:
        if self.schema_version != OPTIMIZATION_REQUEST_SCHEMA_VERSION:
            raise ValueError(
                "optimization request schema_version must be "
                f"{OPTIMIZATION_REQUEST_SCHEMA_VERSION}"
            )
        if self.model_id != SUPPORTED_MODEL_ID:
            raise ValueError(
                f"optimization request currently supports only "
                f"{SUPPORTED_MODEL_ID}"
            )
        if not isinstance(self.frequency_plan, FrequencyPlan):
            raise ValueError(
                "optimization request frequency_plan must be typed"
            )
        if not self.frequency_plan.is_valid:
            raise ValueError(
                self.frequency_plan.validation_error
                or "invalid optimization frequency plan"
            )

        if (
            not isinstance(self.max_optimization_rounds, int)
            or isinstance(self.max_optimization_rounds, bool)
            or not 1 <= self.max_optimization_rounds <= 100
        ):
            raise ValueError(
                "max_optimization_rounds must be an integer from 1 to 100"
            )

        if len(self.rules) < 2:
            raise ValueError(
                "optimization request requires at least two rules"
            )
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("optimization request rule IDs must be unique")
        if not any(rule.hard_constraint for rule in self.rules):
            raise ValueError(
                "optimization request requires at least one hard rule"
            )

        tolerance = self.frequency_plan.tolerance_ghz
        for rule in self.rules:
            expected_bands = (
                (self.frequency_plan.core_band,)
                if rule.hard_constraint
                else (
                    self.frequency_plan.lower_margin_band,
                    self.frequency_plan.upper_margin_band,
                )
            )
            if not any(
                all(
                    abs(actual - expected) <= tolerance
                    for actual, expected in zip(
                        rule.frequency_band, expected_band
                    )
                )
                for expected_band in expected_bands
            ):
                label = (
                    "core"
                    if rule.hard_constraint
                    else "lower/upper margin"
                )
                raise ValueError(
                    f"rule {rule.rule_id} must use the configured "
                    f"{label} band"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id,
            "frequency_plan": self.frequency_plan.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
            "max_optimization_rounds": self.max_optimization_rounds,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_dumps(self.to_dict()).encode("utf-8")
        ).hexdigest()

    def to_target_specification(self) -> dict[str, Any]:
        return {
            "optimization_request_schema_version": self.schema_version,
            "model_id": self.model_id,
            "frequency_plan": self.frequency_plan.to_dict(),
            "rules": [rule.to_dict() for rule in self.rules],
            "max_optimization_rounds": self.max_optimization_rounds,
            "optimization_request_sha256": self.digest,
        }

    def to_evaluation_config(
        self,
        base: EvaluationConfig | None = None,
    ) -> EvaluationConfig:
        template = base or EvaluationConfig()
        return EvaluationConfig(
            candidate_gate_score=template.candidate_gate_score,
            target_score=template.target_score,
            improvement_tolerance=template.improvement_tolerance,
            rules=tuple(rule.to_dict() for rule in self.rules),
            frequency_plan=self.frequency_plan,
        )

    def derived_real_hfss_execution(self) -> dict[str, int]:
        rounds = self.max_optimization_rounds
        return {
            "max_hfss_solve_launches": rounds + 1,
            "automatic_solve_retries": 0,
            "max_controller_iterations": max(128, 40 * rounds + 32),
            "max_optimizer_calls": max(1, rounds),
            "max_candidate_screenings": max(16, 8 * rounds),
            "max_candidate_hfss_calls": rounds,
            "max_reoptimizations": max(0, rounds - 1),
            "max_safe_retries": 0,
            "max_stagnation": rounds,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptimizationRequest":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "model_id",
                "frequency_plan",
                "rules",
                "max_optimization_rounds",
            },
            context="OptimizationRequest",
        )
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            raise ValueError("OptimizationRequest.rules must be a list")
        return cls(
            schema_version=str(data["schema_version"]),
            model_id=str(data["model_id"]),
            frequency_plan=FrequencyPlan.from_mapping(
                dict(data["frequency_plan"])
            ),
            rules=tuple(
                OptimizationRuleRequest.from_dict(item)
                for item in raw_rules
            ),
            max_optimization_rounds=int(
                data["max_optimization_rounds"]
            ),
        )


def load_optimization_request(path: Path) -> OptimizationRequest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("optimization request must be a JSON object")
    return OptimizationRequest.from_dict(payload)


def optimization_request_from_evaluation_contract(
    path: Path,
    *,
    max_optimization_rounds: int,
) -> OptimizationRequest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    plan_raw = payload.get("frequency_plan")
    rules_raw = payload.get("rules")
    if not isinstance(plan_raw, Mapping) or not isinstance(rules_raw, list):
        raise ValueError(
            "default evaluation contract is missing frequency_plan/rules"
        )
    return OptimizationRequest(
        schema_version=OPTIMIZATION_REQUEST_SCHEMA_VERSION,
        model_id=SUPPORTED_MODEL_ID,
        frequency_plan=FrequencyPlan.from_mapping(dict(plan_raw)),
        rules=tuple(
            OptimizationRuleRequest(
                rule_id=str(item["rule_id"]),
                parameter=str(item["parameter"]),
                frequency_band=tuple(item["frequency_band"]),
                operator=str(item["operator"]),
                threshold=float(item["threshold"]),
                hard_constraint=bool(item["hard_constraint"]),
                frequency_unit=str(item.get("frequency_unit", "GHz")),
            )
            for item in rules_raw
        ),
        max_optimization_rounds=max_optimization_rounds,
    )


def load_runtime_optimization_request(
    repository_root: Path,
    config: Mapping[str, Any],
) -> OptimizationRequest:
    raw_path = os.environ.get(OPTIMIZATION_REQUEST_ENV)
    if raw_path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(repository_root).resolve() / path
        if not path.is_file():
            raise FileNotFoundError(f"找不到优化任务文件：{path}")
        return load_optimization_request(path)

    execution = config.get("real_hfss_execution")
    rounds = 1
    if isinstance(execution, Mapping):
        rounds = int(execution.get("max_candidate_hfss_calls", 1))
    return optimization_request_from_evaluation_contract(
        Path(repository_root)
        / "config"
        / "evaluation_contract.production_v1.json",
        max_optimization_rounds=rounds,
    )


def apply_optimization_request_budget(
    config: Mapping[str, Any],
    request: OptimizationRequest,
) -> dict[str, Any]:
    value = dict(config)
    value["real_hfss_execution"] = request.derived_real_hfss_execution()
    return value


def validate_request_against_hfss_contract(
    request: OptimizationRequest,
    contract: Any,
) -> None:
    if request.model_id != contract.design_name:
        raise ValueError(
            "optimization request model_id differs from the HFSS contract design"
        )

    sweep_start_ghz = float(contract.sweep.start_hz) / 1e9
    sweep_stop_ghz = float(contract.sweep.stop_hz) / 1e9
    tolerance = request.frequency_plan.tolerance_ghz

    for label, band in (
        ("lower_margin_band", request.frequency_plan.lower_margin_band),
        ("core_band", request.frequency_plan.core_band),
        ("upper_margin_band", request.frequency_plan.upper_margin_band),
    ):
        if (
            band[0] < sweep_start_ghz - tolerance
            or band[1] > sweep_stop_ghz + tolerance
        ):
            raise ValueError(
                f"{label} [{band[0]}, {band[1]}] GHz exceeds HFSS sweep "
                f"[{sweep_start_ghz}, {sweep_stop_ghz}] GHz"
            )
