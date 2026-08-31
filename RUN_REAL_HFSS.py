"""VS Code entry point: execute the configurable real-HFSS workflow."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.cli import run_real_supplied_demo  # noqa: E402
from hfss_optimization_agent.core.enums import workflow_exit_code  # noqa: E402
from hfss_optimization_agent.harness.real_hfss_safety import (  # noqa: E402
    validate_real_hfss_launch_configuration,
)
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)
from hfss_optimization_agent.task_request import (  # noqa: E402
    apply_optimization_request_budget,
    load_runtime_optimization_request,
)


def _configuration() -> dict:
    raw = json.loads(
        (ROOT / "runtime_config.json").read_text(encoding="utf-8")
    )
    optimization_request = load_runtime_optimization_request(ROOT, raw)
    value = apply_optimization_request_budget(raw, optimization_request)

    manifest_path = os.environ.get("HFSS_REAL_READINESS_MANIFEST")
    if manifest_path:
        value["real_hfss_enabled"] = True
        value["real_hfss_readiness_manifest"] = manifest_path

    value["_readiness_authorization"] = (
        validate_real_hfss_launch_configuration(
            value,
            repository_root=ROOT,
        )
    )
    value["_optimization_request"] = optimization_request

    interpreter = Path(value["pyaedt_python"])
    if not interpreter.is_file():
        raise FileNotFoundError(
            f"找不到 PyAEDT Python：{interpreter}"
        )
    return value


if __name__ == "__main__":
    configure_utf8_output()
    configuration = _configuration()
    authorization = configuration["_readiness_authorization"]
    optimization_request = configuration["_optimization_request"]
    task_id = authorization.manifest.task_id

    emit_status(
        "任务",
        "启动真实 HFSS 自动优化流程",
        detail=task_id,
    )
    emit_status(
        "求解范围",
        "只创建并求解 interposer_temple4",
    )
    emit_status(
        "优化任务",
        (
            f"最多 {optimization_request.max_optimization_rounds} "
            f"轮 Candidate REAL HFSS"
        ),
        detail=optimization_request.digest[:12],
    )
    emit_status(
        "界面模式",
        (
            "显示 AEDT 图形界面"
            if configuration.get("hfss_ui_visible", True)
            else "后台运行"
        ),
    )
    emit_status(
        "模型状态",
        "流程可运行；物理一致性与校准仍待确认",
    )

    summary = run_real_supplied_demo(
        optimizer_source_root=ROOT / "vendor" / "optimizer",
        builder_source_root=ROOT / "vendor" / "hfss_builder",
        pyaedt_python=Path(configuration["pyaedt_python"]),
        contract_path=(
            ROOT
            / "config"
            / "hfss_contract.pa_multi_2025_1.json"
        ),
        evaluation_contract_path=(
            ROOT
            / "config"
            / "evaluation_contract.production_v1.json"
        ),
        artifact_root=Path(configuration["artifact_root"]),
        task_id=task_id,
        quick=bool(configuration.get("quick_optimizer", True)),
        solve_timeout_seconds=float(
            configuration.get("solve_timeout_seconds", 7200.0)
        ),
        execute_real_hfss=True,
        readiness_authorization=authorization,
        non_graphical=not bool(
            configuration.get("hfss_ui_visible", True)
        ),
        optimization_request=optimization_request,
    )
    print_run_summary(summary)
    raise SystemExit(workflow_exit_code(summary["status"]))
