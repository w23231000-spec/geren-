from __future__ import annotations


_DIELECTRIC_MATERIALS = {"pi", "silicon", "silicon_dioxide", "vacuum"}
_CONDUCTOR_MATERIALS = {"copper", "solder ecosol tsc sn-3.8ag-0.7cu"}


def _native_object_attributes(name, material):
    """Build explicit AEDT attributes without PyAEDT material re-evaluation."""
    normalized = material.lower()
    if normalized in _DIELECTRIC_MATERIALS:
        solve_inside = True
    elif normalized in _CONDUCTOR_MATERIALS:
        solve_inside = False
    else:
        raise ValueError("Material requires an explicit SolveInside rule: %s" % material)
    return [
        "NAME:Attributes",
        "Name:=",
        name,
        "Flags:=",
        "",
        "Color:=",
        "(132 132 193)",
        "Transparency:=",
        0.8 if normalized == "vacuum" else 0.2,
        "PartCoordinateSystem:=",
        "Global",
        "SolveInside:=",
        solve_inside,
        "MaterialValue:=",
        '"%s"' % material,
        "UDMId:=",
        "",
        "SurfaceMaterialValue:=",
        '"Steel-oxidised-surface"',
        "ShellElement:=",
        False,
        "ShellElementThickness:=",
        "0mm",
        "IsMaterialEditable:=",
        True,
        "UseMaterialAppearance:=",
        False,
        "IsLightweight:=",
        False,
    ]


def _box(hfss, name, origin, sizes, material):
    if len(origin) != 3 or len(sizes) != 3:
        raise ValueError("Box origin and sizes must each contain three values")
    editor = hfss.modeler.oeditor
    created = editor.CreateBox(
        [
            "NAME:BoxParameters",
            "XPosition:=",
            origin[0],
            "YPosition:=",
            origin[1],
            "ZPosition:=",
            origin[2],
            "XSize:=",
            sizes[0],
            "YSize:=",
            sizes[1],
            "ZSize:=",
            sizes[2],
        ],
        _native_object_attributes(name, material),
    )
    if created != name:
        raise RuntimeError("AEDT failed to create box %r" % name)
    editor.GetObjectIDByName(name)
    return name


def _cylinder(hfss, name, origin, radius, height, material):
    if len(origin) != 3:
        raise ValueError("Cylinder origin must contain three values")
    editor = hfss.modeler.oeditor
    created = editor.CreateCylinder(
        [
            "NAME:CylinderParameters",
            "XCenter:=",
            origin[0],
            "YCenter:=",
            origin[1],
            "ZCenter:=",
            origin[2],
            "Radius:=",
            radius,
            "Height:=",
            height,
            "WhichAxis:=",
            "Z",
            "NumSides:=",
            "0",
        ],
        _native_object_attributes(name, material),
    )
    if created != name:
        raise RuntimeError("AEDT failed to create cylinder %r" % name)
    editor.GetObjectIDByName(name)
    return name


def _sphere(hfss, name, origin, radius, material):
    if len(origin) != 3:
        raise ValueError("Sphere origin must contain three values")
    editor = hfss.modeler.oeditor
    created = editor.CreateSphere(
        [
            "NAME:SphereParameters",
            "XCenter:=",
            origin[0],
            "YCenter:=",
            origin[1],
            "ZCenter:=",
            origin[2],
            "Radius:=",
            radius,
        ],
        _native_object_attributes(name, material),
    )
    if created != name:
        raise RuntimeError("AEDT failed to create sphere %r" % name)
    editor.GetObjectIDByName(name)
    return name


def _unite_named(hfss, target_name, tool_names):
    """Unite named objects without triggering PyAEDT's unstable cache refresh.

    PyAEDT 0.18.1 calls ``cleanup_objects`` after every ``modeler.unite``.  On
    AEDT 2025 R1 that refresh can terminate the interpreter in ``none_dealloc``
    while this builder creates the large TSV arrays.  Calling the same AEDT
    editor operation directly preserves the geometry operation and avoids only
    that Python-side cache refresh.
    """
    names = [target_name] + list(tool_names)
    if len(names) < 2:
        raise ValueError("Unite requires a target and at least one tool object")

    editor = hfss.modeler.oeditor
    editor.Unite(
        ["NAME:Selections", "Selections:=", ",".join(names)],
        [
            "NAME:UniteParameters",
            "KeepOriginals:=",
            False,
            "TurnOnNBodyBoolean:=",
            True,
        ],
    )
    editor.PurgeHistory(
        [
            "NAME:Selections",
            "Selections:=",
            target_name,
            "NewPartsModelFlag:=",
            "Model",
        ]
    )
    # A missing result makes AEDT raise here; do not hide that build failure.
    editor.GetObjectIDByName(target_name)
    return target_name


def _subtract_named(hfss, blank_name, tool_names, keep_originals=True):
    hfss.modeler.subtract(blank_name, list(tool_names), keep_originals=keep_originals)
    return hfss.modeler[blank_name]


