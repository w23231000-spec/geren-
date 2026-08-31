"""Compatibility entry point for Development Authorization.

The implementation lives in
hfss_optimization_agent.application.real_hfss_service.

This script never launches AEDT/HFSS.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.application.real_hfss_service import (  # noqa: E402
    prepare_development_authorization,
    read_runtime_config,
)
from hfss_optimization_agent.task_request import (  # noqa: E402
    load_runtime_optimization_request,
)


def main() -> Path:
    raw_config = read_runtime_config(ROOT)

    optimization_request = load_runtime_optimization_request(
        ROOT,
        raw_config,
    )

    prepared = prepare_development_authorization(
        ROOT,
        optimization_request,
    )

    print(
        json.dumps(
            prepared.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )

    return prepared.manifest_path


if __name__ == "__main__":
    main()
