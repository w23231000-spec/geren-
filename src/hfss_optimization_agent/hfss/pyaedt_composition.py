"""Composition helpers for the explicitly enabled real PyAEDT worker."""

from __future__ import annotations

import os
from pathlib import Path

from .contracts import (
    BuilderAttestation,
    HFSSRunContract,
    attest_builder,
    verify_builder_attestation,
)
from .guarded_adapter import GuardedHFSSAdapter, GuardedHFSSConfig
from .worker_backend import JsonSubprocessHFSSBackend, JsonWorkerConfig


def compose_pyaedt_hfss(
    *,
    contract: HFSSRunContract,
    pyaedt_python: Path,
    builder_source_root: Path,
    artifact_root: Path,
    task_id: str,
    solve_timeout_seconds: float = 7200.0,
    build_timeout_seconds: float = 1800.0,
    extract_timeout_seconds: float = 600.0,
    heartbeat_timeout_seconds: float = 120.0,
    license_wait_seconds: float = 60.0,
    aedt_version: str = "2025.1",
    non_graphical: bool = True,
    cores: int = 4,
    tasks: int = 1,
    gpus: int = 0,
    builder_attestation: BuilderAttestation | None = None,
) -> GuardedHFSSAdapter:
    """Create a process-isolated real adapter without importing PyAEDT in the Agent process."""

    interpreter = pyaedt_python.resolve()
    builder_root = builder_source_root.resolve()
    if not interpreter.is_file():
        raise FileNotFoundError(f"PyAEDT Python interpreter does not exist: {interpreter}")
    if not (builder_root / "nine_parameter_builder.py").is_file():
        raise FileNotFoundError(f"Supplied HFSS builder does not exist: {builder_root}")
    if builder_attestation is None:
        builder_attestation = attest_builder(builder_root, contract.builder_id)
    elif builder_attestation.builder_id != contract.builder_id:
        raise ValueError("Builder attestation ID differs from HFSS contract")
    else:
        verify_builder_attestation(builder_root, builder_attestation)
    package_src = Path(__file__).resolve().parents[2]
    existing_pythonpath = os.environ.get("PYTHONPATH")
    pythonpath = str(package_src)
    if existing_pythonpath:
        pythonpath = os.pathsep.join((pythonpath, existing_pythonpath))
    backend = JsonSubprocessHFSSBackend(
        JsonWorkerConfig(
            command_prefix=(
                str(interpreter),
                "-m",
                "hfss_optimization_agent.hfss.pyaedt_worker",
            ),
            build_timeout_seconds=build_timeout_seconds,
            extract_timeout_seconds=extract_timeout_seconds,
            builder_attestation=builder_attestation,
            heartbeat_timeout_seconds=heartbeat_timeout_seconds,
            termination_grace_seconds=5.0,
            environment={
                "PYTHONPATH": pythonpath,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
            worker_options={
                "builder_source_root": str(builder_root),
                "aedt_version": aedt_version,
                "non_graphical": non_graphical,
                "cores": cores,
                "tasks": tasks,
                "gpus": gpus,
                "use_auto_settings": True,
                "pyaedt_screen_logs": False,
                "project_filename": "pa_multi.aedt",
            },
        )
    )
    root = artifact_root.resolve()
    return GuardedHFSSAdapter(
        backend=backend,
        contract=contract,
        config=GuardedHFSSConfig(
            workspace_root=root / task_id / "hfss_workspaces",
            license_lock_path=root / ".locks" / f"aedt-{aedt_version.replace('.', '_')}.lock",
            solve_timeout_seconds=solve_timeout_seconds,
            license_wait_seconds=license_wait_seconds,
            require_process_isolation=True,
            preserve_failed_workspace=True,
        ),
    )
