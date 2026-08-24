"""Structured, immutable terminal evidence for one RunStore-backed workflow."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from ..domain.canonical_json import (
    CanonicalJsonError,
    canonical_dumps,
    canonical_loads,
    require_exact_fields,
)
from ..domain.contracts import CalibrationEvidence, FrozenMap
from .run_store import RunStore, manifest_identity_sha256


FINAL_RUN_MANIFEST_SCHEMA_VERSION = "final-run-manifest/1.0"


@dataclass(frozen=True, slots=True)
class FinalRunManifestV1:
    schema_version: str
    run_id: str
    task_id: str
    workflow_id: str
    comparison_context_id: str
    execution_mode: str
    run_manifest_sha256: str
    code_revision: str | None
    pre_final_state_sha256: str
    terminal_outcome: FrozenMap
    policy_versions: tuple[str, ...]
    decisions: tuple[FrozenMap, ...]
    events: tuple[FrozenMap, ...]
    artifacts: tuple[FrozenMap, ...]
    ledger_cutoff_sequence: int
    calibration_evidence: FrozenMap | None

    def __post_init__(self) -> None:
        if self.schema_version != FINAL_RUN_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"FinalRunManifest schema_version must be {FINAL_RUN_MANIFEST_SCHEMA_VERSION}"
            )
        for name in (
            "run_id",
            "task_id",
            "workflow_id",
            "comparison_context_id",
            "execution_mode",
            "run_manifest_sha256",
            "pre_final_state_sha256",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"FinalRunManifest.{name} must be a non-empty string")
        if self.execution_mode not in {"offline", "real"}:
            raise ValueError("FinalRunManifest execution_mode must be offline or real")
        if not isinstance(self.ledger_cutoff_sequence, int) or self.ledger_cutoff_sequence < 0:
            raise ValueError("FinalRunManifest ledger cutoff must be non-negative")
        if not self.policy_versions or len(self.policy_versions) != len(
            set(self.policy_versions)
        ):
            raise ValueError("FinalRunManifest policy versions must be non-empty and unique")
        if not self.decisions:
            raise ValueError("FinalRunManifest requires at least one structured decision")

    @classmethod
    def from_dict(cls, value: Any) -> "FinalRunManifestV1":
        data = require_exact_fields(
            value,
            {
                "schema_version",
                "run_id",
                "task_id",
                "workflow_id",
                "comparison_context_id",
                "execution_mode",
                "run_manifest_sha256",
                "code_revision",
                "pre_final_state_sha256",
                "terminal_outcome",
                "policy_versions",
                "decisions",
                "events",
                "artifacts",
                "ledger_cutoff_sequence",
                "calibration_evidence",
            },
            context="FinalRunManifestV1",
        )
        for name in ("policy_versions", "decisions", "events", "artifacts"):
            if not isinstance(data[name], list):
                raise CanonicalJsonError(f"FinalRunManifestV1.{name} must be an array")
        calibration = data["calibration_evidence"]
        return cls(
            schema_version=data["schema_version"],
            run_id=data["run_id"],
            task_id=data["task_id"],
            workflow_id=data["workflow_id"],
            comparison_context_id=data["comparison_context_id"],
            execution_mode=data["execution_mode"],
            run_manifest_sha256=data["run_manifest_sha256"],
            code_revision=data["code_revision"],
            pre_final_state_sha256=data["pre_final_state_sha256"],
            terminal_outcome=FrozenMap.from_dict(data["terminal_outcome"]),
            policy_versions=tuple(data["policy_versions"]),
            decisions=tuple(FrozenMap.from_dict(item) for item in data["decisions"]),
            events=tuple(FrozenMap.from_dict(item) for item in data["events"]),
            artifacts=tuple(FrozenMap.from_dict(item) for item in data["artifacts"]),
            ledger_cutoff_sequence=data["ledger_cutoff_sequence"],
            calibration_evidence=(
                FrozenMap.from_dict(calibration) if calibration is not None else None
            ),
        )


def build_final_run_manifest(state: Any, store: RunStore) -> FinalRunManifestV1:
    """Snapshot the ledger immediately before publishing the manifest itself."""

    manifest = state["manifest"]
    if state.get("terminal_outcome") is None:
        raise ValueError("final manifest requires a typed TerminalOutcome")
    events = store.list_events(manifest.run_id)
    run = store.get_run(manifest.run_id)
    if run is None:
        raise ValueError("final manifest requires a registered Run")
    state_sha256 = hashlib.sha256(canonical_dumps(state).encode("utf-8")).hexdigest()
    decisions = tuple(
        event["payload"] for event in events if event["event_type"] == "policy_decision"
    )
    policy_versions = tuple(
        dict.fromkeys(
            decision["policy_version"]
            for decision in decisions
            if isinstance(decision.get("policy_version"), str)
        )
    )
    if not decisions:
        decision = state.get("decision_outcome")
        if decision is None:
            terminal = canonical_loads(canonical_dumps(state["terminal_outcome"]))
            decision_payload = {
                "decision_id": f"terminal:{manifest.run_id}",
                "input_state_revision": run.latest_checkpoint_revision,
                "input_state_sha256": state_sha256,
                "policy_version": "typed-terminal-policy-v1",
                "iteration": 1,
                "action": "finalize",
                "reason_code": terminal["reason_code"],
                "reason": terminal["reason"],
                "candidate_id": terminal["candidate_id"],
                "evidence_ids": terminal["evidence_ids"],
                "next_step": "end",
            }
        else:
            payload = canonical_loads(canonical_dumps(decision))
            decision_payload = {
                "decision_id": payload["decision_id"],
                "input_state_revision": run.latest_checkpoint_revision,
                "input_state_sha256": state_sha256,
                "policy_version": "one-pass-decision-policy-v1",
                "iteration": 1,
                "action": payload["action"],
                "reason_code": payload["reason_code"],
                "reason": payload["reason"],
                "candidate_id": payload["candidate_id"],
                "evidence_ids": payload["evidence_ids"],
                "next_step": "end",
            }
        decisions = (decision_payload,)
        policy_versions = (decision_payload["policy_version"],)
    config = manifest.config_fingerprints.to_dict()
    calibration_summary = None
    if "calibration_evidence" in config:
        evidence = CalibrationEvidence.from_dict(config["calibration_evidence"])
        if config.get("calibration_evidence_sha256") != evidence.digest:
            raise ValueError("final manifest calibration evidence digest differs")
        calibration_summary = FrozenMap.from_mapping(
            {
                "evidence_id": evidence.evidence_id,
                "evidence_sha256": evidence.digest,
                "policy_version": evidence.policy_version,
                "comparison_context_id": evidence.comparison_context_id,
                "passed": evidence.passed,
                "case_ids": evidence.case_ids,
                "source_artifact_ids": evidence.source_artifact_ids,
            }
        )
    artifacts = store.list_artifacts(manifest.run_id)
    return FinalRunManifestV1(
        schema_version=FINAL_RUN_MANIFEST_SCHEMA_VERSION,
        run_id=manifest.run_id,
        task_id=manifest.task_id,
        workflow_id=manifest.workflow_id,
        comparison_context_id=manifest.design_goal.comparison_context_id,
        execution_mode="real" if manifest.real_execution else "offline",
        run_manifest_sha256=manifest_identity_sha256(manifest),
        code_revision=manifest.code_revision,
        pre_final_state_sha256=state_sha256,
        terminal_outcome=FrozenMap.from_dict(
            canonical_loads(canonical_dumps(state["terminal_outcome"]))
        ),
        policy_versions=policy_versions,
        decisions=tuple(FrozenMap.from_mapping(item) for item in decisions),
        events=tuple(FrozenMap.from_mapping(item) for item in events),
        artifacts=tuple(
            FrozenMap.from_dict(canonical_loads(canonical_dumps(item)))
            for item in artifacts
        ),
        ledger_cutoff_sequence=events[-1]["sequence"] if events else 0,
        calibration_evidence=calibration_summary,
    )
