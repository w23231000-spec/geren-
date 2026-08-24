"""Additional State-V2 semantic corruption and terminal checkpoint chaos tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3

import pytest

from hfss_optimization_agent.agent.comparison_state import create_comparison_state, with_changes
from hfss_optimization_agent.core.enums import WorkflowStatus
from hfss_optimization_agent.core.models import TerminalOutcome
from hfss_optimization_agent.domain.canonical_json import canonical_dumps, canonical_loads
from hfss_optimization_agent.harness.artifacts import ArtifactStore
from hfss_optimization_agent.harness.checkpoint import SQLiteComparisonCheckpointStore
from hfss_optimization_agent.harness.core import HarnessCore, HarnessSettings
from hfss_optimization_agent.harness.fault_injection import (
    ArmedFaultInjector,
    CrashPoint,
    InjectedProcessCrash,
)
from hfss_optimization_agent.harness.run_store import (
    CheckpointCorruption,
    RunStatus,
    RunStore,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import supplied_baseline_candidate


def _state(name: str):
    return create_comparison_state(
        task_id=name,
        run_id=f"run:{name}",
        comparison_context_id=f"context:{name}",
        baseline_parameters=supplied_baseline_candidate(),
        created_at="2026-08-24T00:00:00+00:00",
    )


def _core(tmp_path: Path, current):
    core = HarnessCore(
        store=RunStore(tmp_path / ".runstore" / "runstore.sqlite3"),
        artifacts=ArtifactStore(tmp_path, current["manifest"].task_id),
        settings=HarnessSettings(operation_costs={"artifact": 0}),
    )
    core.ensure_run(current["manifest"])
    return core


def test_canonical_but_semantically_corrupt_state_is_rejected(tmp_path):
    current = _state("semantic-corruption")
    core = _core(tmp_path, current)
    checkpoint = SQLiteComparisonCheckpointStore(core.store)
    checkpoint.bind(current["manifest"].run_id)
    checkpoint.save(current)
    payload = canonical_loads(canonical_dumps(current))
    payload["unknown_state_field"] = "injected-corruption"
    corrupted = canonical_dumps(payload)
    digest = hashlib.sha256(corrupted.encode("utf-8")).hexdigest()
    connection = sqlite3.connect(core.store.path)
    try:
        connection.execute(
            """UPDATE checkpoints SET state_json = ?, state_sha256 = ?
               WHERE run_id = ? AND revision = 1""",
            (corrupted, digest, current["manifest"].run_id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(CheckpointCorruption, match="not a valid State V2"):
        checkpoint.load()


@pytest.mark.parametrize(
    "point,expected_revision,expected_run_status",
    (
        (CrashPoint.CHECKPOINT_BEFORE_COMMIT, 0, RunStatus.ACTIVE),
        (CrashPoint.CHECKPOINT_AFTER_COMMIT, 1, RunStatus.COMPLETED),
    ),
)
def test_terminal_checkpoint_crash_boundaries_and_double_resume(
    tmp_path, point, expected_revision, expected_run_status
):
    current = _state(f"terminal-{point.value}")
    core = _core(tmp_path, current)
    terminal = with_changes(
        current,
        {
            "status": WorkflowStatus.FAILED,
            "terminal_outcome": TerminalOutcome(
                WorkflowStatus.FAILED,
                "chaos_terminal",
                "injected terminal checkpoint boundary",
                current["manifest"].run_id,
                current["manifest"].design_goal.comparison_context_id,
            ),
        },
    )
    checkpoint = SQLiteComparisonCheckpointStore(
        core.store, fault_injector=ArmedFaultInjector({point})
    )
    checkpoint.bind(current["manifest"].run_id)
    with pytest.raises(InjectedProcessCrash):
        checkpoint.complete(terminal)
    run = core.store.get_run(current["manifest"].run_id)
    assert run.latest_checkpoint_revision == expected_revision
    assert run.status is expected_run_status

    if expected_run_status is RunStatus.COMPLETED:
        before_events = core.store.count_rows("events", run_id=run.run_id)

        def resume(_index):
            reopened_store = RunStore(core.store.path)
            reopened = SQLiteComparisonCheckpointStore(reopened_store)
            reopened.bind(run.run_id)
            assert reopened.load() == terminal
            return reopened.complete(terminal)

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert tuple(pool.map(resume, range(2))) == (1, 1)
        assert core.store.count_rows("events", run_id=run.run_id) == before_events
    else:
        reopened = SQLiteComparisonCheckpointStore(RunStore(core.store.path))
        reopened.bind(run.run_id)
        assert reopened.complete(terminal) == 1
        assert core.store.get_run(run.run_id).status is RunStatus.COMPLETED
