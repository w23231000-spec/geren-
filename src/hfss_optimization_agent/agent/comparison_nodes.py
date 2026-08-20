"""Nodes for the confirmed initial-model versus optimized-model comparison workflow."""

from dataclasses import dataclass
from datetime import datetime, timezone

from ..core.enums import NextAction, WorkflowStatus
from ..core.models import CandidateParameters
from ..harness.artifacts import ArtifactStore
from ..harness.checkpoint import JsonComparisonCheckpointStore
from ..harness.errors import HFSSExecutionError, OptimizerError, SParameterCalculationError, WorkflowError
from ..harness.terminal import emit_stage, emit_evaluation_summary, emit_diagnosis_summary, emit_optimization_intent
from ..interfaces.batch_optimizer import BatchOptimizerInterface
from ..interfaces.evaluator import EvaluatorInterface
from ..interfaces.hfss import HFSSInterface
from ..interfaces.sparameters import SParameterInterface
from ..evaluation.comparator import EvaluationComparator
from ..diagnosis import DiagnosisNode
from ..optimization.intent import OptimizationIntentBuilder, OptimizationObjectiveBuilder, ACTIVE
from ..core.models import FrequencyPlan
from ..parameters.validator import ParameterValidator
from .comparison_state import ComparisonAgentState
from .router import WorkflowRouter
from .supervisor import DeterministicSupervisor


