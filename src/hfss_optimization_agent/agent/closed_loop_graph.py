"""Authoritative bounded closed-loop Agent graph.

Every action node returns to ``controller`` and only ``ClosedLoopPolicy`` chooses the next route.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from .closed_loop_contracts import CLOSED_LOOP_WORKFLOW_ID, ControllerAction
from .closed_loop_policy import ClosedLoopPolicy
from .workflow_runner import ComparisonWorkflowRunner
from .comparison_nodes import ComparisonWorkflowNodes
from .comparison_state import (
    ComparisonAgentState,
    append_artifact_refs,
    append_candidate_snapshots,
    baseline_diagnosis,
    baseline_evaluation,
    candidate_evaluation,
    candidate_index,
    current_candidate,
    current_comparison,
    current_comparison_record,
    evaluation_record,
    state_context_id,
    state_run_id,
    with_changes,
)
from ..core.enums import WorkflowStatus
from ..core.models import CandidateParameters, FrequencyPlan, TerminalOutcome
from ..diagnosis import DiagnosisNode, DiagnosisResult
from ..domain.contracts import DecisionAction, DecisionOutcome
from ..domain.canonical_json import canonical_dumps
from ..harness.errors import WorkflowError
from ..optimization.intent import (
    OptimizationIntentBuilder,
    OptimizationObjectiveBuilder,
)


@dataclass(slots=True)
class ClosedLoopWorkflowRunner(ComparisonWorkflowRunner):
    """Admit real manifests only from the explicit Production composition root."""

    allow_real_execution: bool = False

    def invoke(self, state: ComparisonAgentState) -> ComparisonAgentState:
        if state["manifest"].real_execution and not self.allow_real_execution:
            raise WorkflowError(
                "closed-loop-agent-v2 real execution requires explicit Production composition"
            )
        return ComparisonWorkflowRunner.invoke(self, state)


def _apply(
    state: ComparisonAgentState,
    node,
) -> ComparisonAgentState:
    return with_changes(state, node(state))


class ClosedLoopGraphNodes:
    def __init__(
        self,
        workflow: ComparisonWorkflowNodes,
        policy: ClosedLoopPolicy,
        *,
        allow_real_execution: bool,
    ) -> None:
        self.workflow = workflow
        self.policy = policy
        self.allow_real_execution = allow_real_execution

    def _save(self, state: ComparisonAgentState) -> ComparisonAgentState:
        self.workflow.checkpoint.save(state)
        return state

    def bootstrap(self, state: ComparisonAgentState) -> ComparisonAgentState:
        if state["manifest"].real_execution and not self.allow_real_execution:
            raise WorkflowError(
                "closed-loop-agent-v2 real execution requires explicit Production composition"
            )
        working = state
        for node in (
            self.workflow.initialize_task,
            self.workflow.calculate_baseline_sparameters,
            self.workflow.run_baseline_hfss,
            self.workflow.diagnose_baseline,
            self.workflow.freeze_baseline,
        ):
            working = _apply(working, node)
        return self._save(working)

    def controller(self, state: ComparisonAgentState) -> dict:
        controller = self.policy.decide(state)
        decision = controller.decisions[-1]
        run = self.workflow.harness.store.get_run(state_run_id(state))
        if run is None:
            raise WorkflowError("controller decision requires a registered Run")
        evidence_ids = tuple(
            sorted(
                {
                    *(record.record_id for record in state["evaluations"]),
                    *(record.record_id for record in state["comparisons"]),
                    *(artifact.artifact_id for artifact in state["artifact_refs"]),
                }
            )
        )
        decision_payload = {
            "decision_id": decision.decision_id,
            "input_state_revision": run.latest_checkpoint_revision,
            "input_state_sha256": hashlib.sha256(
                canonical_dumps(state).encode("utf-8")
            ).hexdigest(),
            "policy_version": controller.policy_id,
            "iteration": decision.iteration,
            "action": decision.action,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
            "candidate_id": decision.candidate_id,
            "evidence_ids": evidence_ids,
            "next_step": decision.action,
        }
        event_id = "evt_decision_" + hashlib.sha256(
            f"{state_run_id(state)}\0{decision.decision_id}".encode("utf-8")
        ).hexdigest()[:32]
        self.workflow.harness.store.append_event_once(
            state_run_id(state), event_id, "policy_decision", decision_payload
        )
        changes = {
            "controller": controller,
            "execution_trace": (
                *state["execution_trace"],
                f"controller:{decision.iteration}:{decision.action}:{decision.reason_code}",
            ),
        }
        self.workflow.checkpoint.save(with_changes(state, changes))
        return changes

    @staticmethod
    def route(state: ComparisonAgentState) -> str:
        controller = state["controller"]
        if controller is None or controller.pending_action is None:
            raise WorkflowError("controller produced no authoritative route")
        return controller.pending_action.value

    def prepare_optimization(self, state: ComparisonAgentState) -> ComparisonAgentState:
        working = _apply(state, self.workflow.build_optimization_intent)
        working = _apply(working, self.workflow.build_optimization_objective)
        controller = working["controller"]
        assert controller is not None
        working = with_changes(
            working,
            {
                "controller": controller.replace(
                    prepared_optimizer_iteration=controller.optimizer_calls,
                    pending_action=None,
                ),
                "execution_trace": (*working["execution_trace"], "closed_loop:prepared"),
            },
        )
        return self._save(working)

    def reoptimize(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        if controller is None or not controller.consumed_candidate_ids:
            raise WorkflowError("reoptimization requires consumed candidate evidence")
        candidate_id = controller.consumed_candidate_ids[-1]
        diagnosis = next(
            (
                item
                for item in reversed(state["diagnoses"])
                if item.stage == f"optimized:{candidate_id}"
            ),
            None,
        )
        evaluation_record_value = evaluation_record(
            state, candidate_id=candidate_id, stage="optimized"
        )
        if diagnosis is None or evaluation_record_value is None:
            raise WorkflowError("reoptimization requires candidate diagnosis/evaluation evidence")
        evaluation = evaluation_record_value.to_result()
        intent = (self.workflow.intent_builder or OptimizationIntentBuilder()).build(diagnosis)
        objective = (
            self.workflow.objective_builder or OptimizationObjectiveBuilder()
        ).build(
            intent,
            evaluation,
            FrequencyPlan.from_mapping(evaluation.frequency_plan),
            getattr(self.workflow.evaluator, "rules", ()),
        )
        iteration = controller.optimizer_calls
        intent_artifact = self.workflow._record_artifact(
            state,
            subject_id=f"iteration:{iteration}",
            key=f"optimization_intent:iteration:{iteration}",
            role="optimization_intent",
            value=intent,
        )
        objective_artifact = self.workflow._record_artifact(
            state,
            subject_id=f"iteration:{iteration}",
            key=f"optimization_objective:iteration:{iteration}",
            role="optimization_objective",
            value=objective,
        )
        working = with_changes(
            state,
            {
                "optimization_intent": intent,
                "optimization_objective": objective,
                "artifact_refs": append_artifact_refs(
                    state["artifact_refs"],
                    self.workflow._artifact_ref(state, intent_artifact.artifact),
                    self.workflow._artifact_ref(state, objective_artifact.artifact),
                ),
                "controller": controller.replace(
                    reoptimizations=controller.reoptimizations + 1,
                    prepared_optimizer_iteration=iteration,
                    pending_action=None,
                ),
                "execution_trace": (*state["execution_trace"], f"closed_loop:reoptimize:{iteration}"),
            },
        )
        return self._save(working)

    def optimize(self, state: ComparisonAgentState) -> ComparisonAgentState:
        working = _apply(state, self.workflow.run_optimizer)
        controller = working["controller"]
        assert controller is not None
        working = with_changes(
            working,
            {
                "controller": controller.replace(
                    optimizer_calls=controller.optimizer_calls + 1,
                    pending_action=None,
                ),
                "decision_outcome": None,
                "execution_trace": (*working["execution_trace"], "closed_loop:optimized"),
            },
        )
        return self._save(working)

    def select_next_candidate(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        if controller is None or not state["candidate_queue"]:
            raise WorkflowError("candidate selection requires a non-empty queue")
        queue = state["candidate_queue"]
        recommended = (
            state["optimization_run"].recommended_candidate_id
            if state["optimization_run"] is not None
            else None
        )
        selected_id = recommended if recommended in queue else queue[0]
        selected = candidate_index(state)[selected_id].to_candidate()
        artifact = self.workflow._record_artifact(
            state,
            subject_id=selected_id,
            key=f"candidate_parameters:{selected_id}",
            role="candidate_parameters",
            value=selected,
        )
        working = with_changes(
            state,
            {
                "current_candidate_id": selected_id,
                "candidate_queue": tuple(item for item in queue if item != selected_id),
                "decision_outcome": None,
                "artifact_refs": append_artifact_refs(
                    state["artifact_refs"],
                    self.workflow._artifact_ref(
                        state, artifact.artifact, candidate_id=selected_id
                    ),
                ),
                "controller": controller.replace(pending_action=None),
                "execution_trace": (*state["execution_trace"], f"closed_loop:selected:{selected_id}"),
            },
        )
        return self._save(working)

    def screen_candidate(self, state: ComparisonAgentState) -> ComparisonAgentState:
        working = _apply(state, self.workflow.validate_optimized_candidate)
        working = _apply(working, self.workflow.recalculate_candidate_sparameters)
        working = _apply(working, self.workflow.candidate_sparameter_gate)
        controller = working["controller"]
        assert controller is not None
        working = with_changes(
            working,
            {
                "controller": controller.replace(
                    candidate_screenings=controller.candidate_screenings + 1,
                    pending_action=None,
                ),
                "execution_trace": (*working["execution_trace"], "closed_loop:screened"),
            },
        )
        return self._save(working)

    def run_candidate_hfss(self, state: ComparisonAgentState) -> ComparisonAgentState:
        candidate = current_candidate(state)
        if candidate is None:
            raise WorkflowError("candidate HFSS requires a current candidate")
        previous_best = state["best_policy"].selected_candidate_id if state["best_policy"] else None
        working = _apply(state, self.workflow.run_candidate_hfss)
        result = next(
            item for item in working["hfss_results"] if item.candidate_id == candidate.candidate_id
        )
        if result.success:
            working = _apply(working, self.workflow.compare_hfss_results)
            evaluation = candidate_evaluation(working)
            if evaluation is None:
                raise WorkflowError("candidate evaluation is missing after HFSS comparison")
            diagnosis_node = self.workflow.diagnosis or DiagnosisNode()
            diagnosis = DiagnosisResult.from_dict(
                diagnosis_node.diagnose(
                    evaluation,
                    stage=f"optimized:{candidate.candidate_id}",
                    comparison=current_comparison(working),
                    baseline_diagnosis=baseline_diagnosis(working),
                ).to_dict()
            )
            artifact = self.workflow._record_artifact(
                working,
                subject_id=candidate.candidate_id,
                key=f"diagnosis:{candidate.candidate_id}",
                role="candidate_diagnosis",
                value=diagnosis,
            )
            working = with_changes(
                working,
                {
                    "diagnoses": (*working["diagnoses"], diagnosis),
                    "artifact_refs": append_artifact_refs(
                        working["artifact_refs"],
                        self.workflow._artifact_ref(
                            working, artifact.artifact, candidate_id=candidate.candidate_id
                        ),
                    ),
                },
            )
            working = _apply(working, self.workflow.update_hfss_best)
        controller = working["controller"]
        assert controller is not None
        new_best = working["best_policy"].selected_candidate_id if working["best_policy"] else None
        stagnation = 0 if new_best != previous_best else controller.stagnation_count + 1
        working = with_changes(
            working,
            {
                "controller": controller.replace(
                    candidate_hfss_calls=controller.candidate_hfss_calls + 1,
                    stagnation_count=stagnation,
                    pending_action=None,
                ),
                "execution_trace": (*working["execution_trace"], "closed_loop:candidate_hfss_evaluated"),
            },
        )
        return self._save(working)

    def next_candidate(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        candidate_id = state["current_candidate_id"]
        if controller is None or candidate_id is None:
            raise WorkflowError("candidate consumption requires a current candidate")
        consumed = (*controller.consumed_candidate_ids, candidate_id)
        working = with_changes(
            state,
            {
                "current_candidate_id": None,
                "decision_outcome": None,
                "controller": controller.replace(
                    consumed_candidate_ids=consumed,
                    pending_action=None,
                ),
                "execution_trace": (*state["execution_trace"], f"closed_loop:consumed:{candidate_id}"),
            },
        )
        return self._save(working)

    def retry_safe(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        source = current_candidate(state)
        if controller is None or source is None:
            raise WorkflowError("safe retry requires a current candidate")
        retry_number = controller.safe_retries + 1
        retry = CandidateParameters(
            candidate_id=f"{source.candidate_id}-safe-retry-{retry_number}",
            iteration=source.iteration + 1,
            values=dict(source.values),
            metadata={
                **source.metadata,
                "source": "retry-safe-controller",
                "retry_of": source.candidate_id,
                "retry_number": retry_number,
            },
        )
        candidates = append_candidate_snapshots(
            state,
            [retry],
            source="retry-safe-controller",
            parent_candidate_id=source.candidate_id,
        )
        working = with_changes(
            state,
            {
                "candidates": candidates,
                "current_candidate_id": None,
                "candidate_queue": (retry.candidate_id, *state["candidate_queue"]),
                "decision_outcome": None,
                "controller": controller.replace(
                    safe_retries=retry_number,
                    consumed_candidate_ids=(
                        *controller.consumed_candidate_ids,
                        source.candidate_id,
                    ),
                    pending_action=None,
                ),
                "execution_trace": (*state["execution_trace"], f"closed_loop:retry_safe:{retry.candidate_id}"),
            },
        )
        return self._save(working)

    def reconcile(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        if controller is None:
            raise WorkflowError("reconciliation requires controller state")
        decision = DecisionOutcome(
            decision_id=f"decision:{state_run_id(state)}:reconcile",
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            action=DecisionAction.WAITING_RECONCILIATION,
            reason_code="explicit_reconciliation_required",
            reason="No automatic retry is authorized for an UNKNOWN physical outcome.",
        )
        working = with_changes(
            state,
            {
                "status": WorkflowStatus.WAITING_RECONCILIATION,
                "decision_outcome": decision,
                "controller": controller.replace(pending_action=None),
                "execution_trace": (*state["execution_trace"], "closed_loop:reconcile"),
            },
        )
        return self._save(working)

    def finalize(self, state: ComparisonAgentState) -> ComparisonAgentState:
        controller = state["controller"]
        if controller is None or not controller.decisions:
            raise WorkflowError("typed finalization requires a controller decision")
        decision = controller.decisions[-1]
        baseline = baseline_evaluation(state)
        candidate = current_candidate(state)
        evaluation = candidate_evaluation(state) if candidate else None
        if decision.reason_code == "baseline_target_met":
            status = WorkflowStatus.SUCCEEDED_BASELINE
            candidate_id = state["manifest"].baseline_candidate_id
            evidence_ids = tuple(
                item.record_id
                for item in state["evaluations"]
                if item.candidate_id == candidate_id and item.stage == "initial"
            )
        elif decision.reason_code == "candidate_target_met":
            if candidate is None or evaluation is None or not evaluation.pass_target:
                raise WorkflowError("candidate success finalization lacks PASS evidence")
            if state["best_policy"] is None or state["best_policy"].selected_candidate_id != candidate.candidate_id:
                raise WorkflowError("candidate success finalization requires Best promotion")
            status = WorkflowStatus.SUCCEEDED_CANDIDATE
            candidate_id = candidate.candidate_id
            record = evaluation_record(state, candidate_id=candidate_id, stage="optimized")
            comparison = current_comparison_record(state)
            evidence_ids = tuple(
                item
                for item in (
                    record.record_id if record else None,
                    comparison.record_id if comparison else None,
                )
                if item is not None
            )
        elif decision.reason_code == "baseline_evaluation_invalid":
            status = WorkflowStatus.INVALID
            candidate_id = state["manifest"].baseline_candidate_id
            evidence_ids = ()
        else:
            status = WorkflowStatus.NO_SOLUTION
            candidate_id = state["best_policy"].selected_candidate_id if state["best_policy"] else None
            evidence_ids = tuple(record.record_id for record in state["comparisons"])
        outcome = TerminalOutcome(
            status=status,
            reason_code=decision.reason_code,
            reason=decision.reason,
            run_id=state_run_id(state),
            context_id=state_context_id(state),
            candidate_id=candidate_id,
            evidence_ids=evidence_ids,
        )
        artifact = self.workflow._record_artifact(
            state,
            subject_id=candidate_id or "run",
            key="closed_loop_terminal_outcome",
            role="terminal_outcome",
            value=outcome,
        )
        working = with_changes(
            state,
            {
                "status": status,
                "terminal_outcome": outcome,
                "controller": controller.replace(pending_action=None),
                "artifact_refs": append_artifact_refs(
                    state["artifact_refs"],
                    self.workflow._artifact_ref(
                        state, artifact.artifact, candidate_id=candidate_id
                    ),
                ),
                "execution_trace": (*state["execution_trace"], f"closed_loop:finalize:{status}"),
            },
        )
        working = self.workflow.attach_final_manifest(working)
        self.workflow.checkpoint.complete(working)
        return working


def build_closed_loop_graph(
    workflow: ComparisonWorkflowNodes,
    policy: ClosedLoopPolicy | None = None,
    *,
    recursion_limit: int = 512,
    allow_real_execution: bool = False,
) -> ClosedLoopWorkflowRunner:
    controller_nodes = ClosedLoopGraphNodes(
        workflow,
        policy or ClosedLoopPolicy(),
        allow_real_execution=allow_real_execution,
    )
    builder = StateGraph(ComparisonAgentState)
    builder.add_node("bootstrap", controller_nodes.bootstrap)
    builder.add_node("controller", controller_nodes.controller)
    builder.add_node("prepare_optimization", controller_nodes.prepare_optimization)
    builder.add_node("optimize", controller_nodes.optimize)
    builder.add_node("select_next_candidate", controller_nodes.select_next_candidate)
    builder.add_node("screen_candidate", controller_nodes.screen_candidate)
    builder.add_node("run_candidate_hfss", controller_nodes.run_candidate_hfss)
    builder.add_node("next_candidate", controller_nodes.next_candidate)
    builder.add_node("reoptimize", controller_nodes.reoptimize)
    builder.add_node("retry_safe", controller_nodes.retry_safe)
    builder.add_node("reconcile", controller_nodes.reconcile)
    builder.add_node("finalize", controller_nodes.finalize)

    builder.add_edge(START, "bootstrap")
    builder.add_edge("bootstrap", "controller")
    route_map = {action.value: action.value for action in ControllerAction}
    builder.add_conditional_edges("controller", controller_nodes.route, route_map)
    for node in (
        "prepare_optimization",
        "optimize",
        "select_next_candidate",
        "screen_candidate",
        "run_candidate_hfss",
        "next_candidate",
        "reoptimize",
        "retry_safe",
    ):
        builder.add_edge(node, "controller")
    builder.add_edge("reconcile", END)
    builder.add_edge("finalize", END)
    return ClosedLoopWorkflowRunner(
        builder.compile(),
        workflow,
        recursion_limit=recursion_limit,
        expected_workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        allow_real_execution=allow_real_execution,
    )
