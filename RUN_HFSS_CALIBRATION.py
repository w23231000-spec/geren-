"""Execute the separately authorized three-solve HFSS Calibration campaign."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.evaluation.calibration_campaign import run_calibration_campaign
from hfss_optimization_agent.harness.calibration_safety import (
    validate_calibration_collection_configuration,
)


def main() -> int:
    config = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    manifest_path = os.environ.get("HFSS_CALIBRATION_MANIFEST")
    if manifest_path:
        config["real_hfss_calibration_enabled"] = True
        config["real_hfss_calibration_manifest"] = manifest_path
    authorization = validate_calibration_collection_configuration(
        config,
        repository_root=ROOT,
    )
    result = run_calibration_campaign(
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
                "passed": result.passed,
                "task_id": result.task_id,
                "run_id": result.run_id,
                "evidence_path": str(result.evidence_path),
                "evidence_sha256": result.evidence.digest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
