"""Cross-process atomic file lock for serializing access to a configured HFSS license slot."""

import json
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import HFSSLicenseLockError


@dataclass(frozen=True, slots=True)
class LicenseLockConfig:
    path: Path
    acquire_timeout_seconds: float = 30.0
    poll_interval_seconds: float = 0.1

    def __post_init__(self) -> None:
        if self.acquire_timeout_seconds < 0.0:
            raise ValueError("License lock timeout cannot be negative")
        if not 0.01 <= self.poll_interval_seconds <= 5.0:
            raise ValueError("License lock poll interval must be between 0.01 and 5 seconds")


class FileLicenseLock:
    def __init__(self, config: LicenseLockConfig) -> None:
        self.config = config
        self.token = uuid.uuid4().hex
        self.acquired = False
        self.quarantined = False

    @staticmethod
    def pid_is_alive(pid: int) -> bool:
        """Return whether a process exists without sending it a signal on Windows."""
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel32.GetExitCodeProcess.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if handle:
                exit_code = wintypes.DWORD()
                queried = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return bool(queried and exit_code.value == still_active)
            # Access denied still proves that the process exists.
            return ctypes.get_last_error() == 5
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def _reclaim_stale_lock(self, path: Path) -> bool:
        """Remove a lock only when its recorded owner process is certainly gone."""

        try:
            original = path.read_text(encoding="utf-8")
            owner = json.loads(original)
            pid = int(owner["pid"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        if owner.get("status") == "QUARANTINED" or self.pid_is_alive(pid):
            return False
        try:
            if path.read_text(encoding="utf-8") != original:
                return False
            path.unlink()
        except (FileNotFoundError, OSError):
            return False
        return True

    def acquire(self) -> None:
        path = self.config.path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.config.acquire_timeout_seconds
        payload = json.dumps(
            {
                "token": self.token,
                "pid": os.getpid(),
                "status": "ACTIVE",
                "acquired_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        while True:
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(descriptor, payload)
                finally:
                    os.close(descriptor)
                self.acquired = True
                return
            except FileExistsError:
                try:
                    existing = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
                if existing.get("status") == "QUARANTINED":
                    raise HFSSLicenseLockError(
                        f"HFSS license lock is quarantined pending operator reconciliation: {path}"
                    )
                if self._reclaim_stale_lock(path):
                    continue
                if time.monotonic() >= deadline:
                    raise HFSSLicenseLockError(f"Timed out waiting for HFSS license lock: {path}")
                time.sleep(self.config.poll_interval_seconds)

    def release(self) -> None:
        if not self.acquired:
            return
        if self.quarantined:
            self.acquired = False
            return
        path = self.config.path.resolve()
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            self.acquired = False
            raise HFSSLicenseLockError(f"HFSS license lock ownership cannot be verified: {path}") from exc
        if owner.get("token") != self.token:
            self.acquired = False
            raise HFSSLicenseLockError(f"HFSS license lock ownership changed unexpectedly: {path}")
        path.unlink()
        self.acquired = False

    def quarantine(self, reason: str, *, evidence: dict | None = None) -> None:
        """Keep the lock as a durable fail-closed marker after uncertain cleanup."""

        if not self.acquired:
            raise HFSSLicenseLockError("cannot quarantine a license lock that is not held")
        path = self.config.path.resolve()
        try:
            owner = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HFSSLicenseLockError(
                f"HFSS license lock cannot be quarantined safely: {path}"
            ) from exc
        if owner.get("token") != self.token:
            raise HFSSLicenseLockError(
                f"HFSS license lock ownership changed before quarantine: {path}"
            )
        owner.update(
            {
                "status": "QUARANTINED",
                "quarantined_at": datetime.now(timezone.utc).isoformat(),
                "reason": str(reason),
                "evidence": dict(evidence or {}),
            }
        )
        temporary = path.with_name(f".{path.name}.{self.token}.tmp")
        temporary.write_text(
            json.dumps(owner, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        os.replace(temporary, path)
        self.quarantined = True

    def __enter__(self) -> "FileLicenseLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        self.release()
        return False
