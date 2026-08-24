"""Composition root for the authoritative Closed-loop V2 Agent."""

from pathlib import Path

from .agent.workflow_runner import ComparisonWorkflowRunner
from .agent.closed_loop_graph import build_closed_loop_graph
from .agent.comparison_nodes import ComparisonWorkflowNodes
from .agent.router import WorkflowRouter
from .agent.supervisor import DeterministicSupervisor
from .core.config import AppConfig
from .core.models import CandidateParameters
from .evaluation.evaluator import DeterministicEvaluator
from .evaluation.comparator import EvaluationComparator
from .diagnosis import DiagnosisNode
from .harness.artifacts import ArtifactStore
from .harness.checkpoint import SQLiteComparisonCheckpointStore
from .harness.core import HarnessCore
from .harness.run_store import RunStore
from .interfaces.batch_optimizer import BatchOptimizerInterface
from .interfaces.evaluator import EvaluatorInterface
from .interfaces.hfss import HFSSInterface
from .interfaces.sparameters import SParameterInterface
from .parameters.schema import ParameterSchema
from .parameters.validator import ParameterValidator

def compose_comparison_nodes(
    *,
    task_id: str,
    baseline_parameters: CandidateParameters,
    schema: ParameterSchema,
    config: AppConfig,
    sparameters: SParameterInterface,
    optimizer: BatchOptimizerInterface,
    hfss: HFSSInterface,
    evaluator: EvaluatorInterface | None = None,
) -> ComparisonWorkflowNodes:
    """Build the shared Tool/node layer without choosing a graph topology."""

    router = WorkflowRouter(config.evaluation, config.routing)
    artifacts = ArtifactStore(Path(config.artifact_root), task_id)
    run_store = RunStore(Path(config.artifact_root) / ".runstore" / "runstore.sqlite3")
    harness = HarnessCore(
        store=run_store,
        artifacts=artifacts,
        settings=config.harness,
    )
    return ComparisonWorkflowNodes(
        sparameters=sparameters,
        optimizer=optimizer,
        hfss=hfss,
        evaluator=evaluator
        or DeterministicEvaluator(
            target_score=config.evaluation.target_score,
            tolerance=config.evaluation.improvement_tolerance,
            rules=config.evaluation.rules or tuple(config.evaluation.rules),
            frequency_plan=config.evaluation.frequency_plan,
        ),
        validator=ParameterValidator(schema),
        harness=harness,
        checkpoint=SQLiteComparisonCheckpointStore(run_store),
        router=router,
        supervisor=DeterministicSupervisor(router),
        comparator=EvaluationComparator(),
        diagnosis=DiagnosisNode(),
        expected_task_id=task_id,
        expected_baseline=baseline_parameters,
    )


def compose_closed_loop_workflow(
    *,
    task_id: str,
    baseline_parameters: CandidateParameters,
    schema: ParameterSchema,
    config: AppConfig,
    sparameters: SParameterInterface,
    optimizer: BatchOptimizerInterface,
    hfss: HFSSInterface,
    evaluator: EvaluatorInterface | None = None,
    recursion_limit: int = 512,
    allow_real_execution: bool = False,
) -> ComparisonWorkflowRunner:
    """Compose V2; real admission is available only to the validated formal root."""

    if not config.closed_loop_enabled:
        raise ValueError("closed-loop graph requires AppConfig.closed_loop_enabled=True")
    nodes = compose_comparison_nodes(
        task_id=task_id,
        baseline_parameters=baseline_parameters,
        schema=schema,
        config=config,
        sparameters=sparameters,
        optimizer=optimizer,
        hfss=hfss,
        evaluator=evaluator,
    )
    return build_closed_loop_graph(
        nodes,
        recursion_limit=recursion_limit,
        allow_real_execution=allow_real_execution,
    )
