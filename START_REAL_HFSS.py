"""Single interactive launcher for the real-HFSS closed loop."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.domain.canonical_json import (  # noqa: E402
    canonical_dumps,
)
from hfss_optimization_agent.task_request import (  # noqa: E402
    OPTIMIZATION_REQUEST_SCHEMA_VERSION,
    OptimizationRequest,
    OptimizationRuleRequest,
    optimization_request_from_evaluation_contract,
)
from hfss_optimization_agent.application.real_hfss_service import (  # noqa: E402
    execute_real_hfss,
    prepare_development_authorization,
    validate_real_hfss_runtime,
)
from hfss_optimization_agent.core.enums import workflow_exit_code  # noqa: E402
from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_status,
    print_run_summary,
)


def _ask_float(label: str, default: float) -> float:
    while True:
        raw = input(f"{label} [{default:g}]：").strip()
        if not raw:
            return float(default)
        try:
            return float(raw)
        except ValueError:
            print("请输入数字。")


def _ask_int(label: str, default: int) -> int:
    while True:
        raw = input(f"{label} [{default}]：").strip()
        try:
            value = default if not raw else int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if 1 <= value <= 100:
            return value
        print("请输入 1 到 100 之间的整数。")


def _ask_operator(label: str, default: str) -> str:
    while True:
        raw = input(f"{label} [{default}]：").strip() or default
        if raw in {"<=", ">="}:
            return raw
        print("只允许 <= 或 >=。")


def _ask_yes_no(label: str, default: bool = True) -> bool:
    token = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{token}]：").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def _default_request() -> OptimizationRequest:
    config = json.loads(
        (ROOT / "runtime_config.json").read_text(encoding="utf-8")
    )
    rounds = int(
        config["real_hfss_execution"]["max_candidate_hfss_calls"]
    )
    return optimization_request_from_evaluation_contract(
        ROOT / "config" / "evaluation_contract.production_v1.json",
        max_optimization_rounds=rounds,
    )


def _rule_defaults(
    request: OptimizationRequest,
) -> dict[tuple[str, bool, str], OptimizationRuleRequest]:
    result = {}
    plan = request.frequency_plan
    for rule in request.rules:
        if rule.hard_constraint:
            side = "core"
        elif tuple(rule.frequency_band) == tuple(
            plan.lower_margin_band
        ):
            side = "lower"
        else:
            side = "upper"
        result[(rule.parameter, rule.hard_constraint, side)] = rule
    return result


def _prompt_request() -> OptimizationRequest:
    default = _default_request()

    print("\n=== REAL HFSS 优化任务 ===")
    print("直接回车表示使用方括号中的默认值。")
    print(
        "最大优化轮数 = 最多允许多少个 Candidate 进入真实 HFSS。"
    )
    print(
        "真实 HFSS 总上限 = Baseline 1 次 + 最大优化轮数。\n"
    )

    if _ask_yes_no("完全使用当前默认优化目标", default=False):
        return OptimizationRequest(
            schema_version=default.schema_version,
            model_id=default.model_id,
            frequency_plan=default.frequency_plan,
            rules=default.rules,
            max_optimization_rounds=_ask_int(
                "最大优化轮数",
                default.max_optimization_rounds,
            ),
        )

    plan = default.frequency_plan
    core_start = _ask_float("核心频段起点 GHz", plan.core_band[0])
    core_stop = _ask_float("核心频段终点 GHz", plan.core_band[1])
    lower_start = _ask_float(
        "低频扩展频段起点 GHz",
        plan.lower_margin_band[0],
    )
    upper_stop = _ask_float(
        "高频扩展频段终点 GHz",
        plan.upper_margin_band[1],
    )

    from hfss_optimization_agent.core.models import FrequencyPlan

    new_plan = FrequencyPlan(
        core_band=(core_start, core_stop),
        lower_margin_band=(lower_start, core_start),
        upper_margin_band=(core_stop, upper_stop),
        tolerance_ghz=plan.tolerance_ghz,
    )
    if not new_plan.is_valid:
        raise ValueError(new_plan.validation_error)

    defaults = _rule_defaults(default)

    def make_rule(
        rule_id: str,
        parameter: str,
        side: str,
        hard: bool,
        band: tuple[float, float],
    ) -> OptimizationRuleRequest:
        fallback = defaults[(parameter, hard, side)]
        print(
            f"\n{parameter} / "
            f"{band[0]:g}–{band[1]:g} GHz"
        )
        return OptimizationRuleRequest(
            rule_id=rule_id,
            parameter=parameter,
            frequency_band=band,
            operator=_ask_operator("比较符", fallback.operator),
            threshold=_ask_float("阈值 dB", fallback.threshold),
            hard_constraint=hard,
            frequency_unit="GHz",
        )

    rules = (
        make_rule(
            "task_core_s21", "S21", "core", True, new_plan.core_band
        ),
        make_rule(
            "task_core_s11", "S11", "core", True, new_plan.core_band
        ),
        make_rule(
            "task_lower_s21",
            "S21",
            "lower",
            False,
            new_plan.lower_margin_band,
        ),
        make_rule(
            "task_lower_s11",
            "S11",
            "lower",
            False,
            new_plan.lower_margin_band,
        ),
        make_rule(
            "task_upper_s21",
            "S21",
            "upper",
            False,
            new_plan.upper_margin_band,
        ),
        make_rule(
            "task_upper_s11",
            "S11",
            "upper",
            False,
            new_plan.upper_margin_band,
        ),
    )

    return OptimizationRequest(
        schema_version=OPTIMIZATION_REQUEST_SCHEMA_VERSION,
        model_id="interposer_temple4",
        frequency_plan=new_plan,
        rules=rules,
        max_optimization_rounds=_ask_int(
            "最大优化轮数",
            default.max_optimization_rounds,
        ),
    )


def _print_summary(request: OptimizationRequest) -> None:
    print("\n=== 本次任务确认 ===")
    print(f"模型：{request.model_id}")
    for rule in request.rules:
        level = "HARD" if rule.hard_constraint else "SOFT"
        print(
            f"- {level} {rule.parameter} {rule.operator} "
            f"{rule.threshold:g} dB @ "
            f"{rule.frequency_band[0]:g}–"
            f"{rule.frequency_band[1]:g} GHz"
        )
    print(f"最大优化轮数：{request.max_optimization_rounds}")
    print(
        "真实 HFSS 最大求解次数："
        f"{request.max_optimization_rounds + 1}"
        "（含 Baseline 1 次）"
    )


def main() -> int:
    configure_utf8_output()

    request = _prompt_request()
    _print_summary(request)

    if not _ask_yes_no(
        "\n确认生成授权并启动 REAL HFSS",
        default=False,
    ):
        print("已取消。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    request_path = (
        ROOT
        / "runs"
        / "requests"
        / f"optimization-request-{stamp}.json"
    )

    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_bytes(
        canonical_dumps(request.to_dict()).encode("utf-8")
    )

    prepared = prepare_development_authorization(
        ROOT,
        request,
    )

    runtime = validate_real_hfss_runtime(
        ROOT,
        request,
        prepared.manifest_path,
    )

    print(f"\n【优化任务文件】{request_path}")
    print(f"【Development Authorization】{prepared.manifest_path}")
    print("【启动】REAL HFSS closed loop\n")

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
            f"最大 {request.max_optimization_rounds} "
            "轮 Candidate REAL HFSS"
        ),
        detail=request.digest[:12],
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
