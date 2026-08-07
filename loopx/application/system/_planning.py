"""Internal planning guards for system writers without native revision CAS."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from ..contracts import Profile, WriteContext, WriteCorrectness
from ..errors import AuthorityDenied, RevisionConflict, ValidationFailed


PENDING_SYSTEM_WRITER_CORRECTNESS = WriteCorrectness(
    status="pending_migration",
    atomic_revision_check=False,
    idempotent_retry=False,
)


def require_cli_authority(profile: Profile, *, operation_id: str) -> None:
    if profile is not Profile.CLI:
        raise AuthorityDenied(
            details={"operation_id": operation_id, "profile": profile.value}
        )


def validate_write_context(
    write_context: WriteContext,
    *,
    operation_id: str,
) -> None:
    if not isinstance(write_context, WriteContext):
        raise ValidationFailed(details={"field": "write_context"})
    if write_context.expected_revision is not None:
        raise ValidationFailed(
            details={
                "field": "write_context.expected_revision",
                "operation_id": operation_id,
                "reason": "writer_has_no_atomic_revision_contract",
            }
        )


def require_matching_plan_hash(
    supplied: str,
    current: str,
    *,
    operation_id: str,
) -> None:
    if supplied != current:
        raise RevisionConflict(
            details={
                "operation_id": operation_id,
                "expected_plan_hash": supplied,
                "current_plan_hash": current,
                "atomic_revision_check": False,
            }
        )


def semantic_hash(*, operation_id: str, request: object, projection: object) -> str:
    encoded = json.dumps(
        {
            "operation_id": operation_id,
            "request": _json_value(request),
            "projection": _json_value(projection),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            descriptor.name: _json_value(getattr(value, descriptor.name))
            for descriptor in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise ValidationFailed(
        details={"field": "plan_material", "type": type(value).__name__}
    )
