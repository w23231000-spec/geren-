"""Compatibility entry point for the REAL HFSS workflow.

The implementation lives in
hfss_optimization_agent.application.real_hfss_service.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.application.real_hfss_service import (  # noqa: E402
    execute_real_hfss,
    validate_real_hfss_runtime,
)
from hfss_optimization_agent.core.enums import workflow_exit_code  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)
from hfss_optimization_agent.task_request import (  # noqa: E402
    load_runtime_optimization_request,
)


def main() -> int:
    configure_utf8_output()

    raw = json.loads(
        (ROOT / "runtime_config.json").read_text(encoding="utf-8")
    )

    optimization_request = load_runtime_optimization_request(
        ROOT,
        raw,
    )

    runtime = validate_real_hfss_runtime(
        ROOT,
        optimization_request,
        os.environ.get("HFSS_REAL_READINESS_MANIFEST"),
    )

    emit_status(
        "任务",
        "启动真实 HFSS 自动优化流程",
        detail=runtime.task_id,
    )

    emit_status(
        "求解范围",
        "只创建并求解 interposer_temple4",
    )

    emit_status(
        "优化任务",
        (
            f"最大 {optimization_request.max_optimization_rounds} "
            "轮 Candidate REAL HFSS"
        ),
        detail=optimization_request.digest[:12],
    )

    emit_status(
        "界面模式",
        (
            "显示 AEDT 图形界面"
            if runtime.configuration.get("hfss_ui_visible", True)
            else "后台运行"
        ),
    )

    emit_status(
        "模型状态",
        "流程可运行；物理一致性与校准仍待确认",
    )

    summary = execute_real_hfss(
        ROOT,
        runtime,
    )

    print_run_summary(summary)
    return workflow_exit_code(summary["status"])


if __name__ == "__main__":
    raise SystemExit(main())
