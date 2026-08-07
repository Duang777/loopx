"""Shared canonical-source routing for goal-scoped application use cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from loopx.history import validate_goal_id_path_segment
from loopx.registry import registry_goals

from ..errors import (
    ApplicationError,
    GoalNotFound,
    GoalRouteConflict,
    StateUnavailable,
    ValidationFailed,
)

if TYPE_CHECKING:
    from ..context import ApplicationContext


@dataclass(frozen=True, slots=True)
class CanonicalGoalRoute:
    """Internal route descriptor; paths never enter public projections."""

    goal_id: str
    registry_path: Path
    runtime_root: Path
    status: str
    routed_to_source_registry: bool
    goal_revision: str


def resolve_canonical_goal_route(
    *,
    context: ApplicationContext,
    goal_id: str,
) -> CanonicalGoalRoute:
    """Resolve and validate current canonical source state without caching it."""

    normalized_goal_id = _goal_id(goal_id)
    try:
        invoked_registry = context.load_registry(context.registry_path)
    except ApplicationError:
        raise
    except (OSError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "registry", "goal_id": normalized_goal_id}
        ) from exc
    if not isinstance(invoked_registry, dict):
        raise StateUnavailable(
            details={
                "resource": "registry",
                "goal_id": normalized_goal_id,
                "cause": "invalid_payload",
            }
        )
    if not any(
        str(item.get("id") or "") == normalized_goal_id
        for item in registry_goals(invoked_registry)
    ):
        raise GoalNotFound(details={"goal_id": normalized_goal_id})

    try:
        route = context.resolve_goal_route(
            registry_path=context.registry_path,
            goal_id=normalized_goal_id,
            runtime_root_override=None,
            registry=invoked_registry,
        )
    except ApplicationError:
        raise
    except ValueError as exc:
        if exc.__cause__ is not None:
            raise StateUnavailable(
                details={
                    "resource": "canonical_source",
                    "goal_id": normalized_goal_id,
                    "cause": type(exc.__cause__).__name__,
                }
            ) from exc
        raise GoalRouteConflict(details={"goal_id": normalized_goal_id}) from exc
    except (KeyError, OSError) as exc:
        raise GoalRouteConflict(details={"goal_id": normalized_goal_id}) from exc
    if not isinstance(route, dict):
        raise GoalRouteConflict(
            details={"goal_id": normalized_goal_id, "cause": "invalid_route"}
        )
    registry_value = str(route.get("source_registry") or "").strip()
    runtime_value = str(route.get("source_runtime_root") or "").strip()
    if not registry_value or not runtime_value:
        raise GoalRouteConflict(
            details={"goal_id": normalized_goal_id, "cause": "incomplete_route"}
        )
    source_registry = Path(registry_value).expanduser().resolve()
    source_runtime = Path(runtime_value).expanduser().resolve()
    if not source_registry.exists():
        raise GoalRouteConflict(
            details={"goal_id": normalized_goal_id, "cause": "missing_source"}
        )
    try:
        source_payload = context.load_registry(source_registry)
    except (OSError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "canonical_source", "goal_id": normalized_goal_id}
        ) from exc
    if not isinstance(source_payload, dict):
        raise StateUnavailable(
            details={
                "resource": "canonical_source",
                "goal_id": normalized_goal_id,
                "cause": "invalid_payload",
            }
        )
    source_goal = next(
        (
            item
            for item in registry_goals(source_payload)
            if str(item.get("id") or "") == normalized_goal_id
        ),
        None,
    )
    if source_goal is None:
        raise GoalRouteConflict(
            details={"goal_id": normalized_goal_id, "cause": "goal_absent"}
        )
    return CanonicalGoalRoute(
        goal_id=normalized_goal_id,
        registry_path=source_registry,
        runtime_root=source_runtime,
        status=str(route.get("status") or "unknown"),
        routed_to_source_registry=bool(route.get("routed_to_source_registry")),
        goal_revision=_goal_revision(source_goal),
    )


def effective_runtime_root(
    context: ApplicationContext,
    route: CanonicalGoalRoute,
) -> Path:
    override = str(context.runtime_root_override or "").strip()
    return Path(override).expanduser().resolve() if override else route.runtime_root


def _goal_id(value: object) -> str:
    try:
        return validate_goal_id_path_segment(value)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(
            details={"field": "goal_id", "reason": "invalid_path_segment"}
        ) from exc


def _goal_revision(goal: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        goal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
