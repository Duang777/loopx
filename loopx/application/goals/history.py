"""Compact, path-free pagination over shipped goal history collection."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from loopx.history import HISTORY_SEMANTIC_PAGE_SCHEMA_VERSION, collect_history
from ..contracts import application_public_safe_text
from ..errors import RevisionConflict, StateUnavailable, ValidationFailed
from .routing import effective_runtime_root, resolve_canonical_goal_route

if TYPE_CHECKING:
    from ..context import ApplicationContext


_MAX_PAGE_SIZE = 100
_PAGE_TOKEN_VERSION = 1


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    run_id: str
    generated_at: str
    classification: str
    agent_id: str | None
    delivery_outcome: str | None
    progress_scope: str | None
    json_available: bool
    markdown_available: bool
    artifacts_verified: bool


@dataclass(frozen=True, slots=True)
class HistoryPage:
    goal_id: str
    generated_at: str
    revision: str
    items: tuple[HistoryEntry, ...]
    total_count: int
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class GoalHistoryService:
    """Read goal history without retaining routes, paths, or mutable payloads."""

    context: ApplicationContext
    goal_id: str

    def list(
        self,
        *,
        page_size: int = 20,
        page_token: str | None = None,
    ) -> HistoryPage:
        safe_page_size = _page_size(page_size)
        route = resolve_canonical_goal_route(
            context=self.context,
            goal_id=self.goal_id,
        )
        runtime_root = effective_runtime_root(self.context, route)
        offset, expected_revision = _decode_page_token(page_token)
        try:
            payload = collect_history(
                registry_path=route.registry_path,
                runtime_root=runtime_root,
                goal_id=self.goal_id,
                limit=safe_page_size,
                include_runtime_goals=False,
                semantic_page_offset=offset,
            )
        except (KeyError, OSError, ValueError) as exc:
            raise StateUnavailable(
                details={"resource": "goal_history", "goal_id": self.goal_id}
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise StateUnavailable(
                details={"resource": "goal_history", "goal_id": self.goal_id}
            )
        raw_runs = payload.get("runs")
        if not isinstance(raw_runs, list):
            raise StateUnavailable(
                details={"resource": "goal_history", "goal_id": self.goal_id}
            )
        total_count, semantic_revision = _semantic_page_metadata(
            payload,
            expected_offset=offset,
            expected_limit=safe_page_size,
            returned_count=len(raw_runs),
            goal_id=self.goal_id,
        )
        revision = _revision(route.goal_revision, semantic_revision)
        _validate_page_revision(
            expected_revision,
            revision=revision,
            goal_id=self.goal_id,
        )
        if offset > total_count:
            raise ValidationFailed(
                details={"field": "page_token", "reason": "offset_out_of_range"}
            )
        if any(not isinstance(item, Mapping) for item in raw_runs):
            raise StateUnavailable(
                details={"resource": "goal_history", "goal_id": self.goal_id}
            )
        page_items = tuple(_entry(item) for item in raw_runs)
        next_offset = offset + len(page_items)
        next_page_token = (
            _encode_page_token(offset=next_offset, revision=revision)
            if next_offset < total_count
            else None
        )
        return HistoryPage(
            goal_id=self.goal_id,
            generated_at=_generated_at(self.context),
            revision=revision,
            items=page_items,
            total_count=total_count,
            next_page_token=next_page_token,
        )


def _entry(run: Mapping[str, Any]) -> HistoryEntry:
    generated_at = _timestamp(run.get("generated_at"), resource="goal_history")
    classification = _optional_text(run.get("classification"), limit=160) or "unknown"
    json_available = bool(run.get("json_exists"))
    markdown_available = bool(run.get("markdown_exists"))
    identity = {
        "generated_at": generated_at,
        "classification": classification,
        "agent_id": _optional_text(run.get("agent_id"), limit=160),
        "artifact": _opaque_artifact_identity(run),
    }
    return HistoryEntry(
        run_id=_hash(identity),
        generated_at=generated_at,
        classification=classification,
        agent_id=_optional_text(run.get("agent_id"), limit=160),
        delivery_outcome=_optional_text(run.get("delivery_outcome"), limit=120),
        progress_scope=_optional_text(run.get("progress_scope"), limit=120),
        json_available=json_available,
        markdown_available=markdown_available,
        artifacts_verified=json_available and markdown_available,
    )


def _opaque_artifact_identity(run: Mapping[str, Any]) -> str:
    material = "\0".join(
        (
            str(run.get("json_path") or ""),
            str(run.get("markdown_path") or ""),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _revision(goal_revision: str, semantic_revision: str) -> str:
    return _hash(
        {
            "goal_revision": goal_revision,
            "history_semantic_revision": semantic_revision,
        }
    )


def _semantic_page_metadata(
    payload: Mapping[str, Any],
    *,
    expected_offset: int,
    expected_limit: int,
    returned_count: int,
    goal_id: str,
) -> tuple[int, str]:
    metadata = payload.get("semantic_page")
    if not isinstance(metadata, Mapping):
        raise StateUnavailable(
            details={"resource": "goal_history", "goal_id": goal_id}
        )
    total_count = metadata.get("total_count")
    revision = metadata.get("revision")
    payload_run_count = payload.get("run_count")
    if (
        metadata.get("schema_version") != HISTORY_SEMANTIC_PAGE_SCHEMA_VERSION
        or metadata.get("offset") != expected_offset
        or metadata.get("limit") != expected_limit
        or isinstance(total_count, bool)
        or not isinstance(total_count, int)
        or total_count < 0
        or not isinstance(revision, str)
        or not revision.startswith("sha256:")
        or isinstance(payload_run_count, bool)
        or not isinstance(payload_run_count, int)
        or payload_run_count != total_count
        or returned_count > expected_limit
    ):
        raise StateUnavailable(
            details={"resource": "goal_history", "goal_id": goal_id}
        )
    expected_returned_count = min(
        expected_limit,
        max(total_count - expected_offset, 0),
    )
    if returned_count != expected_returned_count:
        raise StateUnavailable(
            details={"resource": "goal_history", "goal_id": goal_id}
        )
    return total_count, revision


def _page_size(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_PAGE_SIZE
    ):
        raise ValidationFailed(details={"field": "page_size"})
    return value


def _encode_page_token(*, offset: int, revision: str) -> str:
    payload = json.dumps(
        {"v": _PAGE_TOKEN_VERSION, "offset": offset, "revision": revision},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_page_token(
    token: str | None,
) -> tuple[int, str | None]:
    if token is None:
        return 0, None
    if not isinstance(token, str) or not token.strip() or len(token) > 512:
        raise ValidationFailed(details={"field": "page_token"})
    try:
        padding = "=" * (-len(token) % 4)
        decoded = base64.b64decode(
            token + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(decoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationFailed(details={"field": "page_token"}) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("v") != _PAGE_TOKEN_VERSION
        or isinstance(payload.get("offset"), bool)
        or not isinstance(payload.get("offset"), int)
        or payload["offset"] < 0
        or not isinstance(payload.get("revision"), str)
    ):
        raise ValidationFailed(details={"field": "page_token"})
    return payload["offset"], payload["revision"]


def _validate_page_revision(
    expected_revision: str | None,
    *,
    revision: str,
    goal_id: str,
) -> None:
    if expected_revision is not None and expected_revision != revision:
        raise RevisionConflict(
            details={
                "goal_id": goal_id,
                "expected_revision": expected_revision,
                "current_revision": revision,
            }
        )


def _optional_text(value: object, *, limit: int) -> str | None:
    return application_public_safe_text(value, limit=limit)


def _generated_at(context: ApplicationContext) -> str:
    try:
        value = context.clock()
    except (OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(details={"resource": "clock"}) from exc
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return _timestamp(value, resource="clock")


def _timestamp(value: object, *, resource: str) -> str:
    text = _optional_text(value, limit=160)
    try:
        if not text:
            raise ValueError
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateUnavailable(
            details={"resource": resource, "cause": "invalid_timestamp"}
        ) from exc
    return text


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
