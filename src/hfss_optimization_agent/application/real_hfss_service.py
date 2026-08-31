"""Application service for the REAL HFSS closed-loop workflow.

This module owns the application-level orchestration around:

OptimizationRequest
→ Development Authorization
→ REAL HFSS Safety Gate
→ LangGraph REAL HFSS workflow

It does not implement GUI behavior and does not launch work at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable

from ..agent.closed_loop_contracts import (
    CLOSED_LOOP_WORKFLOW_ID,
    PRODUCTION_CLOSED_LOOP_POLICY_ID,
    ClosedLoopControllerState,
    production_policy_sha256,
)
from ..agent.comparison_state import create_comparison_state
from ..cli import run_real_supplied_demo
from ..domain.canonical_json import canonical_dumps, canonical_loads
from ..domain.contracts import FrozenMap, canonical_digest
from ..evaluation.contract import (
    PRODUCTION_CONTRACT_ID,
    load_production_evaluation_config,
)
from ..evaluation.model_alignment import load_model_alignment_contract
from ..harness.provenance import source_tree_digest
from ..harness.real_hfss_safety import (
    AUTHORIZATION_MODE_DEVELOPMENT,
    CALIBRATION_STATUS_NOT_PERFORMED,
    DEVELOPMENT_SCHEMA_VERSION,
    HFSS_WORKER_PROTOCOL,
    REAL_HFSS_APPROVAL_SCOPE,
    RealHFSSDevelopmentManifestV1,
    collect_repository_evidence,
    development_execution_from_config,
    file_sha256,
    validate_real_hfss_launch_configuration,
)
from ..harness.run_store import manifest_identity_sha256
from ..hfss.contracts import attest_builder, load_hfss_contract
from ..parameters.nine_parameter_schema import supplied_baseline_candidate
from ..task_request import (
    OptimizationRequest,
    apply_optimization_request_budget,
    validate_request_against_hfss_contract,
)

from .events import RunEvent


@dataclass(frozen=True, slots=True)
class PreparedDevelopmentAuthorization:
    manifest_path: Path
    task_id: str
    expires_at: str
    optimization_request_sha256: str
    max_optimization_rounds: int
    max_hfss_solve_launches: int
    max_candidate_hfss_calls: int
    max_optimizer_calls: int
    max_reoptimizations: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_mode": AUTHORIZATION_MODE_DEVELOPMENT,
            "calibration_status": CALIBRATION_STATUS_NOT_PERFORMED,
            "manifest_path": str(self.manifest_path),
            "task_id": self.task_id,
            "expires_at": self.expires_at,
            "optimization_request_sha256": self.optimization_request_sha256,
            "max_optimization_rounds": self.max_optimization_rounds,
            "max_hfss_solve_launches": self.max_hfss_solve_launches,
            "max_candidate_hfss_calls": self.max_candidate_hfss_calls,
            "max_optimizer_calls": self.max_optimizer_calls,
            "max_reoptimizations": self.max_reoptimizations,
        }


@dataclass(frozen=True, slots=True)
class RealHFSSRuntime:
    configuration: dict[str, Any]
    authorization: Any
    optimization_request: OptimizationRequest

    @property
    def task_id(self) -> str:
        return str(self.authorization.manifest.task_id)


def read_runtime_config(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    return json.loads(
        (root / "runtime_config.json").read_text(encoding="utf-8")
    )


def build_runtime_configuration(
    root: Path,
    optimization_request: OptimizationRequest,
) -> dict[str, Any]:
    raw = read_runtime_config(root)
    return apply_optimization_request_budget(
        raw,
        optimization_request,
    )


def validate_task(
    root: Path,
    optimization_request: OptimizationRequest,
) -> dict[str, Any]:
    """Validate task/configuration without launching AEDT/HFSS."""

    root = Path(root).resolve()
    config = build_runtime_configuration(root, optimization_request)

    contract_path = (root / config["hfss_contract_path"]).resolve()
    evaluation_path = (
        root / "config" / "evaluation_contract.production_v1.json"
    ).resolve()
    alignment_path = (root / config["model_alignment_path"]).resolve()
    pyaedt_python = Path(config["pyaedt_python"]).resolve()

    if not pyaedt_python.is_file():
        raise FileNotFoundError(
            f"PyAEDT Python interpreter does not exist: {pyaedt_python}"
        )

    contract = load_hfss_contract(contract_path)
    validate_request_against_hfss_contract(
        optimization_request,
        contract,
    )

    load_production_evaluation_config(evaluation_path)

    alignment = load_model_alignment_contract(alignment_path)
    if alignment.hfss_contract_id != contract.contract_id:
        raise RuntimeError(
            "Model alignment does not bind the current HFSS contract"
        )

    return config


def prepare_development_authorization(
    root: Path,
    optimization_request: OptimizationRequest,
) -> PreparedDevelopmentAuthorization:
    """Create and validate exact-HEAD Development Authorization.

    This function never launches AEDT/HFSS.
    """

    root = Path(root).resolve()
    config = validate_task(root, optimization_request)

    if config.get("real_hfss_mode") != AUTHORIZATION_MODE_DEVELOPMENT:
        raise RuntimeError(
            "runtime_config.json must set real_hfss_mode to 'development'"
        )

    repository = collect_repository_evidence(root)
    if not repository.working_tree_clean:
        raise RuntimeError(
            "Development authority requires a clean exact Git HEAD"
        )

    contract_path = (root / config["hfss_contract_path"]).resolve()
    evaluation_path = (
        root / "config" / "evaluation_contract.production_v1.json"
    ).resolve()
    alignment_path = (root / config["model_alignment_path"]).resolve()
    optimizer_root = (root / "vendor" / "optimizer").resolve()
    builder_root = (root / "vendor" / "hfss_builder").resolve()
    pyaedt_python = Path(config["pyaedt_python"]).resolve()

    contract = load_hfss_contract(contract_path)
    alignment = load_model_alignment_contract(alignment_path)

    execution_policy, budget = development_execution_from_config(config)

    controller = ClosedLoopControllerState(
        policy_id=PRODUCTION_CLOSED_LOOP_POLICY_ID,
        budget=budget,
    )

    optimizer_digest = source_tree_digest(
        optimizer_root,
        suffixes=(".py", ".csv", ".toml"),
    )

    providers = {
        "agent_source_sha256": repository.agent_source_sha256,
        "supplied_optimizer_source_sha256": optimizer_digest,
        "supplied_surrogate_source_sha256": optimizer_digest,
        "hfss_builder_source_sha256": attest_builder(
            builder_root,
            contract.builder_id,
        ).source_digest,
        "pyaedt_executable_sha256": file_sha256(pyaedt_python),
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(budget),
    }

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")

    task_id = f"real-hfss-development-{stamp}"
    run_id = f"run:{task_id}"
    approval_id = f"approval:{task_id}"
    readiness_id = f"readiness:{task_id}"

    contract_digest = file_sha256(contract_path)
    evaluation_digest = file_sha256(evaluation_path)

    config_fingerprints = {
        "hfss_contract_id": contract.contract_id,
        "hfss_contract_sha256": contract_digest,
        "evaluation_contract_id": PRODUCTION_CONTRACT_ID,
        "evaluation_contract_sha256": evaluation_digest,
        "real_hfss_authorization_id": approval_id,
        "readiness_id": readiness_id,
        "authorization_mode": AUTHORIZATION_MODE_DEVELOPMENT,
        "calibration_status": CALIBRATION_STATUS_NOT_PERFORMED,
        "model_alignment_sha256": alignment.digest,
        "closed_loop_policy_id": controller.policy_id,
        "closed_loop_budget": canonical_loads(
            canonical_dumps(controller.budget)
        ),
        "optimization_request_sha256": optimization_request.digest,
        "max_optimization_rounds": (
            optimization_request.max_optimization_rounds
        ),
    }

    baseline = supplied_baseline_candidate()

    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification=(
            optimization_request.to_target_specification()
        ),
        evaluation_contract_id=PRODUCTION_CONTRACT_ID,
        comparison_context_id=alignment.comparison_context_id,
        run_id=run_id,
        created_at=now.isoformat(),
        code_revision=repository.git_head,
        real_execution=True,
        provider_fingerprints=providers,
        config_fingerprints=config_fingerprints,
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )

    manifest = RealHFSSDevelopmentManifestV1(
        schema_version=DEVELOPMENT_SCHEMA_VERSION,
        authorization_mode=AUTHORIZATION_MODE_DEVELOPMENT,
        calibration_status=CALIBRATION_STATUS_NOT_PERFORMED,
        readiness_id=readiness_id,
        task_id=task_id,
        run_id=run_id,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        comparison_context_id=alignment.comparison_context_id,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=8)).isoformat(),
        git_head=repository.git_head,
        agent_source_sha256=repository.agent_source_sha256,
        run_manifest_sha256=manifest_identity_sha256(
            state["manifest"]
        ),
        design_goal_sha256=canonical_digest(
            state["manifest"].design_goal
        ),
        hfss_contract_sha256=contract_digest,
        evaluation_contract_sha256=evaluation_digest,
        model_alignment_sha256=alignment.digest,
        provider_fingerprints=FrozenMap.from_mapping(providers),
        approval_id=approval_id,
        approval_scope=REAL_HFSS_APPROVAL_SCOPE,
        execution_policy=execution_policy,
        closed_loop_budget=budget,
    )

    path = (
        root
        / "runs"
        / "authorizations"
        / f"{task_id}.json"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        canonical_dumps(manifest).encode("utf-8")
    )

    validation_config = dict(config)
    validation_config["real_hfss_enabled"] = True
    validation_config["real_hfss_readiness_manifest"] = str(path)

    validate_real_hfss_launch_configuration(
        validation_config,
        repository_root=root,
    )

    return PreparedDevelopmentAuthorization(
        manifest_path=path,
        task_id=task_id,
        expires_at=manifest.expires_at,
        optimization_request_sha256=optimization_request.digest,
        max_optimization_rounds=(
            optimization_request.max_optimization_rounds
        ),
        max_hfss_solve_launches=(
            execution_policy.max_hfss_solve_launches
        ),
        max_candidate_hfss_calls=budget.max_candidate_hfss_calls,
        max_optimizer_calls=budget.max_optimizer_calls,
        max_reoptimizations=budget.max_reoptimizations,
    )


def validate_real_hfss_runtime(
    root: Path,
    optimization_request: OptimizationRequest,
    readiness_manifest_path: Path | str | None,
) -> RealHFSSRuntime:
    """Validate a prepared REAL HFSS runtime without solving."""

    root = Path(root).resolve()
    configuration = build_runtime_configuration(
        root,
        optimization_request,
    )

    if readiness_manifest_path is not None:
        configuration["real_hfss_enabled"] = True
        configuration["real_hfss_readiness_manifest"] = str(
            readiness_manifest_path
        )

    authorization = validate_real_hfss_launch_configuration(
        configuration,
        repository_root=root,
    )

    interpreter = Path(configuration["pyaedt_python"])
    if not interpreter.is_file():
        raise FileNotFoundError(
            f"PyAEDT Python interpreter does not exist: {interpreter}"
        )

    return RealHFSSRuntime(
        configuration=configuration,
        authorization=authorization,
        optimization_request=optimization_request,
    )


def execute_real_hfss(
    root: Path,
    runtime: RealHFSSRuntime,
) -> dict[str, Any]:
    """Execute the already validated REAL HFSS workflow."""

    root = Path(root).resolve()
    configuration = runtime.configuration
    optimization_request = runtime.optimization_request

    return run_real_supplied_demo(
        optimizer_source_root=root / "vendor" / "optimizer",
        builder_source_root=root / "vendor" / "hfss_builder",
        pyaedt_python=Path(configuration["pyaedt_python"]),
        contract_path=(
            root
            / "config"
            / "hfss_contract.pa_multi_2025_1.json"
        ),
        evaluation_contract_path=(
            root
            / "config"
            / "evaluation_contract.production_v1.json"
        ),
        artifact_root=Path(configuration["artifact_root"]),
        task_id=runtime.task_id,
        quick=bool(configuration.get("quick_optimizer", True)),
        solve_timeout_seconds=float(
            configuration.get("solve_timeout_seconds", 7200.0)
        ),
        execute_real_hfss=True,
        readiness_authorization=runtime.authorization,
        non_graphical=not bool(
            configuration.get("hfss_ui_visible", True)
        ),
        optimization_request=optimization_request,
    )



@dataclass(frozen=True, slots=True)
class RealHFSSRunResult:
    request_path: Path
    authorization: PreparedDevelopmentAuthorization
    summary: dict[str, Any]

    @property
    def task_id(self) -> str:
        return self.authorization.task_id

    @property
    def status(self) -> str:
        return str(self.summary.get("status", "UNKNOWN"))


RunEventCallback = Callable[[RunEvent], None]


def _emit_run_event(
    callback: RunEventCallback | None,
    *,
    event_type: str,
    stage: str,
    message: str,
    detail: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if callback is None:
        return

    callback(
        RunEvent(
            event_type=event_type,
            stage=stage,
            message=message,
            detail=detail,
            payload=payload,
        )
    )


def persist_optimization_request(
    root: Path,
    optimization_request: OptimizationRequest,
) -> Path:
    """Persist the exact task snapshot used for one REAL HFSS run."""

    root = Path(root).resolve()

    stamp = datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )

    path = (
        root
        / "runs"
        / "requests"
        / f"optimization-request-{stamp}.json"
    )

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_bytes(
        canonical_dumps(
            optimization_request.to_dict()
        ).encode("utf-8")
    )

    return path


def run_real_hfss_task(
    root: Path,
    optimization_request: OptimizationRequest,
    *,
    on_event: RunEventCallback | None = None,
) -> RealHFSSRunResult:
    """Execute one complete application-level REAL HFSS task.

    The task is:

    validate
    → persist request
    → Development Authorization
    → Safety Gate
    → REAL HFSS workflow
    """

    root = Path(root).resolve()

    try:
        _emit_run_event(
            on_event,
            event_type="stage",
            stage="validation",
            message="正在校验优化任务与运行配置",
        )

        validate_task(
            root,
            optimization_request,
        )

        _emit_run_event(
            on_event,
            event_type="success",
            stage="validation",
            message="任务与运行配置校验通过",
            detail=optimization_request.digest[:12],
        )

        request_path = persist_optimization_request(
            root,
            optimization_request,
        )

        _emit_run_event(
            on_event,
            event_type="success",
            stage="request",
            message="本次 OptimizationRequest 已固化",
            detail=str(request_path),
        )

        _emit_run_event(
            on_event,
            event_type="stage",
            stage="authorization",
            message="正在生成 Development Authorization",
        )

        prepared = prepare_development_authorization(
            root,
            optimization_request,
        )

        _emit_run_event(
            on_event,
            event_type="success",
            stage="authorization",
            message="Development Authorization 已生成",
            detail=prepared.task_id,
        )

        _emit_run_event(
            on_event,
            event_type="stage",
            stage="safety_gate",
            message="正在执行 REAL HFSS Safety Gate",
        )

        runtime = validate_real_hfss_runtime(
            root,
            optimization_request,
            prepared.manifest_path,
        )

        _emit_run_event(
            on_event,
            event_type="success",
            stage="safety_gate",
            message="REAL HFSS Safety Gate 通过",
            detail=runtime.task_id,
        )

        _emit_run_event(
            on_event,
            event_type="stage",
            stage="workflow",
            message="开始执行 REAL HFSS closed loop",
            detail=(
                f"Candidate HFSS maximum = "
                f"{optimization_request.max_optimization_rounds}"
            ),
        )

        summary = execute_real_hfss(
            root,
            runtime,
        )

        result = RealHFSSRunResult(
            request_path=request_path,
            authorization=prepared,
            summary=summary,
        )

        _emit_run_event(
            on_event,
            event_type="complete",
            stage="workflow",
            message="REAL HFSS closed loop 已结束",
            detail=result.status,
            payload={
                "task_id": result.task_id,
                "status": result.status,
                "request_path": str(result.request_path),
            },
        )

        return result

    except Exception as exc:
        _emit_run_event(
            on_event,
            event_type="error",
            stage="application",
            message="REAL HFSS 任务执行失败",
            detail=f"{type(exc).__name__}: {exc}",
        )
        raise
