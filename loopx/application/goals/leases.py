"""Transport-neutral task-lease application boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from loopx.control_plane.work_items.task_lease import (
    TASK_LEASE_SCHEMA_VERSION,
    TaskLeaseError,
    acquire_task_lease,
    inspect_task_lease,
    release_task_lease,
    renew_task_lease,
)

from ..contracts import WriteContext, WriteCorrectness
from ..errors import (
    AuthorityDenied,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from .routing import effective_runtime_root, resolve_canonical_goal_route

if TYPE_CHECKING:
    from ..context import ApplicationContext


LEASE_REVISION_PATTERN = re.compile(r"^task_lease_v0:(?P<version>[0-9]+)$")


@dataclass(frozen=True, slots=True)
class TaskLease:
    """Path-free public projection of one Core task lease."""

    goal_id: str
    todo_id: str
    owner: str
    status: str
    active: bool
    version: int
    revision: str
    write_scopes: tuple[str, ...]
    acquire_ttl_seconds: int | None
    acquired_at: str | None
    updated_at: str | None
    expires_at: str | None
    released_at: str | None = None


@dataclass(frozen=True, slots=True)
class TaskLeaseInspection:
    goal_id: str
    todo_id: str
    generated_at: str
    active: bool
    lease: TaskLease | None
    constraint_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TaskLeaseMutationResult:
    action: str
    goal_id: str
    todo_id: str
    generated_at: str
    changed: bool
    idempotent: bool
    missing: bool
    lease: TaskLease | None
    correctness: WriteCorrectness


@dataclass(frozen=True, slots=True)
class GoalLeaseService:
    """Goal-scoped facade over the shipped ``task_lease_v0`` writer."""

    context: ApplicationContext
    goal_id: str

    def __post_init__(self) -> None:
        normalized = str(self.goal_id or "").strip()
        if not normalized or normalized != self.goal_id:
            raise ValidationFailed(details={"field": "goal_id"})

    def inspect(self, todo_id: str) -> TaskLeaseInspection:
        route = resolve_canonical_goal_route(
            context=self.context,
            goal_id=self.goal_id,
        )
        try:
            payload = inspect_task_lease(
                registry_path=route.registry_path,
                runtime_root=effective_runtime_root(self.context, route),
                goal_id=route.goal_id,
                todo_id=todo_id,
            )
        except TaskLeaseError as exc:
            _raise_core_error(exc, operation_id="goal.lease.inspect")
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "task_lease", "goal_id": route.goal_id}
            ) from exc
        lease_payload = payload.get("lease")
        active = bool(payload.get("active"))
        constraint = payload.get("executor_constraint")
        return TaskLeaseInspection(
            goal_id=route.goal_id,
            todo_id=str(payload.get("todo_id") or todo_id),
            generated_at=_generated_at(self.context),
            active=active,
            lease=(
                _project_lease(lease_payload, active=active)
                if isinstance(lease_payload, Mapping)
                else None
            ),
            constraint_reason=(
                str(constraint.get("reason") or "") or None
                if isinstance(constraint, Mapping)
                else None
            ),
        )

    def acquire(
        self,
        todo_id: str,
        *,
        write_context: WriteContext,
        ttl_seconds: int | None = None,
        write_scopes: tuple[str, ...] = (),
    ) -> TaskLeaseMutationResult:
        route, expected_version = self._write_route(
            operation_id="goal.lease.acquire",
            write_context=write_context,
        )
        try:
            payload = acquire_task_lease(
                registry_path=route.registry_path,
                runtime_root=effective_runtime_root(self.context, route),
                goal_id=route.goal_id,
                todo_id=todo_id,
                owner=write_context.actor,
                idempotency_key=write_context.idempotency_key,
                ttl_seconds=ttl_seconds,
                write_scopes=list(write_scopes),
                expected_version=expected_version,
            )
        except TaskLeaseError as exc:
            _raise_core_error(exc, operation_id="goal.lease.acquire")
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "task_lease", "goal_id": route.goal_id}
            ) from exc
        return _mutation_result(
            context=self.context,
            route_goal_id=route.goal_id,
            todo_id=todo_id,
            action="acquire",
            payload=payload,
            changed=bool(payload.get("acquired")),
            idempotent=bool(payload.get("idempotent")),
            expected_version=expected_version,
            idempotent_retry=True,
            active=True,
        )

    def renew(
        self,
        todo_id: str,
        *,
        write_context: WriteContext,
        ttl_seconds: int | None = None,
    ) -> TaskLeaseMutationResult:
        route, expected_version = self._write_route(
            operation_id="goal.lease.renew",
            write_context=write_context,
        )
        try:
            payload = renew_task_lease(
                registry_path=route.registry_path,
                runtime_root=effective_runtime_root(self.context, route),
                goal_id=route.goal_id,
                todo_id=todo_id,
                owner=write_context.actor,
                idempotency_key=write_context.idempotency_key,
                ttl_seconds=ttl_seconds,
                expected_version=expected_version,
            )
        except TaskLeaseError as exc:
            _raise_core_error(exc, operation_id="goal.lease.renew")
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "task_lease", "goal_id": route.goal_id}
            ) from exc
        return _mutation_result(
            context=self.context,
            route_goal_id=route.goal_id,
            todo_id=todo_id,
            action="renew",
            payload=payload,
            changed=bool(payload.get("renewed")),
            idempotent=False,
            expected_version=expected_version,
            idempotent_retry=False,
            active=True,
        )

    def release(
        self,
        todo_id: str,
        *,
        write_context: WriteContext,
    ) -> TaskLeaseMutationResult:
        route, expected_version = self._write_route(
            operation_id="goal.lease.release",
            write_context=write_context,
        )
        try:
            payload = release_task_lease(
                runtime_root=effective_runtime_root(self.context, route),
                goal_id=route.goal_id,
                todo_id=todo_id,
                owner=write_context.actor,
                idempotency_key=write_context.idempotency_key,
                expected_version=expected_version,
            )
        except TaskLeaseError as exc:
            _raise_core_error(exc, operation_id="goal.lease.release")
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "task_lease", "goal_id": route.goal_id}
            ) from exc
        return _mutation_result(
            context=self.context,
            route_goal_id=route.goal_id,
            todo_id=todo_id,
            action="release",
            payload=payload,
            changed=bool(payload.get("released")),
            idempotent=False,
            expected_version=expected_version,
            idempotent_retry=False,
            active=False,
        )

    def _write_route(
        self,
        *,
        operation_id: str,
        write_context: WriteContext,
    ) -> tuple[Any, int | None]:
        if not isinstance(write_context, WriteContext):
            raise ValidationFailed(details={"field": "write_context"})
        if not self.context.writes_available:
            raise AuthorityDenied(
                details={
                    "operation_id": operation_id,
                    "profile": self.context.profile.value,
                }
            )
        expected_version = _expected_version(write_context.expected_revision)
        route = resolve_canonical_goal_route(
            context=self.context,
            goal_id=self.goal_id,
        )
        return route, expected_version


def _expected_version(revision: str | None) -> int | None:
    if revision is None:
        return None
    match = LEASE_REVISION_PATTERN.fullmatch(revision)
    if match is None:
        raise ValidationFailed(
            details={
                "field": "write_context.expected_revision",
                "expected_format": "task_lease_v0:<version>",
            }
        )
    return int(match.group("version"))


def _project_lease(payload: Mapping[str, Any], *, active: bool) -> TaskLease:
    version = int(payload.get("version") or 0)
    return TaskLease(
        goal_id=str(payload.get("goal_id") or ""),
        todo_id=str(payload.get("todo_id") or ""),
        owner=str(payload.get("owner") or ""),
        status=str(payload.get("status") or "unknown"),
        active=active,
        version=version,
        revision=f"{TASK_LEASE_SCHEMA_VERSION}:{version}",
        write_scopes=tuple(str(value) for value in payload.get("write_scopes") or ()),
        acquire_ttl_seconds=(
            int(payload["acquire_ttl_seconds"])
            if payload.get("acquire_ttl_seconds") is not None
            else None
        ),
        acquired_at=_optional_text(payload.get("acquired_at")),
        updated_at=_optional_text(payload.get("updated_at")),
        expires_at=_optional_text(payload.get("expires_at")),
        released_at=_optional_text(payload.get("released_at")),
    )


def _mutation_result(
    *,
    context: ApplicationContext,
    route_goal_id: str,
    todo_id: str,
    action: str,
    payload: Mapping[str, Any],
    changed: bool,
    idempotent: bool,
    expected_version: int | None,
    idempotent_retry: bool,
    active: bool,
) -> TaskLeaseMutationResult:
    lease_payload = payload.get("lease")
    return TaskLeaseMutationResult(
        action=action,
        goal_id=route_goal_id,
        todo_id=todo_id,
        generated_at=_generated_at(context),
        changed=changed,
        idempotent=idempotent,
        missing=bool(payload.get("missing")),
        lease=(
            _project_lease(lease_payload, active=active)
            if isinstance(lease_payload, Mapping)
            else None
        ),
        correctness=WriteCorrectness(
            status="core_enforced",
            atomic_revision_check=expected_version is not None,
            idempotent_retry=idempotent_retry,
        ),
    )


def _raise_core_error(exc: TaskLeaseError, *, operation_id: str) -> None:
    details: dict[str, object] = {
        "operation_id": operation_id,
        "core_code": exc.code,
    }
    for key in (
        "goal_id",
        "todo_id",
        "owner",
        "claimed_by",
        "expected_version",
        "actual_version",
        "requested_ttl_seconds",
    ):
        value = exc.payload.get(key)
        if value is not None:
            details[key] = value
    lease = exc.payload.get("lease")
    if isinstance(lease, Mapping):
        details["current_owner"] = str(lease.get("owner") or "") or None
        details["current_version"] = int(lease.get("version") or 0)
    conflicts = exc.payload.get("conflicts")
    if isinstance(conflicts, list):
        details["conflicting_todo_ids"] = tuple(
            str(item.get("todo_id"))
            for item in conflicts
            if isinstance(item, Mapping) and item.get("todo_id")
        )

    if exc.code in {
        "idempotency_key_reuse",
        "lease_cas_mismatch",
        "todo_lease_conflict",
        "version_mismatch",
        "write_scope_conflict",
    }:
        raise RevisionConflict(details=details) from exc
    if exc.code in {
        "owner_conflicts_with_claim",
        "owner_excluded_from_todo",
        "owner_not_registered",
    }:
        raise AuthorityDenied(details=details) from exc
    if exc.code in {"corrupt_lease", "todo_projection_unavailable"}:
        raise StateUnavailable(
            details={
                "resource": "task_lease",
                "operation_id": operation_id,
                "core_code": exc.code,
            }
        ) from exc
    raise ValidationFailed(details=details) from exc


def _generated_at(context: ApplicationContext) -> str:
    value = context.clock()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    generated_at = str(value or "").strip()
    if not generated_at:
        raise StateUnavailable(details={"resource": "clock", "cause": "invalid_value"})
    return generated_at


def _optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None
