"""LangGraph topology for the confirmed two-HFSS-result comparison workflow."""

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from ..core.enums import NextAction
from ..harness.errors import WorkflowError
from .comparison_nodes import ComparisonWorkflowNodes
from .comparison_state import ComparisonAgentState


@dataclass(slots=True)
class ComparisonWorkflowRunner:
    graph: object
    nodes: ComparisonWorkflowNodes

    def invoke(self, state: ComparisonAgentState) -> ComparisonAgentState:
        try:
            return self.graph.invoke(state)
        except Exception as exc:
            preserved = self.nodes.checkpoint.load() if self.nodes.checkpoint.path.exists() else state
            message = f"{type(exc).__name__}: {exc}"
            failed = ComparisonAgentState(
                **{**preserved, "status": "failed", "last_error": message}
            )
            self.nodes.artifacts.write_candidate_artifact("error", {"error": message})
            self.nodes.checkpoint.save(failed)
            if isinstance(exc, WorkflowError):
                raise
            raise WorkflowError(message) from exc


def build_comparison_graph(nodes: ComparisonWorkflowNodes) -> ComparisonWorkflowRunner:
    builder = StateGraph(ComparisonAgentState)
    builder.add_node("initialize_task", nodes.initialize_task)
    builder.add_node("calculate_baseline_sparameters", nodes.calculate_baseline_sparameters)
    builder.add_node("run_baseline_hfss", nodes.run_baseline_hfss)
    builder.add_node("diagnose_baseline", nodes.diagnose_baseline)
    builder.add_node("freeze_baseline", nodes.freeze_baseline)
    builder.add_node("build_optimization_intent", nodes.build_optimization_intent)
    builder.add_node("build_optimization_objective", nodes.build_optimization_objective)
    builder.add_node("run_optimizer", nodes.run_optimizer)
    builder.add_node("select_optimized_candidate", nodes.select_optimized_candidate)
    builder.add_node("validate_optimized_candidate", nodes.validate_optimized_candidate)
    builder.add_node("recalculate_candidate_sparameters", nodes.recalculate_candidate_sparameters)
    builder.add_node("candidate_sparameter_gate", nodes.candidate_sparameter_gate)
    builder.add_node("run_candidate_hfss", nodes.run_candidate_hfss)
    builder.add_node("compare_hfss_results", nodes.compare_hfss_results)
    builder.add_node("diagnose_candidate", nodes.diagnose_candidate)
    builder.add_node("update_hfss_best", nodes.update_hfss_best)
    builder.add_node("decide_after_hfss", nodes.decide_after_hfss)
    builder.add_node("complete", nodes.complete)

    builder.add_edge(START, "initialize_task")
    builder.add_edge("initialize_task", "calculate_baseline_sparameters")
    builder.add_edge("calculate_baseline_sparameters", "run_baseline_hfss")
    builder.add_edge("run_baseline_hfss", "diagnose_baseline")
    builder.add_edge("diagnose_baseline", "freeze_baseline")
    builder.add_edge("freeze_baseline", "build_optimization_intent")
    builder.add_edge("build_optimization_intent", "build_optimization_objective")

    def route_optimization(state: ComparisonAgentState) -> str:
        return "run_optimizer" if state["optimization_intent"] is not None and state["optimization_intent"].status == "ACTIVE" else "complete"

    builder.add_conditional_edges(
        "build_optimization_objective",
        route_optimization,
        {"run_optimizer": "run_optimizer", "complete": "complete"},
    )
    builder.add_edge("run_optimizer", "select_optimized_candidate")
    builder.add_edge("select_optimized_candidate", "validate_optimized_candidate")
    builder.add_edge("validate_optimized_candidate", "recalculate_candidate_sparameters")
    builder.add_edge("recalculate_candidate_sparameters", "candidate_sparameter_gate")

    def route_gate(state: ComparisonAgentState) -> str:
        return "run_candidate_hfss" if state["next_action"] == NextAction.RUN_HFSS else "complete"

    builder.add_conditional_edges(
        "candidate_sparameter_gate",
        route_gate,
        {"run_candidate_hfss": "run_candidate_hfss", "complete": "complete"},
    )
    builder.add_edge("run_candidate_hfss", "compare_hfss_results")
    builder.add_edge("compare_hfss_results", "diagnose_candidate")
    builder.add_edge("diagnose_candidate", "update_hfss_best")
    builder.add_edge("update_hfss_best", "decide_after_hfss")
    builder.add_edge("decide_after_hfss", "complete")
    builder.add_edge("complete", END)
    return ComparisonWorkflowRunner(builder.compile(), nodes)
