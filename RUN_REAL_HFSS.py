"""VS Code entry point: execute the real two-solve PyAEDT workflow."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.cli import run_real_supplied_demo  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)


def _configuration() -> dict:
    value = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    if not value.get("real_hfss_enabled", False):
        raise RuntimeError("真实 HFSS 未启用：请先在 runtime_config.json 中设置 real_hfss_enabled=true")
    interpreter = Path(value["pyaedt_python"])
    if not interpreter.is_file():
        raise FileNotFoundError(f"找不到 PyAEDT Python：{interpreter}")
    return value


if __name__ == "__main__":
    configure_utf8_output()
    configuration = _configuration()
    task_id = f"real-vscode-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    emit_status("任务", "启动真实 HFSS 自动优化流程", detail=task_id)
    emit_status("求解范围", "只创建并求解 interposer_temple4")
    emit_status(
        "界面模式",
        "显示 AEDT 图形界面" if configuration.get("hfss_ui_visible", True) else "后台运行",
    )
    emit_status("模型状态", "流程可运行；物理一致性与校准仍待确认")
    summary = run_real_supplied_demo(
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(configuration["pyaedt_python"]),
        contract_path=ROOT / "config" / "hfss_contract.pa_multi_2025_1.json",
        evaluation_contract_path=ROOT / "config" / "evaluation_contract.production_v1.json",
        artifact_root=Path(configuration["artifact_root"]),
        task_id=task_id,
        quick=bool(configuration.get("quick_optimizer", True)),
        solve_timeout_seconds=float(configuration.get("solve_timeout_seconds", 7200.0)),
        execute_real_hfss=True,
        non_graphical=not bool(configuration.get("hfss_ui_visible", True)),
    )
    print_run_summary(summary)
