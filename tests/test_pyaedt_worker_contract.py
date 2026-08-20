"""Offline tests for the real-worker contract; these never import or launch PyAEDT."""

from pathlib import Path

import pytest

from hfss_optimization_agent.cli import _contract_frequency_grid, run_real_supplied_demo
from hfss_optimization_agent.hfss.contracts import load_hfss_contract
from hfss_optimization_agent.hfss.pyaedt_composition import compose_pyaedt_hfss
from hfss_optimization_agent.hfss.pyaedt_worker import (
    _candidate_values,
    _frequency_multiplier,
    _logical_expressions,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "config" / "hfss_contract.pa_multi_2025_1.json"


def contract_dict():
    return load_hfss_contract(CONTRACT_PATH).to_dict()


def test_real_contract_solves_template_and_orders_input_port_4_first():
    contract = load_hfss_contract(CONTRACT_PATH)
    assert contract.design_name == "interposer_temple4"
    assert contract.metadata["build_strategy"] == "target_design_only"
    assert [port.exported_name for port in contract.ports] == ["4", "3"]
    assert contract.port_order == ("input", "output")
    assert contract.sweep.points == 200


def test_logical_expression_matrix_maps_s11_and_s21_without_reciprocity_assumption():
    expressions, matrix = _logical_expressions(contract_dict())
    assert matrix == [["S(4,4)", "S(4,3)"], ["S(3,4)", "S(3,3)"]]
    assert expressions == ["S(4,4)", "S(4,3)", "S(3,4)", "S(3,3)"]
    assert matrix[1][0] == "S(3,4)"


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("Hz", 1.0), ("kHz", 1e3), ("MHz", 1e6), ("GHz", 1e9), ("THz", 1e12)],
)
def test_frequency_units_are_converted_to_hz(unit, expected):
    assert _frequency_multiplier(unit) == expected


def test_surrogate_comparison_grid_exactly_matches_hfss_contract():
    grid = _contract_frequency_grid(load_hfss_contract(CONTRACT_PATH))
    assert len(grid) == 200
    assert grid[0] == pytest.approx(0.1e9)
    assert grid[-1] == pytest.approx(20e9)
    assert grid[1] - grid[0] == pytest.approx(0.1e9)


def test_candidate_requires_exact_nine_parameter_contract():
    contract = contract_dict()
    values = {name: 1e-4 for name in contract["parameter_mapping"]}
    request = {"candidate": {"values": values}}
    assert _candidate_values(request, contract) == values
    request["candidate"]["values"].pop("sub_h")
    with pytest.raises(ValueError, match="parameter mismatch"):
        _candidate_values(request, contract)


def test_real_composition_is_inert_and_carries_runtime_options(tmp_path):
    builder = tmp_path / "builder"
    builder.mkdir()
    (builder / "nine_parameter_builder.py").write_text("# inert test builder\n", encoding="utf-8")
    adapter = compose_pyaedt_hfss(
        contract=load_hfss_contract(CONTRACT_PATH),
        pyaedt_python=Path(__import__("sys").executable),
        builder_source_root=builder,
        artifact_root=tmp_path / "runs",
        task_id="inert",
    )
    assert adapter.backend.process_isolated is True
    assert adapter.backend.config.worker_options["builder_source_root"] == str(builder.resolve())
    assert not (tmp_path / "runs").exists()


def test_real_workflow_requires_explicit_execution_acknowledgement(tmp_path):
    with pytest.raises(ValueError, match="execute_real_hfss=True"):
        run_real_supplied_demo(
            optimizer_source_root=tmp_path,
            builder_source_root=tmp_path,
            pyaedt_python=Path(__import__("sys").executable),
            contract_path=CONTRACT_PATH,
            execute_real_hfss=False,
        )
