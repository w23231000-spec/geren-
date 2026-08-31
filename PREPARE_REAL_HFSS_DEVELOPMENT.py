"""Create exact-HEAD uncalibrated Development authority.

Never launches AEDT/HFSS.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.agent.closed_loop_contracts import (  # noqa: E402
    CLOSED_LOOP_WORKFLOW_ID,
    PRODUCTION_CLOSED_LOOP_POLICY_ID,
    ClosedLoopControllerState,
    production_policy_sha256,
)
from hfss_optimization_agent.agent.comparison_state import (  # noqa: E402
    create_comparison_state,
)
from hfss_optimization_agent.domain.canonical_json import (  # noqa: E402
    canonical_dumps,
    canonical_loads,
)
from hfss_optimization_agent.domain.contracts import (  # noqa: E402
    FrozenMap,
    canonical_digest,
)
from hfss_optimization_agent.evaluation.contract import (  # noqa: E402
    PRODUCTION_CONTRACT_ID,
    load_production_evaluation_config,
)
from hfss_optimization_agent.evaluation.model_alignment import (  # noqa: E402
    load_model_alignment_contract,
)
from hfss_optimization_agent.harness.provenance import (  # noqa: E402
    source_tree_digest,
)
from hfss_optimization_agent.harness.real_hfss_safety import (  # noqa: E402
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
from hfss_optimization_agent.harness.run_store import (  # noqa: E402
    manifest_identity_sha256,
)
from hfss_optimization_agent.hfss.contracts import (  # noqa: E402
    attest_builder,
    load_hfss_contract,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (  # noqa: E402
    supplied_baseline_candidate,
)
from hfss_optimization_agent.task_request import (  # noqa: E402
    apply_optimization_request_budget,
    load_runtime_optimization_request,
    validate_request_against_hfss_contract,
)


def main() -> Path:
    config_path = ROOT / "runtime_config.json"
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    optimization_request = load_runtime_optimization_request(
        ROOT, raw_config
    )
    config = apply_optimization_request_budget(
        raw_config, optimization_request
    )

    if config.get("real_hfss_mode") != AUTHORIZATION_MODE_DEVELOPMENT:
        raise RuntimeError(
            "runtime_config.json must set real_hfss_mode to 'development'"
        )

    repository = collect_repository_evidence(ROOT)
    if not repository.working_tree_clean:
        raise RuntimeError(
            "Development authority requires a clean exact Git HEAD"
        )

    contract_path = (ROOT / config["hfss_contract_path"]).resolve()
    evaluation_path = (
        ROOT / "config" / "evaluation_contract.production_v1.json"
    ).resolve()
    alignment_path = (ROOT / config["model_alignment_path"]).resolve()
    optimizer_root = (ROOT / "vendor" / "optimizer").resolve()
    builder_root = (ROOT / "vendor" / "hfss_builder").resolve()
    pyaedt_python = Path(config["pyaedt_python"]).resolve()

    if not pyaedt_python.is_file():
        raise FileNotFoundError(
            f"PyAEDT Python interpreter does not exist: {pyaedt_python}"
        )

    contract = load_hfss_contract(contract_path)
    validate_request_against_hfss_contract(optimization_request, contract)
    load_production_evaluation_config(evaluation_path)
    alignment = load_model_alignment_contract(alignment_path)
    if alignment.hfss_contract_id != contract.contract_id:
        raise RuntimeError(
            "Model alignment does not bind the current HFSS contract"
        )

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
        run_manifest_sha256=manifest_identity_sha256(state["manifest"]),
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
        ROOT
        / "runs"
        / "authorizations"
        / f"{task_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(manifest).encode("utf-8"))

    validation_config = dict(config)
    validation_config["real_hfss_enabled"] = True
    validation_config["real_hfss_readiness_manifest"] = str(path)
    validate_real_hfss_launch_configuration(
        validation_config,
        repository_root=ROOT,
    )

    print(
        json.dumps(
            {
                "authorization_mode": AUTHORIZATION_MODE_DEVELOPMENT,
                "calibration_status": CALIBRATION_STATUS_NOT_PERFORMED,
                "manifest_path": str(path),
                "task_id": task_id,
                "expires_at": manifest.expires_at,
                "optimization_request_sha256": optimization_request.digest,
                "max_optimization_rounds": (
                    optimization_request.max_optimization_rounds
                ),
                "max_hfss_solve_launches": (
                    execution_policy.max_hfss_solve_launches
                ),
                "max_candidate_hfss_calls": (
                    budget.max_candidate_hfss_calls
                ),
                "max_optimizer_calls": budget.max_optimizer_calls,
                "max_reoptimizations": budget.max_reoptimizations,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return path


if __name__ == "__main__":
    main()
