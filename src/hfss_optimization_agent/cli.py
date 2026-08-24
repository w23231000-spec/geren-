"""CLI and programmatic entries for the authoritative Closed-loop V2 Agent."""

from __future__ import annotations

import argparse
import json
import tomllib
import uuid
from pathlib import Path

from .agent.comparison_state import (
    baseline_hfss_result,
    baseline_sparameter_result,
    best_candidate,
    best_score,
    candidate_hfss_result,
    current_candidate,
    current_comparison,
    optimization_batch,
    state_task_id,
    create_comparison_state,
)
from .agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    ClosedLoopBudget,
    ClosedLoopControllerState,
    production_policy_sha256,
)
from .composition import compose_closed_loop_workflow
from .core.config import AppConfig
from .core.enums import workflow_exit_code
from .core.models import CandidateParameters
from .evaluation.contract import (
    OFFLINE_CONTRACT_ID,
    PRODUCTION_CONTRACT_ID,
    load_offline_evaluation_config,
    load_production_evaluation_config,
)
from .hfss.contracts import HFSSRunContract, attest_builder, load_hfss_contract
from .hfss.mock_hfss import MockHFSS
from .hfss.pyaedt_composition import compose_pyaedt_hfss
from .harness.core import HarnessSettings
from .domain.canonical_json import canonical_dumps, canonical_loads
from .domain.contracts import canonical_digest
from .harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    RealHFSSAuthorization,
    file_sha256,
    validate_real_hfss_workflow_binding,
)
from .harness.run_store import ApprovalGrant, manifest_identity_sha256
from .harness.provenance import source_tree_digest
from .optimization.deterministic_batch_optimizer import DeterministicBatchOptimizer
from .optimization.supplied_optimizer_adapter import (
    SuppliedBatchOptimizerAdapter,
    SuppliedOptimizerConfig,
)
from .parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
    supplied_nine_parameter_schema,
)
from .sparameters.mock_surrogate import DeterministicSurrogate
from .sparameters.supplied_adapter import SuppliedSurrogateAdapter, SuppliedSurrogateConfig


def _summary(final: dict, artifact_root: Path) -> dict:
    task_id = state_task_id(final)
    baseline_s = baseline_sparameter_result(final)
    batch = optimization_batch(final)
    comparison = current_comparison(final)
    terminal = final.get("terminal_outcome")
    optimized = current_candidate(final)
    selected_best = best_candidate(final)
    controller = final.get("controller")
    return {
        "task_id": task_id,
        "run_id": final["manifest"].run_id,
        "state_schema_version": final["schema_version"],
        "status": final["status"],
        "baseline_sparameter_provider": baseline_s.provider if baseline_s else None,
        "optimizer_run_id": batch.run_id if batch else None,
        "optimized_candidate": optimized.candidate_id if optimized else None,
        "hfss_comparison_improved": comparison.promotion_eligible if comparison else None,
        "hfss_comparison_classification": comparison.classification if comparison else None,
        "terminal_reason_code": terminal.reason_code if terminal else None,
        "terminal_reason": terminal.reason if terminal else None,
        "best_candidate": selected_best.candidate_id if selected_best else None,
        "best_score": best_score(final),
        "artifact_dir": str(artifact_root / task_id),
        "trace": list(final["execution_trace"]),
        "controller": (
            {
                "iterations": controller.controller_iterations,
                "optimizer_calls": controller.optimizer_calls,
                "candidate_screenings": controller.candidate_screenings,
                "candidate_hfss_calls": controller.candidate_hfss_calls,
                "reoptimizations": controller.reoptimizations,
                "safe_retries": controller.safe_retries,
                "stagnation_count": controller.stagnation_count,
                "consumed_candidate_ids": list(controller.consumed_candidate_ids),
                "decisions": [
                    {
                        "iteration": item.iteration,
                        "action": item.action,
                        "reason_code": item.reason_code,
                        "candidate_id": item.candidate_id,
                    }
                    for item in controller.decisions
                ],
            }
            if controller is not None
            else None
        ),
    }


