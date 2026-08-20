"""Small UTF-8 terminal presenter for concise Chinese workflow progress."""

from __future__ import annotations

import sys
from typing import Any, TextIO


def configure_utf8_output() -> None:
    """Force predictable Chinese output for Windows terminals and redirected runs."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError, ValueError):
                continue


def emit_stage(
    scope: str,
    current: int,
    total: int,
    title: str,
    *,
    detail: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Print one stable, numbered stage line."""

    if current < 1 or total < 1 or current > total:
        raise ValueError("阶段编号必须满足 1 <= current <= total")
    output = stream or sys.stdout
    suffix = f"｜{detail}" if detail else ""
    print(f"【{scope} {current:02d}/{total:02d}】{title}{suffix}", file=output, flush=True)


def emit_status(
    scope: str,
    status: str,
    *,
    detail: str | None = None,
    stream: TextIO | None = None,
) -> None:
    """Print a non-numbered completion, warning, or failure line."""

    output = stream or sys.stdout
    suffix = f"｜{detail}" if detail else ""
    print(f"【{scope}】{status}{suffix}", file=output, flush=True)


def emit_evaluation_summary(evaluation: Any, *, title: str, stream: TextIO | None = None) -> None:
    """Print a compact, data-backed summary for one S-parameter evaluation."""
    output = stream or sys.stdout
    print(f"[{title} Evaluation] {getattr(evaluation, 'status', 'INVALID')}", file=output, flush=True)
    for rule in getattr(evaluation, "rule_results", []):
        print(
            f"{rule['rule_id']}: {rule['status']} | target {rule['operator']} {rule['target']} | "
            f"worst {rule['worst_value']} @ {rule['worst_frequency']} | margin {rule['margin_to_target']}",
            file=output,
            flush=True,
        )


def emit_diagnosis_summary(diagnosis: Any, *, title: str, stream: TextIO | None = None) -> None:
    output = stream or sys.stdout
    print(f"[{title}诊断] {diagnosis.status}", file=output, flush=True)
    primary = getattr(diagnosis, "primary_issue", None)
    print(f"主要问题：{primary.issue_type if primary else '无'}", file=output, flush=True)
    print(f"次要问题：{', '.join(issue.issue_type for issue in diagnosis.secondary_issues) or '无'}", file=output, flush=True)
    if diagnosis.stage == "optimized":
        print(f"已解决：{', '.join(diagnosis.resolved_issues) or '无'}", file=output, flush=True)
        print(f"仍存在：{', '.join(diagnosis.remaining_issues) or '无'}", file=output, flush=True)
        print(f"新增：{', '.join(diagnosis.new_issues) or '无'}", file=output, flush=True)
        migrations = [f"{item.from_location}→{item.to_location}" for item in diagnosis.issue_migrations]
        print(f"问题迁移：{', '.join(migrations) or '无'}", file=output, flush=True)
        print(
            f"低频裕量 delta：{diagnosis.summary.get('lower_frequency_margin_delta')} | "
            f"高频裕量 delta：{diagnosis.summary.get('upper_frequency_margin_delta')}",
            file=output,
            flush=True,
        )
    print(f"优化关注：{', '.join(diagnosis.optimization_focus) or '无'}", file=output, flush=True)


def emit_optimization_intent(intent: Any, *, stream: TextIO | None = None) -> None:
    output = stream or sys.stdout
    print(f"[优化意图] {intent.status}", file=output, flush=True)
    print(f"优化模式：{intent.mode or '无'}", file=output, flush=True)
    print(f"第一优化重点：{intent.primary_focus or '无'}", file=output, flush=True)
    print(f"后续优化重点：{', '.join(intent.secondary_focuses) or '无'}", file=output, flush=True)
    print(f"核心工作带保护：{'启用' if intent.protect_core_constraints else '禁用'}", file=output, flush=True)
    margin = getattr(evaluation, "frequency_margin", {})
    if margin:
        print(
            f"Frequency margin: lower {margin.get('lower_frequency_margin', 0.0):.3f} GHz "
            f"(edge {margin.get('achieved_lower_edge'):.3f}), "
            f"upper {margin.get('upper_frequency_margin', 0.0):.3f} GHz "
            f"(edge {margin.get('achieved_upper_edge'):.3f})",
            file=output,
            flush=True,
        )
        print(
            f"Hard failures: {getattr(evaluation, 'hard_failed_rule_count', 0)} | "
            f"Soft failures: {getattr(evaluation, 'soft_failed_rule_count', 0)}",
            file=output,
            flush=True,
        )
        soft_issue = getattr(evaluation, "worst_soft_issue", None)
        print(
            f"Worst soft issue: {soft_issue.get('rule_id')} | margin {soft_issue.get('margin_to_target')}"
            if soft_issue else "Worst soft issue: none",
            file=output,
            flush=True,
        )


def print_run_summary(summary: dict[str, Any]) -> None:
    """Render the common run summary with Chinese labels."""

    status_names = {"completed": "已完成", "running": "运行中", "failed": "失败"}
    emit_status("运行结果", status_names.get(str(summary.get("status")), str(summary.get("status"))))
    fields = (
        ("任务编号", "task_id"),
        ("优化候选", "optimized_candidate"),
        ("最佳方案", "best_candidate"),
        ("最佳得分", "best_score"),
        ("产物目录", "artifact_dir"),
    )
    for label, key in fields:
        value = summary.get(key)
        if value is not None:
            print(f"  {label}：{value}", flush=True)
