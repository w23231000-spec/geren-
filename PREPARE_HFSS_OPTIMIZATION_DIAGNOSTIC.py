"""Create a short-lived two-solve optimization diagnostic authority; never launches AEDT."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.agent.closed_loop_contracts import (  # noqa: E402
    production_policy_sha256,
)
from hfss_optimization_agent.domain.canonical_json import canonical_dumps  # noqa: E402
from hfss_optimization_agent.domain.contracts import FrozenMap  # noqa: E402
from hfss_optimization_agent.evaluation.model_alignment import (  # noqa: E402
    load_model_alignment_contract,
)
from hfss_optimization_agent.harness.execution_policy import ExecutionPolicy  # noqa: E402
from hfss_optimization_agent.harness.optimization_diagnostic_safety import (  # noqa: E402
    OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE,
    OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION,
    OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
    OptimizationDiagnosticManifestV1,
    diagnostic_plan_sha256,
    optimization_candidate_plan,
    validate_optimization_diagnostic_configuration,
)
from hfss_optimization_agent.harness.provenance import source_tree_digest  # noqa: E402
from hfss_optimization_agent.harness.real_hfss_safety import (  # noqa: E402
    HFSS_WORKER_PROTOCOL,
    collect_repository_evidence,
    file_sha256,
)
from hfss_optimization_agent.hfss.contracts import (  # noqa: E402
    attest_builder,
    load_hfss_contract,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="冻结一次完整代理优化推荐点并签发双 HFSS 诊断授权；不启动 AEDT。"
    )
    parser.add_argument(
        "--optimization-summary",
        type=Path,
        required=True,
        help="完整优化运行的 00_summary.json",
    )
    return parser.parse_args()


def main(summary_path: Path | None = None) -> Path:
    if summary_path is None:
        summary_path = _arguments().optimization_summary
    summary_path = Path(summary_path).resolve()
    try:
        summary_uri = summary_path.relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError("optimization summary must be inside the repository") from exc
    config = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    repository = collect_repository_evidence(ROOT)
    if not repository.working_tree_clean:
        raise RuntimeError(
            "optimization diagnostic authority requires a clean exact Git HEAD"
        )
    alignment_path = ROOT / config["model_alignment_path"]
    contract_path = ROOT / config["hfss_contract_path"]
    alignment = load_model_alignment_contract(alignment_path)
    contract = load_hfss_contract(contract_path)
    if alignment.hfss_contract_id != contract.contract_id:
        raise RuntimeError("approved model alignment does not bind the HFSS contract")
    candidates = optimization_candidate_plan(
        summary_path,
        comparison_context_id=alignment.comparison_context_id,
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    task_id = f"hfss-optimization-diagnostic-{stamp}"
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
    manifest = OptimizationDiagnosticManifestV1(
        schema_version=OPTIMIZATION_DIAGNOSTIC_SCHEMA_VERSION,
        campaign_id=task_id,
        task_id=task_id,
        run_id=f"run:{task_id}",
        workflow_id=OPTIMIZATION_DIAGNOSTIC_WORKFLOW_ID,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(hours=8)).isoformat(),
        git_head=repository.git_head,
        agent_source_sha256=repository.agent_source_sha256,
        hfss_contract_id=contract.contract_id,
        hfss_contract_sha256=file_sha256(contract_path),
        model_alignment_sha256=alignment.digest,
        optimization_summary_uri=summary_uri,
        optimization_summary_sha256=file_sha256(summary_path),
        optimizer_run_id=str(summary["run_id"]),
        recommended_point_id=str(summary["recommended_point_id"]),
        diagnostic_plan_sha256=diagnostic_plan_sha256(candidates),
        provider_fingerprints=FrozenMap.from_mapping(providers),
        candidates=candidates,
        approval_id=f"approval:{task_id}",
        approval_scope=OPTIMIZATION_DIAGNOSTIC_APPROVAL_SCOPE,
        execution_policy=ExecutionPolicy(2, 0),
    )
    path = ROOT / "runs" / "authorizations" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_dumps(manifest).encode("utf-8"))

    validation_config = dict(config)
    validation_config["real_hfss_optimization_diagnostic_enabled"] = True
    validation_config["real_hfss_optimization_diagnostic_manifest"] = str(path)
    validate_optimization_diagnostic_configuration(
        validation_config,
        repository_root=ROOT,
    )
    print(path)
    return path


if __name__ == "__main__":
    main()
