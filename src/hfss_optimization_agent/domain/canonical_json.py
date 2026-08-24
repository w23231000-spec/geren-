"""Strict deterministic JSON encoding for manifests and checkpoints."""

from __future__ import annotations

import json
import math
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Any, Mapping


class CanonicalJsonError(ValueError):
    """Raised when a value is unsafe or ambiguous for durable JSON state."""


def _is_mutable_dataclass(value: Any) -> bool:
    params = getattr(type(value), "__dataclass_params__", None)
    return bool(params is not None and not params.frozen)


def _validate_source_graph(
    value: Any,
    *,
    location: str,
    active: set[int],
    mutable_seen: dict[int, str],
) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError(f"{location} contains a non-finite float")
        return
    if isinstance(value, (Path, PurePath)):
        raise CanonicalJsonError(f"{location} contains a Path; persist a URI string instead")
    if isinstance(value, Enum):
        _validate_source_graph(
            value.value,
            location=location,
            active=active,
            mutable_seen=mutable_seen,
        )
        return

    identity = id(value)
    is_mutable = isinstance(value, (dict, list, set, bytearray)) or _is_mutable_dataclass(value)
    if is_mutable:
        previous = mutable_seen.get(identity)
        if previous is not None:
            raise CanonicalJsonError(
                f"mutable alias detected between {previous} and {location}"
            )
        mutable_seen[identity] = location
    if identity in active:
        raise CanonicalJsonError(f"cycle detected at {location}")
    active.add(identity)
    try:
        if is_dataclass(value):
            for field in fields(value):
                _validate_source_graph(
                    getattr(value, field.name),
                    location=f"{location}.{field.name}",
                    active=active,
                    mutable_seen=mutable_seen,
                )
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise CanonicalJsonError(f"{location} has a non-string object key")
                _validate_source_graph(
                    item,
                    location=f"{location}.{key}",
                    active=active,
                    mutable_seen=mutable_seen,
                )
            return
        if isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                _validate_source_graph(
                    item,
                    location=f"{location}[{index}]",
                    active=active,
                    mutable_seen=mutable_seen,
                )
            return
        raise CanonicalJsonError(
            f"{location} contains unsupported type {type(value).__name__}"
        )
    finally:
        active.remove(identity)


def _to_json_value(value: Any, *, location: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalJsonError(f"{location} contains a non-finite float")
        return value
    if isinstance(value, Enum):
        return _to_json_value(value.value, location=location)
    if is_dataclass(value):
        canonical_value = getattr(value, "__canonical_json__", None)
        if callable(canonical_value):
            return _to_json_value(canonical_value(), location=location)
        return {
            field.name: _to_json_value(
                getattr(value, field.name), location=f"{location}.{field.name}"
            )
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        converted: dict[str, Any] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise CanonicalJsonError(f"{location} has a non-string object key")
            converted[key] = _to_json_value(value[key], location=f"{location}.{key}")
        return converted
    if isinstance(value, (tuple, list)):
        return [
            _to_json_value(item, location=f"{location}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (Path, PurePath)):
        raise CanonicalJsonError(f"{location} contains a Path; persist a URI string instead")
    raise CanonicalJsonError(
        f"{location} contains unsupported type {type(value).__name__}"
    )


def to_json_value(value: Any) -> Any:
    """Validate aliases/types and return a JSON-compatible detached value."""

    _validate_source_graph(value, location="$", active=set(), mutable_seen={})
    return _to_json_value(value, location="$")


def canonical_dumps(value: Any) -> str:
    """Encode one canonical JSON document with stable ordering and no NaN."""

    return json.dumps(
        to_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_loads(text: str) -> Any:
    """Decode JSON while rejecting non-standard NaN/Infinity constants."""

    def reject_constant(value: str) -> None:
        raise CanonicalJsonError(f"non-standard JSON constant {value} is forbidden")

    def reject_duplicate_keys(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise CanonicalJsonError(f"duplicate JSON object key {key!r} is forbidden")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise CanonicalJsonError(f"invalid JSON: {exc}") from exc


def require_exact_fields(
    value: Any,
    expected: set[str] | frozenset[str],
    *,
    context: str,
) -> Mapping[str, Any]:
    """Return a mapping only when its schema has exactly the expected fields."""

    if not isinstance(value, Mapping):
        raise CanonicalJsonError(f"{context} must be an object")
    actual = set(value)
    unknown = sorted(actual - set(expected))
    missing = sorted(set(expected) - actual)
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown fields: {', '.join(unknown)}")
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        raise CanonicalJsonError(f"{context} has " + "; ".join(details))
    return value
