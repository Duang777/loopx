"""Versioned coordination-state record contract shared with TypeScript.

The JSON artifact is the language-neutral schema owner.  Python projection
code may normalize Markdown into this shape, but it must not silently invent a
different field allowlist or discard an unversioned machine-owned field.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any, Mapping


COORDINATION_STATE_CONTRACT_SCHEMA_VERSION = "loopx_coordination_state_contract_v0"
_CONTRACT_RESOURCE = "coordination_state_contract_v0.json"


class CoordinationStateContractError(ValueError):
    """A record or bundled contract violates the coordination-state schema."""


def _string_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CoordinationStateContractError(f"{label} must be a non-empty array")
    if any(not isinstance(item, str) or not item for item in value):
        raise CoordinationStateContractError(f"{label} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise CoordinationStateContractError(f"{label} must not contain duplicates")
    return tuple(value)


def _validate_compatibility(value: object) -> None:
    if not isinstance(value, dict) or value != {
        "unknown_field_policy": "reject",
        "field_removal_policy": "maintainer_approval_required",
        "markdown_role": "human_workbench_and_compatibility_projection",
    }:
        raise CoordinationStateContractError("coordination state contract policy mismatch")


def _load_contract() -> dict[str, Any]:
    raw = json.loads(
        files("loopx.control_plane.coordination")
        .joinpath(_CONTRACT_RESOURCE)
        .read_text(encoding="utf-8")
    )
    if not isinstance(raw, dict) or raw.get("schema_version") != (
        COORDINATION_STATE_CONTRACT_SCHEMA_VERSION
    ):
        raise CoordinationStateContractError("coordination state contract schema mismatch")
    _validate_compatibility(raw.get("compatibility"))
    return raw


COORDINATION_STATE_CONTRACT = _load_contract()
_TODO_READ_RECORD = COORDINATION_STATE_CONTRACT.get("todo_read_record")
if not isinstance(_TODO_READ_RECORD, dict):
    raise CoordinationStateContractError("Todo record contract must be an object")

TODO_CANONICAL_READ_RECORD_SCHEMA_VERSION = _TODO_READ_RECORD.get("schema_version")
TODO_ITEM_SCHEMA_VERSION = _TODO_READ_RECORD.get("item_schema_version")
if (
    not isinstance(TODO_CANONICAL_READ_RECORD_SCHEMA_VERSION, str)
    or not TODO_CANONICAL_READ_RECORD_SCHEMA_VERSION
    or not isinstance(TODO_ITEM_SCHEMA_VERSION, str)
    or not TODO_ITEM_SCHEMA_VERSION
):
    raise CoordinationStateContractError("Todo record schema versions must be strings")
TODO_CANONICAL_READ_RECORD_FIELDS = _string_tuple(
    _TODO_READ_RECORD.get("fields"), label="todo_read_record.fields"
)
TODO_CANONICAL_REQUIRED_READ_FIELDS = _string_tuple(
    _TODO_READ_RECORD.get("required_fields"),
    label="todo_read_record.required_fields",
)
_UNKNOWN_REQUIRED_FIELDS = sorted(
    set(TODO_CANONICAL_REQUIRED_READ_FIELDS).difference(TODO_CANONICAL_READ_RECORD_FIELDS)
)
if _UNKNOWN_REQUIRED_FIELDS:
    raise CoordinationStateContractError(
        "todo_read_record.required_fields are absent from fields: "
        + ", ".join(_UNKNOWN_REQUIRED_FIELDS)
    )

_DOMAIN = COORDINATION_STATE_CONTRACT["todo_domain_record"]
_PROJECTION = COORDINATION_STATE_CONTRACT["todo_projection_metadata"]
if (
    _DOMAIN.get("fields_from") != "todo_read_record"
    or _DOMAIN.get("exclude_fields_from") != "todo_projection_metadata"
):
    raise CoordinationStateContractError("Todo domain contract mismatch")
TODO_PROJECTION_METADATA_FIELDS = _string_tuple(
    _PROJECTION.get("fields"), label="todo_projection_metadata.fields"
)
TODO_DOMAIN_READ_RECORD_SCHEMA_VERSION: str = _DOMAIN["schema_version"]
TODO_DOMAIN_ITEM_SCHEMA_VERSION: str = _DOMAIN["item_schema_version"]
TODO_DOMAIN_RECORD_FIELDS = tuple(
    field for field in TODO_CANONICAL_READ_RECORD_FIELDS
    if field not in TODO_PROJECTION_METADATA_FIELDS
)
TODO_DOMAIN_REQUIRED_FIELDS = _string_tuple(
    _DOMAIN.get("required_fields"), label="todo_domain_record.required_fields"
)
if not set(TODO_DOMAIN_REQUIRED_FIELDS) <= set(TODO_DOMAIN_RECORD_FIELDS):
    raise CoordinationStateContractError("Todo domain required fields are not declared")


def canonical_record_fields(
    value: Mapping[str, object],
    *,
    fields: tuple[str, ...],
    required_fields: tuple[str, ...],
    label: str,
    reject_unknown: bool,
) -> dict[str, object]:
    """Copy one record through the shared field contract.

    ``reject_unknown`` is mandatory for provider-bound projections.  The false
    mode exists only for legacy status callers that may carry presentation-only
    fields outside the machine-owned coordination record.
    """

    unknown_required = sorted(set(required_fields).difference(fields))
    if unknown_required:
        raise CoordinationStateContractError(
            f"{label} required fields are absent from fields: "
            + ", ".join(unknown_required)
        )
    if reject_unknown:
        unexpected = sorted(set(value).difference(fields))
        if unexpected:
            raise CoordinationStateContractError(
                f"{label} has unversioned fields: {', '.join(unexpected)}"
            )
    record = {
        field: value[field]
        for field in fields
        if field in value and value[field] is not None
    }
    missing = [field for field in required_fields if field not in record]
    if missing:
        raise CoordinationStateContractError(
            f"{label} omits required fields: {', '.join(missing)}"
        )
    return record


__all__ = [
    "COORDINATION_STATE_CONTRACT",
    "COORDINATION_STATE_CONTRACT_SCHEMA_VERSION",
    "CoordinationStateContractError",
    "TODO_CANONICAL_READ_RECORD_FIELDS",
    "TODO_CANONICAL_READ_RECORD_SCHEMA_VERSION",
    "TODO_CANONICAL_REQUIRED_READ_FIELDS",
    "TODO_ITEM_SCHEMA_VERSION",
    "TODO_DOMAIN_READ_RECORD_SCHEMA_VERSION",
    "TODO_DOMAIN_ITEM_SCHEMA_VERSION",
    "TODO_DOMAIN_RECORD_FIELDS",
    "TODO_DOMAIN_REQUIRED_FIELDS",
    "TODO_PROJECTION_METADATA_FIELDS",
    "canonical_record_fields",
]
