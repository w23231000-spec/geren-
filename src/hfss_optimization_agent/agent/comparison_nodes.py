"""Nodes for the confirmed initial-model versus optimized-model comparison workflow."""

from dataclasses import dataclass
from pathlib import Path
from ..core.enums import NextAction, WorkflowStatus
from ..core.models import CandidateParameters
from ..domain.contracts import (
    ArtifactRef,
    BestPolicy,
    ComparisonRecord,
    DecisionAction,
    DecisionOutcome,
    EvaluationRecord,
    OptimizationRunRecord,
    canonical_digest,
)
from ..domain.canonical_json import canonical_loads
from ..harness.checkpoint import SQLiteComparisonCheckpointStore
from ..harness.core import HarnessCore
from ..harness.result_codecs import (
    hfss_result_from_dict,
    optimization_batch_from_dict,
    sparameter_result_from_dict,
)
from ..harness.run_store import (
    ApprovalRequired,
    ArtifactReceipt,
    OperationRequest,
    OperationStatus,
)
from ..harness.final_manifest import build_final_run_manifest
from ..harness.errors import HFSSExecutionError, OptimizerError, SParameterCalculationError, WorkflowError
from ..harness.terminal import emit_stage, emit_status, emit_evaluation_summary, emit_diagnosis_summary, emit_optimization_intent
from ..interfaces.batch_optimizer import BatchOptimizerInterface
from ..interfaces.evaluator import EvaluatorInterface
from ..interfaces.hfss import HFSSInterface
from ..interfaces.sparameters import SParameterInterface
from ..evaluation.comparator import EvaluationComparator
from ..diagnosis import DiagnosisNode, DiagnosisResult
from ..optimization.intent import OptimizationIntentBuilder, OptimizationObjectiveBuilder, ACTIVE
from ..optimization.contracts import OptimizerRequest, map_effective_objective
from ..core.models import FrequencyPlan
from ..parameters.validator import ParameterValidator
from .comparison_state import (
    ComparisonAgentState,
    append_candidate_snapshots,
    append_artifact_refs,
    append_record_by_id,
    append_result_by_candidate,
    baseline_candidate,
    baseline_diagnosis,
    baseline_evaluation,
    baseline_evaluation_record,
    baseline_hfss_result,
    baseline_sparameter_result,
    candidate_evaluation,
    candidate_evaluation_record,
    candidate_hfss_result,
    candidate_sparameter_result,
    current_candidate,
    current_comparison,
    current_comparison_record,
    optimization_batch,
    state_context_id,
    state_run_id,
    state_target_specification,
    state_task_id,
    with_changes,
)
from .router import WorkflowRouter
from .supervisor import DeterministicSupervisor
from .terminal_policy import classify_terminal_outcome


