"""Offline regression test for the supplied Builder milestone routing."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_PATH = ROOT / "vendor" / "hfss_builder" / "pa_multi_builder" / "geometry.py"


def load_geometry_module():
    spec = spec_from_file_location("builder_geometry_for_test", GEOMETRY_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_foundation_milestone_does_not_enter_array_or_layer_build(monkeypatch):
    geometry = load_geometry_module()
    calls = []
    stages = []

    monkeypatch.setattr(
        geometry,
        "build_interposer_1_foundation",
        lambda hfss, progress_callback=None, stage_prefix="design": calls.append("foundation")
        or ["pi2"],
    )
    monkeypatch.setattr(
        geometry,
        "build_interposer_1_arrays",
        lambda hfss: calls.append("arrays") or [],
    )
    monkeypatch.setattr(
        geometry,
        "build_interposer_1_layers",
        lambda hfss: calls.append("layers") or [],
    )

    result = geometry.build_interposer_1(
        object(),
        progress_callback=lambda stage, metadata=None: stages.append(stage),
        stage_prefix="interposer_temple4",
        milestone="interposer1_foundation",
    )

    assert result == ["pi2"]
    assert calls == ["foundation"]
    assert stages == ["interposer_temple4:interposer1_foundation:complete"]
