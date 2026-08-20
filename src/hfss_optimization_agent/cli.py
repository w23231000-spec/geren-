"""Minimal CLI and programmatic entry points for the retained presentation workflow."""

from __future__ import annotations

import argparse
import json
import tomllib
import uuid
from pathlib import Path

from .agent.comparison_state import create_comparison_state
from .composition import compose_comparison_workflow
from .core.config import AppConfig, EvaluationConfig
from .core.models import CandidateParameters
from .hfss.contracts import HFSSRunContract, load_hfss_contract
from .hfss.mock_hfss import MockHFSS
from .hfss.pyaedt_composition import compose_pyaedt_hfss
from .optimization.deterministic_batch_optimizer import DeterministicBatchOptimizer
from .optimization.supplied_optimizer_adapter import (
    SuppliedBatchOptimizerAdapter,
    SuppliedOptimizerConfig,
)
from .parameters.nine_parameter_schema import supplied_baseline_candidate, supplied_nine_parameter_schema
from .sparameters.mock_surrogate import DeterministicSurrogate
from .sparameters.supplied_adapter import SuppliedSurrogateAdapter, SuppliedSurrogateConfig


def _summary(final: dict, artifact_root: Path) -> dict:
    baseline_s = final["baseline_sparameter_result"]
    batch = final["optimization_batch"]
    evaluation = final["evaluation_result"]
    return {
        "task_id": final["task_id"],
        "status": final["status"],
        "baseline_sparameter_provider": baseline_s.provider if baseline_s else None,
        "optimizer_run_id": batch.run_id if batch else None,
        "optimized_candidate": (
            final["current_candidate"].candidate_id if final["current_candidate"] else None
        ),
        "hfss_comparison_improved": evaluation.improved if evaluation else None,
        "best_candidate": final["best_candidate"].candidate_id if final["best_candidate"] else None,
        "best_score": final["best_score"],
        "artifact_dir": str(artifact_root / final["task_id"]),
        "trace": final["execution_trace"],
    }


def run_offline_demo(*, artifact_root: Path = Path("runs"), task_id: str | None = None) -> dict:
    """Run the exact production topology with deterministic test-double providers."""

    task_id = task_id or f"offline-{uuid.uuid4().hex[:8]}"
    baseline = supplied_baseline_candidate()
    frequencies_ghz = (1.0, 2.0, 3.0)
    config = AppConfig(artifact_root=artifact_root)
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
    )
    final = compose_comparison_workflow(
        task_id=task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=config,
        sparameters=DeterministicSurrogate(
            baseline.values, tuple(value * 1e9 for value in frequencies_ghz)
        ),
        optimizer=DeterministicBatchOptimizer(),
        hfss=MockHFSS(frequencies_ghz),
    ).invoke(state)
    return _summary(final, artifact_root)


def _supplied_frequency_grid(source_root: Path) -> tuple[float, ...]:
    config = tomllib.loads((source_root / "config" / "config.toml").read_text(encoding="utf-8"))
    frequency = config["frequency"]
    start = float(frequency["start_ghz"]) * 1e9
    stop = float(frequency["stop_ghz"]) * 1e9
    points = int(frequency["points"])
    if points < 2:
        raise ValueError("Supplied frequency grid requires at least two points")
    step = (stop - start) / (points - 1)
    return tuple(start + index * step for index in range(points))


def run_supplied_mock_demo(
    *,
    source_root: Path,
    artifact_root: Path = Path("runs"),
    task_id: str | None = None,
    quick: bool = True,
) -> dict:
    """Run bundled optimizer/surrogate through the production graph with MockHFSS."""

    source_root = source_root.resolve()
    task_id = task_id or f"supplied-mock-{uuid.uuid4().hex[:8]}"
    baseline = supplied_baseline_candidate()
    config = AppConfig(
        artifact_root=artifact_root,
        evaluation=EvaluationConfig(candidate_gate_score=-1.0),
    )
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
    )
    final = compose_comparison_workflow(
        task_id=task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=config,
        sparameters=SuppliedSurrogateAdapter(
            SuppliedSurrogateConfig(
                source_root=source_root,
                frequencies_hz=_supplied_frequency_grid(source_root),
            )
        ),
        optimizer=SuppliedBatchOptimizerAdapter(
            SuppliedOptimizerConfig(
                source_root=source_root,
                output_root=artifact_root / task_id / "optimizer_runs",
                quick=quick,
            )
        ),
        hfss=MockHFSS((1.0, 2.0, 3.0)),
    ).invoke(state)
    return _summary(final, artifact_root)


