"""Build only the first HFSS geometry milestone for troubleshooting; never solves."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hfss_optimization_agent.harness.terminal import (  # noqa: E402
    configure_utf8_output,
    emit_stage,
    emit_status,
)
from hfss_optimization_agent.hfss.pyaedt_worker import (  # noqa: E402
    _BUILD_STAGE_TOTAL,
    _builder_stage_display,
)


def main() -> int:
    configure_utf8_output()
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--builder-root", type=Path, required=True)
    parser.add_argument("--graphical", action="store_true")
    parser.add_argument(
        "--scope",
        choices=("foundation", "full"),
        default="foundation",
        help="foundation 只创建目标设计基础结构；full 完整创建目标设计但不求解",
    )
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    args.builder_root = args.builder_root.resolve()
    sys.path.insert(0, str(args.builder_root))
    from ansys.aedt.core import settings

    settings.enable_screen_logs = False
    from nine_parameter_builder import map_nine_parameters
    from pa_multi_builder import build_project

    last_displayed = None

    def progress(stage, metadata=None):
        del metadata
        nonlocal last_displayed
        displayed = _builder_stage_display(stage)
        if displayed is not None and displayed != last_displayed:
            emit_stage("HFSS 建模检查", displayed[0], _BUILD_STAGE_TOTAL, displayed[1])
            last_displayed = displayed

    result = build_project(
        output_path=args.output.resolve(),
        non_graphical=not args.graphical,
        milestone="interposer1_foundation" if args.scope == "foundation" else None,
        parameter_overrides=map_nine_parameters(request["candidate"]["values"]),
        progress_callback=progress,
    )
    emit_status(
        "建模检查",
        "完成",
        detail=f"输出工程：{result['output']}；未执行求解",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