def _chamfer_edge_at(hfss, object_name, position, distance="0.1mm"):
    """Chamfer an edge selected by geometry, never by a persisted AEDT ID."""
    edge_id = hfss.modeler.get_edgeid_from_position(position, assignment=object_name)
    if edge_id == -1:
        raise RuntimeError("Could not find chamfer edge on %s at %s" % (object_name, position))
    edge = next((item for item in hfss.modeler[object_name].edges if item.id == edge_id), None)
    if edge is None or not edge.chamfer(left_distance=distance):
        raise RuntimeError("Chamfer failed on %s edge %s" % (object_name, edge_id))


def _cut_inter2_signal_chamfers(hfss, blank_name, z_position):
    """Recreate the two source corner cuts without regenerated edge IDs."""
    cuts = [
        (
            "tmp_inter2_fm2_chamfer_right",
            [
                ["x1-signal_w2/2+signal_l4", "y1-signal_l3", z_position],
                ["x1-signal_w2/2+signal_l4-0.1mm", "y1-signal_l3", z_position],
                ["x1-signal_w2/2+signal_l4", "y1-signal_l3+0.1mm", z_position],
            ],
        ),
        (
            "tmp_inter2_fm2_chamfer_left",
            [
                ["x1-signal_w2/2", "y1-signal_l3", z_position],
                ["x1-signal_w2/2+0.1mm", "y1-signal_l3", z_position],
                ["x1-signal_w2/2", "y1-signal_l3+0.1mm", z_position],
            ],
        ),
    ]
    tools = []
    for name, points in cuts:
        tool = hfss.modeler.create_polyline(
            points,
            cover_surface=True,
            close_surface=True,
            name=name,
            material="vacuum",
        )
        tool.sweep_along_vector(["0mm", "0mm", "-rdl_h"])
        tools.append(name)
    _subtract_named(hfss, blank_name, tools, keep_originals=False)


def _cut_inter2_corner(hfss, blank_name):
    """Restore the source Box24 subregion cut at the interposer-2 output edge."""
    tool_name = "tmp_%s_Box24_cut" % blank_name
    _box(
        hfss,
        tool_name,
        [
            "-inter_w/2+inter_w2",
            "y1-signal_l3+signal_l5",
            "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)",
        ],
        ["-offset_inter2", "signal_l3+inter2_y-signal_l5", "-inter_h*1.5"],
        "vacuum",
    )
    _subtract_named(hfss, blank_name, [tool_name], keep_originals=False)


def _build_tsv_composite(hfss, name, x, y):
    _cylinder(hfss, name, [x, y, "inter_h+h_sio2+h_pi"], "r_tsv", "-(inter_h+h2_sio2+h_sio2+h_pi)", "copper")
    cap = "tmp_" + name + "_cap"
    _cylinder(hfss, cap, [x, y, "inter_h+h_sio2"], "r_fm1", "rdl_h", "copper")
    _unite_named(hfss, name, [cap])


def _build_ubm_composite(hfss, name, x, y):
    _cylinder(hfss, name, [x, y, "-h2_sio2-h_pi"], "r_ubm", "-rdl_h", "copper")
    stem = "tmp_" + name + "_stem"
    _cylinder(hfss, stem, [x, y, "-h2_sio2-rdl_h"], "r_tsv", "-h_pi+rdl_h", "copper")
    _unite_named(hfss, name, [stem])


