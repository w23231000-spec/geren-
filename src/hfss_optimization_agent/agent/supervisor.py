"""Deterministic supervisor for candidate gate and final stop decisions."""

from .router import WorkflowRouter
from .comparison_state import ComparisonAgentState


class DeterministicSupervisor:
    def __init__(self, router: WorkflowRouter) -> None:
        self.router = router

    def route_after_candidate_sparameters(self, state: ComparisonAgentState) -> str:
        return self.router.after_candidate_sparameters(state).value

    def route_after_candidate_hfss(self, state: ComparisonAgentState) -> str:
        return self.router.after_candidate_hfss(state).value