@dataclass(slots=True)
class ComparisonWorkflowNodes:
    sparameters: SParameterInterface
    optimizer: BatchOptimizerInterface
    hfss: HFSSInterface
    evaluator: EvaluatorInterface
    validator: ParameterValidator
    harness: HarnessCore
    checkpoint: SQLiteComparisonCheckpointStore
    router: WorkflowRouter
    supervisor: DeterministicSupervisor
    comparator: EvaluationComparator | None = None
    diagnosis: DiagnosisNode | None = None
    intent_builder: OptimizationIntentBuilder | None = None
    objective_builder: OptimizationObjectiveBuilder | None = None
    expected_task_id: str | None = None
    expected_baseline: CandidateParameters | None = None

    @staticmethod
    def _trace(state: ComparisonAgentState, name: str) -> tuple[str, ...]:
        return (*state["execution_trace"], name)

    @staticmethod
    def _announce(current: int, title: str) -> None:
        emit_stage("主流程", current, 14, title)

    def _checkpoint_changes(self, state: ComparisonAgentState, changes: dict) -> None:
        self.checkpoint.save(with_changes(state, changes))

    @staticmethod
    def _provider_native_files(value: object) -> tuple[Path, ...]:
        """Select completed provider files; mutable directories are never ledger evidence."""

        raw_paths = list(getattr(value, "artifact_paths", ()) or ())
        project_path = getattr(value, "project_path", None)
        if project_path:
            raw_paths.append(project_path)
        selected: set[Path] = set()
        approved_directory_suffixes = {
            ".aedt",
            ".s1p",
            ".s2p",
            ".s3p",
            ".s4p",
            ".json",
            ".csv",
            ".toml",
            ".log",
            ".txt",
        }
        for raw in raw_paths:
            if not isinstance(raw, str) or "://" in raw:
                continue
            path = Path(raw)
            if path.is_file():
                selected.add(path.resolve())
            elif path.is_dir():
                discovered = tuple(
                    child.resolve()
                    for child in path.rglob("*")
                    if child.is_file()
                    and child.suffix.lower() in approved_directory_suffixes
                )
                if len(discovered) > 256:
                    raise WorkflowError(
                        "provider native artifact directory exceeds the 256-file freeze limit"
                    )
                selected.update(discovered)
            else:
                raise WorkflowError(f"provider artifact path is missing: {raw}")
        return tuple(sorted(selected, key=lambda item: str(item).casefold()))

    def _artifact_ref(
        self,
        state: ComparisonAgentState,
        receipt: ArtifactReceipt,
        *,
        candidate_id: str | None = None,
    ) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=receipt.artifact_id,
            uri=receipt.relative_uri,
            role=receipt.role,
            media_type=receipt.media_type,
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            candidate_id=candidate_id,
            sha256=receipt.sha256,
        )

    def _provider_request(
        self,
        state: ComparisonAgentState,
        *,
        kind: str,
        subject_id: str,
        idempotency_key: str,
        payload: dict,
        result_role: str,
        ambiguity_on_exception: bool = False,
    ) -> OperationRequest:
        approval_scope = None
        approval_id = None
        if kind == "hfss" and state["manifest"].real_execution:
            approval_scope = "real_hfss"
            expected_approval_id = state[
                "manifest"
            ].config_fingerprints.to_dict().get("real_hfss_authorization_id")
            if not isinstance(expected_approval_id, str) or not expected_approval_id:
                raise ApprovalRequired(
                    "real HFSS RunManifest has no authorization identity fingerprint"
                )
            approval_id = next(
                (
                    grant.approval_id
                    for grant in self.harness.settings.approvals
                    if grant.scope == approval_scope
                    and grant.approval_id == expected_approval_id
                ),
                None,
            )
            if approval_id is None:
                raise ApprovalRequired("real HFSS action has no RunStore approval grant")
        return OperationRequest(
            run_id=state_run_id(state),
            kind=kind,
            subject_id=subject_id,
            idempotency_key=idempotency_key,
            payload={
                **payload,
                "context_id": state_context_id(state),
                "provider_fingerprints": state["manifest"].provider_fingerprints,
                "config_fingerprints": state["manifest"].config_fingerprints,
            },
            result_role=result_role,
            estimated_cost=self.harness.cost_for(kind),
            approval_scope=approval_scope,
            approval_id=approval_id,
            ambiguity_on_exception=ambiguity_on_exception,
        )

    def _run_hfss_provider(
        self, state: ComparisonAgentState, candidate: CandidateParameters
    ):
        result = self.hfss.run(candidate)
        if state["manifest"].real_execution and not result.success:
            # GuardedHFSSAdapter intentionally returns structured failures. Until
            # worker/AEDT termination is positively reconciled, a real failure is
            # conservatively an indeterminate physical outcome, not a safe retry.
            raise HFSSExecutionError(
                f"Real HFSS physical outcome is not confirmed: {result.error}"
            )
        return result

    def _record_artifact(
        self,
        state: ComparisonAgentState,
        *,
        subject_id: str,
        key: str,
        role: str,
        value,
    ):
        return self.harness.record_artifact(
            run_id=state_run_id(state),
            subject_id=subject_id,
            idempotency_key=f"artifact:{key}",
            role=role,
            value=value,
        )

    def attach_final_manifest(
        self, state: ComparisonAgentState
    ) -> ComparisonAgentState:
        """Publish one stable ledger cutoff manifest and reference it from final State."""

        if any(reference.role == "final_run_manifest" for reference in state["artifact_refs"]):
            return state
        existing = self.harness.store.get_operation_by_idempotency(
            state_run_id(state), "artifact:final_run_manifest"
        )
        if (
            existing is not None
            and existing.status is OperationStatus.SUCCEEDED
            and existing.result_json is not None
        ):
            value = canonical_loads(existing.result_json)
        else:
            value = build_final_run_manifest(state, self.harness.store)
        execution = self._record_artifact(
            state,
            subject_id="run",
            key="final_run_manifest",
            role="final_run_manifest",
            value=value,
        )
        return with_changes(
            state,
            {
                "artifact_refs": append_artifact_refs(
                    state["artifact_refs"], self._artifact_ref(state, execution.artifact)
                ),
                "execution_trace": self._trace(state, "final_run_manifest"),
            },
        )

    def initialize_task(self, state: ComparisonAgentState) -> dict:
        task_id = state_task_id(state)
        self.harness.ensure_run(state["manifest"])
        self.checkpoint.bind(state_run_id(state))
        baseline = baseline_candidate(state)
        if self.expected_task_id is not None and task_id != self.expected_task_id:
            raise WorkflowError("RunManifest task_id does not match the composition task")
        if self.expected_baseline is not None and baseline != self.expected_baseline:
            raise WorkflowError("RunManifest baseline snapshot does not match composition")
        self._announce(1, f"初始化任务：{task_id}")
        existing_roles = {reference.role for reference in state["artifact_refs"]}
        if {"task_metadata", "run_manifest"}.issubset(existing_roles):
            return {
                "execution_trace": self._trace(state, "initialize_task:reused")
            }
        metadata = {
            "workflow": state["manifest"].workflow_id,
            "run_id": state_run_id(state),
            "comparison_context_id": state_context_id(state),
            "target_specification": state_target_specification(state),
            "validation_status": "mock_or_uncalibrated",
        }
        task_artifact = self._record_artifact(
            state,
            subject_id="run",
            key="task_metadata",
            role="task_metadata",
            value=metadata,
        )
        manifest_artifact = self._record_artifact(
            state,
            subject_id="run",
            key="run_manifest_v2",
            role="run_manifest",
            value=state["manifest"],
        )
        references = append_artifact_refs(
            state["artifact_refs"],
            self._artifact_ref(state, task_artifact.artifact),
            self._artifact_ref(state, manifest_artifact.artifact),
        )
        return {
            "status": WorkflowStatus.RUNNING,
            "artifact_refs": references,
            "execution_trace": self._trace(state, "initialize_task"),
        }

    def calculate_baseline_sparameters(self, state: ComparisonAgentState) -> dict:
        self._announce(2, "计算初始模型 S 参数")
        existing = baseline_sparameter_result(state)
        if existing is not None:
            return {"execution_trace": self._trace(state, "calculate_baseline_sparameters:reused")}
        baseline = baseline_candidate(state)
        execution = self.harness.execute(
            self._provider_request(
                state,
                kind="sparameters",
                subject_id=baseline.candidate_id,
                idempotency_key=f"sparameters:{baseline.candidate_id}",
                payload={"candidate": baseline},
                result_role="baseline_sparameters",
            ),
            lambda: self.sparameters.run(baseline),
            decoder=sparameter_result_from_dict,
        )
        result = execution.value
        if not result.success:
            raise SParameterCalculationError(f"Baseline S-parameter calculation failed: {result.error}")
        changes = {
            "sparameter_results": append_result_by_candidate(
                state["sparameter_results"], result, label="S-parameter result"
            ),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, execution.artifact, candidate_id=baseline.candidate_id
                ),
            ),
            "execution_trace": self._trace(state, "calculate_baseline_sparameters"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def run_baseline_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(3, "仿真初始模型")
        existing = baseline_hfss_result(state)
        if existing is not None:
            return {"execution_trace": self._trace(state, "run_baseline_hfss:reused")}
        baseline = baseline_candidate(state)
        execution = self.harness.execute(
            self._provider_request(
                state,
                kind="hfss",
                subject_id=baseline.candidate_id,
                idempotency_key=f"hfss:{baseline.candidate_id}",
                payload={"candidate": baseline},
                result_role="baseline_hfss",
                ambiguity_on_exception=True,
            ),
            lambda: self._run_hfss_provider(state, baseline),
            decoder=hfss_result_from_dict,
            native_artifact_paths=self._provider_native_files,
        )
        result = execution.value
        if not result.success:
            raise HFSSExecutionError(f"Baseline HFSS provider failed: {result.error}")
        score = float(result.metrics.get("score", 0.0))
        evaluator_rules = getattr(self.evaluator, "rules", ())
        rules = state_target_specification(state).get("rules", evaluator_rules)
        frequency_plan = getattr(self.evaluator, "frequency_plan", None)
        baseline_eval = self.evaluator.evaluate_sparameters(
            result, evaluated_stage="initial", rules=rules,
            candidate_id=result.candidate_id, frequency_plan=frequency_plan,
        )
        evaluation_artifact = self._record_artifact(
            state,
            subject_id=baseline.candidate_id,
            key=f"evaluation:{baseline.candidate_id}:initial",
            role="baseline_evaluation",
            value=baseline_eval,
        )
        emit_evaluation_summary(baseline_eval, title="Baseline")
        evaluation_record = EvaluationRecord.from_result(
            baseline_eval,
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            artifact_refs=(evaluation_artifact.artifact.artifact_id,),
        )
        best_policy = BestPolicy.seed(
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            baseline_candidate_id=baseline.candidate_id,
            baseline_evaluation_id=evaluation_record.record_id,
        )
        best_artifact = self._record_artifact(
            state,
            subject_id=baseline.candidate_id,
            key="best:baseline_seed",
            role="best_selection",
            value={"candidate": baseline, "hfss_result": result, "score": score},
        )
        changes = {
            "hfss_results": append_result_by_candidate(
                state["hfss_results"], result, label="HFSS result"
            ),
            "evaluations": append_record_by_id(
                state["evaluations"], evaluation_record, label="EvaluationRecord"
            ),
            "best_policy": best_policy,
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state,
                    execution.artifact,
                    candidate_id=baseline.candidate_id,
                ),
                *(
                    self._artifact_ref(
                        state, receipt, candidate_id=baseline.candidate_id
                    )
                    for receipt in execution.supporting_artifacts
                ),
                self._artifact_ref(
                    state,
                    evaluation_artifact.artifact,
                    candidate_id=baseline.candidate_id,
                ),
                self._artifact_ref(
                    state, best_artifact.artifact, candidate_id=baseline.candidate_id
                ),
            ),
            "execution_trace": self._trace(state, "run_baseline_hfss"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def freeze_baseline(self, state: ComparisonAgentState) -> dict:
        self._announce(4, "固化初始模型基线")
        if baseline_sparameter_result(state) is None or baseline_hfss_result(state) is None:
            raise WorkflowError("Both baseline results are required before optimization")
        changes = {"execution_trace": self._trace(state, "freeze_baseline")}
        self.checkpoint.save(with_changes(state, changes))
        return changes

    def diagnose_baseline(self, state: ComparisonAgentState) -> dict:
        self._announce(4, "诊断初始模型")
        if baseline_diagnosis(state) is not None:
            return {"execution_trace": self._trace(state, "diagnose_baseline:reused")}
        evaluation = baseline_evaluation(state)
        if evaluation is None:
            raise WorkflowError("Baseline EvaluationResult is required before diagnosis")
        node = self.diagnosis or DiagnosisNode()
        result = node.diagnose(evaluation, stage="initial")
        result = DiagnosisResult.from_dict(result.to_dict())
        artifact = self._record_artifact(
            state,
            subject_id=state["manifest"].baseline_candidate_id,
            key="diagnosis:baseline",
            role="baseline_diagnosis",
            value=result,
        )
        emit_diagnosis_summary(result, title="初始")
        changes = {
            "diagnoses": (*state["diagnoses"], result),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state,
                    artifact.artifact,
                    candidate_id=state["manifest"].baseline_candidate_id,
                ),
            ),
            "execution_trace": self._trace(state, "diagnose_baseline"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def run_optimizer(self, state: ComparisonAgentState) -> dict:
        self._announce(5, "执行九参数优化")
        controller = state["controller"]
        optimizer_iteration = controller.optimizer_calls if controller is not None else 0
        existing = state["optimization_run"]
        if existing is not None and (
            controller is None
            or existing.metadata.to_dict().get("optimizer_iteration") == optimizer_iteration
        ):
            return {"execution_trace": self._trace(state, "run_optimizer:reused")}
        baseline_sparameters = baseline_sparameter_result(state)
        if baseline_sparameters is None:
            raise WorkflowError("Baseline S parameters are required by the optimizer stage")
        baseline = baseline_candidate(state)
        objective = state["optimization_objective"]
        diagnosis = (
            next(
                (item for item in reversed(state["diagnoses"]) if item.stage != "initial"),
                None,
            )
            if optimizer_iteration > 0
            else baseline_diagnosis(state)
        )
        if objective is None or objective.status != ACTIVE or diagnosis is None:
            raise WorkflowError("ACTIVE objective and baseline diagnosis are required by optimizer")
        target_specification = dict(state_target_specification(state))
        evaluation = baseline_evaluation(state)
        if evaluation is not None and "frequency_plan" not in target_specification:
            target_specification["frequency_plan"] = dict(evaluation.frequency_plan)
        effective_objective = map_effective_objective(objective, target_specification)
        optimizer_request = OptimizerRequest(
            schema_version="optimizer-request/1.0",
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            iteration=optimizer_iteration,
            baseline=baseline,
            baseline_sparameters=baseline_sparameters,
            design_goal={
                "goal_id": state["manifest"].design_goal.goal_id,
                "evaluation_contract_id": state["manifest"].design_goal.evaluation_contract_id,
                "comparison_context_id": state["manifest"].design_goal.comparison_context_id,
                "objective": state["manifest"].design_goal.objective,
                "target_specification": state[
                    "manifest"
                ].design_goal.target_specification.to_dict(),
            },
            diagnosis_digest=canonical_digest(diagnosis.to_dict()),
            target_specification=target_specification,
            optimization_objective=objective,
            effective_objective=effective_objective,
            provider_fingerprints=state["manifest"].provider_fingerprints.to_dict(),
            config_fingerprints=state["manifest"].config_fingerprints.to_dict(),
        )
        execution = self.harness.execute(
            self._provider_request(
                state,
                kind="optimizer",
                subject_id=f"iteration:{optimizer_iteration}",
                idempotency_key=f"optimizer:iteration:{optimizer_iteration}",
                payload={
                    "optimizer_request": optimizer_request,
                    "optimizer_request_digest": optimizer_request.digest,
                    "effective_objective_digest": effective_objective.digest,
                },
                result_role="optimizer_result",
                ambiguity_on_exception=True,
            ),
            lambda: self.optimizer.optimize(request=optimizer_request),
            decoder=optimization_batch_from_dict,
            native_artifact_paths=self._provider_native_files,
        )
        batch = execution.value
        if not batch.success:
            raise OptimizerError(f"Batch optimizer failed: {batch.error}")
        if batch.metadata.get("optimizer_request_digest") != optimizer_request.digest:
            raise OptimizerError("Optimizer result request digest does not match the submitted request")
        if batch.metadata.get("effective_objective_digest") != effective_objective.digest:
            raise OptimizerError("Optimizer result effective objective digest mismatch")
        batch.metadata["optimizer_iteration"] = optimizer_iteration
        intent = state["optimization_intent"]
        ranking_evidence: list[dict] = []
        if objective is not None and objective.status == ACTIVE and intent is not None:
            rules = state_target_specification(state).get(
                "rules", getattr(self.evaluator, "rules", ())
            )
            frequency_plan = getattr(self.evaluator, "frequency_plan", None)
            rank_builder = self.objective_builder or OptimizationObjectiveBuilder()
            ranked = []
            for candidate in batch.candidates:
                surrogate_execution = self.harness.execute(
                    self._provider_request(
                        state,
                        kind="sparameters",
                        subject_id=candidate.candidate_id,
                        idempotency_key=f"sparameters:{candidate.candidate_id}",
                        payload={"candidate": candidate},
                        result_role="candidate_sparameters",
                    ),
                    lambda candidate=candidate: self.sparameters.run(candidate),
                    decoder=sparameter_result_from_dict,
                )
                candidate_sparameters = surrogate_execution.value
                candidate_evaluation = self.evaluator.evaluate_sparameters(
                    candidate_sparameters, evaluated_stage="optimized", rules=rules,
                    candidate_id=candidate.candidate_id, frequency_plan=frequency_plan,
                )
                rank = rank_builder.rank(candidate_evaluation, intent)
                ranked.append((rank.key(), candidate.candidate_id, rank))
                ranking_evidence.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "optimizer_request_digest": optimizer_request.digest,
                        "effective_objective_digest": effective_objective.digest,
                        "surrogate_artifact_id": surrogate_execution.artifact.artifact_id,
                        "surrogate_artifact_sha256": surrogate_execution.artifact.sha256,
                        "surrogate_result": candidate_sparameters.to_dict(),
                        "evaluation": candidate_evaluation.to_dict(),
                        "rank": {
                            "key": list(rank.key()),
                            "invalid_flag": rank.invalid_flag,
                            "hard_failed_rule_count": rank.hard_failed_rule_count,
                            "max_hard_violation": rank.max_hard_violation,
                            "total_hard_violation": rank.total_hard_violation,
                            "soft_failed_rule_count": rank.soft_failed_rule_count,
                            "total_soft_violation": rank.total_soft_violation,
                            "per_rule_violations": list(rank.per_rule_violations),
                        },
                    }
                )
            if ranked:
                ranked.sort(key=lambda item: (item[0], item[1]))
                batch.recommended_candidate_id = ranked[0][1]
                batch.metadata["objective_ranks"] = {
                    candidate_id: {
                        "invalid_flag": rank.invalid_flag,
                        "hard_failed_rule_count": rank.hard_failed_rule_count,
                        "max_hard_violation": rank.max_hard_violation,
                        "total_hard_violation": rank.total_hard_violation,
                        "soft_failed_rule_count": rank.soft_failed_rule_count,
                        "total_soft_violation": rank.total_soft_violation,
                        "per_rule_violations": list(rank.per_rule_violations),
                    }
                    for _, candidate_id, rank in ranked
                }
        batch.metadata["surrogate_ranking_evidence"] = ranking_evidence
        batch.metadata["surrogate_ranking_evidence_digest"] = canonical_digest(
            ranking_evidence
        )
        ranking_artifact = self._record_artifact(
            state,
            subject_id=f"iteration:{optimizer_iteration}",
            key=f"surrogate_ranking_evidence:iteration:{optimizer_iteration}",
            role="surrogate_ranking_evidence",
            value={
                "optimizer_request_digest": optimizer_request.digest,
                "effective_objective_digest": effective_objective.digest,
                "recommended_candidate_id": batch.recommended_candidate_id,
                "evidence": ranking_evidence,
                "evidence_digest": batch.metadata["surrogate_ranking_evidence_digest"],
            },
        )
        batch_artifact = self._record_artifact(
            state,
            subject_id=f"iteration:{optimizer_iteration}",
            key=f"optimization_batch:iteration:{optimizer_iteration}",
            role="optimization_batch",
            value=batch,
        )
        candidates = append_candidate_snapshots(
            state,
            batch.candidates,
            source="optimizer",
            parent_candidate_id=state["manifest"].baseline_candidate_id,
        )
        changes = {
            "candidates": candidates,
            "optimization_run": OptimizationRunRecord.from_batch(batch),
            "candidate_queue": tuple(
                candidate.candidate_id for candidate in batch.candidates
            ),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(state, execution.artifact),
                *(
                    self._artifact_ref(state, receipt)
                    for receipt in execution.supporting_artifacts
                ),
                self._artifact_ref(state, batch_artifact.artifact),
                self._artifact_ref(state, ranking_artifact.artifact),
            ),
            "execution_trace": self._trace(state, f"run_optimizer:{batch.run_id}"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def build_optimization_intent(self, state: ComparisonAgentState) -> dict:
        self._announce(5, "生成优化意图")
        diagnosis = baseline_diagnosis(state)
        if diagnosis is None:
            raise WorkflowError("Baseline DiagnosisResult is required before optimization intent")
        intent = (self.intent_builder or OptimizationIntentBuilder()).build(diagnosis)
        artifact = self._record_artifact(
            state,
            subject_id="iteration:0",
            key="optimization_intent:iteration:0",
            role="optimization_intent",
            value=intent,
        )
        emit_optimization_intent(intent, baseline_evaluation(state))
        changes = {
            "optimization_intent": intent,
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"], self._artifact_ref(state, artifact.artifact)
            ),
            "execution_trace": self._trace(state, "build_optimization_intent"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def build_optimization_objective(self, state: ComparisonAgentState) -> dict:
        self._announce(6, "生成优化目标")
        intent = state["optimization_intent"]
        evaluation = baseline_evaluation(state)
        if intent is None or evaluation is None:
            raise WorkflowError("Optimization intent and baseline evaluation are required")
        plan = FrequencyPlan.from_mapping(evaluation.frequency_plan)
        rules = getattr(self.evaluator, "rules", ())
        objective = (self.objective_builder or OptimizationObjectiveBuilder()).build(intent, evaluation, plan, rules)
        artifact = self._record_artifact(
            state,
            subject_id="iteration:0",
            key="optimization_objective:iteration:0",
            role="optimization_objective",
            value=objective,
        )
        changes = {
            "optimization_objective": objective,
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"], self._artifact_ref(state, artifact.artifact)
            ),
            "execution_trace": self._trace(state, "build_optimization_objective"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def select_optimized_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(6, "选择优化候选")
        if state["current_candidate_id"] is not None:
            return {"execution_trace": self._trace(state, "select_optimized_candidate:reused")}
        batch = optimization_batch(state)
        if batch is None:
            raise WorkflowError("No optimization batch is available")
        selected = batch.recommended_candidate()
        remaining = tuple(
            candidate_id
            for candidate_id in state["candidate_queue"]
            if candidate_id != selected.candidate_id
        )
        artifact = self._record_artifact(
            state,
            subject_id=selected.candidate_id,
            key=f"candidate_parameters:{selected.candidate_id}",
            role="candidate_parameters",
            value=selected,
        )
        return {
            "current_candidate_id": selected.candidate_id,
            "candidate_queue": remaining,
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, artifact.artifact, candidate_id=selected.candidate_id
                ),
            ),
            "execution_trace": self._trace(
                state, f"select_optimized_candidate:{selected.candidate_id}"
            ),
        }

    def validate_optimized_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(7, "校验候选参数")
        candidate = current_candidate(state)
        if candidate is None:
            raise WorkflowError("No optimized candidate is available")
        self.validator.validate(candidate)
        return {"execution_trace": self._trace(state, "validate_optimized_candidate")}

    def recalculate_candidate_sparameters(self, state: ComparisonAgentState) -> dict:
        self._announce(8, "计算候选模型 S 参数")
        candidate = current_candidate(state)
        if candidate is None:
            raise WorkflowError("No optimized candidate is available for S-parameter calculation")
        existing = candidate_sparameter_result(state)
        if existing is not None and existing.candidate_id == candidate.candidate_id:
            return {
                "execution_trace": self._trace(state, "recalculate_candidate_sparameters:reused")
            }
        execution = self.harness.execute(
            self._provider_request(
                state,
                kind="sparameters",
                subject_id=candidate.candidate_id,
                idempotency_key=f"sparameters:{candidate.candidate_id}",
                payload={"candidate": candidate},
                result_role="candidate_sparameters",
            ),
            lambda: self.sparameters.run(candidate),
            decoder=sparameter_result_from_dict,
        )
        result = execution.value
        changes = {
            "sparameter_results": append_result_by_candidate(
                state["sparameter_results"], result, label="S-parameter result"
            ),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, execution.artifact, candidate_id=candidate.candidate_id
                ),
            ),
            "execution_trace": self._trace(state, "recalculate_candidate_sparameters"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def candidate_sparameter_gate(self, state: ComparisonAgentState) -> dict:
        self._announce(9, "执行 S 参数快速筛选")
        action = NextAction(self.supervisor.route_after_candidate_sparameters(state))
        candidate = current_candidate(state)
        if candidate is None:
            raise WorkflowError("No optimized candidate is available for gate decision")
        artifact_refs = state["artifact_refs"]
        if action is not NextAction.RUN_HFSS:
            artifact = self._record_artifact(
                state,
                subject_id=candidate.candidate_id,
                key=f"candidate_gate_status:{candidate.candidate_id}",
                role="candidate_gate_status",
                value={
                    "hfss_not_run": True,
                    "reason": "candidate_sparameter_gate_failed",
                },
            )
            artifact_refs = append_artifact_refs(
                artifact_refs,
                self._artifact_ref(
                    state, artifact.artifact, candidate_id=candidate.candidate_id
                ),
            )
        decision = DecisionOutcome(
            decision_id=f"decision:{candidate.candidate_id}:surrogate_gate",
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            action=DecisionAction(action),
            reason_code=(
                "surrogate_gate_passed"
                if action is NextAction.RUN_HFSS
                else "surrogate_gate_rejected"
            ),
            reason=(
                "Candidate passed the configured surrogate gate."
                if action is NextAction.RUN_HFSS
                else "Candidate did not pass the configured surrogate gate."
            ),
            candidate_id=candidate.candidate_id,
            evidence_ids=(f"sparameter:{candidate.candidate_id}",),
        )
        return {
            "decision_outcome": decision,
            "artifact_refs": artifact_refs,
            "execution_trace": self._trace(state, f"candidate_sparameter_gate:{action}"),
        }

    def run_candidate_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(10, "仿真优化模型")
        candidate = current_candidate(state)
        if candidate is None:
            raise WorkflowError("No optimized candidate is available for HFSS")
        existing = candidate_hfss_result(state)
        if existing is not None and existing.candidate_id == candidate.candidate_id:
            return {"execution_trace": self._trace(state, "run_candidate_hfss:reused")}
        execution = self.harness.execute(
            self._provider_request(
                state,
                kind="hfss",
                subject_id=candidate.candidate_id,
                idempotency_key=f"hfss:{candidate.candidate_id}",
                payload={"candidate": candidate},
                result_role="candidate_hfss",
                ambiguity_on_exception=True,
            ),
            lambda: self._run_hfss_provider(state, candidate),
            decoder=hfss_result_from_dict,
            native_artifact_paths=self._provider_native_files,
        )
        result = execution.value
        changes = {
            "hfss_results": append_result_by_candidate(
                state["hfss_results"], result, label="HFSS result"
            ),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, execution.artifact, candidate_id=candidate.candidate_id
                ),
                *(
                    self._artifact_ref(
                        state, receipt, candidate_id=candidate.candidate_id
                    )
                    for receipt in execution.supporting_artifacts
                ),
            ),
            "execution_trace": self._trace(state, "run_candidate_hfss"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def compare_hfss_results(self, state: ComparisonAgentState) -> dict:
        self._announce(11, "对比两次 HFSS 结果")
        if candidate_evaluation_record(state) is not None:
            return {"execution_trace": self._trace(state, "compare_hfss_results:reused")}
        current = candidate_hfss_result(state)
        evaluator_rules = getattr(self.evaluator, "rules", ())
        rules = state_target_specification(state).get("rules", evaluator_rules)
        frequency_plan = getattr(self.evaluator, "frequency_plan", None)
        candidate_id = current.candidate_id if current is not None else "unknown"
        evaluation = self.evaluator.evaluate_sparameters(
            current, evaluated_stage="optimized", rules=rules,
            candidate_id=candidate_id, frequency_plan=frequency_plan,
        )
        evaluation_artifact = self._record_artifact(
            state,
            subject_id=evaluation.candidate_id,
            key=f"evaluation:{evaluation.candidate_id}:optimized",
            role="candidate_evaluation",
            value=evaluation,
        )
        emit_evaluation_summary(evaluation, title="Final")
        evaluation_record = EvaluationRecord.from_result(
            evaluation,
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            artifact_refs=(evaluation_artifact.artifact.artifact_id,),
        )
        reference_candidate_id = state["manifest"].baseline_candidate_id
        if state["controller"] is not None and state["best_policy"] is not None:
            reference_candidate_id = state["best_policy"].selected_candidate_id
        baseline_record = (
            baseline_evaluation_record(state)
            if reference_candidate_id == state["manifest"].baseline_candidate_id
            else next(
                (
                    record
                    for record in reversed(state["evaluations"])
                    if record.candidate_id == reference_candidate_id
                ),
                None,
            )
        )
        baseline_eval = baseline_record.to_result() if baseline_record else None
        comparison = (self.comparator or EvaluationComparator()).compare(baseline_eval, evaluation) if baseline_eval else None
        comparison_record = None
        comparison_artifact = None
        if comparison is not None:
            comparison_artifact = self._record_artifact(
                state,
                subject_id=evaluation.candidate_id,
                key=f"evaluation_comparison:{evaluation.candidate_id}",
                role="evaluation_comparison",
                value=comparison,
            )
            emit_status("Baseline Comparison", comparison.classification,
                        detail=(f"resolved={len(comparison.resolved_failures)}, remaining={len(comparison.remaining_failures)}, "
                                f"new={len(comparison.new_failures)}, lower_margin_delta={comparison.lower_frequency_margin_delta}, "
                                f"upper_margin_delta={comparison.upper_frequency_margin_delta}"))
            emit_status(
                "Frequency Margin Comparison",
                f"lower_edge {comparison.baseline_frequency_margin.get('achieved_lower_edge')} → "
                f"{comparison.candidate_frequency_margin.get('achieved_lower_edge')}; "
                f"upper_edge {comparison.baseline_frequency_margin.get('achieved_upper_edge')} → "
                f"{comparison.candidate_frequency_margin.get('achieved_upper_edge')}",
            )
            comparison_record = ComparisonRecord.from_comparison(
                comparison,
                run_id=state_run_id(state),
                context_id=state_context_id(state),
                baseline_evaluation_id=baseline_record.record_id,
                candidate_evaluation_id=evaluation_record.record_id,
                baseline_candidate_id=reference_candidate_id,
                candidate_id=evaluation.candidate_id,
            )
        changes = {
            "evaluations": append_record_by_id(
                state["evaluations"], evaluation_record, label="EvaluationRecord"
            ),
            "comparisons": (
                append_record_by_id(
                    state["comparisons"], comparison_record, label="ComparisonRecord"
                )
                if comparison_record is not None
                else state["comparisons"]
            ),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state,
                    evaluation_artifact.artifact,
                    candidate_id=evaluation.candidate_id,
                ),
                *(
                    (
                        self._artifact_ref(
                            state,
                            comparison_artifact.artifact,
                            candidate_id=evaluation.candidate_id,
                        ),
                    )
                    if comparison_artifact is not None
                    else ()
                ),
            ),
            "execution_trace": self._trace(state, "compare_hfss_results"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def update_hfss_best(self, state: ComparisonAgentState) -> dict:
        self._announce(12, "更新最佳方案")
        evaluation_record = candidate_evaluation_record(state)
        evaluation = evaluation_record.to_result() if evaluation_record else None
        candidate = current_candidate(state)
        result = candidate_hfss_result(state)
        comparison_record = current_comparison_record(state)
        comparison = comparison_record.to_comparison() if comparison_record else None
        if candidate is not None and result is not None and result.candidate_id != candidate.candidate_id:
            raise WorkflowError("Candidate HFSS result identity does not match the current candidate")
        if candidate is not None and evaluation is not None and evaluation.candidate_id != candidate.candidate_id:
            raise WorkflowError("Candidate evaluation identity does not match the current candidate")
        update = (
            comparison_record is not None
            and comparison_record.promotion_eligible
            and candidate is not None
            and result is not None
            and result.success
        )
        changes: dict = {
            "execution_trace": self._trace(
                state, f"update_hfss_best:{'updated' if update else 'retained'}"
            )
        }
        if update:
            policy = state["best_policy"]
            if policy is None:
                raise WorkflowError("BestPolicy baseline seed is missing")
            promoted_policy = policy.promote(comparison_record)
            score = float(result.metrics["score"]) if "score" in result.metrics else None
            changes["best_policy"] = promoted_policy
            artifact = self._record_artifact(
                state,
                subject_id=candidate.candidate_id,
                key=f"best:promotion:{comparison_record.record_id}",
                role="best_selection",
                value={
                    "candidate": candidate,
                    "hfss_result": result,
                    "score": score,
                    "comparison": comparison,
                },
            )
            changes["artifact_refs"] = append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, artifact.artifact, candidate_id=candidate.candidate_id
                ),
            )
        self._checkpoint_changes(state, changes)
        return changes

    def diagnose_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(12, "诊断优化模型")
        existing = next(
            (item for item in state["diagnoses"] if item.stage == "optimized"), None
        )
        if existing is not None:
            return {"execution_trace": self._trace(state, "diagnose_candidate:reused")}
        evaluation = candidate_evaluation(state)
        if evaluation is None:
            raise WorkflowError("Candidate EvaluationResult is required before diagnosis")
        node = self.diagnosis or DiagnosisNode()
        result = node.diagnose(
            evaluation,
            stage="optimized",
            comparison=current_comparison(state),
            baseline_diagnosis=baseline_diagnosis(state),
        )
        result = DiagnosisResult.from_dict(result.to_dict())
        artifact = self._record_artifact(
            state,
            subject_id=evaluation.candidate_id,
            key=f"diagnosis:{evaluation.candidate_id}",
            role="candidate_diagnosis",
            value=result,
        )
        emit_diagnosis_summary(result, title="优化后")
        changes = {
            "diagnoses": (*state["diagnoses"], result),
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, artifact.artifact, candidate_id=evaluation.candidate_id
                ),
            ),
            "execution_trace": self._trace(state, "diagnose_candidate"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def decide_after_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(13, "判断工作流结果")
        action = NextAction(self.supervisor.route_after_candidate_hfss(state))
        candidate = current_candidate(state)
        evaluation = candidate_evaluation_record(state)
        comparison = current_comparison_record(state)
        evidence_ids = tuple(
            item
            for item in (
                evaluation.record_id if evaluation else None,
                comparison.record_id if comparison else None,
            )
            if item is not None
        )
        decision = DecisionOutcome(
            decision_id=f"decision:{candidate.candidate_id if candidate else 'unknown'}:hfss",
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            action=DecisionAction(action),
            reason_code=(
                "candidate_target_met"
                if action is NextAction.PASS
                else "candidate_target_not_met"
            ),
            reason=(
                "Candidate HFSS evidence satisfies the configured hard rules."
                if action is NextAction.PASS
                else "Candidate HFSS evidence does not satisfy the configured target."
            ),
            candidate_id=candidate.candidate_id if candidate else None,
            evidence_ids=evidence_ids,
        )
        return {
            "decision_outcome": decision,
            "execution_trace": self._trace(state, f"decide_after_hfss:{action}"),
        }

    def complete(self, state: ComparisonAgentState) -> dict:
        self._announce(14, "工作流终结")
        outcome = classify_terminal_outcome(state)
        artifact = self._record_artifact(
            state,
            subject_id=outcome.candidate_id or "run",
            key="terminal_outcome",
            role="terminal_outcome",
            value=outcome,
        )
        changes = {
            "status": outcome.status,
            "terminal_outcome": outcome,
            "artifact_refs": append_artifact_refs(
                state["artifact_refs"],
                self._artifact_ref(
                    state, artifact.artifact, candidate_id=outcome.candidate_id
                ),
            ),
            "execution_trace": self._trace(state, "complete"),
        }
        finalized = self.attach_final_manifest(with_changes(state, changes))
        self.checkpoint.complete(finalized)
        return {
            **changes,
            "artifact_refs": finalized["artifact_refs"],
            "execution_trace": finalized["execution_trace"],
        }