def build_interposer_1_foundation(hfss, progress_callback=None, stage_prefix="design"):
    """Build the regular, non-array interposer-1 subset."""
    created = []
    if progress_callback:
        progress_callback(stage_prefix + ":first_geometry:start", {"object": "pi2"})
    first = _box(hfss, "pi2", ["-inter_w/2", "-inter_l/2", "inter_h+h_sio2+h_pi"], ["inter_w", "inter_l", "h_pi"], "pi")
    if getattr(first, "name", "pi2") != "pi2":
        raise RuntimeError("AEDT returned an unexpected first object: %r" % getattr(first, "name", None))
    if progress_callback:
        progress_callback(stage_prefix + ":first_geometry:complete", {"object": "pi2"})
    hfss.modeler.fit_all()
    if progress_callback:
        progress_callback(stage_prefix + ":view_fit:complete", {"object": "pi2"})
    created.append("pi2")

    _box(hfss, "inter1_pad", ["inter_w/2", "-inter_l/2+l3", "inter_h"], ["-pad_w1", "pad_w1", "-rdl_h"], "copper")
    for suffix, y_offset in (("upper", "pad_w1+pad_d"), ("lower", "-pad_w1-pad_d")):
        _box(hfss, "tmp_inter1_pad_" + suffix, ["inter_w/2", "-inter_l/2+l3+(%s)" % y_offset, "inter_h"], ["-pad_w1", "pad_w1", "-rdl_h"], "copper")
    _unite_named(hfss, "inter1_pad", ["tmp_inter1_pad_upper", "tmp_inter1_pad_lower"])
    created.append("inter1_pad")

    pad_via_centers = (
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2", "inter_h"],
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2+pad_w1+pad_d", "inter_h"],
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2-pad_w1-pad_d", "inter_h"],
    )
    for index, center in enumerate(pad_via_centers):
        name = "inter1_pad_via" if index == 0 else "tmp_inter1_pad_via_%s" % index
        _cylinder(hfss, name, center, "r_fm1", "h_sio2+rdl_h", "copper")
    _unite_named(hfss, "inter1_pad_via", ["tmp_inter1_pad_via_1", "tmp_inter1_pad_via_2"])
    created.append("inter1_pad_via")

    bp1_centers = (
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2", "inter_h+h_sio2+rdl_h"],
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2-pad_d-pad_w1", "inter_h+h_sio2+rdl_h"],
        ["inter_w/2-pad_w1/2", "-inter_l/2+l1-pad_w/2+(pad_d+pad_w1)", "inter_h+h_sio2+rdl_h"],
    )
    for index, center in enumerate(bp1_centers):
        name = "inter1_bp1_via" if index == 0 else "tmp_inter1_bp1_via_%s" % index
        _cylinder(hfss, name, center, "r_tsv", "h_pi-rdl_h", "copper")
    _unite_named(hfss, "inter1_bp1_via", ["tmp_inter1_bp1_via_1", "tmp_inter1_bp1_via_2"])
    created.append("inter1_bp1_via")

    _box(hfss, "inter1_fm2_signal", ["inter_w/2", "-inter_l/2+l3", "inter_h+h_sio2+h_pi"], ["-pad_w1-delta_d", "pad_w1", "rdl_h"], "copper")
    _box(hfss, "tmp_inter1_fm2_signal_line", ["inter_w/2-pad_w1-delta_d", "-inter_l/2+l3", "inter_h+h_sio2+h_pi"], ["-signal_l1", "signal_w1", "rdl_h"], "copper")
    _cylinder(hfss, "tmp_inter1_fm2_signal_end", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "inter_h+h_sio2+h_pi"], "r1", "rdl_h", "copper")
    _unite_named(hfss, "inter1_fm2_signal", ["tmp_inter1_fm2_signal_line", "tmp_inter1_fm2_signal_end"])
    created.append("inter1_fm2_signal")

    _cylinder(hfss, "inter1_tsv_signal", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "inter_h+h_sio2+h_pi"], "r_tsv", "-(inter_h+h2_sio2+h_sio2+h_pi)", "copper")
    _cylinder(hfss, "tmp_inter1_tsv_signal_cap", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "inter_h+h_sio2"], "r_fm1", "rdl_h", "copper")
    _unite_named(hfss, "inter1_tsv_signal", ["tmp_inter1_tsv_signal_cap"])
    created.append("inter1_tsv_signal")

    _cylinder(hfss, "inter1_bm1_signal", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "-h2_sio2"], "r_fm1", "-rdl_h", "copper")
    created.append("inter1_bm1_signal")

    _cylinder(hfss, "inter1_ubm_signal", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "-h2_sio2-h_pi"], "r_ubm", "-rdl_h", "copper")
    _cylinder(hfss, "tmp_inter1_ubm_signal_stem", ["inter_w/2-pad_w1-delta_d-signal_l1", "-inter_l/2+l3+signal_w1/2", "-h2_sio2-rdl_h"], "r_tsv", "-h_pi+rdl_h", "copper")
    _unite_named(hfss, "inter1_ubm_signal", ["tmp_inter1_ubm_signal_stem"])
    created.append("inter1_ubm_signal")
    return created


def build_interposer_1_arrays(hfss):
    """Build the 39-ground-TSV and 16-ground-UBM normalized arrays."""
    sx = "x1"
    sy = "y1"
    diagonal_tsv = "offset_tsv_line/sqrt(2)"
    tsv_centers = [
        (sx, "y1-offset_tsv_line"),
        ("x1-offset_tsv_line", sy),
        (sx, "y1+offset_tsv_line"),
    ]
    for sign in (-1, 1):
        row_y = "y1%s%s" % ("+" if sign > 0 else "-", diagonal_tsv)
        tsv_centers.append(("x1-" + diagonal_tsv, row_y))
        for index in range(17):
            tsv_centers.append(("x1+%s+%d*0.12mm" % (diagonal_tsv, index), row_y))
    tsv_names = []
    for index, (x, y) in enumerate(tsv_centers):
        name = "inter1_tsv_gnd_all" if index == 0 else "tmp_inter1_tsv_gnd_%02d" % index
        _build_tsv_composite(hfss, name, x, y)
        tsv_names.append(name)
    _unite_named(hfss, "inter1_tsv_gnd_all", tsv_names[1:])

    diagonal_ubm = "offset_ubm_ubm/sqrt(2)"
    ubm_centers = [
        ("x1-offset_ubm_ubm", "y1"),
        ("x1", "y1+offset_ubm_ubm"),
        ("x1-" + diagonal_ubm, "y1-" + diagonal_ubm),
        ("x1+" + diagonal_ubm, "y1-" + diagonal_ubm),
        ("x1-" + diagonal_ubm, "y1+" + diagonal_ubm),
        ("x1+" + diagonal_ubm, "y1+" + diagonal_ubm),
    ]
    for index in range(9):
        ubm_centers.append(("x1-%s+%d*0.6mm" % (diagonal_ubm, index), "y1-%s-0.7mm" % diagonal_ubm))
    ubm_centers.append(("x1-%s+8*0.6mm+delta_x" % diagonal_ubm, "y1-%s-0.7mm+delta_y" % diagonal_ubm))
    ubm_names = []
    for index, (x, y) in enumerate(ubm_centers):
        name = "inter1_ubm_gnd" if index == 0 else "tmp_inter1_ubm_gnd_%02d" % index
        _build_ubm_composite(hfss, name, x, y)
        ubm_names.append(name)
    _unite_named(hfss, "inter1_ubm_gnd", ubm_names[1:])
    return ["inter1_tsv_gnd_all", "inter1_ubm_gnd"]


