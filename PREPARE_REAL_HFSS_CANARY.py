"""Create an exact-HEAD, short-lived two-solve Canary authority; never launches AEDT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.agent.closed_loop_contracts import (  # noqa: E402
    CLOSED_LOOP_WORKFLOW_ID,
    ClosedLoopControllerState,
    production_policy_sha256,
)
from hfss_optimization_agent.agent.comparison_state import create_comparison_state  # noqa: E402
from hfss_optimization_agent.domain.canonical_json import (  # noqa: E402
    canonical_dumps,
    canonical_loads,
)
from hfss_optimization_agent.domain.contracts import (  # noqa: E402
    CalibrationEvidence,
    FrozenMap,
    calibration_policy_sha256,
    canonical_digest,
)
from hfss_optimization_agent.evaluation.contract import (  # noqa: E402
    PRODUCTION_CONTRACT_ID,
    load_production_evaluation_config,
)
from hfss_optimization_agent.evaluation.model_alignment import (  # noqa: E402
    load_model_alignment_contract,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy  # noqa: E402
from hfss_optimization_agent.harness.provenance import source_tree_digest  # noqa: E402
from hfss_optimization_agent.harness.real_hfss_safety import (  # noqa: E402
    HFSS_WORKER_PROTOCOL,
    READINESS_SCHEMA_VERSION,
    REAL_HFSS_APPROVAL_SCOPE,
    RealHFSSReadinessManifestV1,
    collect_repository_evidence,
    file_sha256,
    validate_real_hfss_launch_configuration,
)
from hfss_optimization_agent.harness.run_store import manifest_identity_sha256  # noqa: E402
from hfss_optimization_agent.hfss.contracts import attest_builder, load_hfss_contract  # noqa: E402
from hfss_optimization_agent.parameters.nine_parameter_schema import (  # noqa: E402
    supplied_baseline_candidate,
)


def _evidence_path() -> Path:
    raw = os.environ.get("HFSS_CALIBRATION_EVIDENCE")
    if not raw:
        raise RuntimeError(
            "Set HFSS_CALIBRATION_EVIDENCE to the passing immutable evidence JSON"
        )
    return Path(raw).resolve()


def main() -> Path:
    config_path = ROOT / "runtime_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    repository = collect_repository_evidence(ROOT)
    if not repository.working_tree_clean:
        raise RuntimeError("Canary authority requires a clean exact Git HEAD")

    evidence = CalibrationEvidence.from_dict(
        canonical_loads(_evidence_path().read_text(encoding="utf-8"))
    )
    if not evidence.passed:
        raise RuntimeError("Canary authority requires passing Calibration Evidence")

    contract_path = (ROOT / config["hfss_contract_path"]).resolve()
    evaluation_path = (ROOT / "config" / "evaluation_contract.production_v1.json").resolve()
    policy_path = (ROOT / config["calibration_policy_path"]).resolve()
    alignment_path = (ROOT / config["model_alignment_path"]).resolve()
    optimizer_root = (ROOT / "vendor" / "optimizer").resolve()
    builder_root = (ROOT / "vendor" / "hfss_builder").resolve()
    pyaedt_python = Path(config["pyaedt_python"]).resolve()

    contract = load_hfss_contract(contract_path)
    load_production_evaluation_config(evaluation_path)
    alignment = load_model_alignment_contract(alignment_path)
    policy_payload = canonical_loads(policy_path.read_text(encoding="utf-8"))
    policy_digest = calibration_policy_sha256(policy_payload)
    if alignment.hfss_contract_id != contract.contract_id:
        raise RuntimeError("Model alignment does not bind the current HFSS contract")
    if evidence.hfss_contract_sha256 != file_sha256(contract_path):
        raise RuntimeError("Calibration Evidence does not bind the current HFSS contract")
    if evidence.policy_sha256 != policy_digest:
        raise RuntimeError("Calibration Evidence does not bind the current policy")
    if evidence.comparison_context_id != alignment.comparison_context_id:
        raise RuntimeError("Calibration Evidence does not bind the approved model context")

    providers = {
        "agent_source_sha256": repository.agent_source_sha256,
        "supplied_optimizer_source_sha256": source_tree_digest(
            optimizer_root, suffixes=(".py", ".csv", ".toml")
        ),
        "supplied_surrogate_source_sha256": source_tree_digest(
            optimizer_root, suffixes=(".py", ".csv", ".toml")
        ),
        "hfss_builder_source_sha256": attest_builder(
            builder_root, contract.builder_id
        ).source_digest,
        "pyaedt_executable_sha256": file_sha256(pyaedt_python),
        "hfss_worker_protocol": HFSS_WORKER_PROTOCOL,
        "closed_loop_policy_sha256": production_policy_sha256(),
    }
    controller = ClosedLoopControllerState.production_canary()
    baseline = supplied_baseline_candidate()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    task_id = f"real-hfss-canary-{stamp}"
    run_id = f"run:{task_id}"
    contract_digest = file_sha256(contract_path)
    evaluation_digest = file_sha256(evaluation_path)
    approval_id = f"approval:{task_id}"
    readiness_id = f"readiness:{task_id}"
    state = create_comparison_state(
        task_id=task_id,
        baseline_parameters=baseline,
        target_specification={"minimum_score": -1.0},
        evaluation_contract_id=PRODUCTION_CONTRACT_ID,
        comparison_context_id=alignment.comparison_context_id,
        run_id=run_id,
        created_at=now.isoformat(),
        code_revision=repository.git_head,
        real_execution=True,
        provider_fingerprints=providers,
        config_fingerprints={
            "hfss_contract_id": contract.contract_id,
            "hfss_contract_sha256": contract_digest,
            "evaluation_contract_id": PRODUCTION_CONTRACT_ID,
            "evaluation_contract_sha256": evaluation_digest,
            "real_hfss_authorization_id": approval_id,
            "readiness_id": readiness_id,
            "calibration_evidence_sha256": evidence.digest,
            "model_alignment_sha256": alignment.digest,
            "calibration_policy_sha256": policy_digest,
            "calibration_artifact_manifest_sha256": (
                evidence.source_artifact_manifest_sha256
            ),
            "calibration_evidence": canonical_loads(canonical_dumps(evidence)),
            "closed_loop_policy_id": controller.policy_id,
            "closed_loop_budget": canonical_loads(canonical_dumps(controller.budget)),
        },
        controller=controller,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
    )
    manifest = RealHFSSReadinessManifestV1(
        schema_version=READINESS_SCHEMA_VERSION,
        readiness_id=readiness_id,
        task_id=task_id,
        run_id=run_id,
        workflow_id=CLOSED_LOOP_WORKFLOW_ID,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=8)).isoformat(),
        git_head=repository.git_head,
        agent_source_sha256=repository.agent_source_sha256,
        run_manifest_sha256=manifest_identity_sha256(state["manifest"]),
        design_goal_sha256=canonical_digest(state["manifest"].design_goal),
        hfss_contract_sha256=contract_digest,
        evaluation_contract_sha256=evaluation_digest,
        model_alignment_sha256=alignment.digest,
        calibration_policy_sha256=policy_digest,
        calibration_artifact_manifest_sha256=(
            evidence.source_artifact_manifest_sha256
        ),
        provider_fingerprints=FrozenMap.from_mapping(providers),
        approval_id=approval_id,
        approval_scope=REAL_HFSS_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(2, 0),
        calibration_evidence=evidence,
    )
    path = ROOT / "runs" / "authorizations" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(manifest).encode("utf-8"))

    validation_config = dict(config)
    validation_config["real_hfss_enabled"] = True
    validation_config["real_hfss_readiness_manifest"] = str(path)
    validate_real_hfss_launch_configuration(validation_config, repository_root=ROOT)
    print(path)
    return path


if __name__ == "__main__":
    main()
