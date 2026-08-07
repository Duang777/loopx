from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from loopx.authority import validate_public_safe_text
from loopx.control_plane.runtime.public_safety import public_safe_compact_text

from .errors import ValidationFailed


APPLICATION_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9:</])/(?!/)[^\s`'\"<>]+|"
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s`'\"<>]+)"
)


def application_public_safe_text(value: Any, *, limit: int) -> str | None:
    """Return one compact Application-safe scalar or omit unsafe material."""

    text = public_safe_compact_text(
        value,
        limit=limit,
        local_path_surface_pattern=APPLICATION_ABSOLUTE_PATH_PATTERN,
    )
    if text is None:
        return None
    try:
        validate_public_safe_text("application projection", text)
    except ValueError:
        return None
    return text


class Profile(str, Enum):
    CLI = "cli"
    HTTP_READ_ONLY = "http_read_only"
    HTTP_LOCAL_OPERATOR = "http_local_operator"

    @property
    def allows_writes(self) -> bool:
        return self is not Profile.HTTP_READ_ONLY

    @property
    def allows_execution(self) -> bool:
        return self is Profile.CLI


class CapabilityScope(str, Enum):
    APPLICATION = "application"
    GOAL = "goal"


class CapabilityKind(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class WriteContext:
    actor: str
    idempotency_key: str
    expected_revision: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.actor, str):
            raise ValidationFailed(details={"field": "actor"})
        if not isinstance(self.idempotency_key, str):
            raise ValidationFailed(details={"field": "idempotency_key"})
        if self.expected_revision is not None and not isinstance(
            self.expected_revision, str
        ):
            raise ValidationFailed(details={"field": "expected_revision"})
        actor = self.actor.strip()
        idempotency_key = self.idempotency_key.strip()
        expected_revision = (
            self.expected_revision.strip()
            if self.expected_revision is not None
            else None
        )
        if (
            not actor
            or len(actor) > 160
            or application_public_safe_text(actor, limit=160) != actor
        ):
            raise ValidationFailed(details={"field": "actor"})
        if (
            not idempotency_key
            or len(idempotency_key) > 160
            or application_public_safe_text(idempotency_key, limit=160)
            != idempotency_key
        ):
            raise ValidationFailed(details={"field": "idempotency_key"})
        if self.expected_revision is not None and (
            not expected_revision
            or len(expected_revision) > 256
            or application_public_safe_text(expected_revision, limit=256)
            != expected_revision
        ):
            raise ValidationFailed(details={"field": "expected_revision"})
        object.__setattr__(self, "actor", actor)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "expected_revision", expected_revision)


@dataclass(frozen=True, slots=True)
class WriteCorrectness:
    """Truthful support level of the underlying durable writer."""

    status: str
    atomic_revision_check: bool
    idempotent_retry: bool

    def __post_init__(self) -> None:
        status = str(self.status or "").strip()
        if not status:
            raise ValidationFailed(details={"field": "status"})
        object.__setattr__(self, "status", status)


@dataclass(frozen=True, slots=True)
class GoalSummary:
    goal_id: str
    status: str | None
    domain: str | None
    generated_at: str
    revision: str

    def __post_init__(self) -> None:
        if not self.goal_id.strip():
            raise ValidationFailed(details={"field": "goal_id"})
        if not self.revision.strip():
            raise ValidationFailed(details={"field": "revision"})


@dataclass(frozen=True, slots=True)
class CapabilityUnavailableReason:
    code: str
    message: str
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = self.code.strip()
        message = self.message.strip()
        if not code:
            raise ValidationFailed(details={"field": "code"})
        if not message:
            raise ValidationFailed(details={"field": "message"})
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))


@dataclass(frozen=True, slots=True)
class CapabilityDescription:
    capability_id: str
    scope: CapabilityScope
    kind: CapabilityKind
    available: bool
    supports_preview: bool
    requires_preview: bool
    unavailable_reason: CapabilityUnavailableReason | None = None

    def __post_init__(self) -> None:
        capability_id = self.capability_id.strip()
        if not capability_id:
            raise ValidationFailed(details={"field": "capability_id"})
        if self.requires_preview and not self.supports_preview:
            raise ValidationFailed(
                details={"field": "requires_preview", "capability_id": capability_id}
            )
        if self.available and self.unavailable_reason is not None:
            raise ValidationFailed(
                details={"field": "unavailable_reason", "capability_id": capability_id}
            )
        if not self.available and self.unavailable_reason is None:
            raise ValidationFailed(
                details={"field": "unavailable_reason", "capability_id": capability_id}
            )
        object.__setattr__(self, "capability_id", capability_id)
