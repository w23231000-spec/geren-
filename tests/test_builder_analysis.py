"""Offline tests for Builder analysis creation and optimizer ownership."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "vendor" / "hfss_builder" / "pa_multi_builder" / "analysis.py"


def load_analysis_module():
    spec = spec_from_file_location("builder_analysis_for_test", ANALYSIS_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeSetup:
    def __init__(self):
        self.sweep_calls = []

    def create_linear_step_sweep(self, **kwargs):
        self.sweep_calls.append(kwargs)
        return object()


class ForbiddenParametrics:
    def add(self, *_args, **_kwargs):
        raise AssertionError("HFSS Optimetrics must not own Agent candidate variation")


class FakeHfss:
    def __init__(self):
        self.setup = FakeSetup()
        self.setup_calls = []
        self.parametrics = ForbiddenParametrics()

    def create_setup(self, **kwargs):
        self.setup_calls.append(kwargs)
        return self.setup

    def create_linear_step_sweep(self, **_kwargs):
        raise AssertionError("Top-level sweep API must not re-enumerate setup cache")


def test_analysis_uses_returned_setup_and_leaves_variation_to_agent():
    analysis = load_analysis_module()
    hfss = FakeHfss()
    stages = []

    result = analysis.create_analysis(
        hfss,
        progress_callback=lambda stage, metadata=None: stages.append(stage),
        stage_prefix="interposer_temple4",
    )

    assert result is hfss.setup
    assert hfss.setup_calls[0]["name"] == "Setup1"
    assert hfss.setup.sweep_calls == [
        {
            "unit": "GHz",
            "start_frequency": 0.1,
            "stop_frequency": 20,
            "step_size": 0.1,
            "name": "Sweep",
            "save_fields": True,
            "sweep_type": "Fast",
        }
    ]
    assert stages == [
        "interposer_temple4:setup:complete",
        "interposer_temple4:sweep:complete",
    ]
