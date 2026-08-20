"""Contracts for production providers and the retained presentation test doubles."""

from hfss_optimization_agent.evaluation.evaluator import DeterministicEvaluator
from hfss_optimization_agent.hfss.mock_hfss import MockHFSS
from hfss_optimization_agent.interfaces.batch_optimizer import BatchOptimizerInterface
from hfss_optimization_agent.interfaces.evaluator import EvaluatorInterface
from hfss_optimization_agent.interfaces.hfss import HFSSInterface
from hfss_optimization_agent.interfaces.sparameters import SParameterInterface
from hfss_optimization_agent.optimization.deterministic_batch_optimizer import (
    DeterministicBatchOptimizer,
)
from hfss_optimization_agent.sparameters.mock_surrogate import DeterministicSurrogate


def test_retained_test_doubles_implement_production_interfaces():
    assert isinstance(DeterministicBatchOptimizer(), BatchOptimizerInterface)
    assert isinstance(DeterministicSurrogate({"p1": 1.0}), SParameterInterface)
    assert isinstance(MockHFSS(), HFSSInterface)
    assert isinstance(DeterministicEvaluator(), EvaluatorInterface)


def test_hfss_test_double_supports_better_and_worse_candidates():
    from hfss_optimization_agent.core.models import CandidateParameters

    mock = MockHFSS()
    baseline = mock.run(CandidateParameters("baseline", 0, {"p1": 1.0}))
    better = mock.run(CandidateParameters("better", 1, {"p1": 1.4}))
    worse = mock.run(CandidateParameters("worse", 2, {"p1": 0.8}))
    assert better.metrics["score"] > baseline.metrics["score"] > worse.metrics["score"]
