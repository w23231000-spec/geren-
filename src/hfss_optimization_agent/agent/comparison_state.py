"""Single source of truth for baseline→optimization→candidate HFSS comparison runs."""

from typing import Any, TypedDict

from ..core.enums import WorkflowStatus
from ..core.models import (
    CandidateParameters,
    EvaluationResult,
    HFSSResult,
    OptimizationBatch,
    SParameterResult,
    ComplexSParameters,
    EvaluationComparison,
)
from ..diagnosis import DiagnosisResult
from ..optimization.intent import OptimizationIntent, OptimizationObjective


class ComparisonAgentState(TypedDict):
    task_id: str
    target_specification: dict[str, float]
    baseline_parameters: CandidateParameters
    baseline_sparameter_result: SParameterResult | None
    baseline_hfss_result: HFSSResult | None
    optimization_batch: OptimizationBatch | None
    candidate_queue: list[CandidateParameters]
    current_candidate: CandidateParameters | None
    candidate_sparameter_result: SParameterResult | None
    candidate_hfss_result: HFSSResult | None
    evaluation_result: EvaluationResult | None
    baseline_evaluation: EvaluationResult | None
    evaluation_comparison: EvaluationComparison | None
    baseline_diagnosis: DiagnosisResult | None
    diagnosis_result: DiagnosisResult | None
    diagnosis_history: list[DiagnosisResult]
    optimization_intent: OptimizationIntent | None
    optimization_objective: OptimizationObjective | None
    best_candidate: CandidateParameters | None
    best_hfss_result: HFSSResult | None
    best_score: float | None
    sparameter_history: list[SParameterResult]
    hfss_history: list[HFSSResult]
    evaluation_history: list[EvaluationResult]
    status: str
    next_action: str
    last_error: str | None
    run_metadata: dict[str, Any]
    execution_trace: list[str]


def create_comparison_state(
    *,
    task_id: str,
    baseline_parameters: CandidateParameters,
    target_specification: dict[str, float] | None = None,
) -> ComparisonAgentState:
    return ComparisonAgentState(
        task_id=task_id,
        target_specification=dict(target_specification or {}),
        baseline_parameters=baseline_parameters,
        baseline_sparameter_result=None,
        baseline_hfss_result=None,
        optimization_batch=None,
        candidate_queue=[],
        current_candidate=None,
        candidate_sparameter_result=None,
        candidate_hfss_result=None,
        evaluation_result=None,
        baseline_evaluation=None,
        evaluation_comparison=None,
        baseline_diagnosis=None,
        diagnosis_result=None,
        diagnosis_history=[],
        optimization_intent=None,
        optimization_objective=None,
        best_candidate=None,
        best_hfss_result=None,
        best_score=None,
        sparameter_history=[],
        hfss_history=[],
        evaluation_history=[],
        status=WorkflowStatus.CREATED,
        next_action="",
        last_error=None,
        run_metadata={},
        execution_trace=[],
    )


def _response_from_dict(value: dict[str, Any] | None) -> ComplexSParameters | None:
    if value is None:
        return None
    copied = dict(value)
    copied["port_order"] = tuple(copied.get("port_order", ("port_1", "port_2")))
    return ComplexSParameters(**copied)


def _sparameter_from_dict(value: dict[str, Any] | None) -> SParameterResult | None:
    if value is None:
        return None
    copied = dict(value)
    copied["response"] = _response_from_dict(copied.get("response"))
    return SParameterResult(**copied)


def _batch_from_dict(value: dict[str, Any] | None) -> OptimizationBatch | None:
    if value is None:
        return None
    copied = dict(value)
    copied["candidates"] = [CandidateParameters(**candidate) for candidate in copied["candidates"]]
    return OptimizationBatch(**copied)


def _hfss_from_dict(value: dict[str, Any] | None) -> HFSSResult | None:
    if value is None:
        return None
    copied = dict(value)
    copied["complex_response"] = _response_from_dict(copied.get("complex_response"))
    return HFSSResult(**copied)


