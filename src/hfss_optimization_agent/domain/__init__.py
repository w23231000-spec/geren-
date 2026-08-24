"""Versioned domain contracts for durable Agent state and evidence."""

from .contracts import (
    STATE_SCHEMA_VERSION,
    ArtifactRef,
    BestPolicy,
    CandidateSnapshot,
    ComparisonRecord,
    DecisionAction,
    DecisionOutcome,
    DesignGoal,
    EvaluationRecord,
    FrozenMap,
    OptimizationRunRecord,
    RunManifestV2,
)

__all__ = [
    "STATE_SCHEMA_VERSION",
    "ArtifactRef",
    "BestPolicy",
    "CandidateSnapshot",
    "ComparisonRecord",
    "DecisionAction",
    "DecisionOutcome",
    "DesignGoal",
    "EvaluationRecord",
    "FrozenMap",
    "OptimizationRunRecord",
    "RunManifestV2",
]