def build_interposer_1_layers(hfss):
    """Build substrate/dielectric/ground layers and cut them with named copper objects."""
    created = []
    _box(hfss, "inter1", ["-inter_w/2", "-inter_l/2", "0mm"], ["inter_w", "inter_l", "inter_h"], "silicon")
    _box(hfss, "tmp_inter1_extension", ["inter_w/2", "-inter_l/2", "0mm"], ["inter_w3", "inter_l", "inter_h1"], "silicon")
    _unite_named(hfss, "inter1", ["tmp_inter1_extension"])
    _subtract_named(hfss, "inter1", ["inter1_tsv_signal", "inter1_tsv_gnd_all"], keep_originals=True)
    created.append("inter1")

    _box(hfss, "inter1_sio2_f", ["-inter_w/2", "-inter_l/2", "inter_h"], ["inter_w", "inter_l", "h_sio2"], "silicon_dioxide")
    _subtract_named(hfss, "inter1_sio2_f", ["inter1_pad_via", "inter1_tsv_signal", "inter1_tsv_gnd_all"], keep_originals=True)
    created.append("inter1_sio2_f")

    _box(hfss, "inter1_sio2_b", ["-inter_w/2", "-inter_l/2", "0mm"], ["inter_w", "inter_l", "-h2_sio2"], "silicon_dioxide")
    _box(hfss, "tmp_inter1_sio2_b_extension", ["inter_w/2", "-inter_l/2", "0mm"], ["inter_w3", "inter_l", "-h2_sio2"], "silicon_dioxide")
    _unite_named(hfss, "inter1_sio2_b", ["tmp_inter1_sio2_b_extension"])
    _subtract_named(hfss, "inter1_sio2_b", ["inter1_tsv_signal", "inter1_tsv_gnd_all"], keep_originals=True)
    created.append("inter1_sio2_b")

    _box(hfss, "pi1", ["-inter_w/2", "-inter_l/2", "inter_h+h_sio2"], ["inter_w", "inter_l", "h_pi"], "pi")
    _subtract_named(hfss, "pi1", ["inter1_pad_via", "inter1_tsv_signal", "inter1_tsv_gnd_all"], keep_originals=True)
    created.append("pi1")

    _box(hfss, "pi3", ["-inter_w/2", "-inter_l/2", "-h2_sio2"], ["inter_w", "inter_l", "-h_pi"], "pi")
    _box(hfss, "tmp_pi3_extension", ["inter_w/2", "-inter_l/2", "-h2_sio2"], ["inter_w3", "inter_l", "-h_pi"], "pi")
    _unite_named(hfss, "pi3", ["tmp_pi3_extension"])
    _subtract_named(hfss, "pi3", ["inter1_ubm_signal", "inter1_ubm_gnd"], keep_originals=True)
    created.append("pi3")

    _box(hfss, "inter1_bm1_gnd", ["-inter_w/2", "-inter_l/2", "-h2_sio2"], ["inter_w", "inter_l", "-rdl_h"], "copper")
    clearance = "tmp_inter1_bm1_signal_clearance"
    _cylinder(hfss, clearance, ["x1", "y1", "-h2_sio2"], "r_inter1_fm2_gnd", "-rdl_h", "copper")
    _subtract_named(hfss, "inter1_bm1_gnd", [clearance], keep_originals=False)
    _box(hfss, "tmp_inter1_bm1_gnd_extension", ["inter_w/2", "-inter_l/2", "-h2_sio2"], ["inter_w3", "inter_l", "-rdl_h"], "copper")
    _unite_named(hfss, "inter1_bm1_gnd", ["tmp_inter1_bm1_gnd_extension"])
    created.append("inter1_bm1_gnd")

    _box(hfss, "inter1_fm2_gnd", ["-inter_w/2", "-inter_l/2", "inter_h+h_sio2+h_pi"], ["inter_w", "inter_l", "rdl_h"], "copper")
    _box(hfss, "tmp_chip_out", ["inter_w/2", "-inter_l/2", "inter_h+h_sio2+h_pi"], ["-pad_w1-delta_d", "inter_w", "rdl_h"], "copper")
    _subtract_named(hfss, "inter1_fm2_gnd", ["tmp_chip_out"], keep_originals=False)
    _box(hfss, "tmp_inter1_fm2_gnd_pad_lower", ["inter_w/2", "-inter_l/2+l3-pad_d", "inter_h+h_sio2+h_pi+rdl_h"], ["-pad_w1-delta_d", "-pad_w1", "-rdl_h"], "copper")
    _box(hfss, "tmp_inter1_fm2_gnd_pad_upper", ["inter_w/2", "-inter_l/2+l3+pad_w1+pad_d", "inter_h+h_sio2+h_pi+rdl_h"], ["-pad_w1-delta_d", "pad_w1", "-rdl_h"], "copper")
    _unite_named(hfss, "inter1_fm2_gnd", ["tmp_inter1_fm2_gnd_pad_lower", "tmp_inter1_fm2_gnd_pad_upper"])
    _box(hfss, "tmp_inter1_fm2_gap_pad", ["inter_w/2", "-inter_l/2+l1", "inter_h+h_sio2+h_pi"], ["-pad_w1-delta_d", "-pad_w", "rdl_h"], "copper")
    _box(hfss, "tmp_inter1_fm2_gap_line", ["inter_w/2-pad_w1-delta_d", "-inter_l/2+l1-pad_w/2-signal_w1/2-signal_d1", "inter_h+h_sio2+h_pi"], ["-signal_l1", "signal_w1+2*signal_d1", "rdl_h"], "copper")
    _cylinder(hfss, "tmp_inter1_fm2_gap_end", ["x1", "-inter_l/2+l1-pad_w/2+signal_w1/2-signal_d1", "inter_h+h_sio2+h_pi"], "r_inter1_fm2", "rdl_h", "copper")
    _unite_named(hfss, "tmp_inter1_fm2_gap_pad", ["tmp_inter1_fm2_gap_line", "tmp_inter1_fm2_gap_end"])
    _subtract_named(hfss, "inter1_fm2_gnd", ["tmp_inter1_fm2_gap_pad"], keep_originals=False)
    created.append("inter1_fm2_gnd")
    return created


