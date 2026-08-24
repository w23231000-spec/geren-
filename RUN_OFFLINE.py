"""VS Code entry point: run the complete comparison workflow with offline providers."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.cli import run_offline_demo  # noqa: E402
from hfss_optimization_agent.core.enums import workflow_exit_code  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)


if __name__ == "__main__":
    configure_utf8_output()
    emit_status("任务", "启动保留的一次性离线工作流")
    summary = run_offline_demo(artifact_root=ROOT / "runs")
    print_run_summary(summary)
    raise SystemExit(workflow_exit_code(summary["status"]))
