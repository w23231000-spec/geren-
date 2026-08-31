"""Alias-free Version-2 state for baseline→candidate comparison workflows."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from typing import Any, TypedDict

from ..core.enums import WorkflowStatus
from ..core.models import (
    CandidateParameters,
    ComplexSParameters,
    HFSSResult,
    SParameterResult,
    TerminalOutcome,
)
from ..diagnosis import DiagnosisResult
from ..domain.canonical_json import (
    CanonicalJsonError,
    require_exact_fields,
    to_json_value,
)
from ..domain.contracts import (
    STATE_SCHEMA_VERSION,
    ArtifactRef,
    BestPolicy,
    CandidateSnapshot,
    ComparisonRecord,
    DecisionOutcome,
    DesignGoal,
    EvaluationRecord,
    FrozenMap,
    OptimizationRunRecord,
    RunManifestV2,
)
from ..optimization.intent import OptimizationIntent, OptimizationObjective
from .closed_loop_contracts import ClosedLoopControllerState


WORKFLOW_ID_V2 = "baseline-optimize-hfss-compare-v2"


class ComparisonAgentState(TypedDict):
    schema_version: str
    manifest: RunManifestV2
    candidates: tuple[CandidateSnapshot, ...]
    current_candidate_id: str | None
    candidate_queue: tuple[str, ...]
    sparameter_results: tuple[SParameterResult, ...]
    hfss_results: tuple[HFSSResult, ...]
    evaluations: tuple[EvaluationRecord, ...]
    comparisons: tuple[ComparisonRecord, ...]
    diagnoses: tuple[DiagnosisResult, ...]
    optimization_run: OptimizationRunRecord | None
    optimization_intent: OptimizationIntent | None
    optimization_objective: OptimizationObjective | None
    best_policy: BestPolicy | None
    decision_outcome: DecisionOutcome | None
    terminal_outcome: TerminalOutcome | None
    controller: ClosedLoopControllerState | None
    artifact_refs: tuple[ArtifactRef, ...]
    status: str
    last_error: str | None
    execution_trace: tuple[str, ...]


def create_comparison_state(
    *,
    task_id: str,
    baseline_parameters: CandidateParameters,
    target_specification: dict[str, Any] | None = None,
    evaluation_contract_id: str = "unspecified-evaluation-contract",
    comparison_context_id: str | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    code_revision: str | None = None,
    provider_fingerprints: dict[str, Any] | None = None,
    config_fingerprints: dict[str, Any] | None = None,
    real_execution: bool = False,
    controller: ClosedLoopControllerState | None = None,
    workflow_id: str = WORKFLOW_ID_V2,
) -> ComparisonAgentState:
    context_id = comparison_context_id or f"context:{task_id}"
    normalized_run_id = run_id or f"run:{task_id}"
    goal = DesignGoal(
        goal_id=f"goal:{task_id}",
        evaluation_contract_id=evaluation_contract_id,
        comparison_context_id=context_id,
        objective="Satisfy the configured S-parameter hard rules.",
        target_specification=FrozenMap.from_mapping(target_specification or {}),
    )
    manifest = RunManifestV2(
        schema_version=STATE_SCHEMA_VERSION,
        run_id=normalized_run_id,
        task_id=task_id,
        workflow_id=workflow_id,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        design_goal=goal,
        baseline_candidate_id=baseline_parameters.candidate_id,
        code_revision=code_revision,
        provider_fingerprints=FrozenMap.from_mapping(provider_fingerprints),
        config_fingerprints=FrozenMap.from_mapping(config_fingerprints),
        real_execution=real_execution,
    )
    baseline = CandidateSnapshot.from_candidate(
        baseline_parameters,
        context_id=context_id,
        source="baseline",
    )
    state = ComparisonAgentState(
        schema_version=STATE_SCHEMA_VERSION,
        manifest=manifest,
        candidates=(baseline,),
        current_candidate_id=None,
        candidate_queue=(),
        sparameter_results=(),
        hfss_results=(),
        evaluations=(),
        comparisons=(),
        diagnoses=(),
        optimization_run=None,
        optimization_intent=None,
        optimization_objective=None,
        best_policy=None,
        decision_outcome=None,
        terminal_outcome=None,
        controller=controller,
        artifact_refs=(),
        status=WorkflowStatus.CREATED,
        last_error=None,
        execution_trace=(),
    )
    return validate_comparison_state(state)


def state_task_id(state: ComparisonAgentState) -> str:
    return state["manifest"].task_id


def state_run_id(state: ComparisonAgentState) -> str:
    return state["manifest"].run_id


def state_context_id(state: ComparisonAgentState) -> str:
    return state["manifest"].design_goal.comparison_context_id


def state_target_specification(state: ComparisonAgentState) -> dict[str, Any]:
    return state["manifest"].design_goal.to_target_specification()


def candidate_index(state: ComparisonAgentState) -> dict[str, CandidateSnapshot]:
    return {candidate.candidate_id: candidate for candidate in state["candidates"]}


def candidate_snapshot(
    state: ComparisonAgentState, candidate_id: str | None
) -> CandidateSnapshot | None:
    if candidate_id is None:
        return None
    return candidate_index(state).get(candidate_id)


def candidate_parameters(
    state: ComparisonAgentState, candidate_id: str | None
) -> CandidateParameters | None:
    snapshot = candidate_snapshot(state, candidate_id)
    return snapshot.to_candidate() if snapshot is not None else None


def baseline_candidate(state: ComparisonAgentState) -> CandidateParameters:
    candidate = candidate_parameters(state, state["manifest"].baseline_candidate_id)
    if candidate is None:
        raise ValueError("manifest baseline_candidate_id is not present in candidates")
    return candidate


def current_candidate(state: ComparisonAgentState) -> CandidateParameters | None:
    return candidate_parameters(state, state["current_candidate_id"])


def best_candidate(state: ComparisonAgentState) -> CandidateParameters | None:
    policy = state["best_policy"]
    return candidate_parameters(state, policy.selected_candidate_id) if policy else None


def sparameter_result(
    state: ComparisonAgentState, candidate_id: str | None
) -> SParameterResult | None:
    return next(
        (item for item in state["sparameter_results"] if item.candidate_id == candidate_id),
        None,
    )


def hfss_result(
    state: ComparisonAgentState, candidate_id: str | None
) -> HFSSResult | None:
    return next(
        (item for item in state["hfss_results"] if item.candidate_id == candidate_id),
        None,
    )


def baseline_sparameter_result(state: ComparisonAgentState) -> SParameterResult | None:
    return sparameter_result(state, state["manifest"].baseline_candidate_id)


def candidate_sparameter_result(state: ComparisonAgentState) -> SParameterResult | None:
    return sparameter_result(state, state["current_candidate_id"])


def baseline_hfss_result(state: ComparisonAgentState) -> HFSSResult | None:
    return hfss_result(state, state["manifest"].baseline_candidate_id)


def candidate_hfss_result(state: ComparisonAgentState) -> HFSSResult | None:
    return hfss_result(state, state["current_candidate_id"])


def best_hfss_result(state: ComparisonAgentState) -> HFSSResult | None:
    policy = state["best_policy"]
    return hfss_result(state, policy.selected_candidate_id) if policy else None


def best_score(state: ComparisonAgentState) -> float | None:
    result = best_hfss_result(state)
    if result is None or "score" not in result.metrics:
        return None
    return float(result.metrics["score"])


def evaluation_record(
    state: ComparisonAgentState,
    *,
    candidate_id: str | None = None,
    stage: str | None = None,
    record_id: str | None = None,
) -> EvaluationRecord | None:
    matches = [
        item
        for item in state["evaluations"]
        if (candidate_id is None or item.candidate_id == candidate_id)
        and (stage is None or item.stage == stage)
        and (record_id is None or item.record_id == record_id)
    ]
    return matches[-1] if matches else None


def baseline_evaluation_record(state: ComparisonAgentState) -> EvaluationRecord | None:
    return evaluation_record(
        state,
        candidate_id=state["manifest"].baseline_candidate_id,
        stage="initial",
    )


def candidate_evaluation_record(state: ComparisonAgentState) -> EvaluationRecord | None:
    return evaluation_record(
        state,
        candidate_id=state["current_candidate_id"],
        stage="optimized",
    )


def baseline_evaluation(state: ComparisonAgentState):
    record = baseline_evaluation_record(state)
    return record.to_result() if record else None


def candidate_evaluation(state: ComparisonAgentState):
    record = candidate_evaluation_record(state)
    return record.to_result() if record else None


def current_comparison_record(state: ComparisonAgentState) -> ComparisonRecord | None:
    candidate_id = state["current_candidate_id"]
    matches = [item for item in state["comparisons"] if item.candidate_id == candidate_id]
    return matches[-1] if matches else None


def current_comparison(state: ComparisonAgentState):
    record = current_comparison_record(state)
    return record.to_comparison() if record else None


def diagnosis_for_stage(
    state: ComparisonAgentState, stage: str
) -> DiagnosisResult | None:
    matches = [item for item in state["diagnoses"] if item.stage == stage]
    return matches[-1] if matches else None


def baseline_diagnosis(state: ComparisonAgentState) -> DiagnosisResult | None:
    return diagnosis_for_stage(state, "initial")


def candidate_diagnosis(state: ComparisonAgentState) -> DiagnosisResult | None:
    return diagnosis_for_stage(state, "optimized")


def optimization_batch(state: ComparisonAgentState):
    record = state["optimization_run"]
    return record.to_batch(candidate_index(state)) if record else None


def append_candidate_snapshots(
    state: ComparisonAgentState,
    candidates: list[CandidateParameters] | tuple[CandidateParameters, ...],
    *,
    source: str,
    parent_candidate_id: str | None,
) -> tuple[CandidateSnapshot, ...]:
    existing = candidate_index(state)
    ordered = list(state["candidates"])
    for candidate in candidates:
        snapshot = CandidateSnapshot.from_candidate(
            candidate,
            context_id=state_context_id(state),
            source=source,
            parent_candidate_id=parent_candidate_id,
        )
        prior = existing.get(snapshot.candidate_id)
        if prior is not None and prior != snapshot:
            raise ValueError(f"candidate ID {snapshot.candidate_id} has conflicting snapshots")
        if prior is None:
            existing[snapshot.candidate_id] = snapshot
            ordered.append(snapshot)
    return tuple(ordered)


def append_result_by_candidate(
    existing: tuple[Any, ...], result: Any, *, label: str
) -> tuple[Any, ...]:
    prior = next(
        (item for item in existing if item.candidate_id == result.candidate_id), None
    )
    if prior is not None:
        if prior != result:
            raise ValueError(
                f"{label} for candidate {result.candidate_id} conflicts with existing evidence"
            )
        return existing
    return (*existing, result)


def append_record_by_id(
    existing: tuple[Any, ...], record: Any, *, label: str
) -> tuple[Any, ...]:
    prior = next((item for item in existing if item.record_id == record.record_id), None)
    if prior is not None:
        if prior != record:
            raise ValueError(f"{label} ID {record.record_id} has conflicting evidence")
        return existing
    return (*existing, record)


def append_artifact_refs(
    existing: tuple[ArtifactRef, ...], *references: ArtifactRef
) -> tuple[ArtifactRef, ...]:
    by_id = {reference.artifact_id: reference for reference in existing}
    ordered = list(existing)
    for reference in references:
        prior = by_id.get(reference.artifact_id)
        if prior is not None and prior != reference:
            raise ValueError(
                f"ArtifactRef ID {reference.artifact_id} has conflicting evidence"
            )
        if prior is None:
            by_id[reference.artifact_id] = reference
            ordered.append(reference)
    return tuple(ordered)


def with_changes(state: ComparisonAgentState, changes: dict[str, Any]) -> ComparisonAgentState:
    return validate_comparison_state(ComparisonAgentState(**{**state, **changes}))


def validate_comparison_state(state: ComparisonAgentState) -> ComparisonAgentState:
    if set(state) != set(ComparisonAgentState.__required_keys__):
        unknown = sorted(set(state) - set(ComparisonAgentState.__required_keys__))
        missing = sorted(set(ComparisonAgentState.__required_keys__) - set(state))
        raise ValueError(f"State V2 fields mismatch; unknown={unknown}, missing={missing}")
    if state["schema_version"] != STATE_SCHEMA_VERSION:
        raise ValueError(f"State schema_version must be {STATE_SCHEMA_VERSION}")
    manifest = state["manifest"]
    if manifest.schema_version != STATE_SCHEMA_VERSION:
        raise ValueError("State and manifest schema versions do not match")
    run_id = manifest.run_id
    context_id = manifest.design_goal.comparison_context_id

    candidates = candidate_index(state)
    if len(candidates) != len(state["candidates"]):
        raise ValueError("candidate IDs must be unique")
    if manifest.baseline_candidate_id not in candidates:
        raise ValueError("manifest baseline candidate is missing")
    for snapshot in state["candidates"]:
        if snapshot.context_id != context_id:
            raise ValueError(
                f"candidate {snapshot.candidate_id} has wrong comparison context"
            )
        if snapshot.parent_candidate_id is not None and snapshot.parent_candidate_id not in candidates:
            raise ValueError(
                f"candidate {snapshot.candidate_id} references an unknown parent"
            )
    referenced_candidate_ids = [
        candidate_id
        for candidate_id in (state["current_candidate_id"], *state["candidate_queue"])
        if candidate_id is not None
    ]
    if len(state["candidate_queue"]) != len(set(state["candidate_queue"])):
        raise ValueError("candidate queue IDs must be unique")
    for candidate_id in referenced_candidate_ids:
        if candidate_id not in candidates:
            raise ValueError(f"state references unknown candidate {candidate_id}")

    for label, values in (
        ("S-parameter result", state["sparameter_results"]),
        ("HFSS result", state["hfss_results"]),
    ):
        ids = [value.candidate_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{label} candidate IDs must be unique")
        for candidate_id in ids:
            if candidate_id not in candidates:
                raise ValueError(f"{label} references unknown candidate {candidate_id}")

    evaluations = {record.record_id: record for record in state["evaluations"]}
    if len(evaluations) != len(state["evaluations"]):
        raise ValueError("EvaluationRecord IDs must be unique")
    for record in state["evaluations"]:
        if record.run_id != run_id or record.context_id != context_id:
            raise ValueError(f"EvaluationRecord {record.record_id} has wrong run/context")
        if record.candidate_id not in candidates:
            raise ValueError(
                f"EvaluationRecord {record.record_id} references unknown candidate"
            )

    comparisons = {record.record_id: record for record in state["comparisons"]}
    if len(comparisons) != len(state["comparisons"]):
        raise ValueError("ComparisonRecord IDs must be unique")
    for record in state["comparisons"]:
        if record.run_id != run_id or record.context_id != context_id:
            raise ValueError(f"ComparisonRecord {record.record_id} has wrong run/context")
        baseline = evaluations.get(record.baseline_evaluation_id)
        candidate = evaluations.get(record.candidate_evaluation_id)
        if baseline is None or candidate is None:
            raise ValueError(
                f"ComparisonRecord {record.record_id} references unknown evaluation evidence"
            )
        if (
            baseline.candidate_id != record.baseline_candidate_id
            or candidate.candidate_id != record.candidate_id
        ):
            raise ValueError(
                f"ComparisonRecord {record.record_id} candidate identity is inconsistent"
            )

    diagnosis_stages = [diagnosis.stage for diagnosis in state["diagnoses"]]
    if len(diagnosis_stages) != len(set(diagnosis_stages)):
        raise ValueError("Diagnosis facts must be unique by stage")

    policy = state["best_policy"]
    if policy is not None:
        if policy.run_id != run_id or policy.context_id != context_id:
            raise ValueError("BestPolicy has wrong run/context")
        if policy.selected_candidate_id not in candidates:
            raise ValueError("BestPolicy selected candidate is unknown")
        seed = evaluations.get(policy.seed_evaluation_id)
        if seed is None or seed.candidate_id != manifest.baseline_candidate_id:
            raise ValueError("BestPolicy seed must reference baseline Evaluation evidence")
        if policy.selection_comparison_id is None:
            if policy.selected_candidate_id != manifest.baseline_candidate_id:
                raise ValueError(
                    "BestPolicy can select a non-baseline candidate only from Comparison evidence"
                )
        else:
            comparison = comparisons.get(policy.selection_comparison_id)
            if comparison is None:
                raise ValueError("BestPolicy references unknown Comparison evidence")
            if not comparison.promotion_eligible:
                raise ValueError("BestPolicy references ineligible Comparison evidence")
            if comparison.candidate_id != policy.selected_candidate_id:
                raise ValueError("BestPolicy candidate does not match Comparison evidence")

    decision = state["decision_outcome"]
    if decision is not None:
        if decision.run_id != run_id or decision.context_id != context_id:
            raise ValueError("DecisionOutcome has wrong run/context")
        if decision.candidate_id is not None and decision.candidate_id not in candidates:
            raise ValueError("DecisionOutcome references unknown candidate")

    terminal = state["terminal_outcome"]
    if terminal is not None:
        if terminal.run_id != run_id or terminal.context_id != context_id:
            raise ValueError("TerminalOutcome has wrong run/context")
        if terminal.candidate_id is not None and terminal.candidate_id not in candidates:
            raise ValueError("TerminalOutcome references unknown candidate")

    controller = state["controller"]
    if controller is not None:
        if manifest.workflow_id != "closed-loop-agent-v2":
            raise ValueError("controller state is allowed only for closed-loop-agent-v2")
        if any(candidate_id not in candidates for candidate_id in controller.consumed_candidate_ids):
            raise ValueError("controller references an unknown consumed candidate")
        if state["current_candidate_id"] in controller.consumed_candidate_ids:
            raise ValueError("current candidate cannot already be consumed")

    artifact_ids = [artifact.artifact_id for artifact in state["artifact_refs"]]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise ValueError("ArtifactRef IDs must be unique")
    for artifact in state["artifact_refs"]:
        if artifact.run_id != run_id or artifact.context_id != context_id:
            raise ValueError(f"ArtifactRef {artifact.artifact_id} has wrong run/context")
        if artifact.candidate_id is not None and artifact.candidate_id not in candidates:
            raise ValueError(f"ArtifactRef {artifact.artifact_id} has wrong candidate")
    artifact_id_set = set(artifact_ids)
    for evaluation in state["evaluations"]:
        if not set(evaluation.artifact_refs).issubset(artifact_id_set):
            raise ValueError(
                f"EvaluationRecord {evaluation.record_id} references unknown artifacts"
            )
    return state


def comparison_state_to_dict(state: ComparisonAgentState) -> dict[str, Any]:
    """Return a detached strict JSON projection while detecting source aliases."""

    return to_json_value(validate_comparison_state(state))


def _expected_dataclass_fields(cls: type) -> set[str]:
    return {field.name for field in fields(cls)}


def _response_from_dict(value: Any) -> ComplexSParameters | None:
    if value is None:
        return None
    data = require_exact_fields(
        value, _expected_dataclass_fields(ComplexSParameters), context="ComplexSParameters"
    )
    return ComplexSParameters(
        frequency_hz=list(data["frequency_hz"]),
        real=[[list(row) for row in matrix] for matrix in data["real"]],
        imag=[[list(row) for row in matrix] for matrix in data["imag"]],
        port_order=tuple(data["port_order"]),
        reference_impedance_ohm=data["reference_impedance_ohm"],
    )


def _sparameter_from_dict(value: Any) -> SParameterResult:
    data = require_exact_fields(
        value, _expected_dataclass_fields(SParameterResult), context="SParameterResult"
    )
    return SParameterResult(
        candidate_id=data["candidate_id"],
        success=data["success"],
        response=_response_from_dict(data["response"]),
        metrics=dict(data["metrics"]),
        provider=data["provider"],
        model_version=data["model_version"],
        calibration_status=data["calibration_status"],
        artifact_paths=list(data["artifact_paths"]),
        error=data["error"],
        metadata=dict(data["metadata"]),
    )


def _hfss_from_dict(value: Any) -> HFSSResult:
    data = require_exact_fields(
        value, _expected_dataclass_fields(HFSSResult), context="HFSSResult"
    )
    return HFSSResult(
        candidate_id=data["candidate_id"],
        success=data["success"],
        frequency=list(data["frequency"]),
        s_parameters={key: list(item) for key, item in data["s_parameters"].items()},
        metrics=dict(data["metrics"]),
        project_path=data["project_path"],
        artifact_paths=list(data["artifact_paths"]),
        error=data["error"],
        complex_response=_response_from_dict(data["complex_response"]),
        execution_metadata=dict(data["execution_metadata"]),
    )


def _diagnosis_from_dict(value: Any) -> DiagnosisResult:
    require_exact_fields(
        value, _expected_dataclass_fields(DiagnosisResult), context="DiagnosisResult"
    )
    return DiagnosisResult.from_dict(dict(value))


def _intent_from_dict(value: Any) -> OptimizationIntent | None:
    if value is None:
        return None
    data = require_exact_fields(
        value, _expected_dataclass_fields(OptimizationIntent), context="OptimizationIntent"
    )
    copied = dict(data)
    copied["secondary_focuses"] = list(copied["secondary_focuses"])
    return OptimizationIntent(**copied)


def _objective_from_dict(value: Any) -> OptimizationObjective | None:
    if value is None:
        return None
    data = require_exact_fields(
        value,
        _expected_dataclass_fields(OptimizationObjective),
        context="OptimizationObjective",
    )
    copied = dict(data)
    copied["priority_terms"] = [dict(item) for item in copied["priority_terms"]]
    copied["protected_constraints"] = list(copied["protected_constraints"])
    copied["source_intent"] = dict(copied["source_intent"])
    return OptimizationObjective(**copied)


def _terminal_from_dict(value: Any) -> TerminalOutcome | None:
    if value is None:
        return None
    data = require_exact_fields(
        value, _expected_dataclass_fields(TerminalOutcome), context="TerminalOutcome"
    )
    return TerminalOutcome(**{**data, "evidence_ids": tuple(data["evidence_ids"])})


def comparison_state_from_dict(data: dict[str, Any]) -> ComparisonAgentState:
    """Strictly decode State V2; V1 is handled only by the checkpoint migrator."""

    expected = set(ComparisonAgentState.__required_keys__)
    legacy_phase3_fields = expected - {"controller"}
    if set(data) == legacy_phase3_fields:
        data = {**data, "controller": None}
    value = require_exact_fields(data, expected, context="ComparisonAgentStateV2")
    state = ComparisonAgentState(
        schema_version=value["schema_version"],
        manifest=RunManifestV2.from_dict(value["manifest"]),
        candidates=tuple(CandidateSnapshot.from_dict(item) for item in value["candidates"]),
        current_candidate_id=value["current_candidate_id"],
        candidate_queue=tuple(value["candidate_queue"]),
        sparameter_results=tuple(
            _sparameter_from_dict(item) for item in value["sparameter_results"]
        ),
        hfss_results=tuple(_hfss_from_dict(item) for item in value["hfss_results"]),
        evaluations=tuple(
            EvaluationRecord.from_dict(item) for item in value["evaluations"]
        ),
        comparisons=tuple(
            ComparisonRecord.from_dict(item) for item in value["comparisons"]
        ),
        diagnoses=tuple(_diagnosis_from_dict(item) for item in value["diagnoses"]),
        optimization_run=(
            OptimizationRunRecord.from_dict(value["optimization_run"])
            if value["optimization_run"] is not None
            else None
        ),
        optimization_intent=_intent_from_dict(value["optimization_intent"]),
        optimization_objective=_objective_from_dict(value["optimization_objective"]),
        best_policy=(
            BestPolicy.from_dict(value["best_policy"])
            if value["best_policy"] is not None
            else None
        ),
        decision_outcome=(
            DecisionOutcome.from_dict(value["decision_outcome"])
            if value["decision_outcome"] is not None
            else None
        ),
        terminal_outcome=_terminal_from_dict(value["terminal_outcome"]),
        controller=(
            ClosedLoopControllerState.from_dict(value["controller"])
            if value["controller"] is not None
            else None
        ),
        artifact_refs=tuple(ArtifactRef.from_dict(item) for item in value["artifact_refs"]),
        status=value["status"],
        last_error=value["last_error"],
        execution_trace=tuple(value["execution_trace"]),
    )
    return validate_comparison_state(state)