def build_interposer_1(
    hfss, progress_callback=None, stage_prefix="design", milestone=None
):
    created = build_interposer_1_foundation(
        hfss, progress_callback=progress_callback, stage_prefix=stage_prefix
    )
    if progress_callback:
        progress_callback(stage_prefix + ":interposer1_foundation:complete", {"objects": len(created)})
    if milestone == "interposer1_foundation":
        return created
    created.extend(build_interposer_1_arrays(hfss))
    if progress_callback:
        progress_callback(stage_prefix + ":interposer1_arrays:complete", {"objects": len(created)})
    created.extend(build_interposer_1_layers(hfss))
    if progress_callback:
        progress_callback(stage_prefix + ":interposer1_layers:complete", {"objects": len(created)})
    return created


def build_bga_transition(hfss):
    """Build the clipped signal ball and the 16-ball ground array.

    The source history makes one sphere in ``RelativeCS1``, clips it between
    the XY planes of ``RelativeCS1`` and ``RelativeCS2``, then duplicates it.
    We reproduce the resulting solid directly as a sphere intersected with a
    parameterized box.  This avoids keeping fragile Split operation IDs while
    preserving the exact geometry and design-variable dependency.
    """
    solder = "Solder Ecosol TSC Sn-3.8Ag-0.7Cu"

    def clipped_ball(name, x, y):
        sphere_name = _sphere(
            hfss,
            name,
            [x, y, "-rdl_h-h2_sio2-h_pi-(r_bga-delta_bga)"],
            "r_bga",
            solder,
        )
        clip = "tmp_" + name + "_clip"
        _box(
            hfss,
            clip,
            [x + "-r_bga", y + "-r_bga", "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)"],
            ["2*r_bga", "2*r_bga", "2*(r_bga-delta_bga)"],
            solder,
        )
        hfss.modeler.intersect([sphere_name, clip], keep_originals=False)
        return hfss.modeler[name]

    clipped_ball("inter1to2_bga_signal", "x1", "y1")

    diagonal = "offset_ubm_ubm/sqrt(2)"
    centers = [
        ("x1", "y1+offset_ubm_ubm"),
        ("x1-offset_ubm_ubm", "y1"),
        ("x1-" + diagonal, "y1+" + diagonal),
        ("x1+" + diagonal, "y1+" + diagonal),
        ("x1-" + diagonal, "y1-" + diagonal),
        ("x1+" + diagonal, "y1-" + diagonal),
    ]
    for index in range(9):
        centers.append(("x1-%s+%d*0.6mm" % (diagonal, index), "y1-%s-0.7mm" % diagonal))
    centers.append(("x1-%s+8*0.6mm+delta_x" % diagonal, "y1-%s-0.7mm+delta_y" % diagonal))

    names = []
    for index, (x, y) in enumerate(centers):
        name = "inter1to2_bga_gnd" if index == 0 else "tmp_inter1to2_bga_gnd_%02d" % index
        clipped_ball(name, x, y)
        names.append(name)
    _unite_named(hfss, "inter1to2_bga_gnd", names[1:])
    return ["inter1to2_bga_signal", "inter1to2_bga_gnd"]


