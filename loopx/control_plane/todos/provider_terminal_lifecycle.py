"""Provider-first complete, supersede, and archive adapters.

Python projects registry facts, constructs caller proposals, executes a typed
validation effect, and drains the committed Markdown projection outbox.  The
TypeScript transaction is the sole owner of lifecycle admission and writes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import wraps
from inspect import signature
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from ...agent_registry import load_goal_from_registry, registered_agent_ids_for_goal
from ...state_refresh import now_local
from ..coordination.local_authority import (
    LocalCoordinationAuthorityUnavailable,
    read_canonical_todos_if_promoted,
)
from ..coordination.local_authority_shadow_adapter import effective_runtime_root
from ..effect_runtime import effect_runtime_result
from .completion_policy import (
    build_completion_policy_request,
    linked_successor_from_todo,
)
from .completion_validation import (
    resolve_private_completion_validation_declaration,
    run_declared_completion_validation_effect,
)
from .completion_transaction import require_completion_successor_todo_ids
from .contract import (
    build_todo_id,
    normalize_todo_metadata_for_write,
    normalize_todo_task_class,
    resolve_next_user_task_class,
)
from .mutation_authority import normalize_todo_lifecycle_authority
from .path_resolution import resolve_todo_state_path
from .provider_projection import settle_canonical_todo_projection
from .text import inherit_todo_priority


_TERMINAL_REQUEST_SCHEMA = "loopx_local_coordination_todo_terminal_lifecycle_request_v0"
_ARCHIVE_REQUEST_SCHEMA = "loopx_local_coordination_todo_archive_request_v0"
_ACCEPTED = {"applied", "recovered", "replayed", "no_change", "planned"}


TodoMutation = Callable[..., dict[str, Any]]


def _route_terminal_call(command: str, call: Mapping[str, Any]) -> dict[str, Any] | None:
    registry_path = Path(call["registry_path"])
    goal_id = str(call["goal_id"])
    runtime_root = effective_runtime_root(registry_path, call.get("runtime_root_arg"))
    if command == "archive":
        role = str(call["role"])
        max_active_done = int(call["max_active_done"])
        if role not in {"user", "agent"}:
            raise ValueError("todo role must be one of: user, agent")
        if max_active_done < 0:
            raise ValueError("max_active_done must be non-negative")
        project, state_file = resolve_todo_state_path(
            registry_path=registry_path,
            goal_id=goal_id,
            project=call.get("project"),
            state_file=call.get("state_file"),
        )
        return archive_canonical_todos_if_promoted(
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            role=role,
            max_active_done=max_active_done,
            dry_run=bool(call["dry_run"]),
            project=project,
            state_file=state_file,
        )

    next_agent_todo = call.get("next_agent_todo")
    if call.get("next_task_repository") and not next_agent_todo:
        raise ValueError("--next-task-repository requires --next-agent-todo")
    if call.get("next_required_capabilities") and not next_agent_todo:
        raise ValueError("--next-required-capability requires --next-agent-todo")
    project, state_file = resolve_todo_state_path(
        registry_path=registry_path,
        goal_id=goal_id,
        project=call.get("project"),
        state_file=call.get("state_file"),
    )
    complete = command == "complete"
    return terminal_canonical_todo_if_promoted(
        registry_path=registry_path,
        runtime_root=runtime_root,
        goal_id=goal_id,
        command=command,
        todo_id=str(call["todo_id"]),
        role=call.get("role"),
        actor_agent_id=call.get("agent_id"),
        authority_reason=call.get("authority_reason"),
        decision_outcome=call.get("decision_outcome") if complete else None,
        evidence=call.get("evidence") if complete else None,
        note=call.get("note") if complete else "superseded",
        reason=None if complete else call.get("reason"),
        completion_turn_key=call.get("completion_turn_key") if complete else None,
        completion_identity_source=(
            call.get("completion_identity_source") if complete else None
        ),
        task_lease_idempotency_key=call.get("task_lease_idempotency_key"),
        task_lease_expected_version=call.get("task_lease_expected_version"),
        no_followup=bool(call.get("no_followup")) if complete else False,
        successor_todo_ids=(
            require_completion_successor_todo_ids(call.get("successor_todo_ids"))
            if complete
            else []
        ),
        claimed_by=call.get("claimed_by") if complete else None,
        clear_claim=bool(call.get("clear_claim")) if complete else False,
        next_agent_todo=next_agent_todo,
        next_user_todo=call.get("next_user_todo"),
        next_user_task_class=resolve_next_user_task_class(
            call.get("next_user_todo"), call.get("next_user_task_class")
        ),
        next_claimed_by=call.get("next_claimed_by"),
        next_task_class=call.get("next_task_class"),
        next_action_kind=call.get("next_action_kind"),
        next_task_repository=call.get("next_task_repository"),
        next_required_capabilities=call.get("next_required_capabilities"),
        next_continuation_policy=call.get("next_continuation_policy"),
        next_excluded_agents=call.get("next_excluded_agents"),
        self_merged=bool(call.get("self_merged")) if complete else False,
        dry_run=bool(call["dry_run"]),
        project=project,
        state_file=state_file,
    )


def provider_first_terminal_lifecycle(command: str) -> Callable[[TodoMutation], TodoMutation]:
    """Route the public facade through canonical authority before legacy fallback."""
    if command not in {"complete", "supersede", "archive"}:
        raise ValueError(f"unsupported terminal lifecycle command: {command}")

    def decorate(legacy: TodoMutation) -> TodoMutation:
        call_signature = signature(legacy)

        @wraps(legacy)
        def routed(*args: Any, **kwargs: Any) -> dict[str, Any]:
            bound = call_signature.bind(*args, **kwargs)
            bound.apply_defaults()
            result = _route_terminal_call(command, bound.arguments)
            return result if result is not None else legacy(*args, **kwargs)

        return routed

    return decorate


def _goal_facts(
    registry_path: Path, goal_id: str
) -> tuple[list[str], list[dict[str, Any]]]:
    goal = load_goal_from_registry(registry_path, goal_id)
    registered = registered_agent_ids_for_goal(goal)
    coordination = goal.get("coordination") if isinstance(goal, Mapping) else None
    grants = normalize_todo_lifecycle_authority(
        coordination.get("todo_lifecycle_authority")
        if isinstance(coordination, Mapping)
        else None,
        registered_agents=registered,
    )
    return registered, grants


def _todo_by_id(
    todos: Iterable[Mapping[str, Any]], todo_id: str
) -> dict[str, Any] | None:
    return next(
        (dict(todo) for todo in todos if str(todo.get("todo_id") or "") == todo_id),
        None,
    )


def _successor_record(
    *,
    todos: Sequence[Mapping[str, Any]],
    role: str,
    text: str,
    actor_agent_id: str | None,
    metadata: Mapping[str, Any],
    offset: int,
) -> dict[str, Any]:
    section = "Agent Todo" if role == "agent" else "User Todo"
    same_role_count = sum(1 for todo in todos if todo.get("role") == role)
    normalized = normalize_todo_metadata_for_write(dict(metadata))
    return {
        "schema_version": "todo_domain_record_v0",
        "todo_id": build_todo_id(
            role=role,
            source_section=section,
            index=same_role_count + offset,
            text=text,
        ),
        "role": role,
        "status": "open",
        "done": False,
        "text": text,
        "archive_state": "active",
        "task_class": normalize_todo_task_class(
            normalized.get("task_class"),
            text=text,
            action_kind=normalized.get("action_kind"),
        ),
        **normalized,
        **({"created_by": actor_agent_id} if actor_agent_id else {}),
    }


def _build_successors(
    *,
    todos: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    command: str,
    next_agent_todo: str | None,
    next_user_todo: str | None,
    next_user_task_class: str | None,
    next_claimed_by: str | None,
    next_task_class: str | None,
    next_action_kind: str | None,
    next_task_repository: str | None,
    next_required_capabilities: list[str] | None,
    next_continuation_policy: str | None,
    next_excluded_agents: list[str] | None,
    actor_agent_id: str | None,
    completing_claimed_by: str | None,
) -> list[dict[str, Any]]:
    successors: list[dict[str, Any]] = []
    target_id = str(target.get("todo_id") or "")
    target_text = str(target.get("text") or "")
    if next_agent_todo:
        successors.append(
            _successor_record(
                todos=todos,
                role="agent",
                text=inherit_todo_priority(next_agent_todo, target_text),
                actor_agent_id=actor_agent_id,
                offset=1,
                metadata={
                    "task_class": next_task_class or "advancement_task",
                    "action_kind": next_action_kind,
                    "capability_binding_ref": target.get("capability_binding_ref"),
                    "task_repository": next_task_repository,
                    "required_capabilities": next_required_capabilities,
                    "continuation_policy": next_continuation_policy,
                    "claimed_by": next_claimed_by,
                    "excluded_agents": next_excluded_agents or [],
                    "unblocks_todo_id": (
                        target_id
                        if command == "complete"
                        else target.get("unblocks_todo_id")
                    ),
                },
            )
        )
    if next_user_todo:
        effective_task_class = resolve_next_user_task_class(
            next_user_todo, next_user_task_class
        )
        inherited_binding = target.get("bound_agent") or target.get("blocks_agent")
        bound_agent = (
            completing_claimed_by
            if command == "complete"
            else inherited_binding or target.get("claimed_by") or next_claimed_by
        )
        successors.append(
            _successor_record(
                todos=todos,
                role="user",
                text=inherit_todo_priority(next_user_todo, target_text),
                actor_agent_id=actor_agent_id,
                offset=1,
                metadata={
                    "task_class": effective_task_class,
                    "action_kind": (
                        "gate" if effective_task_class == "user_gate" else None
                    ),
                    "bound_agent": bound_agent,
                    "blocks_agent": (
                        bound_agent if effective_task_class == "user_gate" else None
                    ),
                },
            )
        )
    return successors


def _terminal_failure_payload(
    result: Mapping[str, Any], *, goal_id: str, todo_id: str, dry_run: bool
) -> dict[str, Any] | None:
    if result.get("status") != "failed":
        return None
    if result.get("reason_code") not in {
        "validation_declaration_invalid",
        "validation_failed",
    }:
        return None
    return {
        "ok": False,
        "dry_run": dry_run,
        "completed": False,
        "changed": False,
        "goal_id": goal_id,
        "todo_id": todo_id,
        "validation_blocked_completion": True,
        "reason": result.get("reason"),
        "validation_failure": result.get("validation_failure"),
        **dict(result),
    }


def _projection_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LocalCoordinationAuthorityUnavailable(
            "canonical Todo projection returned an invalid result",
            code="local_authority_todo_projection_invalid_result",
            payload={"source_authority": "file_v0"},
        )
    return dict(value)


def terminal_canonical_todo_if_promoted(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    command: str,
    todo_id: str,
    role: str | None,
    actor_agent_id: str | None,
    authority_reason: str | None,
    decision_outcome: str | None,
    evidence: str | None,
    note: str | None,
    reason: str | None,
    completion_turn_key: str | None,
    completion_identity_source: str | None,
    task_lease_idempotency_key: str | None,
    task_lease_expected_version: int | None,
    no_followup: bool,
    successor_todo_ids: list[str],
    claimed_by: str | None,
    clear_claim: bool,
    next_agent_todo: str | None,
    next_user_todo: str | None,
    next_user_task_class: str | None,
    next_claimed_by: str | None,
    next_task_class: str | None,
    next_action_kind: str | None,
    next_task_repository: str | None,
    next_required_capabilities: list[str] | None,
    next_continuation_policy: str | None,
    next_excluded_agents: list[str] | None,
    self_merged: bool,
    dry_run: bool,
    project: Path | None = None,
    state_file: Path | None = None,
) -> dict[str, Any] | None:
    canonical = read_canonical_todos_if_promoted(
        runtime_root=runtime_root, goal_id=goal_id
    )
    if canonical is None:
        return None
    todos = [dict(todo) for todo in canonical["todos"]]
    target = _todo_by_id(todos, todo_id)
    if target is None:
        raise ValueError(f"todo_id {todo_id!r} was not found in canonical authority")
    registered, grants = _goal_facts(registry_path, goal_id)
    successors = _build_successors(
        todos=todos,
        target=target,
        command=command,
        next_agent_todo=next_agent_todo,
        next_user_todo=next_user_todo,
        next_user_task_class=next_user_task_class,
        next_claimed_by=next_claimed_by,
        next_task_class=next_task_class,
        next_action_kind=next_action_kind,
        next_task_repository=next_task_repository,
        next_required_capabilities=next_required_capabilities,
        next_continuation_policy=next_continuation_policy,
        next_excluded_agents=next_excluded_agents,
        actor_agent_id=actor_agent_id,
        completing_claimed_by=claimed_by,
    )
    linked = [
        linked_successor_from_todo(todo)
        for linked_id in successor_todo_ids
        if (todo := _todo_by_id(todos, linked_id)) is not None
    ]
    completion_policy_request = (
        build_completion_policy_request(
            registry_path=registry_path,
            goal_id=goal_id,
            claimed_by=claimed_by,
            next_claimed_by=next_claimed_by,
            next_agent_todo=next_agent_todo,
            next_action_kind=next_action_kind,
            next_continuation_policy=next_continuation_policy,
            next_excluded_agents=next_excluded_agents or [],
            self_merged=self_merged,
            evidence=evidence,
            linked_successors=linked,
        )
        if command == "complete"
        else None
    )
    operation_id = f"todo-terminal:{command}:{goal_id}:{todo_id}:{uuid4().hex}"
    validation_declaration = None
    if command == "complete" and target.get("completion_validation_required") is True:
        if state_file is None:
            raise ValueError(
                "canonical Todo completion validation requires its private state projection"
            )
        validation_declaration = resolve_private_completion_validation_declaration(
            canonical_todo=target,
            state_file=state_file,
            runtime_root=runtime_root,
            registry_path=registry_path,
            goal_id=goal_id,
            todo_id=todo_id,
            role=role,
            persist_if_resolved=not dry_run,
        )
    request = {
        "schema_version": _TERMINAL_REQUEST_SCHEMA,
        "runtime_root": str(runtime_root.expanduser().resolve(strict=False)),
        "goal_id": goal_id,
        "todo_id": todo_id,
        "role": role,
        "command": command,
        "actor_agent_id": actor_agent_id,
        "registered_agents": registered,
        "lifecycle_grants": grants,
        "authority_reason": authority_reason,
        "decision_outcome": decision_outcome,
        "operation_id": operation_id,
        "lease_idempotency_key": task_lease_idempotency_key,
        "lease_expected_version": task_lease_expected_version,
        "allow_user_gate_auto_acquire": command == "complete",
        "requested_no_followup": no_followup,
        "requested_completion_turn_key": completion_turn_key,
        "requested_completion_identity_source": completion_identity_source,
        "linked_successor_todo_ids": successor_todo_ids,
        "successors": successors,
        "note": note,
        "evidence": evidence,
        "reason": reason,
        "clear_claim": clear_claim,
        "validation_declaration": validation_declaration,
        "validation_receipt": None,
        "completion_policy_request": completion_policy_request,
        "dry_run": dry_run,
        "observed_at": now_local(),
    }
    result = effect_runtime_result(
        "coordination.local_authority.todo_terminal", request
    )
    if isinstance(result, Mapping) and result.get("status") == "execute_validation":
        effect = result.get("validation_effect")
        if not isinstance(effect, Mapping):
            raise RuntimeError("Todo terminal validation effect shape mismatch")
        request["validation_receipt"] = run_declared_completion_validation_effect(
            effect=effect,
            registry_path=registry_path,
            goal_id=goal_id,
        )
        result = effect_runtime_result(
            "coordination.local_authority.todo_terminal", request
        )
    if not isinstance(result, Mapping):
        raise LocalCoordinationAuthorityUnavailable(
            "canonical Todo terminal transaction returned an invalid result",
            code="local_authority_todo_terminal_invalid_result",
            payload={"source_authority": "file_v0"},
        )
    validation_failure = _terminal_failure_payload(
        result, goal_id=goal_id, todo_id=todo_id, dry_run=dry_run
    )
    if validation_failure is not None:
        return validation_failure
    payload = dict(result)
    if (
        payload.get("status") not in _ACCEPTED
        or payload.get("source_authority") != "file_v0"
        or payload.get("decision_read_from_provider") is not True
        or payload.get("legacy_fallback_used") is not False
    ):
        raise LocalCoordinationAuthorityUnavailable(
            str(payload.get("reason") or "canonical Todo terminal transaction failed"),
            code=str(
                payload.get("reason_code") or "local_authority_todo_terminal_failed"
            ),
            payload=payload,
        )
    response = {
        "ok": True,
        "dry_run": dry_run,
        "completed": command == "complete",
        "superseded": command == "supersede",
        "goal_id": goal_id,
        "role": target.get("role"),
        "todo_id": todo_id,
        "status": "done",
        "next_todos": successors,
        "mutation_authority": payload.get("terminal_decision"),
        "task_lease_fence": payload.get("terminal_decision"),
        **payload,
    }
    return _projection_payload(
        settle_canonical_todo_projection(
            response,
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            project=project,
            state_file=state_file,
        )
    )


def archive_canonical_todos_if_promoted(
    *,
    registry_path: Path,
    runtime_root: Path,
    goal_id: str,
    role: str,
    max_active_done: int,
    dry_run: bool,
    project: Path | None = None,
    state_file: Path | None = None,
) -> dict[str, Any] | None:
    if (
        read_canonical_todos_if_promoted(runtime_root=runtime_root, goal_id=goal_id)
        is None
    ):
        return None
    result = effect_runtime_result(
        "coordination.local_authority.todo_archive",
        {
            "schema_version": _ARCHIVE_REQUEST_SCHEMA,
            "runtime_root": str(runtime_root.expanduser().resolve(strict=False)),
            "goal_id": goal_id,
            "role": role,
            "max_active_done": max_active_done,
            "operation_id": f"todo-archive:{goal_id}:{role}:{uuid4().hex}",
            "dry_run": dry_run,
            "observed_at": now_local(),
        },
    )
    if not isinstance(result, Mapping) or result.get("status") not in _ACCEPTED:
        payload = dict(result) if isinstance(result, Mapping) else {}
        raise LocalCoordinationAuthorityUnavailable(
            str(payload.get("reason") or "canonical Todo archive transaction failed"),
            code=str(
                payload.get("reason_code") or "local_authority_todo_archive_failed"
            ),
            payload=payload,
        )
    return _projection_payload(
        settle_canonical_todo_projection(
            {"ok": True, "dry_run": dry_run, "goal_id": goal_id, **dict(result)},
            registry_path=registry_path,
            runtime_root=runtime_root,
            goal_id=goal_id,
            project=project,
            state_file=state_file,
        )
    )


__all__ = [
    "archive_canonical_todos_if_promoted",
    "provider_first_terminal_lifecycle",
    "terminal_canonical_todo_if_promoted",
]
