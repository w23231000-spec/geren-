"""Read-only presentation preflight; it never imports PyAEDT in-process or starts AEDT."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

from hfss_optimization_agent.harness.license_lock import FileLicenseLock
from hfss_optimization_agent.harness.terminal import configure_utf8_output


ROOT = Path(__file__).resolve().parent


def _check(label: str, condition: bool, detail: str) -> bool:
    print(f"[{'通过' if condition else '失败'}] {label}：{detail}")
    return condition


def _check_license_lock(lock_path: Path) -> bool:
    """Report active and stale Agent locks without changing the filesystem."""

    if not lock_path.exists():
        return _check("HFSS Agent 锁", True, "空闲")
    try:
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        pid = int(owner["pid"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return _check("HFSS Agent 锁", False, f"锁文件无效：{lock_path}")
    if FileLicenseLock.pid_is_alive(pid):
        return _check("HFSS Agent 锁", False, f"Agent 进程正在运行，PID={pid}")
    return _check(
        "HFSS Agent 锁",
        True,
        f"检测到已退出的 PID={pid}；下次真实运行会自动回收",
    )


def main() -> int:
    configure_utf8_output()
    configuration = json.loads((ROOT / "runtime_config.json").read_text(encoding="utf-8"))
    pyaedt_python = Path(configuration["pyaedt_python"])
    aedt_exe = Path(configuration["aedt_root"]) / "ansysedt.exe"
    artifact_root = Path(configuration["artifact_root"])
    checks = [
        _check("Agent Python", Path(sys.executable).is_file(), sys.executable),
        _check("LangGraph", bool(importlib.metadata.version("langgraph")), importlib.metadata.version("langgraph")),
        _check("PyAEDT Python", pyaedt_python.is_file(), str(pyaedt_python)),
        _check("AEDT 2025.1", aedt_exe.is_file(), str(aedt_exe)),
        _check("HFSS 建模模块", (ROOT / "vendor" / "hfss_builder" / "nine_parameter_builder.py").is_file(), "已内置"),
        _check("优化模块", (ROOT / "vendor" / "optimizer" / "app" / "run.py").is_file(), "已内置"),
        _check("HFSS 运行合同", (ROOT / "config" / "hfss_contract.pa_multi_2025_1.json").is_file(), "interposer_temple4"),
        _check("AEDT 界面可见", bool(configuration.get("hfss_ui_visible")), str(configuration.get("hfss_ui_visible"))),
        _check("产物目录", artifact_root.parent.is_dir(), str(artifact_root)),
        _check_license_lock(artifact_root / ".locks" / "aedt-2025_1.lock"),
    ]
    if pyaedt_python.is_file():
        completed = subprocess.run(
            [
                str(pyaedt_python),
                "-c",
                "import importlib.metadata as m; print(m.version('pyaedt'))",
            ],
            capture_output=True,
            text=True,
            timeout=20.0,
            check=False,
            shell=False,
        )
        version = completed.stdout.strip() if completed.returncode == 0 else completed.stderr.strip()
        checks.append(_check("PyAEDT package", completed.returncode == 0, version))
    print("\n说明：环境预检不占用 HFSS 许可证；许可证是否可用只能在 AEDT 启动后确认。")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
