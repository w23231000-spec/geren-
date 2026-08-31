"""Verify that the real Builder creates exactly the contracted target design."""

import importlib
import sys
from types import ModuleType


def test_build_project_creates_target_design_once(monkeypatch, tmp_path):
    created_sessions = []

    class FakeHfss:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.released = False
            created_sessions.append(self)

        def save_project(self, path):
            from pathlib import Path

            Path(path).write_text("offline fake project", encoding="utf-8")

        def release_desktop(self, **kwargs):
            self.released = kwargs

    ansys = ModuleType("ansys")
    aedt = ModuleType("ansys.aedt")
    core = ModuleType("ansys.aedt.core")
    core.Hfss = FakeHfss
    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.aedt", aedt)
    monkeypatch.setitem(sys.modules, "ansys.aedt.core", core)

    from pathlib import Path

    repository_builder_root = Path(__file__).resolve().parents[1] / "vendor" / "hfss_builder"
    monkeypatch.syspath_prepend(str(repository_builder_root))
    for module_name in list(sys.modules):
        if module_name == "pa_multi_builder" or module_name.startswith("pa_multi_builder."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)

    project = importlib.import_module("pa_multi_builder.project")
    build_calls = []

    def fake_build_design(hfss, **kwargs):
        build_calls.append((hfss, kwargs))
        return {"built_objects": ["target"]}

    monkeypatch.setattr(project, "build_design", fake_build_design)
    stages = []
    output = tmp_path / "target.aedt"

    result = project.build_project(
        output,
        non_graphical=False,
        parameter_overrides={"r_tsv": "0.015mm"},
        progress_callback=lambda stage, metadata=None: stages.append(stage),
    )

    assert len(created_sessions) == 1
    assert created_sessions[0].kwargs["design"] == "interposer_temple4"
    assert len(build_calls) == 1
    assert build_calls[0][1]["include_radiation_region"] is True
    assert build_calls[0][1]["stage_prefix"] == "interposer_temple4"
    assert result["design_name"] == "interposer_temple4"
    assert "aedt_session:ready" in stages
    assert "project_saved" in stages
    assert created_sessions[0].released == {"close_projects": True, "close_desktop": True}
