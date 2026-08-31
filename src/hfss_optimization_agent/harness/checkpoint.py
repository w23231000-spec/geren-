"""Canonical State-V2 checkpoint storage with evidence-only V1 migration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from .._compat import StrEnum
from pathlib import Path
from typing import Any, Mapping

from ..agent.comparison_state import (
    ComparisonAgentState,
    comparison_state_from_dict,
    comparison_state_to_dict,
    validate_comparison_state,
)
from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
)
from ..domain.contracts import STATE_SCHEMA_VERSION
from .fault_injection import CrashPoint, FaultInjector, NoFaultInjector
from .run_store import CheckpointCorruption, RunStore


class CheckpointDisposition(StrEnum):
    RESUMABLE_V2 = "RESUMABLE_V2"
    HISTORICAL_EVIDENCE_ONLY = "HISTORICAL_EVIDENCE_ONLY"
    WAITING_RECONCILIATION = "WAITING_RECONCILIATION"


class EvidenceLevel(StrEnum):
    V2_STATE = "V2_STATE"
    HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class LegacyCheckpointEvidence:
    source_uri: str
    source_sha256: str
    disposition: CheckpointDisposition
    evidence_level: EvidenceLevel
    legacy_status: str
    task_id: str | None
    baseline_candidate_id: str | None
    current_candidate_id: str | None
    best_candidate_id: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CheckpointReadResult:
    schema_version: str
    disposition: CheckpointDisposition
    evidence_level: EvidenceLevel
    source_uri: str
    state: ComparisonAgentState | None = None
    legacy_evidence: LegacyCheckpointEvidence | None = None


class LegacyCheckpointNotResumable(RuntimeError):
    def __init__(self, evidence: LegacyCheckpointEvidence) -> None:
        self.evidence = evidence
        super().__init__(
            f"V1 checkpoint is {evidence.disposition}; it cannot resume execution: "
            f"{evidence.reason}"
        )


def _candidate_id(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    candidate_id = value.get("candidate_id")
    return candidate_id if isinstance(candidate_id, str) and candidate_id else None


class JsonComparisonCheckpointStore:
    """Atomic V2-only writer and dual-read V1/V2 checkpoint store."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._active_path: Path | None = None

    @property
    def v2_sibling_path(self) -> Path:
        return self.path.with_name(f"{self.path.stem}.v2{self.path.suffix}")

    @property
    def active_path(self) -> Path:
        if self._active_path is not None:
            return self._active_path
        if self.v2_sibling_path.exists():
            return self.v2_sibling_path
        return self.path

    def _payload_at(self, path: Path) -> tuple[str, Any]:
        text = path.read_text(encoding="utf-8")
        return text, canonical_loads(text)

    @staticmethod
    def _is_v2(payload: Any) -> bool:
        return (
            isinstance(payload, Mapping)
            and payload.get("schema_version") == STATE_SCHEMA_VERSION
        )

    def _write_target(self) -> Path:
        if self._active_path is not None:
            return self._active_path
        if self.v2_sibling_path.exists():
            text, payload = self._payload_at(self.v2_sibling_path)
            if not self._is_v2(payload):
                raise CanonicalJsonError(
                    f"{self.v2_sibling_path.name} exists but is not State V2"
                )
            del text
            self._active_path = self.v2_sibling_path
            return self._active_path
        if self.path.exists():
            _text, payload = self._payload_at(self.path)
            self._active_path = self.path if self._is_v2(payload) else self.v2_sibling_path
            return self._active_path
        self._active_path = self.path
        return self._active_path

    def save(self, state: ComparisonAgentState) -> Path:
        """Validate and atomically write canonical V2 without overwriting V1."""

        validate_comparison_state(state)
        encoded = canonical_dumps(state)
        target = self._write_target()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(target)
        return target

    def _legacy_evidence(
        self, *, path: Path, text: str, payload: Any
    ) -> LegacyCheckpointEvidence:
        if not isinstance(payload, Mapping):
            raise CanonicalJsonError("V1 checkpoint root must be an object")
        status = payload.get("status")
        legacy_status = status if isinstance(status, str) else "UNKNOWN"
        completed = legacy_status == "completed"
        disposition = (
            CheckpointDisposition.HISTORICAL_EVIDENCE_ONLY
            if completed
            else CheckpointDisposition.WAITING_RECONCILIATION
        )
        evidence_level = (
            EvidenceLevel.HISTORICAL_EVIDENCE
            if completed
            else EvidenceLevel.INSUFFICIENT_EVIDENCE
        )
        reason = (
            "Completed V1 may be imported only as historical evidence; it is not "
            "a resumable execution state."
            if completed
            else "Interrupted/non-completed V1 has insufficient identity and action "
            "evidence; reconciliation is required before any new action."
        )
        return LegacyCheckpointEvidence(
            source_uri=path.name,
            source_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            disposition=disposition,
            evidence_level=evidence_level,
            legacy_status=legacy_status,
            task_id=payload.get("task_id") if isinstance(payload.get("task_id"), str) else None,
            baseline_candidate_id=_candidate_id(payload.get("baseline_parameters")),
            current_candidate_id=_candidate_id(payload.get("current_candidate")),
            best_candidate_id=_candidate_id(payload.get("best_candidate")),
            reason=reason,
        )

    def read(self) -> CheckpointReadResult:
        """Read V2 for resume or classify V1 into non-resumable evidence."""

        source = self.v2_sibling_path if self.v2_sibling_path.exists() else self.path
        text, payload = self._payload_at(source)
        if self._is_v2(payload):
            state = comparison_state_from_dict(dict(payload))
            self._active_path = source
            return CheckpointReadResult(
                schema_version=STATE_SCHEMA_VERSION,
                disposition=CheckpointDisposition.RESUMABLE_V2,
                evidence_level=EvidenceLevel.V2_STATE,
                source_uri=source.name,
                state=state,
            )
        evidence = self._legacy_evidence(path=source, text=text, payload=payload)
        return CheckpointReadResult(
            schema_version="1.x",
            disposition=evidence.disposition,
            evidence_level=evidence.evidence_level,
            source_uri=source.name,
            legacy_evidence=evidence,
        )

    def read_original_v1_evidence(self) -> LegacyCheckpointEvidence | None:
        """Read preserved original V1 even after a V2 sibling has been written."""

        if not self.path.exists():
            return None
        text, payload = self._payload_at(self.path)
        if self._is_v2(payload):
            return None
        return self._legacy_evidence(path=self.path, text=text, payload=payload)

    def load(self) -> ComparisonAgentState:
        result = self.read()
        if result.state is not None:
            return result.state
        if result.legacy_evidence is None:
            raise RuntimeError("checkpoint read returned neither V2 state nor V1 evidence")
        raise LegacyCheckpointNotResumable(result.legacy_evidence)


