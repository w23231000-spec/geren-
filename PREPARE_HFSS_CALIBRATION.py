"""Create a short-lived, exact-HEAD Calibration collection authority; never launches AEDT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.agent.closed_loop_contracts import production_policy_sha256
from hfss_optimization_agent.domain.canonical_json import canonical_dumps
from hfss_optimization_agent.domain.contracts import FrozenMap
from hfss_optimization_agent.evaluation.calibration import CalibrationPolicy
from hfss_optimization_agent.evaluation.model_alignment import load_model_alignment_contract
from hfss_optimization_agent.harness.calibration_safety import (
    CALIBRATION_COLLECTION_APPROVAL_SCOPE,
    CALIBRATION_COLLECTION_SCHEMA_VERSION,
    CALIBRATION_COLLECTION_WORKFLOW_ID,
    CalibrationCollectionManifestV1,
    calibration_plan_sha256,
    deterministic_calibration_candidates,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy
from hfss_optimization_agent.harness.provenance import source_tree_digest
from hfss_optimization_agent.harness.real_hfss_safety import (
    HFSS_WORKER_PROTOCOL,
    collect_repository_evidence,
    file_sha256,
)
from hfss_optimization_agent.hfss.contracts import attest_builder, load_hfss_contract


def main() -> Path:
    config = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    repository = collect_repository_evidence(ROOT)
    if not repository.working_tree_clean:
        raise RuntimeError("Calibration authority requires a clean exact Git HEAD")
    policy_path = ROOT / config["calibration_policy_path"]
    alignment_path = ROOT / config["model_alignment_path"]
    contract_path = ROOT / config["hfss_contract_path"]
    policy = CalibrationPolicy.from_dict(
        json.loads(policy_path.read_text(encoding="utf-8"))
    )
    alignment = load_model_alignment_contract(alignment_path)
    contract = load_hfss_contract(contract_path)
    if alignment.hfss_contract_id != contract.contract_id:
        raise RuntimeError("approved model alignment does not bind the current HFSS contract")
    candidates = deterministic_calibration_candidates(
        comparison_context_id=alignment.comparison_context_id
    )
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    task_id = f"hfss-calibration-{stamp}"
    optimizer_root = ROOT / "vendor" / "optimizer"
    builder_root = ROOT / "vendor" / "hfss_builder"
    pyaedt_python = Path(config["pyaedt_python"])
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
    manifest = CalibrationCollectionManifestV1(
        schema_version=CALIBRATION_COLLECTION_SCHEMA_VERSION,
        campaign_id=task_id,
        task_id=task_id,
        run_id=f"run:{task_id}",
        workflow_id=CALIBRATION_COLLECTION_WORKFLOW_ID,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=8)).isoformat(),
        git_head=repository.git_head,
        agent_source_sha256=repository.agent_source_sha256,
        hfss_contract_id=contract.contract_id,
        hfss_contract_sha256=file_sha256(contract_path),
        model_alignment_sha256=alignment.digest,
        calibration_policy_sha256=__import__("hashlib").sha256(
            canonical_dumps(policy.to_dict()).encode("utf-8")
        ).hexdigest(),
        calibration_plan_sha256=calibration_plan_sha256(candidates),
        provider_fingerprints=FrozenMap.from_mapping(providers),
        candidates=candidates,
        approval_id=f"approval:{task_id}",
        approval_scope=CALIBRATION_COLLECTION_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(3, 0),
    )
    path = ROOT / "runs" / "authorizations" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(manifest).encode("utf-8"))
    print(path)
    return path


if __name__ == "__main__":
    main()
