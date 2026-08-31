"""Bounded subprocess supervision with Windows Job Object containment.

The parent never performs an unbounded wait.  On Windows a worker is created
suspended, assigned to a kill-on-close Job Object, then resumed before it can
spawn AEDT or another child.  Timeout/cancellation/heartbeat loss terminates the
whole job and verifies that no assigned process remains.  Failure to prove that
fact is an indeterminate physical outcome, not a retryable timeout.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Mapping, Sequence

from .errors import (
    ProcessCancelled,
    ProcessHeartbeatLost,
    ProcessOutcomeUnknown,
    ProcessSupervisorError,
    ProcessTimedOut,
)


HEARTBEAT_PATH_ENV = "HFSS_AGENT_WORKER_HEARTBEAT_PATH"
HEARTBEAT_INTERVAL_ENV = "HFSS_AGENT_WORKER_HEARTBEAT_INTERVAL_SECONDS"


@dataclass(frozen=True, slots=True)
class SupervisionPolicy:
    timeout_seconds: float
    heartbeat_timeout_seconds: float = 15.0
    termination_grace_seconds: float = 5.0
    poll_interval_seconds: float = 0.05

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0.0:
            raise ValueError("process timeout must be positive")
        if self.heartbeat_timeout_seconds <= 0.0:
            raise ValueError("heartbeat timeout must be positive")
        if self.termination_grace_seconds <= 0.0:
            raise ValueError("termination grace must be positive")
        if not 0.01 <= self.poll_interval_seconds <= 1.0:
            raise ValueError("poll interval must be between 0.01 and 1 second")


@dataclass(frozen=True, slots=True)
class SupervisedProcessResult:
    returncode: int
    pid: int
    elapsed_seconds: float
    heartbeat_path: Path


def _atomic_heartbeat(path: Path, *, worker_pid: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "pid": os.getpid() if worker_pid is None else worker_pid,
                "monotonic": time.monotonic(),
                "wall_time": time.time(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@contextmanager
def worker_heartbeat_from_environment(*, native_call_safe: bool = False) -> Iterator[None]:
    """Emit a heartbeat for a worker when the supervisor configured one.

    Ordinary Python workers use a thread. PyAEDT opts into a companion process
    because a blocking native AEDT call can starve every Python thread while the
    physical solve is still progressing. The companion inherits the worker's
    process-containment job, and the independent action timeout remains the hard
    upper bound for a genuinely stuck native call.
    """

    raw_path = os.environ.get(HEARTBEAT_PATH_ENV)
    if not raw_path:
        yield
        return
    path = Path(raw_path)
    try:
        interval = float(os.environ.get(HEARTBEAT_INTERVAL_ENV, "1.0"))
    except ValueError:
        interval = 1.0
    interval = min(max(interval, 0.05), 5.0)
    if native_call_safe:
        _atomic_heartbeat(path, worker_pid=os.getpid())
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        companion = subprocess.Popen(
            (
                sys.executable,
                "-m",
                "hfss_optimization_agent.harness.heartbeat_companion",
                str(path),
                str(interval),
                str(os.getpid()),
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creation_flags,
        )
        try:
            yield
        finally:
            if companion.poll() is None:
                companion.terminate()
                try:
                    companion.wait(timeout=min(interval * 2.0, 1.0))
                except subprocess.TimeoutExpired:
                    companion.kill()
                    companion.wait(timeout=1.0)
        return

    stop = threading.Event()

    def emit() -> None:
        while not stop.is_set():
            try:
                _atomic_heartbeat(path)
            except OSError:
                # The parent treats a stale heartbeat as a bounded failure.
                pass
            stop.wait(interval)

    thread = threading.Thread(target=emit, name="worker-heartbeat", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=min(interval * 2.0, 1.0))


class _ProcessContainment:
    def active_processes(self) -> int | None:
        raise NotImplementedError

    def terminate(self, exit_code: int) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class _PosixProcessGroup(_ProcessContainment):
    def __init__(self, process: subprocess.Popen) -> None:
        self.process = process
        self.pgid = process.pid

    def active_processes(self) -> int | None:
        try:
            os.killpg(self.pgid, 0)
        except ProcessLookupError:
            return 0
        except PermissionError:
            return 1
        except OSError:
            return None
        return 1

    def terminate(self, exit_code: int) -> bool:
        del exit_code
        try:
            os.killpg(self.pgid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        return True

    def close(self) -> None:
        return


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1
    _WAIT_OBJECT_0 = 0

    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.restype = wintypes.BOOL
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_longlong),
            ("TotalKernelTime", ctypes.c_longlong),
            ("ThisPeriodTotalUserTime", ctypes.c_longlong),
            ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    class _WindowsJob(_ProcessContainment):
        def __init__(self, process: subprocess.Popen) -> None:
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise ProcessOutcomeUnknown(
                    "CreateJobObjectW failed",
                    evidence={"winerror": ctypes.get_last_error(), "pid": process.pid},
                )
            self.handle = handle
            limits = _EXTENDED_LIMIT_INFORMATION()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            configured = _kernel32.SetInformationJobObject(
                handle,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            )
            if not configured:
                error = ctypes.get_last_error()
                _kernel32.CloseHandle(handle)
                raise ProcessOutcomeUnknown(
                    "SetInformationJobObject failed",
                    evidence={"winerror": error, "pid": process.pid},
                )
            process_handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
            if not _kernel32.AssignProcessToJobObject(handle, process_handle):
                error = ctypes.get_last_error()
                _kernel32.TerminateProcess(process_handle, 0xEE)
                _kernel32.CloseHandle(handle)
                raise ProcessOutcomeUnknown(
                    "AssignProcessToJobObject failed",
                    evidence={"winerror": error, "pid": process.pid},
                )
            status = _ntdll.NtResumeProcess(process_handle)
            if status != 0:
                _kernel32.TerminateJobObject(handle, 0xEF)
                _kernel32.CloseHandle(handle)
                raise ProcessOutcomeUnknown(
                    "NtResumeProcess failed",
                    evidence={"ntstatus": int(status), "pid": process.pid},
                )

        def active_processes(self) -> int | None:
            accounting = _BASIC_ACCOUNTING_INFORMATION()
            if not _kernel32.QueryInformationJobObject(
                self.handle,
                _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
                ctypes.byref(accounting),
                ctypes.sizeof(accounting),
                None,
            ):
                return None
            return int(accounting.ActiveProcesses)

        def terminate(self, exit_code: int) -> bool:
            return bool(_kernel32.TerminateJobObject(self.handle, exit_code))

        def close(self) -> None:
            if self.handle:
                _kernel32.CloseHandle(self.handle)
                self.handle = None


class SupervisedProcessRunner:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str] | None,
        heartbeat_path: Path,
        policy: SupervisionPolicy,
        cancel_event: threading.Event | None = None,
    ) -> SupervisedProcessResult:
        if not command or any(not str(value) for value in command):
            raise ValueError("supervised command cannot be empty")
        heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            heartbeat_path.unlink()
        except FileNotFoundError:
            pass
        child_environment = dict(os.environ)
        if environment is not None:
            child_environment.update({str(key): str(value) for key, value in environment.items()})
        child_environment[HEARTBEAT_PATH_ENV] = str(heartbeat_path)
        child_environment[HEARTBEAT_INTERVAL_ENV] = str(
            min(max(policy.heartbeat_timeout_seconds / 4.0, 0.05), 1.0)
        )
        creation_flags = 0
        start_new_session = os.name != "nt"
        if os.name == "nt":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004  # CREATE_SUSPENDED
        started = time.monotonic()
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=child_environment,
            stdin=subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            shell=False,
            creationflags=creation_flags,
            start_new_session=start_new_session,
        )
        containment: _ProcessContainment | None = None
        try:
            if os.name == "nt":
                containment = _WindowsJob(process)  # type: ignore[name-defined]
            else:
                containment = _PosixProcessGroup(process)
            deadline = started + policy.timeout_seconds
            heartbeat_deadline = started + policy.heartbeat_timeout_seconds
            last_heartbeat_mtime: float | None = None
            reason: str | None = None
            while True:
                returncode = process.poll()
                if returncode is not None:
                    if self._wait_empty(containment, process, policy.termination_grace_seconds, policy.poll_interval_seconds):
                        return SupervisedProcessResult(
                            returncode=returncode,
                            pid=process.pid,
                            elapsed_seconds=time.monotonic() - started,
                            heartbeat_path=heartbeat_path,
                        )
                    reason = "worker_exited_with_live_descendants"
                    break
                now = time.monotonic()
                if cancel_event is not None and cancel_event.is_set():
                    reason = "cancelled"
                    break
                if now >= deadline:
                    reason = "timeout"
                    break
                try:
                    heartbeat_mtime = heartbeat_path.stat().st_mtime
                except OSError:
                    heartbeat_mtime = None
                if heartbeat_mtime is not None and heartbeat_mtime != last_heartbeat_mtime:
                    last_heartbeat_mtime = heartbeat_mtime
                    heartbeat_deadline = now + policy.heartbeat_timeout_seconds
                if now >= heartbeat_deadline:
                    reason = "heartbeat_lost"
                    break
                time.sleep(min(policy.poll_interval_seconds, max(0.0, deadline - now)))

            terminated = containment.terminate(0xF0)
            verified = terminated and self._wait_empty(
                containment,
                process,
                policy.termination_grace_seconds,
                policy.poll_interval_seconds,
            )
            evidence = {
                "pid": process.pid,
                "reason": reason,
                "terminate_requested": terminated,
                "verified_no_processes": verified,
                "elapsed_seconds": time.monotonic() - started,
                "active_processes": containment.active_processes(),
            }
            if not verified:
                raise ProcessOutcomeUnknown(
                    f"worker process tree could not be verified stopped after {reason}",
                    evidence=evidence,
                )
            if reason == "timeout":
                raise ProcessTimedOut(
                    f"worker exceeded {policy.timeout_seconds:g} seconds and was terminated"
                )
            if reason == "cancelled":
                raise ProcessCancelled("worker was cancelled and its process tree was terminated")
            if reason == "heartbeat_lost":
                raise ProcessHeartbeatLost("worker heartbeat was lost and its process tree was terminated")
            raise ProcessOutcomeUnknown(
                "worker exited while descendants remained active",
                evidence=evidence,
            )
        except ProcessSupervisorError:
            raise
        except BaseException as exc:
            if containment is not None:
                terminated = containment.terminate(0xF1)
                verified = terminated and self._wait_empty(
                    containment,
                    process,
                    policy.termination_grace_seconds,
                    policy.poll_interval_seconds,
                )
                if verified:
                    raise ProcessCancelled(
                        "worker supervision was interrupted and its process tree was terminated"
                    ) from exc
                raise ProcessOutcomeUnknown(
                    "worker supervision was interrupted and cleanup could not be verified",
                    evidence={
                        "pid": process.pid,
                        "reason": type(exc).__name__,
                        "terminate_requested": terminated,
                        "verified_no_processes": verified,
                        "active_processes": containment.active_processes(),
                    },
                ) from exc
            if containment is None:
                try:
                    process.kill()
                    process.wait(timeout=1.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            raise
        finally:
            if containment is not None:
                containment.close()

    @staticmethod
    def _wait_empty(
        containment: _ProcessContainment,
        process: subprocess.Popen,
        grace_seconds: float,
        poll_interval_seconds: float,
    ) -> bool:
        deadline = time.monotonic() + grace_seconds
        while True:
            active = containment.active_processes()
            if active == 0:
                try:
                    process.wait(timeout=0.0)
                except subprocess.TimeoutExpired:
                    pass
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_interval_seconds)
