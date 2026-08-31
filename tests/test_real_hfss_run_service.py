from pathlib import Path
from types import SimpleNamespace

import pytest

import hfss_optimization_agent.application.real_hfss_service as service
from hfss_optimization_agent.task_request import (
    optimization_request_from_evaluation_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _request():
    return optimization_request_from_evaluation_contract(
        ROOT / "config" / "evaluation_contract.production_v1.json",
        max_optimization_rounds=3,
    )


def test_persist_optimization_request_writes_exact_snapshot(
    tmp_path: Path,
) -> None:
    request = _request()

    path = service.persist_optimization_request(
        tmp_path,
        request,
    )

    assert path.is_file()
    assert path.parent == tmp_path / "runs" / "requests"

    loaded = path.read_text(encoding="utf-8")

    assert request.digest
    assert '"max_optimization_rounds":3' in loaded


def test_run_real_hfss_task_orchestrates_application_boundary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    events = []
    calls = []

    request_path = (
        tmp_path
        / "runs"
        / "requests"
        / "request.json"
    )

    prepared = SimpleNamespace(
        manifest_path=tmp_path / "authorization.json",
        task_id="task-test",
    )

    runtime = SimpleNamespace(
        task_id="task-test",
    )

    monkeypatch.setattr(
        service,
        "validate_task",
        lambda root, optimization_request: calls.append(
            "validate"
        ) or {},
    )

    monkeypatch.setattr(
        service,
        "persist_optimization_request",
        lambda root, optimization_request: calls.append(
            "persist"
        ) or request_path,
    )

    monkeypatch.setattr(
        service,
        "prepare_development_authorization",
        lambda root, optimization_request: calls.append(
            "authorize"
        ) or prepared,
    )

    monkeypatch.setattr(
        service,
        "validate_real_hfss_runtime",
        lambda root, optimization_request, manifest, **kwargs: calls.append(
            "safety"
        ) or runtime,
    )

    monkeypatch.setattr(
        service,
        "execute_real_hfss",
        lambda root, runtime: calls.append(
            "execute"
        ) or {"status": "PASS"},
    )

    result = service.run_real_hfss_task(
        tmp_path,
        request,
        on_event=events.append,
    )

    assert calls == [
        "validate",
        "persist",
        "authorize",
        "safety",
        "execute",
    ]

    assert result.task_id == "task-test"
    assert result.status == "PASS"
    assert result.request_path == request_path

    assert [event.stage for event in events] == [
        "validation",
        "validation",
        "request",
        "authorization",
        "authorization",
        "safety_gate",
        "safety_gate",
        "hfss_mode",
        "workflow",
        "workflow",
    ]

    assert events[-1].event_type == "complete"


def test_run_real_hfss_task_emits_error_and_reraises(
    monkeypatch,
    tmp_path: Path,
) -> None:
    request = _request()
    events = []

    monkeypatch.setattr(
        service,
        "validate_task",
        lambda root, optimization_request: (_ for _ in ()).throw(
            RuntimeError("synthetic failure")
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="synthetic failure",
    ):
        service.run_real_hfss_task(
            tmp_path,
            request,
            on_event=events.append,
        )

    assert events[-1].event_type == "error"
    assert events[-1].stage == "application"
    assert "synthetic failure" in (events[-1].detail or "")


def test_gui_uses_background_thread_for_real_hfss() -> None:
    source = (
        ROOT
        / "src"
        / "hfss_optimization_agent"
        / "ui"
        / "main_window.py"
    ).read_text(encoding="utf-8")

    assert "threading.Thread(" in source
    assert "target=self._run_real_hfss_worker" in source
    assert "run_real_hfss_task(" in source
    assert 'daemon=False' in source
