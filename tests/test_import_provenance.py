"""Regression coverage for the repository-local editable installation."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess


def test_project_venv_imports_package_from_current_repository():
    repository_root = Path(__file__).resolve().parents[1]
    src_root = (repository_root / "src").resolve()
    venv_python = repository_root / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            str(venv_python),
            "-c",
            "import hfss_optimization_agent; print(hfss_optimization_agent.__file__)",
        ],
        cwd=repository_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    package_file = Path(completed.stdout.strip()).resolve()
    assert package_file.is_relative_to(src_root), (
        f"project .venv imported {package_file}, expected a package under {src_root}"
    )