def _contract_frequency_grid(contract: HFSSRunContract) -> tuple[float, ...]:
    sweep = contract.sweep
    if sweep.spacing != "linear":
        raise ValueError("The current supplied surrogate composition requires a linear HFSS grid")
    step = (sweep.stop_hz - sweep.start_hz) / (sweep.points - 1)
    return tuple(sweep.start_hz + index * step for index in range(sweep.points))


def run_real_supplied_demo(
    *,
    optimizer_source_root: Path,
    builder_source_root: Path,
    pyaedt_python: Path,
    contract_path: Path,
    artifact_root: Path = Path("runs"),
    task_id: str | None = None,
    quick: bool = False,
    solve_timeout_seconds: float = 7200.0,
    execute_real_hfss: bool = False,
    non_graphical: bool = True,
) -> dict:
    """Run baseline and optimized-candidate real HFSS validation."""

    if not execute_real_hfss:
        raise ValueError("Real HFSS execution requires execute_real_hfss=True")
    optimizer_source_root = optimizer_source_root.resolve()
    builder_source_root = builder_source_root.resolve()
    artifact_root = artifact_root.resolve()
    contract = load_hfss_contract(contract_path.resolve())
    if contract.design_name != "interposer_temple4":
        raise ValueError("The approved real workflow may solve only interposer_temple4")
    if contract.metadata.get("build_strategy") != "target_design_only":
        raise ValueError("The real contract must require target-design-only construction")
    schema = supplied_nine_parameter_schema()
    if set(contract.parameter_mapping) != set(schema.by_name):
        raise ValueError("HFSS contract and supplied nine-parameter schema differ")
    task_id = task_id or f"real-supplied-{uuid.uuid4().hex[:8]}"
    baseline = supplied_baseline_candidate()
    config = AppConfig(
        artifact_root=artifact_root,
        evaluation=EvaluationConfig(candidate_gate_score=-1.0),
    )
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
    )
    hfss = compose_pyaedt_hfss(
        contract=contract,
        pyaedt_python=pyaedt_python,
        builder_source_root=builder_source_root,
        artifact_root=artifact_root,
        task_id=task_id,
        solve_timeout_seconds=solve_timeout_seconds,
        non_graphical=non_graphical,
    )
    final = compose_comparison_workflow(
        task_id=task_id,
        baseline_parameters=baseline,
        schema=schema,
        config=config,
        sparameters=SuppliedSurrogateAdapter(
            SuppliedSurrogateConfig(
                source_root=optimizer_source_root,
                frequencies_hz=_contract_frequency_grid(contract),
                reference_impedance_ohm=contract.reference_impedance_ohm,
                comparison_context_id=contract.metadata.get("comparison_context_id"),
                port_order=contract.port_order,
            )
        ),
        optimizer=SuppliedBatchOptimizerAdapter(
            SuppliedOptimizerConfig(
                source_root=optimizer_source_root,
                output_root=artifact_root / task_id / "optimizer_runs",
                quick=quick,
            )
        ),
        hfss=hfss,
    ).invoke(state)
    summary = _summary(final, artifact_root)
    summary.update(
        real_hfss=True,
        hfss_ui_visible=not non_graphical,
        hfss_contract_id=contract.contract_id,
        solved_design=contract.design_name,
        build_strategy=contract.metadata["build_strategy"],
        baseline_project=final["baseline_hfss_result"].project_path,
        candidate_project=(
            final["candidate_hfss_result"].project_path
            if final["candidate_hfss_result"] is not None
            else None
        ),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hfss-optimization-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)
    offline = subparsers.add_parser("offline-demo")
    offline.add_argument("--artifact-root", type=Path, default=Path("runs"))
    offline.add_argument("--task-id")
    supplied = subparsers.add_parser("supplied-mock-demo")
    supplied.add_argument("--source-root", type=Path, required=True)
    supplied.add_argument("--artifact-root", type=Path, default=Path("runs"))
    supplied.add_argument("--task-id")
    supplied.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "offline-demo":
        print(json.dumps(run_offline_demo(artifact_root=args.artifact_root, task_id=args.task_id), indent=2))
        return 0
    if args.command == "supplied-mock-demo":
        print(
            json.dumps(
                run_supplied_mock_demo(
                    source_root=args.source_root,
                    artifact_root=args.artifact_root,
                    task_id=args.task_id,
                    quick=not args.full,
                ),
                indent=2,
            )
        )
        return 0
    return 2
