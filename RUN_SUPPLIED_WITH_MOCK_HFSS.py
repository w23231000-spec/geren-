"""VS Code entry point: run the bundled optimizer/surrogate with MockHFSS."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.cli import run_supplied_mock_demo  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)


if __name__ == "__main__":
    configure_utf8_output()
    emit_status("任务", "启动优化模块与模拟 HFSS 演示")
    summary = run_supplied_mock_demo(
        source_root=ROOT / "vendor" / "optimizer",
        artifact_root=ROOT / "runs",
        quick=True,
    )
    print_run_summary(summary)
