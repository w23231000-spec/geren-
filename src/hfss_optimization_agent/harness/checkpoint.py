"""Provides atomic local JSON save and restore for the complete workflow state."""

import json
from pathlib import Path

from ..agent.comparison_state import (
    ComparisonAgentState,
    comparison_state_from_dict,
    comparison_state_to_dict,
)


class JsonComparisonCheckpointStore:
    """Atomic checkpoint store for the confirmed baseline-comparison workflow."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def save(self, state: ComparisonAgentState) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(comparison_state_to_dict(state), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return self.path

    def load(self) -> ComparisonAgentState:
        return comparison_state_from_dict(json.loads(self.path.read_text(encoding="utf-8")))
