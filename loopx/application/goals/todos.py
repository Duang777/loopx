"""Typed todo read and lifecycle use cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping

from loopx.control_plane.runtime.local_state_write_correctness import (
    active_state_revision,
)
from loopx.control_plane.todos.contract import (
    normalize_todo_claimed_by,
    normalize_todo_id,
    normalize_todo_status,
)
from loopx.todos import (
    complete_goal_todo,
    list_goal_todos,
    resolve_todo_state,
    update_goal_todo,
)

from ..contracts import (
    WriteContext,
    WriteCorrectness,
    application_public_safe_text,
)
from ..errors import (
    AuthorityDenied,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from .routing import effective_runtime_root, resolve_canonical_goal_route

if TYPE_CHECKING:
    from ..context import ApplicationContext


TODO_WRITE_CORRECTNESS = WriteCorrectness(
    status="pending_migration",
    atomic_revision_check=False,
    idempotent_retry=False,
)


@dataclass(frozen=True, slots=True)
class TodoItem:
    todo_id: str
    role: str
    status: str
    text: str | None
    task_class: str | None
    action_kind: str | None
    claimed_by: str | None
    blocks_agent: str | None
    successor_todo_ids: tuple[str, ...]
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class TodoList:
    goal_id: str
    generated_at: str
    revision: str
    items: tuple[TodoItem, ...]


@dataclass(frozen=True, slots=True)
class TodoUpdatePatch:
    text: str | None = None
    status: str | None = None
    role: str | None = None
    note: str | None = None
    evidence: str | None = None
    reason: str | None = None
    task_class: str | None = None
    action_kind: str | None = None
    claimed_by: str | None = None
    clear_claim: bool = False


@dataclass(frozen=True, slots=True)
class TodoCompletion:
    evidence: str | None = None
    note: str | None = None
    decision_outcome: str | None = None
    claimed_by: str | None = None
    clear_claim: bool = False
    no_followup: bool = False
    successor_todo_ids: tuple[str, ...] = ()
    next_agent_todo: str | None = None
    next_user_todo: str | None = None
    next_user_task_class: str | None = None
    next_claimed_by: str | None = None
    next_task_class: str | None = None
    next_action_kind: str | None = None
    next_task_repository: str | None = None
    next_required_capabilities: tuple[str, ...] = ()
    next_continuation_policy: str | None = None
    next_excluded_agents: tuple[str, ...] = ()
    self_merged: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "successor_todo_ids",
            "next_required_capabilities",
            "next_excluded_agents",
        ):
            value = getattr(self, field_name)
            if isinstance(value, (str, bytes)):
                raise ValidationFailed(details={"field": field_name})
            object.__setattr__(self, field_name, tuple(str(item) for item in value))


@dataclass(frozen=True, slots=True)
class TodoCompletionPlan:
    goal_id: str
    todo_id: str
    actor: str
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    changed: bool
    successor_todo_ids: tuple[str, ...]
    completion: TodoCompletion
    correctness: WriteCorrectness = TODO_WRITE_CORRECTNESS


@dataclass(frozen=True, slots=True)
class TodoMutationResult:
    goal_id: str
    todo_id: str
    generated_at: str
    revision: str
    changed: bool
    item: TodoItem | None
    successor_todo_ids: tuple[str, ...]
    correctness: WriteCorrectness = TODO_WRITE_CORRECTNESS


@dataclass(frozen=True, slots=True)
class GoalTodoService:
    context: ApplicationContext
    goal_id: str

    def list(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        todo_id: str | None = None,
        agent_id: str | None = None,
    ) -> TodoList:
        role, status, todo_id, agent_id = _list_filters(
            role=role,
            status=status,
            todo_id=todo_id,
            agent_id=agent_id,
        )
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        try:
            payload = list_goal_todos(
                registry_path=route.registry_path,
                goal_id=self.goal_id,
                role=role,
                status=status,
                todo_id=todo_id,
                agent_id=agent_id,
                runtime_root_arg=str(effective_runtime_root(self.context, route)),
            )
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "goal_todos", "goal_id": self.goal_id}
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise StateUnavailable(
                details={"resource": "goal_todos", "goal_id": self.goal_id}
            ) from exc
        items = tuple(
            _todo_item(item)
            for item in payload.get("todos") or ()
            if isinstance(item, dict)
        )
        return TodoList(
            goal_id=self.goal_id,
            generated_at=_generated_at(self.context),
            revision=_state_revision(route.registry_path, self.goal_id),
            items=items,
        )

    def claim(
        self,
        todo_id: str,
        *,
        write_context: WriteContext,
    ) -> TodoMutationResult:
        _require_write(self.context, "goal.todos.claim")
        _write_context(write_context)
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        before_revision = _state_revision(route.registry_path, self.goal_id)
        _check_expected_revision(write_context, before_revision, goal_id=self.goal_id)
        payload = _update(
            operation_id="goal.todos.claim",
            registry_path=route.registry_path,
            goal_id=self.goal_id,
            todo_id=todo_id,
            claimed_by=write_context.actor,
            agent_id=write_context.actor,
            claim_only=True,
            dry_run=False,
        )
        return self._mutation_result(todo_id=todo_id, payload=payload)

    def update(
        self,
        todo_id: str,
        patch: TodoUpdatePatch,
        *,
        write_context: WriteContext,
    ) -> TodoMutationResult:
        _require_write(self.context, "goal.todos.update")
        _write_context(write_context)
        if not isinstance(patch, TodoUpdatePatch):
            raise ValidationFailed(details={"field": "patch"})
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        before_revision = _state_revision(route.registry_path, self.goal_id)
        _check_expected_revision(write_context, before_revision, goal_id=self.goal_id)
        options = {
            key: value
            for key, value in asdict(patch).items()
            if value is not None and (value is not False or key == "clear_claim")
        }
        payload = _update(
            operation_id="goal.todos.update",
            registry_path=route.registry_path,
            goal_id=self.goal_id,
            todo_id=todo_id,
            agent_id=write_context.actor,
            dry_run=False,
            **options,
        )
        return self._mutation_result(todo_id=todo_id, payload=payload)

    def preview_complete(
        self,
        todo_id: str,
        completion: TodoCompletion,
        *,
        actor: str,
    ) -> TodoCompletionPlan:
        _require_write(self.context, "goal.todos.complete.preview")
        if not isinstance(completion, TodoCompletion):
            raise ValidationFailed(details={"field": "completion"})
        normalized_actor = _required_text(actor, field="actor")
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        revision = _state_revision(route.registry_path, self.goal_id)
        payload = _complete(
            operation_id="goal.todos.complete.preview",
            registry_path=route.registry_path,
            goal_id=self.goal_id,
            todo_id=todo_id,
            actor=normalized_actor,
            completion=completion,
            dry_run=True,
        )
        successor_ids = _successor_ids(payload)
        return TodoCompletionPlan(
            goal_id=self.goal_id,
            todo_id=todo_id,
            actor=normalized_actor,
            generated_at=_generated_at(self.context),
            revision=revision,
            plan_hash=_completion_plan_hash(
                goal_id=self.goal_id,
                todo_id=todo_id,
                revision=revision,
                actor=normalized_actor,
                completion=completion,
            ),
            can_apply=bool(payload.get("ok", True)),
            changed=bool(payload.get("changed")),
            successor_todo_ids=successor_ids,
            completion=completion,
        )

    def apply_complete(
        self,
        plan: TodoCompletionPlan,
        *,
        write_context: WriteContext,
    ) -> TodoMutationResult:
        _require_write(self.context, "goal.todos.complete.apply")
        _write_context(write_context)
        if not isinstance(plan, TodoCompletionPlan) or plan.goal_id != self.goal_id:
            raise ValidationFailed(details={"field": "plan"})
        if plan.actor != write_context.actor:
            raise AuthorityDenied(
                details={
                    "operation_id": "goal.todos.complete.apply",
                    "reason": "actor_mismatch",
                }
            )
        if write_context.expected_revision is None:
            raise ValidationFailed(details={"field": "write_context.expected_revision"})
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        revision = _state_revision(route.registry_path, self.goal_id)
        _check_expected_revision(write_context, revision, goal_id=self.goal_id)
        current_hash = _completion_plan_hash(
            goal_id=self.goal_id,
            todo_id=plan.todo_id,
            revision=revision,
            actor=plan.actor,
            completion=plan.completion,
        )
        if revision != plan.revision or current_hash != plan.plan_hash:
            raise RevisionConflict(
                details={
                    "goal_id": self.goal_id,
                    "expected_revision": plan.revision,
                    "current_revision": revision,
                    "reason": "plan_stale",
                }
            )
        if not plan.can_apply:
            raise ValidationFailed(details={"field": "plan", "reason": "gated"})
        payload = _complete(
            operation_id="goal.todos.complete.apply",
            registry_path=route.registry_path,
            goal_id=self.goal_id,
            todo_id=plan.todo_id,
            actor=write_context.actor,
            completion=plan.completion,
            dry_run=False,
        )
        return self._mutation_result(todo_id=plan.todo_id, payload=payload)

    def _mutation_result(
        self,
        *,
        todo_id: str,
        payload: Mapping[str, Any],
    ) -> TodoMutationResult:
        refreshed = self.list(todo_id=todo_id)
        item = refreshed.items[0] if refreshed.items else None
        return TodoMutationResult(
            goal_id=self.goal_id,
            todo_id=todo_id,
            generated_at=_generated_at(self.context),
            revision=refreshed.revision,
            changed=bool(payload.get("changed")),
            item=item,
            successor_todo_ids=_successor_ids(payload),
        )


def _update(*, operation_id: str, **options: Any) -> dict[str, Any]:
    try:
        payload = update_goal_todo(**options)
    except OSError as exc:
        raise StateUnavailable(details={"resource": "goal_todos"}) from exc
    except ValueError as exc:
        _raise_if_state_unavailable(options)
        _raise_if_authority_denied(exc, operation_id=operation_id)
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    except (KeyError, TypeError) as exc:
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    if not isinstance(payload, dict):
        raise StateUnavailable(
            details={"resource": "goal_todos", "cause": "invalid_payload"}
        )
    return payload


def _complete(
    *,
    operation_id: str,
    registry_path: Any,
    goal_id: str,
    todo_id: str,
    actor: str | None,
    completion: TodoCompletion,
    dry_run: bool,
) -> dict[str, Any]:
    options = {
        key: value
        for key, value in asdict(completion).items()
        if value not in (None, (), False)
    }
    if completion.clear_claim:
        options["clear_claim"] = True
    if completion.no_followup:
        options["no_followup"] = True
    if completion.self_merged:
        options["self_merged"] = True
    for key in (
        "successor_todo_ids",
        "next_required_capabilities",
        "next_excluded_agents",
    ):
        if key in options:
            options[key] = list(options[key])
    try:
        payload = complete_goal_todo(
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            agent_id=actor,
            dry_run=dry_run,
            **options,
        )
    except OSError as exc:
        raise StateUnavailable(details={"resource": "goal_todos"}) from exc
    except ValueError as exc:
        _raise_if_state_unavailable(
            {"registry_path": registry_path, "goal_id": goal_id},
        )
        _raise_if_authority_denied(exc, operation_id=operation_id)
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    except (KeyError, TypeError) as exc:
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    if not isinstance(payload, dict):
        raise StateUnavailable(
            details={"resource": "goal_todos", "cause": "invalid_payload"}
        )
    return payload


def _todo_item(payload: Mapping[str, Any]) -> TodoItem:
    return TodoItem(
        todo_id=str(payload.get("todo_id") or ""),
        role=str(payload.get("role") or "unknown"),
        status=str(payload.get("status") or "unknown"),
        text=application_public_safe_text(
            payload.get("text") or payload.get("todo"),
            limit=500,
        ),
        task_class=_optional_text(payload.get("task_class")),
        action_kind=_optional_text(payload.get("action_kind")),
        claimed_by=_optional_text(payload.get("claimed_by")),
        blocks_agent=_optional_text(payload.get("blocks_agent")),
        successor_todo_ids=tuple(
            str(item) for item in payload.get("successor_todo_ids") or ()
        ),
        updated_at=_optional_text(payload.get("updated_at")),
    )


def _successor_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    values = list(payload.get("successor_todo_ids") or ())
    for item in payload.get("next_todos") or ():
        if isinstance(item, Mapping) and item.get("todo_id"):
            values.append(str(item["todo_id"]))
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _state_revision(registry_path: Any, goal_id: str) -> str:
    try:
        _, _, state_text, _ = resolve_todo_state(
            registry_path=registry_path,
            goal_id=goal_id,
        )
    except OSError as exc:
        raise StateUnavailable(
            details={"resource": "goal_todos", "goal_id": goal_id}
        ) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "goal_todos", "goal_id": goal_id}
        ) from exc
    return active_state_revision(state_text)["value"]


def _completion_plan_hash(
    *,
    goal_id: str,
    todo_id: str,
    revision: str,
    actor: str,
    completion: TodoCompletion,
) -> str:
    material = {
        "goal_id": goal_id,
        "todo_id": todo_id,
        "revision": revision,
        "actor": actor,
        "completion": asdict(completion),
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _check_expected_revision(
    write_context: WriteContext,
    current_revision: str,
    *,
    goal_id: str,
) -> None:
    expected = write_context.expected_revision
    if expected is not None and expected != current_revision:
        raise RevisionConflict(
            details={
                "goal_id": goal_id,
                "expected_revision": expected,
                "current_revision": current_revision,
            }
        )


def _write_context(value: object) -> WriteContext:
    if not isinstance(value, WriteContext):
        raise ValidationFailed(details={"field": "write_context"})
    return value


def _require_write(context: ApplicationContext, operation_id: str) -> None:
    if not context.writes_available:
        raise AuthorityDenied(
            details={"operation_id": operation_id, "profile": context.profile.value}
        )


def _generated_at(context: ApplicationContext) -> str:
    value = context.clock()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    text = str(value or "").strip()
    if not text:
        raise StateUnavailable(details={"resource": "clock", "cause": "invalid_value"})
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value.strip()


def _list_filters(
    *,
    role: str | None,
    status: str | None,
    todo_id: str | None,
    agent_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    normalized_role = None
    if role is not None:
        normalized_role = str(role).strip().lower()
        if normalized_role not in {"agent", "user"}:
            raise ValidationFailed(details={"field": "role"})

    normalized_status = None
    if status is not None:
        normalized_status = normalize_todo_status(status)
        if normalized_status is None:
            raise ValidationFailed(details={"field": "status"})

    normalized_todo_id = None
    if todo_id is not None:
        normalized_todo_id = normalize_todo_id(todo_id)
        if normalized_todo_id is None:
            raise ValidationFailed(details={"field": "todo_id"})

    normalized_agent_id = None
    if agent_id is not None:
        normalized_agent_id = normalize_todo_claimed_by(agent_id)
        if normalized_agent_id is None:
            raise ValidationFailed(details={"field": "agent_id"})

    return (
        normalized_role,
        normalized_status,
        normalized_todo_id,
        normalized_agent_id,
    )


def _raise_if_state_unavailable(
    options: Mapping[str, Any],
) -> None:
    registry_path = options.get("registry_path")
    goal_id = str(options.get("goal_id") or "")
    try:
        resolve_todo_state(registry_path=registry_path, goal_id=goal_id)
    except (KeyError, OSError, TypeError, ValueError) as state_error:
        raise StateUnavailable(
            details={"resource": "goal_todos", "goal_id": goal_id}
        ) from state_error


def _raise_if_authority_denied(exc: ValueError, *, operation_id: str) -> None:
    message = str(exc).lower()
    authority_markers = (
        "requires --agent-id",
        "is excluded from mutating",
        " is not registered for goal ",
        "has no coordination.registered_agents",
        "cannot complete todo_id",
        "cannot update todo_id",
        "cannot claim todo_id",
        "does not grant action",
        "override requires --authority-reason",
        "todo claim requires --claimed-by",
    )
    if any(marker in message for marker in authority_markers):
        raise AuthorityDenied(
            details={
                "operation_id": operation_id,
                "reason": "core_authority_denied",
            }
        ) from exc
