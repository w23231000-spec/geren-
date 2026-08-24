"""Opt-in VS Code entry for supplied Tools in the bounded closed-loop Agent."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.cli import run_closed_loop_supplied_mock_demo  # noqa: E402
from hfss_optimization_agent.core.enums import workflow_exit_code  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)


if __name__ == "__main__":
    configure_utf8_output()
    emit_status("任务", "启动 V2 supplied-Mock Closed-loop Agent")
    summary = run_closed_loop_supplied_mock_demo(
        source_root=ROOT / "vendor" / "optimizer",
        artifact_root=ROOT / "runs",
        quick=True,
    )
    print_run_summary(summary)
    raise SystemExit(workflow_exit_code(summary["status"]))