@dataclass(slots=True)
class ComparisonWorkflowNodes:
    sparameters: SParameterInterface
    optimizer: BatchOptimizerInterface
    hfss: HFSSInterface
    evaluator: EvaluatorInterface
    validator: ParameterValidator
    artifacts: ArtifactStore
    checkpoint: JsonComparisonCheckpointStore
    router: WorkflowRouter
    supervisor: DeterministicSupervisor
    comparator: EvaluationComparator | None = None
    diagnosis: DiagnosisNode | None = None
    intent_builder: OptimizationIntentBuilder | None = None
    objective_builder: OptimizationObjectiveBuilder | None = None

    @staticmethod
    def _trace(state: ComparisonAgentState, name: str) -> list[str]:
        return [*state["execution_trace"], name]

    @staticmethod
    def _announce(current: int, title: str) -> None:
        emit_stage("主流程", current, 14, title)

    def _checkpoint_changes(self, state: ComparisonAgentState, changes: dict) -> None:
        self.checkpoint.save(ComparisonAgentState(**{**state, **changes}))

    def initialize_task(self, state: ComparisonAgentState) -> dict:
        self._announce(1, f"初始化任务：{state['task_id']}")
        metadata = {
            "workflow": "baseline-optimize-hfss-compare-v1",
            "target_specification": state["target_specification"],
            "validation_status": "mock_or_uncalibrated",
        }
        self.artifacts.initialize(metadata)
        return {
            "status": WorkflowStatus.RUNNING,
            "run_metadata": {"started_at": datetime.now(timezone.utc).isoformat(), **metadata},
            "execution_trace": self._trace(state, "initialize_task"),
        }

    def calculate_baseline_sparameters(self, state: ComparisonAgentState) -> dict:
        self._announce(2, "计算初始模型 S 参数")
        existing = state["baseline_sparameter_result"]
        if existing is not None:
            return {"execution_trace": self._trace(state, "calculate_baseline_sparameters:reused")}
        result = self.sparameters.run(state["baseline_parameters"])
        if not result.success:
            raise SParameterCalculationError(f"Baseline S-parameter calculation failed: {result.error}")
        self.artifacts.write_baseline_sparameters(result)
        changes = {
            "baseline_sparameter_result": result,
            "sparameter_history": [*state["sparameter_history"], result],
            "execution_trace": self._trace(state, "calculate_baseline_sparameters"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def run_baseline_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(3, "仿真初始模型")
        existing = state["baseline_hfss_result"]
        if existing is not None:
            return {"execution_trace": self._trace(state, "run_baseline_hfss:reused")}
        result = self.hfss.run(state["baseline_parameters"])
        if not result.success:
            raise HFSSExecutionError(f"Baseline HFSS provider failed: {result.error}")
        score = float(result.metrics.get("score", 0.0))
        self.artifacts.write_baseline(result)
        evaluator_rules = getattr(self.evaluator, "rules", ())
        rules = state["target_specification"].get("rules", evaluator_rules)
        frequency_plan = getattr(self.evaluator, "frequency_plan", None)
        baseline_eval = self.evaluator.evaluate_sparameters(
            result, evaluated_stage="initial", rules=rules,
            candidate_id=result.candidate_id, frequency_plan=frequency_plan,
        )
        self.artifacts.write_baseline_evaluation(baseline_eval)
        emit_evaluation_summary(baseline_eval, title="Baseline")
        self.artifacts.write_best(state["baseline_parameters"], result, score)
        changes = {
            "baseline_hfss_result": result,
            "best_candidate": state["baseline_parameters"],
            "best_hfss_result": result,
            "best_score": score,
            "baseline_evaluation": baseline_eval,
            "hfss_history": [*state["hfss_history"], result],
            "execution_trace": self._trace(state, "run_baseline_hfss"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def freeze_baseline(self, state: ComparisonAgentState) -> dict:
        self._announce(4, "固化初始模型基线")
        if state["baseline_sparameter_result"] is None or state["baseline_hfss_result"] is None:
            raise WorkflowError("Both baseline results are required before optimization")
        changes = {"execution_trace": self._trace(state, "freeze_baseline")}
        self.checkpoint.save(ComparisonAgentState(**{**state, **changes}))
        return changes

    def diagnose_baseline(self, state: ComparisonAgentState) -> dict:
        self._announce(4, "诊断初始模型")
        evaluation = state["baseline_evaluation"]
        if evaluation is None:
            raise WorkflowError("Baseline EvaluationResult is required before diagnosis")
        node = self.diagnosis or DiagnosisNode()
        result = node.diagnose(evaluation, stage="initial")
        self.artifacts.write_baseline_diagnosis(result)
        emit_diagnosis_summary(result, title="初始")
        changes = {
            "baseline_diagnosis": result,
            "diagnosis_result": result,
            "diagnosis_history": [*state["diagnosis_history"], result],
            "execution_trace": self._trace(state, "diagnose_baseline"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def run_optimizer(self, state: ComparisonAgentState) -> dict:
        self._announce(5, "执行九参数优化")
        existing = state["optimization_batch"]
        if existing is not None:
            return {"execution_trace": self._trace(state, "run_optimizer:reused")}
        baseline_sparameters = state["baseline_sparameter_result"]
        if baseline_sparameters is None:
            raise WorkflowError("Baseline S parameters are required by the optimizer stage")
        batch = self.optimizer.optimize(
            baseline=state["baseline_parameters"],
            baseline_sparameters=baseline_sparameters,
            target_specification=state["target_specification"],
            optimization_objective=state["optimization_objective"],
        )
        if not batch.success:
            raise OptimizerError(f"Batch optimizer failed: {batch.error}")
        objective = state["optimization_objective"]
        intent = state["optimization_intent"]
        if objective is not None and objective.status == ACTIVE and intent is not None:
            rules = state["target_specification"].get("rules", getattr(self.evaluator, "rules", ()))
            frequency_plan = getattr(self.evaluator, "frequency_plan", None)
            rank_builder = self.objective_builder or OptimizationObjectiveBuilder()
            ranked = []
            for candidate in batch.candidates:
                candidate_sparameters = self.sparameters.run(candidate)
                candidate_evaluation = self.evaluator.evaluate_sparameters(
                    candidate_sparameters, evaluated_stage="optimized", rules=rules,
                    candidate_id=candidate.candidate_id, frequency_plan=frequency_plan,
                )
                rank = rank_builder.rank(candidate_evaluation, intent)
                ranked.append((rank.key(), candidate.candidate_id, rank))
            if ranked:
                ranked.sort(key=lambda item: (item[0], item[1]))
                batch.recommended_candidate_id = ranked[0][1]
                batch.metadata["objective_ranks"] = {
                    candidate_id: {
                        "invalid_flag": rank.invalid_flag,
                        "hard_failed_rule_count": rank.hard_failed_rule_count,
                        "primary_focus_penalty": rank.primary_focus_penalty,
                        "total_hard_violation": rank.total_hard_violation,
                        "secondary_focus_penalties": list(rank.secondary_focus_penalties),
                        "remaining_soft_penalties": list(rank.remaining_soft_penalties),
                    }
                    for _, candidate_id, rank in ranked
                }
        self.artifacts.write_optimization_batch(batch)
        changes = {
            "optimization_batch": batch,
            "candidate_queue": list(batch.candidates),
            "execution_trace": self._trace(state, f"run_optimizer:{batch.run_id}"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def build_optimization_intent(self, state: ComparisonAgentState) -> dict:
        self._announce(5, "生成优化意图")
        diagnosis = state["baseline_diagnosis"]
        if diagnosis is None:
            raise WorkflowError("Baseline DiagnosisResult is required before optimization intent")
        intent = (self.intent_builder or OptimizationIntentBuilder()).build(diagnosis)
        self.artifacts.write_optimization_artifact("optimization_intent", intent)
        emit_optimization_intent(intent)
        changes = {"optimization_intent": intent, "execution_trace": self._trace(state, "build_optimization_intent")}
        self._checkpoint_changes(state, changes)
        return changes

    def build_optimization_objective(self, state: ComparisonAgentState) -> dict:
        self._announce(6, "生成优化目标")
        intent = state["optimization_intent"]
        evaluation = state["baseline_evaluation"]
        if intent is None or evaluation is None:
            raise WorkflowError("Optimization intent and baseline evaluation are required")
        plan = FrequencyPlan.from_mapping(evaluation.frequency_plan)
        rules = getattr(self.evaluator, "rules", ())
        objective = (self.objective_builder or OptimizationObjectiveBuilder()).build(intent, evaluation, plan, rules)
        self.artifacts.write_optimization_artifact("optimization_objective", objective)
        changes = {"optimization_objective": objective, "execution_trace": self._trace(state, "build_optimization_objective")}
        self._checkpoint_changes(state, changes)
        return changes

    def select_optimized_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(6, "选择优化候选")
        if state["current_candidate"] is not None:
            return {"execution_trace": self._trace(state, "select_optimized_candidate:reused")}
        batch = state["optimization_batch"]
        if batch is None:
            raise WorkflowError("No optimization batch is available")
        selected = batch.recommended_candidate()
        remaining = [
            candidate for candidate in state["candidate_queue"] if candidate.candidate_id != selected.candidate_id
        ]
        self.artifacts.write_candidate_artifact("parameters", selected)
        return {
            "current_candidate": selected,
            "candidate_queue": remaining,
            "execution_trace": self._trace(
                state, f"select_optimized_candidate:{selected.candidate_id}"
            ),
        }

    def validate_optimized_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(7, "校验候选参数")
        candidate = state["current_candidate"]
        if candidate is None:
            raise WorkflowError("No optimized candidate is available")
        self.validator.validate(candidate)
        return {"execution_trace": self._trace(state, "validate_optimized_candidate")}

    def recalculate_candidate_sparameters(self, state: ComparisonAgentState) -> dict:
        self._announce(8, "计算候选模型 S 参数")
        candidate = state["current_candidate"]
        if candidate is None:
            raise WorkflowError("No optimized candidate is available for S-parameter calculation")
        existing = state["candidate_sparameter_result"]
        if existing is not None and existing.candidate_id == candidate.candidate_id:
            return {
                "execution_trace": self._trace(state, "recalculate_candidate_sparameters:reused")
            }
        result = self.sparameters.run(candidate)
        self.artifacts.write_candidate_artifact("sparameter_result", result)
        changes = {
            "candidate_sparameter_result": result,
            "sparameter_history": [*state["sparameter_history"], result],
            "execution_trace": self._trace(state, "recalculate_candidate_sparameters"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def candidate_sparameter_gate(self, state: ComparisonAgentState) -> dict:
        self._announce(9, "执行 S 参数快速筛选")
        action = NextAction(self.supervisor.route_after_candidate_sparameters(state))
        if action is not NextAction.RUN_HFSS:
            self.artifacts.write_candidate_artifact(
                "status", {"hfss_not_run": True, "reason": "candidate_sparameter_gate_failed"}
            )
        return {
            "next_action": action,
            "execution_trace": self._trace(state, f"candidate_sparameter_gate:{action}"),
        }

    def run_candidate_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(10, "仿真优化模型")
        candidate = state["current_candidate"]
        if candidate is None:
            raise WorkflowError("No optimized candidate is available for HFSS")
        existing = state["candidate_hfss_result"]
        if existing is not None and existing.candidate_id == candidate.candidate_id:
            return {"execution_trace": self._trace(state, "run_candidate_hfss:reused")}
        result = self.hfss.run(candidate)
        self.artifacts.write_candidate_artifact("hfss_result", result)
        changes = {
            "candidate_hfss_result": result,
            "hfss_history": [*state["hfss_history"], result],
            "execution_trace": self._trace(state, "run_candidate_hfss"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def compare_hfss_results(self, state: ComparisonAgentState) -> dict:
        self._announce(11, "对比两次 HFSS 结果")
        if state["evaluation_result"] is not None:
            return {"execution_trace": self._trace(state, "compare_hfss_results:reused")}
        baseline = state["baseline_hfss_result"]
        current = state["candidate_hfss_result"]
        evaluator_rules = getattr(self.evaluator, "rules", ())
        rules = state["target_specification"].get("rules", evaluator_rules)
        frequency_plan = getattr(self.evaluator, "frequency_plan", None)
        candidate_id = current.candidate_id if current is not None else "unknown"
        evaluation = self.evaluator.evaluate_sparameters(
            current, evaluated_stage="optimized", rules=rules,
            candidate_id=candidate_id, frequency_plan=frequency_plan,
        )
        self.artifacts.write_candidate_artifact("evaluation_result", evaluation)
        emit_evaluation_summary(evaluation, title="Final")
        baseline_eval = state["baseline_evaluation"]
        comparison = (self.comparator or EvaluationComparator()).compare(baseline_eval, evaluation) if baseline_eval else None
        if comparison is not None:
            self.artifacts.write_candidate_artifact("evaluation_comparison", comparison)
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
        self.artifacts.write_candidate_artifact("hfss_comparison", evaluation)
        changes = {
            "evaluation_result": evaluation,
            "evaluation_comparison": comparison,
            "evaluation_history": [*state["evaluation_history"], evaluation],
            "execution_trace": self._trace(state, "compare_hfss_results"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def update_hfss_best(self, state: ComparisonAgentState) -> dict:
        self._announce(12, "更新最佳方案")
        evaluation = state["evaluation_result"]
        candidate = state["current_candidate"]
        result = state["candidate_hfss_result"]
        update = (
            evaluation is not None
            and evaluation.improved
            and candidate is not None
            and result is not None
            and result.success
            and (state["best_score"] is None or evaluation.score > state["best_score"])
        )
        changes: dict = {
            "execution_trace": self._trace(
                state, f"update_hfss_best:{'updated' if update else 'retained'}"
            )
        }
        if update:
            changes.update(
                best_candidate=candidate,
                best_hfss_result=result,
                best_score=evaluation.score,
            )
            self.artifacts.write_best(candidate, result, evaluation.score)
        self._checkpoint_changes(state, changes)
        return changes

    def diagnose_candidate(self, state: ComparisonAgentState) -> dict:
        self._announce(12, "诊断优化模型")
        evaluation = state["evaluation_result"]
        if evaluation is None:
            raise WorkflowError("Candidate EvaluationResult is required before diagnosis")
        node = self.diagnosis or DiagnosisNode()
        result = node.diagnose(
            evaluation,
            stage="optimized",
            comparison=state["evaluation_comparison"],
            baseline_diagnosis=state["baseline_diagnosis"],
        )
        self.artifacts.write_candidate_artifact("diagnosis_result", result)
        emit_diagnosis_summary(result, title="优化后")
        changes = {
            "diagnosis_result": result,
            "diagnosis_history": [*state["diagnosis_history"], result],
            "execution_trace": self._trace(state, "diagnose_candidate"),
        }
        self._checkpoint_changes(state, changes)
        return changes

    def decide_after_hfss(self, state: ComparisonAgentState) -> dict:
        self._announce(13, "判断工作流结果")
        action = NextAction(self.supervisor.route_after_candidate_hfss(state))
        return {
            "next_action": action,
            "execution_trace": self._trace(state, f"decide_after_hfss:{action}"),
        }

    def complete(self, state: ComparisonAgentState) -> dict:
        self._announce(14, "工作流完成")
        changes = {
            "status": WorkflowStatus.COMPLETED,
            "execution_trace": self._trace(state, "complete"),
        }
        self.checkpoint.save(ComparisonAgentState(**{**state, **changes}))
        return changes
