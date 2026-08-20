"""Complex response, optimization batch, and nine-parameter contract tests."""

import pytest

from hfss_optimization_agent.agent.comparison_state import (
    comparison_state_from_dict,
    comparison_state_to_dict,
    create_comparison_state,
)
from hfss_optimization_agent.core.models import (
    CandidateParameters,
    ComplexSParameters,
    OptimizationBatch,
    SParameterResult,
    HFSSResult,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)


def response() -> ComplexSParameters:
    return ComplexSParameters.from_complex_matrices(
        frequency_hz=[1e9, 2e9],
        matrices=[
            [[0.1 + 0.2j, 0.8 - 0.1j], [0.8 - 0.1j, 0.1 + 0.2j]],
            [[0.2 + 0.1j, 0.7 - 0.2j], [0.7 - 0.2j, 0.2 + 0.1j]],
        ],
    )


def test_complex_sparameters_are_json_safe_and_validate_shape():
    result = response()
    assert result.real[0][0][0] == pytest.approx(0.1)
    assert result.imag[0][0][0] == pytest.approx(0.2)
    assert result.port_order == ("port_1", "port_2")
    with pytest.raises(ValueError, match="2x2"):
        ComplexSParameters([1.0, 2.0], [[[1.0]], [[1.0]]], [[[0.0]], [[0.0]]])


def test_nine_parameter_contract_matches_supplied_modules():
    schema = supplied_nine_parameter_schema()
    baseline = supplied_baseline_candidate()
    assert tuple(schema.by_name) == (
        "sub_h",
        "TSV_r",
        "TSV_p",
        "BGA_r",
        "BGA_p",
        "RDL_w_layer1",
        "RDL_d_layer1",
        "RDL_w_layer2",
        "RDL_d_layer2",
    )
    assert baseline.values["sub_h"] == pytest.approx(200e-6)
    assert baseline.values["BGA_p"] == pytest.approx(660e-6)
    assert schema.by_name["TSV_r"].lower_bound == pytest.approx(7.5e-6)


def test_comparison_state_round_trip_preserves_complex_curves_and_batch():
    baseline = supplied_baseline_candidate()
    state = create_comparison_state(task_id="round-trip", baseline_parameters=baseline)
    s_result = SParameterResult("baseline", True, response(), {"screening_score": 0.0})
    candidate = CandidateParameters("candidate", 1, dict(baseline.values))
    batch = OptimizationBatch("run", True, [candidate], "candidate", 1)
    state["baseline_sparameter_result"] = s_result
    state["optimization_batch"] = batch
    state["candidate_queue"] = [candidate]
    state["baseline_hfss_result"] = HFSSResult(
        "baseline",
        True,
        complex_response=response(),
        execution_metadata={"comparison_context_id": "aligned-v1"},
    )
    state["hfss_history"] = [state["baseline_hfss_result"]]
    restored = comparison_state_from_dict(comparison_state_to_dict(state))
    assert restored["baseline_sparameter_result"].response.imag == s_result.response.imag
    assert restored["optimization_batch"].recommended_candidate_id == "candidate"
    assert restored["candidate_queue"][0].values == candidate.values
    assert restored["baseline_hfss_result"].complex_response.real == response().real
    assert restored["hfss_history"][0].execution_metadata["comparison_context_id"] == "aligned-v1"
