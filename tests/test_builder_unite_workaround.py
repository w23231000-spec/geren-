"""Regression tests for the AEDT-native unite compatibility path."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_PATH = ROOT / "vendor" / "hfss_builder" / "pa_multi_builder" / "geometry.py"


def load_geometry_module():
    spec = spec_from_file_location("builder_geometry_unite_test", GEOMETRY_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeEditor:
    def __init__(self, *, object_lookup_error=None):
        self.unite_calls = []
        self.purge_calls = []
        self.object_lookup_error = object_lookup_error

    def Unite(self, selections, parameters):
        self.unite_calls.append((selections, parameters))

    def PurgeHistory(self, selections):
        self.purge_calls.append(selections)

    def GetObjectIDByName(self, name):
        if self.object_lookup_error is not None:
            raise self.object_lookup_error
        return 42


class FakeModeler:
    def __init__(self, editor):
        self.oeditor = editor

    def unite(self, *_args, **_kwargs):
        raise AssertionError("PyAEDT modeler.unite must not be used by the workaround")


class FakeHfss:
    def __init__(self, editor):
        self.modeler = FakeModeler(editor)


def test_unite_calls_aedt_editor_without_pyaedt_cache_refresh():
    geometry = load_geometry_module()
    editor = FakeEditor()

    result = geometry._unite_named(FakeHfss(editor), "target", ["tool_a", "tool_b"])

    assert result == "target"
    assert editor.unite_calls == [
        (
            ["NAME:Selections", "Selections:=", "target,tool_a,tool_b"],
            [
                "NAME:UniteParameters",
                "KeepOriginals:=",
                False,
                "TurnOnNBodyBoolean:=",
                True,
            ],
        )
    ]
    assert editor.purge_calls == [
        [
            "NAME:Selections",
            "Selections:=",
            "target",
            "NewPartsModelFlag:=",
            "Model",
        ]
    ]


def test_unite_propagates_missing_result_error():
    geometry = load_geometry_module()
    editor = FakeEditor(object_lookup_error=RuntimeError("missing target"))

    with pytest.raises(RuntimeError, match="missing target"):
        geometry._unite_named(FakeHfss(editor), "target", ["tool"])


def test_unite_requires_at_least_one_tool():
    geometry = load_geometry_module()

    with pytest.raises(ValueError, match="at least one tool"):
        geometry._unite_named(FakeHfss(FakeEditor()), "target", [])