def run_offline_demo(
    *, artifact_root: Path = Path("runs"), task_id: str | None = None
) -> dict:
    """Run the canonical Closed-loop V2 topology with deterministic providers."""

    return run_closed_loop_offline_demo(artifact_root=artifact_root, task_id=task_id)


def _supplied_frequency_grid(source_root: Path) -> tuple[float, ...]:
    config = tomllib.loads(
        (source_root / "config" / "config.toml").read_text(encoding="utf-8")
    )
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
    """Run supplied Tools through the canonical Closed-loop V2 topology."""

    return run_closed_loop_supplied_mock_demo(
        source_root=source_root,
        artifact_root=artifact_root,
        task_id=task_id,
        quick=quick,
    )


def run_closed_loop_offline_demo(
    *,
    artifact_root: Path = Path("runs"),
    task_id: str | None = None,
    budget: ClosedLoopBudget | None = None,
) -> dict:
    """Run the opt-in bounded V2 Agent with deterministic fake providers."""

    task_id = task_id or f"closed-loop-offline-{uuid.uuid4().hex[:8]}"
    baseline = supplied_baseline_candidate()
    frequencies_ghz = (1.0, 2.0, 3.0)
    offline_evaluation = load_offline_evaluation_config(
        Path(__file__).resolve().parents[2]
        / "config"
        / "evaluation_contract.offline_v1.json"
    )
    config = AppConfig(
        artifact_root=artifact_root,
        evaluation=offline_evaluation,
        closed_loop_enabled=True,
    )
    controller = ClosedLoopControllerState.initial(budget or ClosedLoopBudget())
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=OFFLINE_CONTRACT_ID,
        provider_fingerprints={
            "optimizer": "deterministic-optimizer-request-v1",
            "surrogate": "deterministic-surrogate-v1",
            "hfss": "mock-hfss-v1",
            "controller": controller.policy_id,
        },
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )
    final = compose_closed_loop_workflow(
        task_id=task_id,
        baseline_parameters=baseline,
        schema=supplied_nine_parameter_schema(),
        config=config,
        sparameters=DeterministicSurrogate(
            baseline.values, tuple(value * 1e9 for value in frequencies_ghz)
        ),
        optimizer=DeterministicBatchOptimizer(),
        hfss=MockHFSS(frequencies_ghz, baseline.values),
        recursion_limit=2 * controller.budget.max_controller_iterations + 16,
    ).invoke(state)
    return _summary(final, artifact_root)


def run_closed_loop_supplied_mock_demo(
    *,
    source_root: Path,
    artifact_root: Path = Path("runs"),
    task_id: str | None = None,
    quick: bool = True,
    budget: ClosedLoopBudget | None = None,
) -> dict:
    """Run the supervised supplied optimizer/surrogate in the bounded V2 Agent."""

    source_root = source_root.resolve()
    task_id = task_id or f"closed-loop-supplied-{uuid.uuid4().hex[:8]}"
    baseline = supplied_baseline_candidate()
    offline_evaluation = load_offline_evaluation_config(
        Path(__file__).resolve().parents[2]
        / "config"
        / "evaluation_contract.offline_v1.json"
    )
    offline_evaluation.candidate_gate_score = -1.0
    config = AppConfig(
        artifact_root=artifact_root,
        evaluation=offline_evaluation,
        closed_loop_enabled=True,
    )
    controller = ClosedLoopControllerState.initial(budget or ClosedLoopBudget())
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=OFFLINE_CONTRACT_ID,
        provider_fingerprints={
            "supplied_optimizer_source_sha256": source_tree_digest(
                source_root, suffixes=(".py", ".csv", ".toml")
            ),
            "supplied_surrogate_source_sha256": source_tree_digest(
                source_root, suffixes=(".py", ".csv", ".toml")
            ),
            "hfss": "mock-hfss-v1",
            "controller": controller.policy_id,
        },
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )
    final = compose_closed_loop_workflow(
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
        hfss=MockHFSS((1.0, 2.0, 3.0), baseline.values),
        recursion_limit=2 * controller.budget.max_controller_iterations + 16,
    ).invoke(state)
    return _summary(final, artifact_root)


