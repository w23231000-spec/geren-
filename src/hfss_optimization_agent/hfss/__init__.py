# Guarded real-HFSS orchestration contracts and worker boundary.

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "GuardedHFSSAdapter",
    "GuardedHFSSConfig",
    "HFSSBackendInterface",
    "HFSSRunContract",
    "MaterialContract",
    "compose_pyaedt_hfss",
    "PortContract",
    "RawSParameterData",
    "JsonSubprocessHFSSBackend",
    "JsonWorkerConfig",
    "SweepContract",
    "UnavailableHFSSBackend",
    "load_hfss_contract",
]

_EXPORTS = {
    "HFSSBackendInterface": (".backend", "HFSSBackendInterface"),
    "RawSParameterData": (".backend", "RawSParameterData"),
    "UnavailableHFSSBackend": (".backend", "UnavailableHFSSBackend"),
    "HFSSRunContract": (".contracts", "HFSSRunContract"),
    "MaterialContract": (".contracts", "MaterialContract"),
    "PortContract": (".contracts", "PortContract"),
    "SweepContract": (".contracts", "SweepContract"),
    "load_hfss_contract": (".contracts", "load_hfss_contract"),
    "GuardedHFSSAdapter": (".guarded_adapter", "GuardedHFSSAdapter"),
    "GuardedHFSSConfig": (".guarded_adapter", "GuardedHFSSConfig"),
    "compose_pyaedt_hfss": (".pyaedt_composition", "compose_pyaedt_hfss"),
    "JsonSubprocessHFSSBackend": (".worker_backend", "JsonSubprocessHFSSBackend"),
    "JsonWorkerConfig": (".worker_backend", "JsonWorkerConfig"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
