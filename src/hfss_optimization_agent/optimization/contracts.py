"""Versioned contracts for diagnosis-driven, auditable optimizer workers."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ..core.models import CandidateParameters, ComplexSParameters, SParameterResult
from ..domain.canonical_json import canonical_dumps
from ..evaluation.rule_semantics import violation_expression
from .intent import OptimizationObjective


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_dumps(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EffectiveObjectiveTerm:
    name: str
    expression: str
    direction: str
    target: float | None
    recommendation_weight: float
    start_ghz: float | None
    stop_ghz: float | None
    unit: str
    description: str
    source_focus: str
    priority: int

    def __post_init__(self) -> None:
        if not self.name or not self.expression or not self.source_focus:
            raise ValueError("effective objective identity fields cannot be empty")
        if self.direction not in {"min", "max", "target"}:
            raise ValueError("effective objective direction must be min/max/target")
        if self.direction == "target" and self.target is None:
            raise ValueError("target objective requires target")
        if self.direction != "target" and self.target is not None:
            raise ValueError("only target objectives may carry target")
        if not math.isfinite(self.recommendation_weight) or self.recommendation_weight <= 0.0:
            raise ValueError("effective objective weight must be positive and finite")
        if (self.start_ghz is None) != (self.stop_ghz is None):
            raise ValueError("effective objective band endpoints must be paired")
        if self.start_ghz is not None and not self.start_ghz < self.stop_ghz:  # type: ignore[operator]
            raise ValueError("effective objective band must have start < stop")
        if self.priority < 1:
            raise ValueError("effective objective priority must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectiveObjectiveTerm":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class EffectiveObjective:
    schema_version: str
    terms: tuple[EffectiveObjectiveTerm, ...]
    protected_constraints: tuple[str, ...]
    source_objective_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != "optimizer-objective/1.0":
            raise ValueError("unsupported effective objective schema")
        if len(self.terms) < 2:
            raise ValueError("vendor optimizer requires at least two effective objectives")
        names = [term.name for term in self.terms]
        if len(names) != len(set(names)):
            raise ValueError("effective objective names must be unique")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "terms": [term.to_dict() for term in self.terms],
            "protected_constraints": list(self.protected_constraints),
            "source_objective_digest": self.source_objective_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EffectiveObjective":
        return cls(
            schema_version=str(value["schema_version"]),
            terms=tuple(EffectiveObjectiveTerm.from_dict(item) for item in value["terms"]),
            protected_constraints=tuple(str(item) for item in value["protected_constraints"]),
            source_objective_digest=str(value["source_objective_digest"]),
        )


def map_effective_objective(
    objective: OptimizationObjective,
    target_specification: Mapping[str, Any],
) -> EffectiveObjective:
    """Translate Agent priority terms into the vendor's runtime objective rows."""

    source = objective.to_dict()
    source_digest = _digest(source)
    terms: list[EffectiveObjectiveTerm] = []
    for raw in objective.priority_terms:
        rule_id = str(raw.get("source_rule_id") or "UNKNOWN")
        priority = int(raw.get("priority", len(terms) + 1))
        parameter = str(raw.get("parameter", "")).upper()
        operator = str(raw.get("operator", ""))
        threshold = float(raw.get("threshold"))
        band = raw.get("frequency_band")
        if not isinstance(band, (list, tuple)) or len(band) != 2:
            raise ValueError(f"effective objective rule {rule_id} requires a frequency band")
        start_ghz, stop_ghz = float(band[0]), float(band[1])
        penalty = max(0.0, float(raw.get("penalty", 0.0)))
        hard = bool(raw.get("hard_constraint"))
        safe_rule_id = "".join(character if character.isalnum() else "_" for character in rule_id)
        terms.append(
            EffectiveObjectiveTerm(
                name=f"agent_p{priority}_{safe_rule_id}_violation_db",
                expression=violation_expression(
                    parameter=parameter,
                    operator=operator,
                    threshold=threshold,
                ),
                direction="min",
                target=None,
                recommendation_weight=((10.0 if hard else 1.0) * (1.0 + penalty)) / priority,
                start_ghz=start_ghz,
                stop_ghz=stop_ghz,
                unit="dB violation",
                description=(
                    f"Rule {rule_id}: {parameter} {operator} {threshold:g} dB "
                    f"for every sample in [{start_ghz:g}, {stop_ghz:g}] GHz"
                ),
                source_focus=rule_id,
                priority=priority,
            )
        )
    if not terms:
        raise ValueError("ACTIVE optimization objective must contain rule-driven terms")
    return EffectiveObjective(
        schema_version="optimizer-objective/1.0",
        terms=tuple(terms),
        protected_constraints=tuple(str(item) for item in objective.protected_constraints),
        source_objective_digest=source_digest,
    )


@dataclass(frozen=True, slots=True)
class OptimizerRequest:
    schema_version: str
    run_id: str
    context_id: str
    iteration: int
    baseline: CandidateParameters
    baseline_sparameters: SParameterResult
    design_goal: dict[str, Any]
    diagnosis_digest: str
    target_specification: dict[str, Any]
    optimization_objective: OptimizationObjective
    effective_objective: EffectiveObjective
    provider_fingerprints: dict[str, Any]
    config_fingerprints: dict[str, Any]

    def __post_init__(self) -> None:
        if self.schema_version != "optimizer-request/1.0":
            raise ValueError("unsupported optimizer request schema")
        if not self.run_id or not self.context_id or not self.diagnosis_digest:
            raise ValueError("optimizer request identity fields cannot be empty")
        if self.iteration < 0:
            raise ValueError("optimizer iteration cannot be negative")
        if self.optimization_objective.status != "ACTIVE":
            raise ValueError("optimizer request requires an ACTIVE objective")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "context_id": self.context_id,
            "iteration": self.iteration,
            "baseline": self.baseline.to_dict(),
            "baseline_sparameters": self.baseline_sparameters.to_dict(),
            "design_goal": self.design_goal,
            "diagnosis_digest": self.diagnosis_digest,
            "target_specification": self.target_specification,
            "optimization_objective": self.optimization_objective.to_dict(),
            "effective_objective": self.effective_objective.to_dict(),
            "provider_fingerprints": self.provider_fingerprints,
            "config_fingerprints": self.config_fingerprints,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptimizerRequest":
        baseline_raw = dict(value["baseline"])
        result_raw = dict(value["baseline_sparameters"])
        response_raw = result_raw.get("response")
        if response_raw is not None:
            response = ComplexSParameters(
                **{**response_raw, "port_order": tuple(response_raw["port_order"])}
            )
        else:
            response = None
        result_raw["response"] = response
        objective_raw = dict(value["optimization_objective"])
        return cls(
            schema_version=str(value["schema_version"]),
            run_id=str(value["run_id"]),
            context_id=str(value["context_id"]),
            iteration=int(value["iteration"]),
            baseline=CandidateParameters(**baseline_raw),
            baseline_sparameters=SParameterResult(**result_raw),
            design_goal=dict(value["design_goal"]),
            diagnosis_digest=str(value["diagnosis_digest"]),
            target_specification=dict(value["target_specification"]),
            optimization_objective=OptimizationObjective(**objective_raw),
            effective_objective=EffectiveObjective.from_dict(value["effective_objective"]),
            provider_fingerprints=dict(value["provider_fingerprints"]),
            config_fingerprints=dict(value["config_fingerprints"]),
        )