class SQLiteComparisonCheckpointStore:
    """Append-only State-V2 revisions stored transactionally in the RunStore."""

    def __init__(
        self,
        store: RunStore,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.store = store
        self.path = store.path
        self._run_id: str | None = None
        self._revision: int | None = None
        self._run_owner_token: str | None = None
        self._run_fence: int | None = None
        self.fault_injector = fault_injector or NoFaultInjector()

    @property
    def active_path(self) -> Path:
        """Compatibility path; SQLite is the authoritative checkpoint."""

        return self.path

    def bind(self, run_id: str) -> None:
        if self._run_id is not None and self._run_id != run_id:
            raise ValueError("checkpoint store is already bound to a different run")
        self._run_id = run_id
        if self._revision is None:
            run = self.store.get_run(run_id)
            self._revision = run.latest_checkpoint_revision if run is not None else 0

    def set_invocation_fence(self, owner_token: str | None, fence: int | None) -> None:
        self._run_owner_token = owner_token
        self._run_fence = fence

    def has_checkpoint(self) -> bool:
        return bool(
            self._run_id is not None
            and self.store.has_checkpoint(self._run_id)
        )

    def _bound_run_id(self) -> str:
        if self._run_id is None:
            raise RuntimeError("SQLite checkpoint store must be bound to a run first")
        return self._run_id

    def save(self, state: ComparisonAgentState) -> int:
        validate_comparison_state(state)
        run_id = state["manifest"].run_id
        self.bind(run_id)
        self.fault_injector.hit(CrashPoint.CHECKPOINT_BEFORE_COMMIT)
        revision = self.store.save_checkpoint(
            run_id,
            canonical_dumps(comparison_state_to_dict(state)),
            expected_revision=self._revision,
            run_owner_token=self._run_owner_token,
            run_fence=self._run_fence,
        )
        self.fault_injector.hit(CrashPoint.CHECKPOINT_AFTER_COMMIT)
        self._revision = revision
        return revision

    def complete(self, state: ComparisonAgentState) -> int:
        validate_comparison_state(state)
        run_id = state["manifest"].run_id
        self.bind(run_id)
        self.fault_injector.hit(CrashPoint.CHECKPOINT_BEFORE_COMMIT)
        revision = self.store.save_checkpoint(
            run_id,
            canonical_dumps(comparison_state_to_dict(state)),
            complete=True,
            terminal_status=state["status"],
            expected_revision=self._revision,
            run_owner_token=self._run_owner_token,
            run_fence=self._run_fence,
        )
        self.fault_injector.hit(CrashPoint.CHECKPOINT_AFTER_COMMIT)
        self._revision = revision
        return revision

    def load(self) -> ComparisonAgentState:
        run_id = self._bound_run_id()
        text = self.store.load_checkpoint_json(run_id)
        if text is None:
            raise FileNotFoundError(f"no SQLite checkpoint exists for run {run_id}")
        payload = canonical_loads(text)
        run = self.store.get_run(run_id)
        self._revision = run.latest_checkpoint_revision if run is not None else None
        try:
            return comparison_state_from_dict(payload)
        except (CanonicalJsonError, TypeError, ValueError) as exc:
            raise CheckpointCorruption(
                f"checkpoint for Run {run_id} is not a valid State V2"
            ) from exc

    def read(self) -> CheckpointReadResult:
        state = self.load()
        return CheckpointReadResult(
            schema_version=STATE_SCHEMA_VERSION,
            disposition=CheckpointDisposition.RESUMABLE_V2,
            evidence_level=EvidenceLevel.V2_STATE,
            source_uri=self.path.name,
            state=state,
        )
