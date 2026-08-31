from __future__ import annotations


EXPECTED_PARAMETERS = 56
EXPECTED_COORDINATES = {"Global", "RelativeCS1", "RelativeCS2", "RelativeCS3", "RelativeCS4"}


def validate_framework(hfss):
    variables = set(hfss.variable_manager.design_variable_names)
    coordinate_systems = {item.name for item in hfss.modeler.coordinate_systems}
    coordinate_systems.add("Global")
    return {
        "parameter_count": len(variables),
        "parameter_count_ok": len(variables) == EXPECTED_PARAMETERS,
        "coordinate_systems": sorted(coordinate_systems),
        "coordinate_systems_ok": EXPECTED_COORDINATES.issubset(coordinate_systems),
    }


def assert_framework(hfss):
    result = validate_framework(hfss)
    if not result["parameter_count_ok"] or not result["coordinate_systems_ok"]:
        raise RuntimeError("Builder framework validation failed: %r" % result)
    return result
