"""V2-only checkpoint writes and evidence-only V1 migration policy."""

import json
from pathlib import Path

import pytest

from hfss_optimization_agent.agent.comparison_state import create_comparison_state
from hfss_optimization_agent.core.models import HFSSResult, SParameterResult
from hfss_optimization_agent.domain.canonical_json import CanonicalJsonError
from hfss_optimization_agent.harness.checkpoint import (
    CheckpointDisposition,
    EvidenceLevel,
    JsonComparisonCheckpointStore,
    LegacyCheckpointNotResumable,
)
from hfss_optimization_agent.parameters.nine_parameter_schema import (
    supplied_baseline_candidate,
)


def state_v2():
    return create_comparison_state(
        task_id="checkpoint-v2",
        baseline_parameters=supplied_baseline_candidate(),
        evaluation_contract_id="offline-evaluation-v1",
        comparison_context_id="checkpoint-context",
        run_id="checkpoint-run",
        created_at="2026-08-21T08:00:00+00:00",
    )


def write_v1(path: Path, *, status: str) -> str:
    text = json.dumps(
        {
            "task_id": "legacy-task",
            "status": status,
            "baseline_parameters": {"candidate_id": "baseline"},
            "current_candidate": {"candidate_id": "candidate"},
            "best_candidate": {"candidate_id": "baseline"},
        },
        ensure_ascii=False,
        indent=2,
    )
    path.write_text(text, encoding="utf-8")
    return text


def test_new_checkpoint_write_is_canonical_v2_and_round_trips(tmp_path):
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")
    state = state_v2()
    written = store.save(state)
    assert written == tmp_path / "checkpoint.json"
    assert store.load() == state
    text = written.read_text(encoding="utf-8")
    assert "\n" not in text
    assert json.loads(text)["schema_version"] == "2.0"


def test_interrupted_v1_is_insufficient_evidence_and_never_overwritten(tmp_path):
    path = tmp_path / "checkpoint.json"
    original = write_v1(path, status="running")
    store = JsonComparisonCheckpointStore(path)
    read = store.read()
    assert read.disposition is CheckpointDisposition.WAITING_RECONCILIATION
    assert read.evidence_level is EvidenceLevel.INSUFFICIENT_EVIDENCE
    with pytest.raises(LegacyCheckpointNotResumable, match="cannot resume execution"):
        store.load()

    written = store.save(state_v2())
    assert written == tmp_path / "checkpoint.v2.json"
    assert path.read_text(encoding="utf-8") == original
    assert store.load()["schema_version"] == "2.0"
    preserved = store.read_original_v1_evidence()
    assert preserved is not None
    assert preserved.disposition is CheckpointDisposition.WAITING_RECONCILIATION


def test_completed_v1_imports_only_as_historical_evidence(tmp_path):
    path = tmp_path / "checkpoint.json"
    write_v1(path, status="completed")
    store = JsonComparisonCheckpointStore(path)
    read = store.read()
    assert read.disposition is CheckpointDisposition.HISTORICAL_EVIDENCE_ONLY
    assert read.evidence_level is EvidenceLevel.HISTORICAL_EVIDENCE
    assert read.legacy_evidence.best_candidate_id == "baseline"
    with pytest.raises(LegacyCheckpointNotResumable):
        store.load()


def test_checkpoint_rejects_path_nan_and_mutable_alias_before_write(tmp_path):
    store = JsonComparisonCheckpointStore(tmp_path / "checkpoint.json")

    state = state_v2()
    state["sparameter_results"] = (
        SParameterResult(
            "baseline",
            False,
            error="offline failure",
            metadata={"path": Path("unsafe")},
        ),
    )
    with pytest.raises(CanonicalJsonError, match="Path"):
        store.save(state)

    state = state_v2()
    state["hfss_results"] = (
        HFSSResult("baseline", False, metrics={"score": float("nan")}, error="x"),
    )
    with pytest.raises(CanonicalJsonError, match="non-finite"):
        store.save(state)

    shared = {}
    state = state_v2()
    state["sparameter_results"] = (
        SParameterResult("baseline", False, error="x", metadata=shared),
    )
    state["hfss_results"] = (
        HFSSResult("baseline", False, error="x", execution_metadata=shared),
    )
    with pytest.raises(CanonicalJsonError, match="mutable alias"):
        store.save(state)

    state = state_v2()
    state["unknown_state_fact"] = True
    with pytest.raises(ValueError, match="unknown=.*unknown_state_fact"):
        store.save(state)
    assert not (tmp_path / "checkpoint.json").exists()


def test_checkpoint_load_rejects_unknown_v2_fields(tmp_path):
    path = tmp_path / "checkpoint.json"
    store = JsonComparisonCheckpointStore(path)
    store.save(state_v2())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknown_state_fact"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CanonicalJsonError, match="unknown fields"):
        JsonComparisonCheckpointStore(path).load()
