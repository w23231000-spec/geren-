from pathlib import Path

import hfss_optimization_agent.application.real_hfss_service as service
from hfss_optimization_agent.task_request import (
    optimization_request_from_evaluation_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _request():
    return optimization_request_from_evaluation_contract(
        ROOT / "config" / "evaluation_contract.production_v1.json",
        max_optimization_rounds=1,
    )


def test_validate_runtime_can_override_hfss_visibility(
    monkeypatch,
) -> None:
    request = _request()
    captured = {}

    monkeypatch.setattr(
        service,
        "build_runtime_configuration",
        lambda root, optimization_request: {
            "pyaedt_python": str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "hfss_ui_visible": False,
        },
    )

    monkeypatch.setattr(
        service,
        "validate_real_hfss_launch_configuration",
        lambda config, repository_root: (
            captured.update(config) or object()
        ),
    )

    runtime = service.validate_real_hfss_runtime(
        ROOT,
        request,
        "synthetic-manifest.json",
        hfss_ui_visible=True,
    )

    assert captured["hfss_ui_visible"] is True
    assert runtime.configuration["hfss_ui_visible"] is True


def test_execute_real_hfss_uses_visible_mode(
    monkeypatch,
) -> None:
    request = _request()
    captured = {}

    authorization = type(
        "Authorization",
        (),
        {
            "manifest": type(
                "Manifest",
                (),
                {"task_id": "task-visible"},
            )()
        },
    )()

    runtime = service.RealHFSSRuntime(
        configuration={
            "pyaedt_python": str(
                ROOT / ".venv" / "Scripts" / "python.exe"
            ),
            "artifact_root": str(ROOT / "runs"),
            "quick_optimizer": True,
            "solve_timeout_seconds": 7200.0,
            "hfss_ui_visible": True,
        },
        authorization=authorization,
        optimization_request=request,
    )

    monkeypatch.setattr(
        service,
        "run_real_supplied_demo",
        lambda **kwargs: (
            captured.update(kwargs)
            or {"status": "PASS"}
        ),
    )

    service.execute_real_hfss(
        ROOT,
        runtime,
    )

    assert captured["non_graphical"] is False


def test_gui_defaults_to_visible_hfss() -> None:
    source = (
        ROOT
        / "src"
        / "hfss_optimization_agent"
        / "ui"
        / "main_window.py"
    ).read_text(encoding="utf-8")

    assert "tk.BooleanVar(value=True)" in source
    assert "显示 AEDT / HFSS 图形界面" in source
    assert "hfss_ui_visible=hfss_ui_visible" in source