def _contract_frequency_grid(contract: HFSSRunContract) -> tuple[float, ...]:
    sweep = contract.sweep
    if sweep.spacing != "linear":
        raise ValueError(
            "The current supplied surrogate composition requires a linear HFSS grid"
        )
    step = (sweep.stop_hz - sweep.start_hz) / (sweep.points - 1)
    return tuple(sweep.start_hz + index * step for index in range(sweep.points))


def run_real_supplied_demo(
    *,
    optimizer_source_root: Path,
    builder_source_root: Path,
    pyaedt_python: Path,
    contract_path: Path,
    evaluation_contract_path: Path | None = None,
    artifact_root: Path = Path("runs"),
    task_id: str | None = None,
    quick: bool = False,
    solve_timeout_seconds: float = 7200.0,
    execute_real_hfss: bool = False,
    readiness_authorization: RealHFSSAuthorization | None = None,
    non_graphical: bool = True,
) -> dict:
    """Run the readiness-bound Production Closed-loop V2 Agent."""

    if not execute_real_hfss:
        raise ValueError("Real HFSS execution requires execute_real_hfss=True")
    if readiness_authorization is None:
        raise ValueError("Real HFSS execution requires a validated readiness authorization")
    readiness = readiness_authorization.manifest
    if task_id is not None and task_id != readiness.task_id:
        raise ValueError("requested task_id does not match the readiness manifest")
    optimizer_source_root = optimizer_source_root.resolve()
    builder_source_root = builder_source_root.resolve()
    artifact_root = artifact_root.resolve()
    contract = load_hfss_contract(contract_path.resolve())
    if evaluation_contract_path is None:
        raise ValueError("WF-001 requires Production Evaluation Contract v1")
    production_evaluation = load_production_evaluation_config(
        evaluation_contract_path.resolve()
    )
    if contract.design_name != "interposer_temple4":
        raise ValueError("The approved real workflow may solve only interposer_temple4")
    if contract.metadata.get("build_strategy") != "target_design_only":
        raise ValueError("The real contract must require target-design-only construction")
    schema = supplied_nine_parameter_schema()
    if set(contract.parameter_mapping) != set(schema.by_name):
        raise ValueError("HFSS contract and supplied nine-parameter schema differ")

    task_id = readiness.task_id
    baseline = supplied_baseline_candidate()
    controller = ClosedLoopControllerState.production_canary()
    builder_attestation = attest_builder(builder_source_root, contract.builder_id)
    optimizer_source_digest = source_tree_digest(
        optimizer_source_root, suffixes=(".py", ".csv", ".toml")
    )
    agent_source_digest = source_tree_digest(
        Path(__file__).resolve().parents[1], suffixes=(".py",)
    )
    provider_fingerprints = {
        "agent_source_sha256": agent_source_digest,
        "supplied_optimizer_source_sha256": optimizer_source_digest,
        "supplied_surrogate_source_sha256": optimizer_source_digest,
        "hfss_builder_source_sha256": builder_attestation.source_digest,
        "pyaedt_executable_sha256": file_sha256(pyaedt_python),
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }
    hfss_contract_digest = file_sha256(contract_path.resolve())
    evaluation_contract_digest = file_sha256(evaluation_contract_path.resolve())
    config = AppConfig(
        artifact_root=artifact_root,
        closed_loop_enabled=True,
        evaluation=production_evaluation,
        harness=HarnessSettings(
            execution_policy=readiness.execution_policy,
            required_approval_scopes={"hfss": "real_hfss"},
            approvals=(
                ApprovalGrant(
                    approval_id=readiness.approval_id,
                    scope="real_hfss",
                    granted_by=f"readiness_manifest:{readiness.readiness_id}",
                    expires_at=readiness.expires_at,
                ),
            ),
        ),
    )
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=PRODUCTION_CONTRACT_ID,
        comparison_context_id=(
            contract.metadata.get("comparison_context_id")
            or f"{contract.contract_id}:{contract.design_name}"
        ),
        run_id=readiness.run_id,
        created_at=readiness.created_at,
        code_revision=readiness_authorization.repository.git_head,
        real_execution=True,
        provider_fingerprints=provider_fingerprints,
        config_fingerprints={
            "hfss_contract_id": contract.contract_id,
            "hfss_contract_sha256": hfss_contract_digest,
            "evaluation_contract_id": PRODUCTION_CONTRACT_ID,
            "evaluation_contract_sha256": evaluation_contract_digest,
            "real_hfss_authorization_id": readiness.approval_id,
            "readiness_id": readiness.readiness_id,
            "calibration_evidence_sha256": readiness.calibration_evidence.digest,
            "calibration_evidence": canonical_loads(
                canonical_dumps(readiness.calibration_evidence)
            ),
            "closed_loop_policy_id": controller.policy_id,
            "closed_loop_budget": canonical_loads(canonical_dumps(controller.budget)),
        },
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )
    validate_real_hfss_workflow_binding(
        readiness_authorization,
        run_manifest_sha256=manifest_identity_sha256(state["manifest"]),
        design_goal_sha256=canonical_digest(state["manifest"].design_goal),
        hfss_contract_sha256=hfss_contract_digest,
        evaluation_contract_sha256=evaluation_contract_digest,
        provider_fingerprints=provider_fingerprints,
        task_id=task_id,
        run_id=state["manifest"].run_id,
        workflow_id=state["manifest"].workflow_id,
        comparison_context_id=state["manifest"].design_goal.comparison_context_id,
        calibration_evidence_sha256=readiness.calibration_evidence.digest,
    )

    hfss = compose_pyaedt_hfss(
        contract=contract,
        pyaedt_python=pyaedt_python,
        builder_source_root=builder_source_root,
        artifact_root=artifact_root,
        task_id=task_id,
        solve_timeout_seconds=solve_timeout_seconds,
        non_graphical=non_graphical,
        builder_attestation=builder_attestation,
    )
    final = compose_closed_loop_workflow(
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
        recursion_limit=2 * controller.budget.max_controller_iterations + 16,
        allow_real_execution=True,
    ).invoke(state)
    summary = _summary(final, artifact_root)
    summary.update(
        real_hfss=True,
        hfss_ui_visible=not non_graphical,
        hfss_contract_id=contract.contract_id,
        solved_design=contract.design_name,
        build_strategy=contract.metadata["build_strategy"],
        baseline_project=baseline_hfss_result(final).project_path,
        candidate_project=(
            candidate_hfss_result(final).project_path
            if candidate_hfss_result(final) is not None
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
    closed_offline = subparsers.add_parser("closed-loop-offline-demo")
    closed_offline.add_argument("--artifact-root", type=Path, default=Path("runs"))
    closed_offline.add_argument("--task-id")
    closed_supplied = subparsers.add_parser("closed-loop-supplied-mock-demo")
    closed_supplied.add_argument("--source-root", type=Path, required=True)
    closed_supplied.add_argument("--artifact-root", type=Path, default=Path("runs"))
    closed_supplied.add_argument("--task-id")
    closed_supplied.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "offline-demo":
        summary = run_offline_demo(
            artifact_root=args.artifact_root, task_id=args.task_id
        )
        print(json.dumps(summary, indent=2))
        return workflow_exit_code(summary["status"])
    if args.command == "supplied-mock-demo":
        summary = run_supplied_mock_demo(
            source_root=args.source_root,
            artifact_root=args.artifact_root,
            task_id=args.task_id,
            quick=not args.full,
        )
        print(json.dumps(summary, indent=2))
        return workflow_exit_code(summary["status"])
    if args.command == "closed-loop-offline-demo":
        summary = run_closed_loop_offline_demo(
            artifact_root=args.artifact_root, task_id=args.task_id
        )
        print(json.dumps(summary, indent=2))
        return workflow_exit_code(summary["status"])
    if args.command == "closed-loop-supplied-mock-demo":
        summary = run_closed_loop_supplied_mock_demo(
            source_root=args.source_root,
            artifact_root=args.artifact_root,
            task_id=args.task_id,
            quick=not args.full,
        )
        print(json.dumps(summary, indent=2))
        return workflow_exit_code(summary["status"])
    return 2
