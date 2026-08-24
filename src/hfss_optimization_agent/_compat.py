"""Small runtime compatibility shims required by the AEDT 2025 R1 Python 3.10 worker."""

from __future__ import annotations

try:
    from enum import StrEnum as StrEnum
except ImportError:  # Python 3.10 embedded in AEDT 2025 R1.
    from enum import Enum

    class StrEnum(str, Enum):
        """Behavioral subset of Python 3.11 ``enum.StrEnum`` used by this project."""

        def __str__(self) -> str:
            return str.__str__(self.value)


__all__ = ["StrEnum"]