def build_interposer_2(hfss):
    """Build the mirrored second interposer and its 89-location TSV network."""
    created = []

    # Signal route on the upper redistribution layer of interposer 2.
    z_fm2 = "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)-h_pi"
    _box(hfss, "inter2_fm2_signal", ["x1-signal_w2/2", "y1", z_fm2], ["signal_w2", "-signal_l3", "-rdl_h"], "copper")
    _box(hfss, "tmp_inter2_fm2_horizontal", ["x1-signal_w2/2", "y1-signal_l3", z_fm2], ["signal_l4", "signal_w2", "-rdl_h"], "copper")
    _box(hfss, "tmp_inter2_fm2_end", ["x1-signal_w2/2+signal_l4-signal_w2", "y1-signal_l3", z_fm2], ["signal_w2", "signal_l5", "-rdl_h"], "copper")
    _cylinder(hfss, "tmp_inter2_fm2_round", ["x1", "y1", z_fm2], "signal_w2/2", "-rdl_h", "copper")
    _unite_named(hfss, "inter2_fm2_signal", ["tmp_inter2_fm2_horizontal", "tmp_inter2_fm2_end", "tmp_inter2_fm2_round"])
    _cut_inter2_signal_chamfers(hfss, "inter2_fm2_signal", z_fm2)
    created.append("inter2_fm2_signal")

    _cylinder(hfss, "inter2_fm1_signal", ["x1", "y1", "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)-2*h_pi"], "r_fm1", "-rdl_h", "copper")
    created.append("inter2_fm1_signal")

    # 89 TSV centers.  The compact formulas are reconstructed from the source
    # duplicate history and retain its 0.12 mm pitch and diagonal offset.
    d = "offset_tsv_line/sqrt(2)"
    centers = []
    for i in range(39):
        centers.append(("x1-%s+%d*0.12mm" % (d, i), "y1-%s-0.72mm" % d))
    for i in range(1, 7):
        centers.append(("x1-" + d, "y1-%s-0.72mm+%d*0.12mm" % (d, i)))
    for i in range(1, 5):
        centers.append(("x1-%s+38*0.12mm" % d, "y1-%s-0.72mm+%d*0.12mm" % (d, i)))
    mid_y = "y1-%s-0.36mm" % d
    centers.extend([("x1+" + d, mid_y), ("x1+%s+0.12mm" % d, mid_y)])
    for i in range(29):
        centers.append(("x1+%s+0.48mm+%d*0.12mm" % (d, i), mid_y))
    centers.extend(
        [
            ("x1+" + d, "y1-%s-0.24mm" % d),
            ("x1+%s+3.84mm" % d, "y1-%s-0.24mm" % d),
            ("x1+" + d, "y1-%s-0.12mm" % d),
            ("x1+" + d, "y1-" + d),
            ("x1-" + d, "y1+" + d),
            ("x1", "y1+offset_tsv_line"),
            ("x1+" + d, "y1+" + d),
            ("x1-offset_tsv_line", "y1"),
            ("x1+offset_tsv_line", "y1"),
        ]
    )
    assert len(centers) == 89

    def build_inter2_tsv(name, x, y):
        z_top = "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)-2*h_pi"
        _cylinder(hfss, name, [x, y, z_top], "r_fm1", "-rdl_h", "copper")
        _cylinder(hfss, "tmp_" + name + "_top", [x, y, z_top], "r_tsv", "h_pi-rdl_h", "copper")
        _cylinder(hfss, "tmp_" + name + "_body", [x, y, z_top + "-rdl_h"], "r_tsv", "-inter_h-h2_sio2-h_sio2", "copper")
        _unite_named(hfss, name, ["tmp_" + name + "_top", "tmp_" + name + "_body"])

    tsv_names = []
    for index, (x, y) in enumerate(centers):
        name = "inter2_tsv_gnd" if index == 0 else "tmp_inter2_tsv_gnd_%02d" % index
        build_inter2_tsv(name, x, y)
        tsv_names.append(name)
    _unite_named(hfss, "inter2_tsv_gnd", tsv_names[1:])
    created.append("inter2_tsv_gnd")

    # Mirrored signal and ground UBMs are constructed explicitly to avoid the
    # source project's mirror-operation IDs.
    z_ubm = "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)"
    _cylinder(hfss, "inter22_ubm_signal", ["x1", "y1", z_ubm], "r_ubm", "-rdl_h", "copper")
    _cylinder(hfss, "tmp_inter22_ubm_signal_stem", ["x1", "y1", z_ubm + "-rdl_h"], "r_tsv", "-h_pi+rdl_h", "copper")
    _unite_named(hfss, "inter22_ubm_signal", ["tmp_inter22_ubm_signal_stem"])
    created.append("inter22_ubm_signal")

    diagonal_ubm = "offset_ubm_ubm/sqrt(2)"
    ubm_centers = [
        ("x1-offset_ubm_ubm", "y1"), ("x1", "y1+offset_ubm_ubm"),
        ("x1-" + diagonal_ubm, "y1-" + diagonal_ubm), ("x1+" + diagonal_ubm, "y1-" + diagonal_ubm),
        ("x1-" + diagonal_ubm, "y1+" + diagonal_ubm), ("x1+" + diagonal_ubm, "y1+" + diagonal_ubm),
    ]
    for i in range(9):
        ubm_centers.append(("x1-%s+%d*0.6mm" % (diagonal_ubm, i), "y1-%s-0.7mm" % diagonal_ubm))
    ubm_centers.append(("x1-%s+8*0.6mm+delta_x" % diagonal_ubm, "y1-%s-0.7mm+delta_y" % diagonal_ubm))
    ubm_names = []
    for index, (x, y) in enumerate(ubm_centers):
        name = "inter2_ubm_gnd_new" if index == 0 else "tmp_inter2_ubm_gnd_%02d" % index
        _cylinder(hfss, name, [x, y, z_ubm], "r_ubm", "-rdl_h", "copper")
        _cylinder(hfss, "tmp_" + name + "_stem", [x, y, z_ubm + "-rdl_h"], "r_tsv", "-h_pi+rdl_h", "copper")
        _unite_named(hfss, name, ["tmp_" + name + "_stem"])
        ubm_names.append(name)
    _unite_named(hfss, "inter2_ubm_gnd_new", ubm_names[1:])
    created.append("inter2_ubm_gnd_new")

    # Output pad and its three vertical feed structures.
    pad_x = "x1-pad_w/2+signal_l4-signal_w2"
    pad_y = "y1-signal_l3+signal_l5"
    z_pad = z_fm2 + "-rdl_h-h_sio2-h_pi"
    _box(hfss, "inter2_pad", [pad_x, pad_y, z_pad], ["pad_w", "-pad_w2", "-rdl_h"], "copper")
    _box(hfss, "tmp_inter2_pad_left", [pad_x + "-pad_d", pad_y, z_pad], ["-pad_w2", "-pad_w2", "-rdl_h"], "copper")
    _box(hfss, "tmp_inter2_pad_right", ["x1+pad_d+pad_w/2+signal_l4-signal_w2", pad_y, z_pad], ["pad_w2", "-pad_w2", "-rdl_h"], "copper")
    _unite_named(hfss, "inter2_pad", ["tmp_inter2_pad_left", "tmp_inter2_pad_right"])
    created.append("inter2_pad")

    via_x = "x1+signal_l4-signal_w2"
    via_y = "y1-signal_l3+signal_l5-pad_w2/2"
    via_centers = [via_x, via_x + "-(pad_w+pad_w2)/2-pad_d", via_x + "+(pad_w+pad_w2)/2+pad_d"]
    via_names = []
    for index, x in enumerate(via_centers):
        name = "inter2_pad_via" if index == 0 else "tmp_inter2_pad_via_%d" % index
        _cylinder(hfss, name, [x, via_y, z_pad], "r_fm1", "rdl_h+h_sio2", "copper")
        _cylinder(hfss, "tmp_" + name + "_top", [x, via_y, z_fm2 + "-h_pi"], "r_tsv", "h_pi-rdl_h", "copper")
        _unite_named(hfss, name, ["tmp_" + name + "_top"])
        via_names.append(name)
    _unite_named(hfss, "inter2_pad_via", via_names[1:])
    created.append("inter2_pad_via")

    # Continuous layers.  Named copper objects are retained while used as
    # subtraction tools, so assignments never depend on transient face IDs.
    x0, y0 = "-inter_w/2", "-inter_l/2"
    z_si_top = z_fm2 + "-rdl_h-h_sio2-h_pi"
    _box(hfss, "inter2", [x0, y0, z_si_top], ["inter_w2", "inter_l", "-inter_h"], "silicon")
    _subtract_named(hfss, "inter2", ["inter2_tsv_gnd"], keep_originals=True)
    _cut_inter2_corner(hfss, "inter2")
    created.append("inter2")
    _box(hfss, "inter2_sio2_f", [x0, y0, z_si_top], ["inter_w2", "inter_l", "h_sio2"], "silicon_dioxide")
    _subtract_named(hfss, "inter2_sio2_f", ["inter2_tsv_gnd", "inter2_pad_via"], keep_originals=True)
    _cut_inter2_corner(hfss, "inter2_sio2_f")
    created.append("inter2_sio2_f")
    _box(hfss, "inter2_sio2_b", [x0, y0, z_si_top + "-inter_h"], ["inter_w2", "inter_l", "-h2_sio2"], "silicon_dioxide")
    _subtract_named(hfss, "inter2_sio2_b", ["inter2_tsv_gnd"], keep_originals=True)
    _cut_inter2_corner(hfss, "inter2_sio2_b")
    created.append("inter2_sio2_b")
    _box(hfss, "inter2_fp1", [x0, y0, z_fm2 + "-rdl_h-h_pi"], ["inter_w2", "inter_l", "h_pi"], "pi")
    _subtract_named(hfss, "inter2_fp1", ["inter2_tsv_gnd", "inter2_pad_via"], keep_originals=True)
    _cut_inter2_corner(hfss, "inter2_fp1")
    created.append("inter2_fp1")
    _box(hfss, "inter2_fp2", [x0, y0, z_fm2 + "-rdl_h"], ["inter_w2", "inter_l", "h_pi"], "pi")
    _subtract_named(hfss, "inter2_fp2", ["inter22_ubm_signal", "inter2_ubm_gnd_new"], keep_originals=True)
    _cut_inter2_corner(hfss, "inter2_fp2")
    created.append("inter2_fp2")
    _box(hfss, "inter2_bm1_gnd", [x0, y0, z_si_top + "-inter_h-h2_sio2"], ["inter_w2", "inter_l", "-rdl_h"], "copper")
    _cut_inter2_corner(hfss, "inter2_bm1_gnd")
    created.append("inter2_bm1_gnd")
    _box(hfss, "inter2_bp1", [x0, y0, z_si_top + "-inter_h-h2_sio2"], ["inter_w2", "inter_l", "-h_pi"], "pi")
    _cut_inter2_corner(hfss, "inter2_bp1")
    created.append("inter2_bp1")
    _box(hfss, "inter2_fm2_gnd", [x0, y0, z_fm2], ["inter_w2", "inter_l", "-rdl_h"], "copper")
    clearance = "tmp_inter2_fm2_clearance"
    # Source Box20: clearance around the vertical signal stem.  This piece is
    # essential; a bounding-box-only regression cannot detect its omission
    # because the ground plane keeps the same outer extents.
    _box(
        hfss,
        clearance,
        ["x1-signal_w2/2-signal_d2", "y1", z_fm2],
        ["signal_w2+2*signal_d2", "-signal_l3", "-rdl_h"],
        "copper",
    )
    horizontal_clearance = "tmp_inter2_fm2_clearance_horizontal"
    _box(hfss, horizontal_clearance, ["x1-signal_w2/2-signal_d2", "y1-signal_l3-signal_d2", z_fm2], ["signal_l4+2*signal_d2", "signal_w2+2*signal_d2", "-rdl_h"], "copper")
    _cylinder(hfss, "tmp_inter2_fm2_clearance_round", ["x1", "y1", z_fm2], "r_inter2_fm2", "-rdl_h", "copper")
    _box(hfss, "tmp_inter2_fm2_clearance_end", ["x1-signal_w2/2+signal_l4-signal_w2-signal_d2", "y1-signal_l3-signal_d2", z_fm2], ["signal_w2+2*signal_d2", "signal_l5+2*signal_d2", "-rdl_h"], "copper")
    _unite_named(
        hfss,
        clearance,
        [horizontal_clearance, "tmp_inter2_fm2_clearance_round", "tmp_inter2_fm2_clearance_end"],
    )
    _subtract_named(hfss, "inter2_fm2_gnd", [clearance], keep_originals=False)
    _cut_inter2_corner(hfss, "inter2_fm2_gnd")
    created.append("inter2_fm2_gnd")
    return created


