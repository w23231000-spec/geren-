"""Composition root for the single baseline-optimize-HFSS-compare workflow."""

from pathlib import Path

from .agent.comparison_graph import ComparisonWorkflowRunner, build_comparison_graph
from .agent.comparison_nodes import ComparisonWorkflowNodes
from .agent.router import WorkflowRouter
from .agent.supervisor import DeterministicSupervisor
from .core.config import AppConfig
from .core.models import CandidateParameters
from .evaluation.evaluator import DeterministicEvaluator
from .evaluation.comparator import EvaluationComparator
from .diagnosis import DiagnosisNode
from .harness.artifacts import ArtifactStore
from .harness.checkpoint import JsonComparisonCheckpointStore
from .harness.logging import build_logger
from .interfaces.batch_optimizer import BatchOptimizerInterface
from .interfaces.evaluator import EvaluatorInterface
from .interfaces.hfss import HFSSInterface
from .interfaces.sparameters import SParameterInterface
from .parameters.schema import ParameterSchema
from .parameters.validator import ParameterValidator


def compose_comparison_workflow(
    *,
    task_id: str,
    baseline_parameters: CandidateParameters,
    schema: ParameterSchema,
    config: AppConfig,
    sparameters: SParameterInterface,
    optimizer: BatchOptimizerInterface,
    hfss: HFSSInterface,
    evaluator: EvaluatorInterface | None = None,
) -> ComparisonWorkflowRunner:
    """Inject professional providers without coupling the LangGraph topology to implementations."""

    router = WorkflowRouter(config.evaluation, config.routing)
    artifacts = ArtifactStore(Path(config.artifact_root), task_id)
    build_logger(artifacts.task_dir).info("Composing presentation workflow for %s", task_id)
    nodes = ComparisonWorkflowNodes(
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
        artifacts=artifacts,
        checkpoint=JsonComparisonCheckpointStore(artifacts.task_dir / "checkpoint.json"),
        router=router,
        supervisor=DeterministicSupervisor(router),
        comparator=EvaluationComparator(),
        diagnosis=DiagnosisNode(),
    )
    return build_comparison_graph(nodes)
