"""Safely resolves the supplied optimizer package without importing it at project import time."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

from ..harness.errors import OptimizerError


def import_supplied_module(source_root: Path, module_name: str) -> ModuleType:
    root = Path(source_root).resolve()
    if not (root / "app").is_dir() or not (root / "models").is_dir():
        raise OptimizerError(f"Supplied optimizer root is invalid: {root}")
    root_text = str(root)
    existing = sys.modules.get(module_name)
    if existing is not None:
        module_file = Path(getattr(existing, "__file__", "")).resolve()
        if root not in module_file.parents:
            raise OptimizerError(
                f"Module name collision for {module_name!r}: already loaded from {module_file}"
            )
        return existing
    sys.path.insert(0, root_text)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise OptimizerError(f"Unable to import supplied module {module_name!r}: {exc}") from exc
    finally:
        if sys.path and sys.path[0] == root_text:
            sys.path.pop(0)
    module_file = Path(getattr(module, "__file__", "")).resolve()
    if root not in module_file.parents:
        raise OptimizerError(f"Imported {module_name!r} from unexpected path {module_file}")
    return module
