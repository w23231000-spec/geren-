"""Presentation-ready electromagnetic optimization and HFSS validation workflow.

The package root stays import-light because the AEDT 2025 R1 embedded Python imports
the isolated worker through this package before any Agent-only modules are needed.
"""

from __future__ import annotations

from typing import Any

__all__ = ["AppConfig"]


def __getattr__(name: str) -> Any:
    if name == "AppConfig":
        from .core.config import AppConfig

        return AppConfig
    raise AttributeError(name)
