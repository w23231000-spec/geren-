from __future__ import annotations


REQUIRED_MATERIALS = (
    "copper",
    "silicon",
    "silicon_dioxide",
    "pi",
    "Solder Ecosol TSC Sn-3.8Ag-0.7Cu",
    "vacuum",
)

SOURCE_MATERIAL_PROPERTIES = {
    "vacuum": {"permittivity": "1"},
    "silicon": {"permittivity": "11.9"},
    "silicon_dioxide": {"permittivity": "4"},
    "Solder Ecosol TSC Sn-3.8Ag-0.7Cu": {"conductivity": "7540000"},
    "copper": {"permeability": "0.999991", "conductivity": "58000000"},
    "pi": {"permittivity": "3.5", "dielectric_loss_tangent": "0.02"},
}


def ensure_materials(hfss):
    """Load system materials and recreate the project-only PI definition."""
    missing = []
    for name in REQUIRED_MATERIALS:
        material = hfss.materials.exists_material(name)
        if not material:
            properties = SOURCE_MATERIAL_PROPERTIES[name]
            material = hfss.materials.add_material(name, properties=properties)
        if not material:
            missing.append(name)
    if missing:
        raise RuntimeError("Required AEDT materials could not be loaded: " + ", ".join(missing))
