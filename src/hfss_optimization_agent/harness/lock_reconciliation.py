"""Explicit, auditable release of a quarantined HFSS license marker."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .errors import HFSSLicenseLockError
from .license_lock import LicenseLockConfig
from .run_store import RunStore


def reconcile_quarantined_lock(
    config: LicenseLockConfig,
    *,
    store: RunStore,
    operation_id: str,
) -> Path:
    """Archive a quarantine only after RunStore accepted matching operator evidence.

    The reconciliation evidence must attest a verified-empty process tree and
    bind the exact quarantine bytes/token.  The marker is archived rather than
    deleted, preserving the operational evidence.  No automatic caller uses
    this function.
    """

    reconciliation = store.get_reconciliation(operation_id)
    if reconciliation is None:
        raise HFSSLicenseLockError(
            "license quarantine requires an accepted operation reconciliation"
        )
    evidence = reconciliation.request.evidence.to_dict()
    if evidence.get("verified_no_processes") is not True:
        raise HFSSLicenseLockError(
            "license quarantine cannot clear without verified_no_processes=true"
        )
    path = config.path.resolve()
    archive_suffix = hashlib.sha256(
        reconciliation.request.reconciliation_id.encode("utf-8")
    ).hexdigest()[:16]
    archive = path.with_name(f"{path.name}.reconciled.{archive_suffix}.json")
    if not path.exists() and archive.exists():
        try:
            archived = json.loads(archive.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HFSSLicenseLockError(
                "license reconciliation archive cannot be verified"
            ) from exc
        if (
            archived.get("status") != "RECONCILED"
            or archived.get("reconciliation_id")
            != reconciliation.request.reconciliation_id
            or archived.get("reconciliation_sha256")
            != reconciliation.request_sha256
            or archived.get("original_lock_sha256") != evidence.get("lock_sha256")
            or archived.get("token") != evidence.get("lock_token")
        ):
            raise HFSSLicenseLockError("license reconciliation archive identity conflicts")
        return archive
    try:
        raw = path.read_bytes()
        owner = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HFSSLicenseLockError(
            f"license quarantine evidence cannot be read: {path}"
        ) from exc
    digest = hashlib.sha256(raw).hexdigest()
    if (
        owner.get("status") not in {"QUARANTINED", "RECONCILED"}
        or owner.get("token") != evidence.get("lock_token")
        or digest != evidence.get("lock_sha256")
    ):
        if not (
            owner.get("status") == "RECONCILED"
            and owner.get("reconciliation_id")
            == reconciliation.request.reconciliation_id
            and owner.get("original_lock_sha256") == evidence.get("lock_sha256")
        ):
            raise HFSSLicenseLockError(
                "license quarantine bytes/token do not match reconciliation evidence"
            )
    archive_suffix = hashlib.sha256(
        reconciliation.request.reconciliation_id.encode("utf-8")
    ).hexdigest()[:16]
    archive = path.with_name(f"{path.name}.reconciled.{archive_suffix}.json")
    owner.update(
        {
            "status": "RECONCILED",
            "reconciliation_id": reconciliation.request.reconciliation_id,
            "reconciliation_sha256": reconciliation.request_sha256,
            "original_lock_sha256": evidence["lock_sha256"],
        }
    )
    encoded = json.dumps(owner, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if archive.exists():
        if archive.read_bytes() != encoded:
            raise HFSSLicenseLockError("license reconciliation archive identity conflicts")
        if path.exists() and path.read_bytes() == encoded:
            path.unlink()
        return archive
    temporary = path.with_name(f".{path.name}.{archive_suffix}.reconcile.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        os.replace(path, archive)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return archive
