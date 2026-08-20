from __future__ import annotations

from pathlib import Path

from ansys.aedt.core import Hfss

from .analysis import assign_boundaries_and_ports, create_analysis, create_reports
from .coordinates import create_coordinate_systems
from .geometry import (
    build_bga_transition,
    build_interposer_1,
    build_interposer_2,
    build_ports_and_pec_sheets,
    build_radiation_region,
)
from .materials import ensure_materials
from .parameters import apply_parameters
from .validation import assert_framework


def build_design(
    hfss,
    include_radiation_region=False,
    framework_only=False,
    milestone=None,
    parameter_overrides=None,
    progress_callback=None,
    stage_prefix="design",
):
    if progress_callback:
        progress_callback(stage_prefix + ":parameters:start")
    apply_parameters(hfss, overrides=parameter_overrides)
    if progress_callback:
        progress_callback(stage_prefix + ":parameters:complete")
    ensure_materials(hfss)
    if progress_callback:
        progress_callback(stage_prefix + ":materials:complete")
    create_coordinate_systems(hfss)
    if progress_callback:
        progress_callback(stage_prefix + ":coordinates:complete")
    result = assert_framework(hfss)
    if progress_callback:
        progress_callback(stage_prefix + ":framework_validation:complete", result)
    if framework_only:
        return result
    result["built_objects"] = build_interposer_1(
        hfss,
        progress_callback=progress_callback,
        stage_prefix=stage_prefix,
        milestone=milestone,
    )
    if milestone == "interposer1_foundation":
        return result
    result["built_objects"].extend(build_bga_transition(hfss))
    if progress_callback:
        progress_callback(stage_prefix + ":bga_transition:complete", {"objects": len(result["built_objects"])})
    if milestone == "bga_transition":
        return result
    result["built_objects"].extend(build_interposer_2(hfss))
    if progress_callback:
        progress_callback(stage_prefix + ":interposer2:complete", {"objects": len(result["built_objects"])})
    if milestone == "interposer2":
        return result
    result["built_objects"].extend(build_ports_and_pec_sheets(hfss))
    if progress_callback:
        progress_callback(stage_prefix + ":geometry:complete", {"objects": len(result["built_objects"])})
    if milestone == "geometry_complete":
        return result
    if include_radiation_region:
        result["built_objects"].extend(build_radiation_region(hfss))
    assign_boundaries_and_ports(hfss, include_radiation_region=include_radiation_region)
    if progress_callback:
        progress_callback(stage_prefix + ":boundaries_and_ports:complete")
    create_analysis(
        hfss,
        progress_callback=progress_callback,
        stage_prefix=stage_prefix,
    )
    create_reports(hfss)
    if progress_callback:
        progress_callback(stage_prefix + ":reports:complete")
    if progress_callback:
        progress_callback(stage_prefix + ":analysis_and_reports:complete", {"objects": len(result["built_objects"])})
    return result


def build_project(
    output_path,
    framework_only=False,
    non_graphical=True,
    milestone=None,
    parameter_overrides=None,
    progress_callback=None,
):
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    hfss = Hfss(
        project=str(output_path),
        design="interposer_temple4",
        solution_type="Modal",
        version="2025.1",
        non_graphical=non_graphical,
        new_desktop=True,
        close_on_exit=True,
    )
    try:
        if progress_callback:
            progress_callback("aedt_session:ready", {"design": "interposer_temple4"})
        design_result = build_design(
            hfss,
            include_radiation_region=True,
            framework_only=framework_only,
            milestone=milestone,
            parameter_overrides=parameter_overrides,
            progress_callback=progress_callback,
            stage_prefix="interposer_temple4",
        )
        hfss.save_project(str(output_path))
        if progress_callback:
            progress_callback("project_saved", {"output": str(output_path)})
        return {
            "design_name": "interposer_temple4",
            "design": design_result,
            "output": str(output_path),
        }
    finally:
        hfss.release_desktop(close_projects=True, close_desktop=True)
