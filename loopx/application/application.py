from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..history import validate_goal_id_path_segment
from ..registry import registry_goals
from .context import ApplicationContext
from .contracts import (
    CapabilityDescription,
    CapabilityKind,
    CapabilityScope,
    CapabilityUnavailableReason,
    GoalSummary,
)
from .errors import (
    ApplicationError,
    GoalNotFound,
    GoalRouteConflict,
    StateUnavailable,
    ValidationFailed,
)

if TYPE_CHECKING:
    from .goals import GoalHandle


class LoopXApplication:
    """Synchronous application facade over uncached LoopX Core state."""

    __slots__ = ("_context",)

    def __init__(self, context: ApplicationContext) -> None:
        if not isinstance(context, ApplicationContext):
            raise ValidationFailed(details={"field": "context"})
        self._context = context

    @property
    def context(self) -> ApplicationContext:
        return self._context

    def list_goals(self) -> tuple[GoalSummary, ...]:
        registry = self._load_registry()
        generated_at = self._generated_at()
        return tuple(
            GoalSummary(
                goal_id=str(goal["id"]),
                status=_optional_text(goal.get("status")),
                domain=_optional_text(goal.get("domain")),
                generated_at=generated_at,
                revision=_stable_revision(goal),
            )
            for goal in registry_goals(registry)
        )

    def get_goal(self, goal_id: str) -> GoalHandle:
        normalized_goal_id = _require_goal_id(goal_id)
        registry = self._load_registry()
        goal = next(
            (
                row
                for row in registry_goals(registry)
                if str(row.get("id") or "") == normalized_goal_id
            ),
            None,
        )
        if goal is None:
            raise GoalNotFound(details={"goal_id": normalized_goal_id})
        self._validate_canonical_route(normalized_goal_id, registry)

        from .goals import GoalHandle

        return GoalHandle(context=self._context, goal_id=normalized_goal_id)

    def describe_capabilities(self) -> tuple[CapabilityDescription, ...]:
        writes_available = self._context.writes_available
        write_unavailable_reason = (
            None
            if writes_available
            else CapabilityUnavailableReason(
                code="profile_read_only",
                message="The selected application profile does not permit writes.",
                details={"profile": self._context.profile.value},
            )
        )
        turn_plan_available = self._context.turn_envelope_source is not None
        turn_plan_unavailable_reason = (
            None
            if turn_plan_available
            else CapabilityUnavailableReason(
                code="turn_envelope_source_unavailable",
                message="No Turn envelope source is configured for this application.",
                details={"provider": "turn_envelope_source"},
            )
        )
        turn_execution_available = self._context.execution_available
        turn_execution_unavailable_reason = (
            None
            if turn_execution_available
            else _turn_execution_unavailable_reason(self._context)
        )
        return (
            _read_capability("application.list_goals", CapabilityScope.APPLICATION),
            _read_capability("application.get_goal", CapabilityScope.APPLICATION),
            _read_capability(
                "application.describe_capabilities",
                CapabilityScope.APPLICATION,
            ),
            _read_capability("goal.status", CapabilityScope.GOAL),
            _read_capability("goal.overview", CapabilityScope.GOAL),
            _read_capability("goal.todos.list", CapabilityScope.GOAL),
            _read_capability("goal.lease.inspect", CapabilityScope.GOAL),
            _read_capability("goal.quota.should_run", CapabilityScope.GOAL),
            _read_capability("goal.history.list", CapabilityScope.GOAL),
            _read_capability(
                "goal.turn.plan",
                CapabilityScope.GOAL,
                available=turn_plan_available,
                unavailable_reason=turn_plan_unavailable_reason,
            ),
            _execute_capability(
                "goal.turn.run_once",
                available=turn_execution_available,
                unavailable_reason=turn_execution_unavailable_reason,
                supports_preview=True,
                requires_preview=True,
            ),
            _write_capability(
                "goal.configuration.preview",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
            ),
            _write_capability(
                "goal.configuration.apply",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
                requires_preview=True,
            ),
            _write_capability(
                "goal.todos.claim",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
            ),
            _write_capability(
                "goal.todos.update",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
            ),
            _write_capability(
                "goal.todos.complete.preview",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
            ),
            _write_capability(
                "goal.todos.complete.apply",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
                requires_preview=True,
            ),
            *(
                _write_capability(
                    capability_id,
                    available=writes_available,
                    unavailable_reason=write_unavailable_reason,
                )
                for capability_id in (
                    "goal.lease.acquire",
                    "goal.lease.renew",
                    "goal.lease.release",
                )
            ),
            _write_capability(
                "goal.quota.spend.preview",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
            ),
            _write_capability(
                "goal.quota.spend.apply",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
                requires_preview=True,
            ),
            _write_capability(
                "goal.quota.void.preview",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
            ),
            _write_capability(
                "goal.quota.void.apply",
                available=writes_available,
                unavailable_reason=write_unavailable_reason,
                supports_preview=True,
                requires_preview=True,
            ),
        )

    def _load_registry(self) -> dict[str, Any]:
        try:
            registry = self._context.load_registry(self._context.registry_path)
        except ApplicationError:
            raise
        except (OSError, ValueError) as exc:
            raise StateUnavailable(
                details={"resource": "registry", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(registry, dict):
            raise StateUnavailable(
                details={"resource": "registry", "cause": "invalid_payload"}
            )
        return registry

    def _generated_at(self) -> str:
        value = self._context.clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat().replace("+00:00", "Z")
        generated_at = str(value or "").strip()
        if not generated_at:
            raise StateUnavailable(
                details={"resource": "clock", "cause": "invalid_value"}
            )
        return generated_at

    def _validate_canonical_route(
        self,
        goal_id: str,
        registry: dict[str, Any],
    ) -> None:
        try:
            route = self._context.resolve_goal_route(
                registry_path=self._context.registry_path,
                goal_id=goal_id,
                runtime_root_override=None,
                registry=registry,
            )
        except ApplicationError:
            raise
        except ValueError as exc:
            if exc.__cause__ is not None:
                raise StateUnavailable(
                    details={
                        "resource": "canonical_source",
                        "goal_id": goal_id,
                        "cause": type(exc.__cause__).__name__,
                    }
                ) from exc
            raise GoalRouteConflict(
                details={"goal_id": goal_id, "cause": type(exc).__name__}
            ) from exc
        except (KeyError, OSError) as exc:
            raise GoalRouteConflict(
                details={"goal_id": goal_id, "cause": type(exc).__name__}
            ) from exc
        if (
            not isinstance(route, dict)
            or not route.get("source_registry")
            or not route.get("source_runtime_root")
        ):
            raise GoalRouteConflict(
                details={"goal_id": goal_id, "cause": "incomplete_route"}
            )


def _read_capability(
    capability_id: str,
    scope: CapabilityScope,
    *,
    available: bool = True,
    unavailable_reason: CapabilityUnavailableReason | None = None,
) -> CapabilityDescription:
    return CapabilityDescription(
        capability_id=capability_id,
        scope=scope,
        kind=CapabilityKind.READ,
        available=available,
        supports_preview=False,
        requires_preview=False,
        unavailable_reason=unavailable_reason,
    )


def _write_capability(
    capability_id: str,
    *,
    available: bool,
    unavailable_reason: CapabilityUnavailableReason | None,
    supports_preview: bool = False,
    requires_preview: bool = False,
) -> CapabilityDescription:
    return CapabilityDescription(
        capability_id=capability_id,
        scope=CapabilityScope.GOAL,
        kind=CapabilityKind.WRITE,
        available=available,
        supports_preview=supports_preview,
        requires_preview=requires_preview,
        unavailable_reason=unavailable_reason,
    )


def _execute_capability(
    capability_id: str,
    *,
    available: bool,
    unavailable_reason: CapabilityUnavailableReason | None,
    supports_preview: bool,
    requires_preview: bool,
) -> CapabilityDescription:
    return CapabilityDescription(
        capability_id=capability_id,
        scope=CapabilityScope.GOAL,
        kind=CapabilityKind.EXECUTE,
        available=available,
        supports_preview=supports_preview,
        requires_preview=requires_preview,
        unavailable_reason=unavailable_reason,
    )


def _turn_execution_unavailable_reason(
    context: ApplicationContext,
) -> CapabilityUnavailableReason:
    if not context.profile.allows_execution:
        return CapabilityUnavailableReason(
            code="profile_execution_denied",
            message="The selected application profile does not permit execution.",
            details={"profile": context.profile.value},
        )
    if context.turn_envelope_source is None:
        return CapabilityUnavailableReason(
            code="turn_envelope_source_unavailable",
            message="No Turn envelope source is configured for this application.",
            details={"provider": "turn_envelope_source"},
        )
    if context.turn_executor is None:
        return CapabilityUnavailableReason(
            code="executor_unavailable",
            message="No Turn executor is configured for this application.",
            details={"provider": "turn_executor"},
        )
    return CapabilityUnavailableReason(
        code="commit_coordinator_unavailable",
        message="No Turn commit coordinator is configured for this application.",
        details={"provider": "turn_commit_coordinator"},
    )


def _require_goal_id(goal_id: str) -> str:
    try:
        return validate_goal_id_path_segment(goal_id)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(
            details={"field": "goal_id", "reason": "invalid_path_segment"}
        ) from exc


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _stable_revision(goal: dict[str, Any]) -> str:
    canonical = json.dumps(
        goal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