def comparison_state_to_dict(state: ComparisonAgentState) -> dict[str, Any]:
    result: dict[str, Any] = dict(state)
    for key in ("baseline_parameters", "current_candidate", "best_candidate"):
        value = state[key]
        result[key] = value.to_dict() if value is not None else None
    for key in ("baseline_sparameter_result", "candidate_sparameter_result"):
        value = state[key]
        result[key] = value.to_dict() if value is not None else None
    for key in ("baseline_hfss_result", "candidate_hfss_result", "best_hfss_result"):
        value = state[key]
        result[key] = value.to_dict() if value is not None else None
    evaluation = state["evaluation_result"]
    result["evaluation_result"] = evaluation.to_dict() if evaluation is not None else None
    baseline_evaluation = state["baseline_evaluation"]
    result["baseline_evaluation"] = baseline_evaluation.to_dict() if baseline_evaluation is not None else None
    comparison = state["evaluation_comparison"]
    result["evaluation_comparison"] = comparison.to_dict() if comparison is not None else None
    baseline_diagnosis = state["baseline_diagnosis"]
    result["baseline_diagnosis"] = baseline_diagnosis.to_dict() if baseline_diagnosis is not None else None
    diagnosis = state["diagnosis_result"]
    result["diagnosis_result"] = diagnosis.to_dict() if diagnosis is not None else None
    result["diagnosis_history"] = [item.to_dict() for item in state["diagnosis_history"]]
    intent = state["optimization_intent"]
    result["optimization_intent"] = intent.to_dict() if intent is not None else None
    objective = state["optimization_objective"]
    result["optimization_objective"] = objective.to_dict() if objective is not None else None
    batch = state["optimization_batch"]
    result["optimization_batch"] = batch.to_dict() if batch is not None else None
    result["candidate_queue"] = [candidate.to_dict() for candidate in state["candidate_queue"]]
    result["sparameter_history"] = [item.to_dict() for item in state["sparameter_history"]]
    result["hfss_history"] = [item.to_dict() for item in state["hfss_history"]]
    result["evaluation_history"] = [item.to_dict() for item in state["evaluation_history"]]
    return result


def comparison_state_from_dict(data: dict[str, Any]) -> ComparisonAgentState:
    restored: dict[str, Any] = dict(data)
    for key in ("baseline_parameters", "current_candidate", "best_candidate"):
        value = data.get(key)
        restored[key] = CandidateParameters(**value) if value is not None else None
    for key in ("baseline_sparameter_result", "candidate_sparameter_result"):
        restored[key] = _sparameter_from_dict(data.get(key))
    for key in ("baseline_hfss_result", "candidate_hfss_result", "best_hfss_result"):
        restored[key] = _hfss_from_dict(data.get(key))
    evaluation = data.get("evaluation_result")
    restored["evaluation_result"] = EvaluationResult(**evaluation) if evaluation is not None else None
    baseline_evaluation = data.get("baseline_evaluation")
    restored["baseline_evaluation"] = EvaluationResult(**baseline_evaluation) if baseline_evaluation is not None else None
    comparison = data.get("evaluation_comparison")
    restored["evaluation_comparison"] = EvaluationComparison(**comparison) if comparison is not None else None
    baseline_diagnosis = data.get("baseline_diagnosis")
    restored["baseline_diagnosis"] = DiagnosisResult.from_dict(baseline_diagnosis) if baseline_diagnosis is not None else None
    diagnosis = data.get("diagnosis_result")
    restored["diagnosis_result"] = DiagnosisResult.from_dict(diagnosis) if diagnosis is not None else None
    restored["diagnosis_history"] = [DiagnosisResult.from_dict(item) for item in data.get("diagnosis_history", [])]
    intent = data.get("optimization_intent")
    restored["optimization_intent"] = OptimizationIntent(**intent) if intent is not None else None
    objective = data.get("optimization_objective")
    restored["optimization_objective"] = OptimizationObjective(**objective) if objective is not None else None
    restored["optimization_batch"] = _batch_from_dict(data.get("optimization_batch"))
    restored["candidate_queue"] = [CandidateParameters(**item) for item in data["candidate_queue"]]
    restored["sparameter_history"] = [
        _sparameter_from_dict(item) for item in data["sparameter_history"]
    ]
    restored["hfss_history"] = [_hfss_from_dict(item) for item in data["hfss_history"]]
    restored["evaluation_history"] = [EvaluationResult(**item) for item in data["evaluation_history"]]
    return ComparisonAgentState(**restored)