def build_ports_and_pec_sheets(hfss):
    """Create stable, explicitly named modal-port and PEC reference sheets."""
    # Input side: sheet lies in the global YZ plane (normal X).
    hfss.modeler.create_rectangle(
        "YZ",
        ["inter_w/2", "-inter_l/2+l1-pad_w/2-signal_w1/2", "inter_h-rdl_h"],
        ["pad_w1", "-port_h"],
        name="Rectangle1",
    )
    hfss.modeler.create_rectangle(
        "YZ",
        ["inter_w/2", "-inter_l/2+l1-pad_w/2-signal_w1/2-pad_d-pad_w1", "inter_h-rdl_h"],
        ["pad_w1*3+2*pad_d", "-port_h*2"],
        name="Rectangle8",
    )
    input_cut = "tmp_Rectangle8_cut"
    hfss.modeler.create_rectangle(
        "YZ",
        ["inter_w/2", "-inter_l/2+l1-pad_w/2-signal_w1/2-pad_d", "inter_h-rdl_h"],
        ["pad_w1+2*pad_d", "-port_h"],
        name=input_cut,
    )
    _subtract_named(hfss, "Rectangle8", [input_cut], keep_originals=False)

    # Output side: sheet lies in the global XZ plane (normal Y).  Global
    # formulas replace RelativeCS2 coordinates so assignments remain explicit.
    output_y = "y1-signal_l3+signal_l5"
    output_z = "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)-2*h_pi-rdl_h-h_sio2-rdl_h"
    hfss.modeler.create_rectangle(
        "XZ",
        ["x1-pad_w/2+signal_l4-signal_w2", output_y, output_z],
        ["-port_h", "pad_w"],
        name="Rectangle4",
    )
    hfss.modeler.create_rectangle(
        "XZ",
        ["x1-pad_w/2+signal_l4-signal_w2-pad_d-pad_w2", output_y, output_z],
        ["-port_h*2", "pad_w+2*pad_d+2*pad_w2"],
        name="Rectangle6",
    )
    output_cut = "tmp_Rectangle6_cut"
    hfss.modeler.create_rectangle(
        "XZ",
        ["x1-pad_w/2+signal_l4-signal_w2-pad_d", output_y, output_z],
        ["-port_h", "pad_w+2*pad_d"],
        name=output_cut,
    )
    _subtract_named(hfss, "Rectangle6", [output_cut], keep_originals=False)
    return ["Rectangle1", "Rectangle4", "Rectangle6", "Rectangle8"]


def build_radiation_region(hfss):
    region = hfss.modeler.create_region(
        ["0.5mm", "0mm", "0mm", "0mm", "3*inter_h", "0mm"],
        pad_type="Absolute Offset",
        name="RadiatingSurface",
    )
    region.material_name = "vacuum"
    return [region.name]
