"""Regression tests for concise Chinese terminal progress."""

from io import StringIO

import pytest

from hfss_optimization_agent.harness.terminal import emit_stage, emit_status
from hfss_optimization_agent.hfss.pyaedt_worker import _BUILD_STAGE_TOTAL, _builder_stage_display


def test_numbered_stage_and_status_are_concise_chinese_lines():
    output = StringIO()
    emit_stage("主流程", 3, 14, "仿真初始模型", stream=output)
    emit_status("运行结果", "已完成", detail="任务编号 demo-001", stream=output)
    assert output.getvalue().splitlines() == [
        "【主流程 03/14】仿真初始模型",
        "【运行结果】已完成｜任务编号 demo-001",
    ]


@pytest.mark.parametrize(
    ("internal_stage", "expected"),
    [
        ("worker_ready", (1, "建模进程就绪")),
        (
            "interposer_temple4:interposer1_arrays:complete",
            (7, "目标设计 interposer_temple4：生成阵列结构"),
        ),
        (
            "interposer_temple4:analysis_and_reports:complete",
            (12, "目标设计 interposer_temple4：配置端口、边界和扫频"),
        ),
        ("project_saved", (13, "保存 HFSS 工程")),
    ],
)
def test_builder_internal_events_have_stable_chinese_stage_names(internal_stage, expected):
    assert _builder_stage_display(internal_stage) == expected


def test_invalid_stage_number_is_rejected():
    with pytest.raises(ValueError, match="阶段编号"):
        emit_stage("主流程", 0, 14, "无效阶段", stream=StringIO())


def test_target_only_builder_has_thirteen_stages():
    assert _BUILD_STAGE_TOTAL == 13
