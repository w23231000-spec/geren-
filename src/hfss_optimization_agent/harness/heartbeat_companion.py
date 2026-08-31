"""GIL-independent heartbeat emitter for workers blocked in native calls."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from .process_supervisor import _atomic_heartbeat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hfss-agent-heartbeat-companion")
    parser.add_argument("path", type=Path)
    parser.add_argument("interval", type=float)
    parser.add_argument("worker_pid", type=int)
    args = parser.parse_args(argv)
    interval = min(max(args.interval, 0.05), 5.0)
    while True:
        try:
            _atomic_heartbeat(args.path, worker_pid=args.worker_pid)
        except OSError:
            # The supervisor treats a stale heartbeat as a bounded failure.
            pass
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
