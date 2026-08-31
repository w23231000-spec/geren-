"""Small configuration surface for the single presentation workflow."""

from dataclasses import dataclass, field
from pathlib import Path

from .models import FrequencyPlan
from ..harness.core import HarnessSettings


@dataclass(slots=True)
class EvaluationConfig:
    candidate_gate_score: float = -1.0
    target_score: float = 0.5
    improvement_tolerance: float = 1e-12
    rules: tuple[dict, ...] = ()
    frequency_plan: FrequencyPlan = field(default_factory=FrequencyPlan)


@dataclass(slots=True)
class RoutingConfig:
    stop_on_target: bool = True


@dataclass(slots=True)
class AppConfig:
    artifact_root: Path = Path("runs")
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    harness: HarnessSettings = field(default_factory=HarnessSettings)
    closed_loop_enabled: bool = False
