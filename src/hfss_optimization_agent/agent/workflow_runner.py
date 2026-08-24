"""Shared transactional runner for the authoritative Agent graph."""

from dataclasses import dataclass

from ..core.enums import WorkflowStatus
from ..core.models import TerminalOutcome
from ..domain.contracts import DecisionAction, DecisionOutcome
from ..harness.core import OperationUnknownError
from ..harness.errors import WorkflowError
from ..harness.run_store import (
    CheckpointCorruption,
    RunInvocationDisposition,
    RunStatus,
)
from .comparison_nodes import ComparisonWorkflowNodes
from .comparison_state import (
    ComparisonAgentState,
    WORKFLOW_ID_V2,
    state_context_id,
    state_run_id,
    with_changes,
)


@dataclass(slots=True)
class ComparisonWorkflowRunner:
    graph: object
    nodes: ComparisonWorkflowNodes
    recursion_limit: int = 100
    expected_workflow_id: str = WORKFLOW_ID_V2

    def invoke(self, state: ComparisonAgentState) -> ComparisonAgentState:
        if state["manifest"].workflow_id != self.expected_workflow_id:
            raise WorkflowError(
                "Graph/workflow identity is incompatible: expected "
                f"{self.expected_workflow_id!r}, got {state['manifest'].workflow_id!r}"
            )
        run_id = state_run_id(state)
        self.nodes.harness.ensure_run(state["manifest"])
        self.nodes.checkpoint.bind(run_id)
        with self.nodes.harness.run_invocation(run_id) as claim:
            if claim.disposition is RunInvocationDisposition.OWNER:
                self.nodes.checkpoint.set_invocation_fence(
                    self.nodes.harness.owner_token, claim.fence
                )
            else:
                self.nodes.checkpoint.set_invocation_fence(None, None)
            try:
                return self._invoke_serialized(state)
            finally:
                self.nodes.checkpoint.set_invocation_fence(None, None)

    def _waiting_state(
        self,
        state: ComparisonAgentState,
        *,
        decision_id: str,
        reason_code: str,
        reason: str,
        evidence_ids: tuple[str, ...] = (),
    ) -> ComparisonAgentState:
        return with_changes(
            state,
            {
                "status": WorkflowStatus.WAITING_RECONCILIATION,
                "decision_outcome": DecisionOutcome(
                    decision_id=decision_id,
                    run_id=state_run_id(state),
                    context_id=state_context_id(state),
                    action=DecisionAction.WAITING_RECONCILIATION,
                    reason_code=reason_code,
                    reason=reason,
                    evidence_ids=evidence_ids,
                ),
                "terminal_outcome": None,
            },
        )

    def _invoke_serialized(self, state: ComparisonAgentState) -> ComparisonAgentState:
        run_id = state_run_id(state)
        self.nodes.harness.store.expire_stale_operations(run_id)
        run = self.nodes.harness.store.get_run(run_id)
        if run is None:
            raise RuntimeError("RunStore lost the registered run")
        if self.nodes.checkpoint.has_checkpoint():
            try:
                self.nodes.checkpoint.load()
            except CheckpointCorruption as exc:
                if run.status is RunStatus.COMPLETED:
                    raise
                reason = f"{type(exc).__name__}: {exc}"
                waiting = self._waiting_state(
                    state,
                    decision_id=(
                        f"decision:checkpoint_corrupt:{run.latest_checkpoint_revision}"
                    ),
                    reason_code="checkpoint_corrupt",
                    reason=reason,
                    evidence_ids=(
                        f"checkpoint:{run_id}:{run.latest_checkpoint_revision}",
                    ),
                )
                self.nodes.harness.store.mark_waiting_reconciliation(
                    run_id, reason=reason
                )
                self.nodes.harness.store.append_event_once(
                    run_id,
                    (
                        f"event:checkpoint_corrupt:{run_id}:"
                        f"{run.latest_checkpoint_revision}"
                    ),
                    "checkpoint_corrupt",
                    {
                        "revision": run.latest_checkpoint_revision,
                        "reason": reason,
                    },
                )
                return waiting
        if run.status in {RunStatus.COMPLETED, RunStatus.WAITING_RECONCILIATION}:
            preserved = (
                self.nodes.checkpoint.load()
                if self.nodes.checkpoint.has_checkpoint()
                else state
            )
            if run.status is RunStatus.COMPLETED:
                if not self.nodes.checkpoint.has_checkpoint():
                    raise RuntimeError("completed Run has no authoritative checkpoint")
                return preserved
            if run.status is RunStatus.WAITING_RECONCILIATION:
                existing_decision = preserved.get("decision_outcome")
                if (
                    WorkflowStatus(preserved["status"])
                    is WorkflowStatus.WAITING_RECONCILIATION
                    and existing_decision is not None
                    and existing_decision.action
                    is DecisionAction.WAITING_RECONCILIATION
                ):
                    return preserved
                waiting = self._waiting_state(
                    preserved,
                    decision_id="decision:run:waiting_reconciliation",
                    reason_code="operation_outcome_unknown",
                    reason="An action has UNKNOWN physical outcome and requires reconciliation.",
                )
                if waiting != preserved:
                    self.nodes.checkpoint.save(waiting)
                return waiting
        if self.nodes.checkpoint.has_checkpoint():
            state = self.nodes.checkpoint.load()
        try:
            return self.graph.invoke(
                state, config={"recursion_limit": self.recursion_limit}
            )
        except OperationUnknownError as exc:
            preserved = state
            if self.nodes.checkpoint.has_checkpoint():
                try:
                    preserved = self.nodes.checkpoint.load()
                except (FileNotFoundError, RuntimeError):
                    preserved = state
            message = f"{type(exc).__name__}: {exc}"
            waiting = with_changes(
                preserved,
                {
                    "status": WorkflowStatus.WAITING_RECONCILIATION,
                    "decision_outcome": DecisionOutcome(
                        decision_id=f"decision:{exc.operation.operation_id}:waiting",
                        run_id=state_run_id(preserved),
                        context_id=state_context_id(preserved),
                        action=DecisionAction.WAITING_RECONCILIATION,
                        reason_code="operation_outcome_unknown",
                        reason=message,
                        evidence_ids=(exc.operation.operation_id,),
                    ),
                    "last_error": message,
                },
            )
            self.nodes.harness.store.mark_waiting_reconciliation(run_id, reason=message)
            self.nodes.checkpoint.save(waiting)
            return waiting
        except WorkflowError as exc:
            preserved = state
            if self.nodes.checkpoint.has_checkpoint():
                preserved = self.nodes.checkpoint.load()
            message = f"{type(exc).__name__}: {exc}"
            failed = with_changes(
                preserved,
                {
                    "status": WorkflowStatus.FAILED,
                    "terminal_outcome": TerminalOutcome(
                        WorkflowStatus.FAILED,
                        "workflow_exception",
                        message,
                        state_run_id(preserved),
                        state_context_id(preserved),
                    ),
                    "last_error": message,
                },
            )
            self.nodes.harness.record_artifact(
                run_id=run_id,
                subject_id="run",
                idempotency_key="artifact:workflow_error",
                role="workflow_error",
                value={"error": message},
            )
            failed = self.nodes.attach_final_manifest(failed)
            self.nodes.checkpoint.complete(failed)
            raise
