"""Deterministic source-tree attestations used before external side effects."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


def source_tree_manifest(
    root: Path,
    *,
    suffixes: Iterable[str] = (".py",),
) -> tuple[tuple[str, str], ...]:
    base = root.resolve()
    allowed = {suffix.lower() for suffix in suffixes}
    if not base.is_dir():
        raise FileNotFoundError(f"source tree does not exist: {base}")
    rows: list[tuple[str, str]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        relative = path.relative_to(base).as_posix()
        rows.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    if not rows:
        raise ValueError(f"source tree has no attested files: {base}")
    return tuple(rows)


def source_manifest_digest(manifest: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_digest in manifest:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def source_tree_digest(root: Path, *, suffixes: Iterable[str] = (".py",)) -> str:
    return source_manifest_digest(source_tree_manifest(root, suffixes=suffixes))
