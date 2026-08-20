"""Regression tests for AEDT-native high-volume primitive creation."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_PATH = ROOT / "vendor" / "hfss_builder" / "pa_multi_builder" / "geometry.py"
MATERIALS_PATH = ROOT / "vendor" / "hfss_builder" / "pa_multi_builder" / "materials.py"


def load_geometry_module():
    spec = spec_from_file_location("builder_geometry_primitives_test", GEOMETRY_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_materials_module():
    spec = spec_from_file_location("builder_materials_primitives_test", MATERIALS_PATH)
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeEditor:
    def __init__(self):
        self.box_calls = []
        self.cylinder_calls = []
        self.sphere_calls = []
        self.lookups = []

    def CreateBox(self, parameters, attributes):
        self.box_calls.append((parameters, attributes))
        return attributes[2]

    def CreateCylinder(self, parameters, attributes):
        self.cylinder_calls.append((parameters, attributes))
        return attributes[2]

    def CreateSphere(self, parameters, attributes):
        self.sphere_calls.append((parameters, attributes))
        return attributes[2]

    def GetObjectIDByName(self, name):
        self.lookups.append(name)
        return 42


class FakeModeler:
    def __init__(self, editor):
        self.oeditor = editor

    def create_box(self, *_args, **_kwargs):
        raise AssertionError("PyAEDT create_box material checking must be bypassed")

    def create_cylinder(self, *_args, **_kwargs):
        raise AssertionError("PyAEDT create_cylinder material checking must be bypassed")

    def create_sphere(self, *_args, **_kwargs):
        raise AssertionError("PyAEDT create_sphere material checking must be bypassed")


class FakeHfss:
    def __init__(self, editor):
        self.modeler = FakeModeler(editor)


def attribute_value(attributes, key):
    return attributes[attributes.index(key) + 1]


def test_native_cylinder_preserves_conductor_material_and_solve_inside():
    geometry = load_geometry_module()
    editor = FakeEditor()

    result = geometry._cylinder(
        FakeHfss(editor),
        "via",
        ["x1", "y1", "0mm"],
        "r_tsv",
        "-inter_h",
        "copper",
    )

    parameters, attributes = editor.cylinder_calls[0]
    assert result == "via"
    assert parameters[parameters.index("Radius:=") + 1] == "r_tsv"
    assert parameters[parameters.index("Height:=") + 1] == "-inter_h"
    assert attribute_value(attributes, "MaterialValue:=") == '"copper"'
    assert attribute_value(attributes, "SolveInside:=") is False
    assert editor.lookups == ["via"]


def test_native_box_preserves_dielectric_material_and_solve_inside():
    geometry = load_geometry_module()
    editor = FakeEditor()

    result = geometry._box(
        FakeHfss(editor),
        "substrate",
        ["0mm", "0mm", "0mm"],
        ["1mm", "2mm", "3mm"],
        "silicon_dioxide",
    )

    parameters, attributes = editor.box_calls[0]
    assert result == "substrate"
    assert parameters[parameters.index("ZSize:=") + 1] == "3mm"
    assert attribute_value(attributes, "MaterialValue:=") == '"silicon_dioxide"'
    assert attribute_value(attributes, "SolveInside:=") is True
    assert editor.lookups == ["substrate"]


def test_native_attributes_reject_unknown_material_physics():
    geometry = load_geometry_module()

    with pytest.raises(ValueError, match="explicit SolveInside rule"):
        geometry._native_object_attributes("unknown", "unreviewed_material")


def test_native_sphere_preserves_solder_conductor_physics():
    geometry = load_geometry_module()
    editor = FakeEditor()
    solder = "Solder Ecosol TSC Sn-3.8Ag-0.7Cu"

    result = geometry._sphere(
        FakeHfss(editor),
        "bga",
        ["x1", "y1", "z1"],
        "r_bga",
        solder,
    )

    parameters, attributes = editor.sphere_calls[0]
    assert result == "bga"
    assert parameters[parameters.index("Radius:=") + 1] == "r_bga"
    assert attribute_value(attributes, "MaterialValue:=") == '"%s"' % solder
    assert attribute_value(attributes, "SolveInside:=") is False


def test_native_material_classification_covers_every_builder_material():
    geometry = load_geometry_module()
    materials = load_materials_module()

    classified = geometry._DIELECTRIC_MATERIALS | geometry._CONDUCTOR_MATERIALS
    required = {name.lower() for name in materials.REQUIRED_MATERIALS}

    assert classified == required
    for name, properties in materials.SOURCE_MATERIAL_PROPERTIES.items():
        attributes = geometry._native_object_attributes("probe", name)
        expected_solve_inside = "conductivity" not in properties
        assert attribute_value(attributes, "SolveInside:=") is expected_solve_inside
