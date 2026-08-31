"""Isolated PyAEDT worker for the supplied PA_MULTI builder and two-port extraction."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..harness.process_supervisor import worker_heartbeat_from_environment
from ..harness.terminal import configure_utf8_output, emit_stage, emit_status
from .contracts import (
    BuilderAttestation,
    HFSSCompositeRequest,
    SweepContract,
    validate_sweep_frequency_grid,
    verify_builder_attestation,
)


_BUILD_STAGE_TOTAL = 13
_ACTIVE_DESIGN_COMPAT_MARKER = "_hfss_agent_active_design_compat_v1"


def _resolve_active_design(
    project_object,
    name: str,
    *,
    timeout_seconds: float = 30.0,
    application_refresher=None,
):
    """Resolve a gRPC design object when ``SetActiveDesign`` returns bool/None.

    PyAEDT 0.18.1 assumes the gRPC call returns an object, but AEDT 2025 R1 can
    acknowledge the call with ``True`` or ``None`` before the design object is
    queryable.  Poll only the exact requested design; never select a fallback.
    """

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    observed_designs: tuple[str, ...] = ()
    application_refreshed = False
    try:
        requested_project_name = str(project_object.GetName())
    except Exception:
        requested_project_name = ""
    while True:
        for method_name, arguments in (
            # AEDT can acknowledge InsertDesign before the new design is visible
            # through gRPC. Retrying activation is what crosses that boundary;
            # one early SetActiveDesign followed only by reads does not.
            ("SetActiveDesign", (name,)),
            ("GetDesign", (name,)),
            ("GetActiveDesign", ()),
        ):
            method = getattr(project_object, method_name, None)
            if not callable(method):
                continue
            try:
                candidate = method(*arguments)
                if (
                    candidate is not None
                    and not isinstance(candidate, bool)
                    and hasattr(candidate, "GetName")
                    and str(candidate.GetName()) == name
                ):
                    return candidate
            except Exception:
                pass
        if application_refresher is not None and not application_refreshed:
            application_refreshed = True
            try:
                refreshed_desktop = application_refresher()
                refreshed_project = None
                if requested_project_name:
                    set_project = getattr(refreshed_desktop, "SetActiveProject", None)
                    if callable(set_project):
                        refreshed_project = set_project(requested_project_name)
                if refreshed_project is None:
                    get_project = getattr(refreshed_desktop, "GetActiveProject", None)
                    if callable(get_project):
                        refreshed_project = get_project()
                if refreshed_project is not None:
                    refreshed_name = str(refreshed_project.GetName())
                    if requested_project_name and refreshed_name != requested_project_name:
                        raise RuntimeError(
                            "refreshed AEDT application selected the wrong project"
                        )
                    project_object = refreshed_project
                    continue
            except Exception:
                pass
        list_designs = getattr(project_object, "GetTopDesignList", None)
        if callable(list_designs):
            try:
                observed_designs = tuple(
                    str(value).rsplit(";", 1)[-1] for value in list_designs()
                )
            except Exception:
                pass
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"AEDT did not expose the exact active design {name!r} within "
                f"{timeout_seconds:.1f}s; observed top designs={observed_designs!r}; "
                f"application_refreshed={application_refreshed}"
            )
        time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))


def _install_pyaedt_active_design_compatibility() -> None:
    """Install the narrow PyAEDT 0.18.1/AEDT 2025 R1 gRPC compatibility hook."""

    from ansys.aedt.core.desktop import Desktop

    if getattr(Desktop, _ACTIVE_DESIGN_COMPAT_MARKER, False):
        return
    original = Desktop.active_design

    def active_design(self, project_object=None, name=None, design_type=None):
        if project_object is not None and isinstance(name, str) and name:
            refresher = None
            if getattr(self, "is_grpc_api", False) and getattr(
                self, "grpc_plugin", None
            ) is not None:
                def refresh_application():
                    refreshed = self.grpc_plugin.recreate_application(True)
                    self._odesktop = refreshed
                    return refreshed

                refresher = refresh_application
            return _resolve_active_design(
                project_object,
                name,
                application_refresher=refresher,
            )
        return original(
            self,
            project_object=project_object,
            name=name,
            design_type=design_type,
        )

    Desktop.active_design = active_design
    setattr(Desktop, _ACTIVE_DESIGN_COMPAT_MARKER, True)


def _builder_stage_display(stage: str) -> tuple[int, str] | None:
    """Translate internal Builder events into concise Chinese terminal stages."""

    direct = {
        "worker_ready": (1, "建模进程就绪"),
        "aedt_session:ready": (2, "AEDT 会话就绪"),
        "project_saved": (13, "保存 HFSS 工程"),
        "build_complete": (13, "HFSS 工程创建完成"),
    }
    if stage in direct:
        return direct[stage]
    if ":" not in stage:
        return None
    design, event = stage.split(":", 1)
    design_names = {"interposer_temple4": "目标设计 interposer_temple4"}
    if design not in design_names:
        return None
    base = 3
    event_stages = {
        "parameters:start": (0, "加载参数"),
        "parameters:complete": (0, "加载参数"),
        "materials:complete": (1, "配置材料"),
        "coordinates:complete": (2, "建立坐标与参数框架"),
        "framework_validation:complete": (2, "建立坐标与参数框架"),
        "first_geometry:start": (3, "构建基础几何并调整视图"),
        "first_geometry:complete": (3, "构建基础几何并调整视图"),
        "view_fit:complete": (3, "构建基础几何并调整视图"),
        "interposer1_foundation:complete": (3, "构建基础几何并调整视图"),
        "interposer1_arrays:complete": (4, "生成阵列结构"),
        "interposer1_layers:complete": (5, "生成层结构"),
        "bga_transition:complete": (6, "生成 BGA 过渡结构"),
        "interposer2:complete": (7, "生成第二互连结构"),
        "geometry:complete": (8, "完成全部几何"),
        "boundaries_and_ports:complete": (9, "配置边界和端口"),
        "setup:complete": (9, "创建求解设置 Setup1"),
        "sweep:complete": (9, "创建频率扫描 Sweep"),
        "reports:complete": (9, "创建 S 参数报告"),
        "analysis_and_reports:complete": (9, "配置端口、边界和扫频"),
    }
    mapped = event_stages.get(event)
    if mapped is None:
        return None
    offset, title = mapped
    return base + offset, f"{design_names[design]}：{title}"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _worker_options(request: dict[str, Any]) -> dict[str, Any]:
    value = request.get("worker_options", {})
    if not isinstance(value, dict):
        raise ValueError("worker_options must be an object")
    return value


def _aedt_version(options: dict[str, Any]) -> str:
    return str(options.get("aedt_version", "2025.1"))


def _logical_expressions(contract: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    ports = contract.get("ports")
    if not isinstance(ports, (list, tuple)) or len(ports) != 2:
        raise ValueError("HFSS contract must contain exactly two ports")
    names = [str(port["exported_name"]) for port in ports]
    matrix = [
        [f"S({names[0]},{names[0]})", f"S({names[0]},{names[1]})"],
        [f"S({names[1]},{names[0]})", f"S({names[1]},{names[1]})"],
    ]
    return [expression for row in matrix for expression in row], matrix


def _frequency_multiplier(unit: str | None) -> float:
    normalized = (unit or "Hz").strip().lower()
    values = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12}
    if normalized not in values:
        raise ValueError(f"Unsupported HFSS frequency unit {unit!r}")
    return values[normalized]


def _candidate_values(request: dict[str, Any], contract: dict[str, Any]) -> dict[str, float]:
    candidate = request.get("candidate")
    if not isinstance(candidate, dict) or not isinstance(candidate.get("values"), dict):
        raise ValueError("Build request requires candidate.values")
    values = {str(name): float(value) for name, value in candidate["values"].items()}
    expected = set(contract.get("parameter_mapping", {}))
    if set(values) != expected:
        raise ValueError(
            f"Candidate/contract parameter mismatch; missing={sorted(expected-set(values))}, "
            f"extra={sorted(set(values)-expected)}"
        )
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("Candidate parameters must be finite")
    return values


def _open_hfss(project_path: Path, contract: dict[str, Any], options: dict[str, Any]):
    from ansys.aedt.core import Hfss, settings

    settings.enable_screen_logs = bool(options.get("pyaedt_screen_logs", False))
    _install_pyaedt_active_design_compatibility()

    return Hfss(
        project=str(project_path),
        design=str(contract["design_name"]),
        solution_type=str(contract.get("solution_type", "Modal")),
        version=_aedt_version(options),
        non_graphical=bool(options.get("non_graphical", True)),
        new_desktop=True,
        close_on_exit=True,
        remove_lock=False,
    )


def _assert_design_and_setup(hfss, contract: dict[str, Any]) -> None:
    expected_design = str(contract["design_name"])
    if str(hfss.design_name) != expected_design:
        raise RuntimeError(
            f"Active design is {hfss.design_name!r}; refusing to operate outside {expected_design!r}"
        )
    setup_name = str(contract["setup_name"])
    if setup_name not in list(hfss.setup_names):
        raise RuntimeError(f"Required setup {setup_name!r} is absent from {expected_design!r}")


def _build(request: dict[str, Any]) -> dict[str, Any]:
    contract = request["contract"]
    options = _worker_options(request)
    builder_root = Path(str(options["builder_source_root"])).resolve()
    if not (builder_root / "nine_parameter_builder.py").is_file():
        raise FileNotFoundError(f"Supplied nine-parameter builder is missing: {builder_root}")
    attestation_raw = request.get("builder_attestation")
    if attestation_raw is not None:
        verify_builder_attestation(
            builder_root, BuilderAttestation.from_dict(attestation_raw)
        )
    workspace = Path(str(request["workspace"])).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    progress_path = workspace / "build_progress.json"
    last_displayed: tuple[int, str] | None = None

    def report(stage: str, metadata: dict[str, Any] | None = None) -> None:
        nonlocal last_displayed
        payload = {
            "stage": stage,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": dict(metadata or {}),
        }
        _write_json(progress_path, payload)
        displayed = _builder_stage_display(stage)
        if displayed is not None and displayed != last_displayed:
            emit_stage("HFSS 建模", displayed[0], _BUILD_STAGE_TOTAL, displayed[1])
            last_displayed = displayed

    project_path = workspace / str(options.get("project_filename", "pa_multi.aedt"))
    if project_path.exists():
        raise FileExistsError(f"Refusing to overwrite HFSS project: {project_path}")
    sys.path.insert(0, str(builder_root))
    try:
        from ansys.aedt.core import settings

        settings.enable_screen_logs = bool(options.get("pyaedt_screen_logs", False))
        _install_pyaedt_active_design_compatibility()
        from nine_parameter_builder import build_from_nine_parameters

        report("worker_ready", {"project_path": str(project_path)})
        result = build_from_nine_parameters(
            _candidate_values(request, contract),
            project_path,
            non_graphical=bool(options.get("non_graphical", True)),
            progress_callback=report,
        )
    finally:
        try:
            sys.path.remove(str(builder_root))
        except ValueError:
            pass
    if not project_path.is_file():
        raise RuntimeError(f"Builder returned without creating {project_path}")
    report("build_complete", {"project_path": str(project_path)})
    return {
        "status": "success",
        "project_path": str(project_path),
        "design_name": str(contract["design_name"]),
        "metadata": {
            "builder_id": contract["builder_id"],
            "builder_source_root": str(builder_root),
            "builder_result": result,
            "build_strategy": "target_design_only",
            "builder_attestation_digest": (
                attestation_raw.get("source_digest")
                if isinstance(attestation_raw, dict)
                else None
            ),
        },
    }


def _solve(request: dict[str, Any]) -> dict[str, Any]:
    contract = request["contract"]
    options = _worker_options(request)
    project = request["project"]
    project_path = Path(str(project["project_path"])).resolve()
    if str(project.get("design_name")) != str(contract["design_name"]):
        raise RuntimeError("Project design identity differs from the HFSS contract")
    emit_stage("HFSS 求解", 1, 3, "打开已建工程")
    hfss = _open_hfss(project_path, contract, options)
    try:
        emit_stage("HFSS 求解", 2, 3, "校验目标设计与求解设置")
        _assert_design_and_setup(hfss, contract)
        setup_name = str(contract["setup_name"])
        emit_stage(
            "HFSS 求解",
            3,
            3,
            "提交求解任务",
            detail=f"{contract['design_name']} / {setup_name}",
        )
        solved = hfss.analyze_setup(
            setup_name,
            cores=int(options.get("cores", 4)),
            tasks=int(options.get("tasks", 1)),
            gpus=int(options.get("gpus", 0)),
            use_auto_settings=bool(options.get("use_auto_settings", True)),
            blocking=True,
        )
        if solved is False:
            raise RuntimeError(f"HFSS analyze_setup({setup_name!r}) returned False")
        emit_status("HFSS 求解", "求解完成", detail=f"{contract['design_name']} / {setup_name}")
        hfss.save_project(str(project_path), overwrite=True)
        return {
            "status": "success",
            "project_path": str(project_path),
            "design_name": str(contract["design_name"]),
            "solution_id": f"{setup_name} : {contract['sweep']['name']}",
            "metadata": {
                "solved_design": str(contract["design_name"]),
                "build_strategy": "target_design_only",
                "aedt_version": _aedt_version(options),
            },
        }
    finally:
        hfss.release_desktop(close_projects=True, close_desktop=True)


def _extract(request: dict[str, Any]) -> dict[str, Any]:
    contract = request["contract"]
    options = _worker_options(request)
    solved = request["solved"]
    project_path = Path(str(solved["project_path"])).resolve()
    emit_stage("结果导出", 1, 3, "打开求解工程")
    hfss = _open_hfss(project_path, contract, options)
    try:
        _assert_design_and_setup(hfss, contract)
        emit_stage("结果导出", 2, 3, "读取复数 S 参数")
        expressions, matrix_expressions = _logical_expressions(contract)
        solution_id = f"{contract['setup_name']} : {contract['sweep']['name']}"
        data = hfss.post.get_solution_data(
            expressions=expressions,
            setup_sweep_name=solution_id,
            domain="Sweep",
            primary_sweep_variable="Freq",
            report_category="Modal Solution Data",
        )
        if not data:
            raise RuntimeError(f"No solution data returned for {solution_id}")
        data.enable_pandas_output = False
        frequency_unit = data.units_sweeps.get("Freq", "Hz")
        multiplier = _frequency_multiplier(frequency_unit)
        frequency_hz = [float(value) * multiplier for value in data.primary_sweep_values]
        validate_sweep_frequency_grid(frequency_hz, SweepContract(**contract["sweep"]))
        real_by_expression = {
            expression: [float(value) for value in data.data_real(expression)]
            for expression in expressions
        }
        imag_by_expression = {
            expression: [float(value) for value in data.data_imag(expression)]
            for expression in expressions
        }
        if any(
            len(values) != len(frequency_hz)
            for values in (*real_by_expression.values(), *imag_by_expression.values())
        ):
            raise RuntimeError("HFSS complex trace lengths do not match the frequency grid")
        first = [
            [[real_by_expression[expression][index] for expression in row] for row in matrix_expressions]
            for index in range(len(frequency_hz))
        ]
        second = [
            [[imag_by_expression[expression][index] for expression in row] for row in matrix_expressions]
            for index in range(len(frequency_hz))
        ]
        export_dir = project_path.parent / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        touchstone_path = export_dir / f"{project_path.stem}_{contract['design_name']}.s2p"
        emit_stage("结果导出", 3, 3, "导出 Touchstone 与结构化数据")
        exported = hfss.export_touchstone(
            setup=str(contract["setup_name"]),
            sweep=str(contract["sweep"]["name"]),
            output_file=str(touchstone_path),
            renormalization=all(bool(port.get("renormalize", True)) for port in contract["ports"]),
            impedance=float(contract["ports"][0]["reference_impedance_ohm"]),
            gamma_impedance_comments=True,
        )
        if exported is False or not touchstone_path.is_file():
            raise RuntimeError(f"HFSS did not export Touchstone file {touchstone_path}")
        structured_path = export_dir / "sparameters_real_imag.json"
        structured = {
            "frequency_hz": frequency_hz,
            "real": first,
            "imag": second,
            "port_order": [port["physical_role"] for port in contract["ports"]],
            "hfss_port_order": [port["exported_name"] for port in contract["ports"]],
            "expressions": matrix_expressions,
            "reference_impedance_ohm": float(contract["ports"][0]["reference_impedance_ohm"]),
        }
        _write_json(structured_path, structured)
        return {
            "status": "success",
            "frequency_hz": frequency_hz,
            "first": first,
            "second": second,
            "representation": "real_imag",
            "port_order": structured["port_order"],
            "reference_impedance_ohm": structured["reference_impedance_ohm"],
            "metadata": {
                "solution_id": solution_id,
                "solved_design": str(contract["design_name"]),
                "touchstone_path": str(touchstone_path),
                "structured_sparameter_path": str(structured_path),
                "frequency_unit_from_aedt": frequency_unit,
                "expressions": matrix_expressions,
            },
        }
    finally:
        hfss.release_desktop(close_projects=True, close_desktop=True)


def _execute(stage: str, request: dict[str, Any]) -> dict[str, Any]:
    if stage == "composite":
        attestation = BuilderAttestation.from_dict(request["builder_attestation"])
        composite = HFSSCompositeRequest(
            schema_version=str(request["schema_version"]),
            candidate=dict(request["candidate"]),
            contract=dict(request["contract"]),
            workspace=str(request["workspace"]),
            builder_attestation=attestation,
            worker_options=dict(request["worker_options"]),
        )
        builder_root = Path(str(composite.worker_options["builder_source_root"])).resolve()
        verify_builder_attestation(builder_root, attestation)
        build_request = composite.to_dict()
        built = _build(build_request)
        solved = _solve(
            {
                "contract": composite.contract,
                "worker_options": composite.worker_options,
                "project": built,
            }
        )
        raw = _extract(
            {
                "contract": composite.contract,
                "worker_options": composite.worker_options,
                "solved": solved,
            }
        )
        return {
            "status": "success",
            "request_digest": composite.digest,
            "builder_attestation_digest": attestation.source_digest,
            "built": built,
            "solved": solved,
            "raw": raw,
        }
    if stage == "build":
        return _build(request)
    if stage == "solve":
        return _solve(request)
    if stage == "extract":
        return _extract(request)
    raise ValueError(f"Unknown worker stage {stage!r}")


def main(argv: list[str] | None = None) -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser(prog="pyaedt-hfss-worker")
    parser.add_argument(
        "--stage", choices=("composite", "build", "solve", "extract"), required=True
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    args = parser.parse_args(argv)
    with worker_heartbeat_from_environment(native_call_safe=True):
        try:
            response = _execute(args.stage, _read_json(args.request))
        except Exception as exc:
            response = {
                "status": "error",
                "stage": args.stage,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
            _write_json(args.response, response)
            print(response["traceback"], file=sys.stderr)
            return 1
        _write_json(args.response, response)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
