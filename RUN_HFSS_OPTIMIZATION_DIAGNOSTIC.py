"""Execute the separately authorized baseline-versus-optimized HFSS diagnostic."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.evaluation.optimization_diagnostic_campaign import (  # noqa: E402
    run_optimization_diagnostic_campaign,
)
from hfss_optimization_agent.harness.optimization_diagnostic_safety import (  # noqa: E402
    validate_optimization_diagnostic_configuration,
)
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
)


def main() -> int:
    configure_utf8_output()
    config = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    manifest_path = os.environ.get("HFSS_OPTIMIZATION_DIAGNOSTIC_MANIFEST")
    if manifest_path:
        config["real_hfss_optimization_diagnostic_enabled"] = True
        config["real_hfss_optimization_diagnostic_manifest"] = manifest_path
    authorization = validate_optimization_diagnostic_configuration(
        config,
        repository_root=ROOT,
    )
    emit_status("任务", "启动基准与冻结优化候选的双 HFSS 诊断")
    emit_status("求解预算", "严格两次，零自动重试")
    emit_status("生产边界", "诊断实验；不会签发正式 Canary")
    result = run_optimization_diagnostic_campaign(
        authorization,
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(config["pyaedt_python"]),
        artifact_root=Path(config["artifact_root"]),
        solve_timeout_seconds=float(config.get("solve_timeout_seconds", 7200.0)),
        non_graphical=True,
    )
    print(
        json.dumps(
            {
                "physical_improvement_observed": result.physical_improvement_observed,
                "task_id": result.task_id,
                "run_id": result.run_id,
                "evidence_path": str(result.evidence_path),
                "evidence_sha256": result.evidence_sha256,
                "report": result.evidence.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.physical_improvement_observed else 2


if __name__ == "__main__":
    raise SystemExit(main())
