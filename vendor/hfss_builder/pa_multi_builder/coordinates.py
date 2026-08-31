from __future__ import annotations


COORDINATE_SYSTEMS = (
    ("RelativeCS1", "Global", ["x1", "y1", "-rdl_h-h2_sio2-h_pi"]),
    ("RelativeCS2", "RelativeCS1", ["0mm", "0mm", "-2*(r_bga-delta_bga)"]),
    ("RelativeCS3", "RelativeCS2", ["0mm", "0mm", "r_bga-delta_bga"]),
    ("RelativeCS4", "RelativeCS2", ["inter2_x", "inter2_y", "0mm"]),
)


def create_coordinate_systems(hfss):
    for name, parent, origin in COORDINATE_SYSTEMS:
        hfss.modeler.create_coordinate_system(
            origin=origin,
            reference_cs=parent,
            name=name,
            mode="axis",
            x_pointing=["1mm", "0mm", "0mm"],
            y_pointing=["0mm", "1mm", "0mm"],
        )
    hfss.modeler.set_working_coordinate_system("Global")

