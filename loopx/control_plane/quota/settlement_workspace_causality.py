"""Typed repository-workspace causality for quota settlement effects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..todos.contract import (
    normalize_required_write_scopes,
    normalize_todo_continuation_policy,
    normalize_todo_id,
    normalize_todo_task_repository,
)

DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION = "delivery_workspace_causality_v0"
DELIVERY_WORKSPACE_REQUIREMENTS = frozenset(
    {"required", "not_required", "unknown"}
)


def build_delivery_workspace_causality(
    todo: Mapping[str, Any] | None,
    *,
    source: str = "selected_todo_contract",
) -> dict[str, str] | None:
    """Classify whether one exact Todo makes a repository workspace causal.

    Missing repository metadata alone cannot bypass the workspace guard. Only
    an explicit non-delivery continuation without a write capability is a
    positive no-workspace contract; underspecified legacy Todos stay unknown.
    """

    if not isinstance(todo, Mapping):
        return None
    todo_id = normalize_todo_id(todo.get("todo_id"))
    if not todo_id:
        return None
    task_repository = normalize_todo_task_repository(todo.get("task_repository"))
    required_write_scopes = normalize_required_write_scopes(
        todo.get("required_write_scopes") or todo.get("required_write_scope")
    )
    capabilities = todo.get("required_capabilities")
    required_capabilities = {
        str(capability).strip()
        for capability in (
            capabilities if isinstance(capabilities, (list, tuple, set)) else []
        )
        if str(capability).strip()
    }
    continuation_policy = normalize_todo_continuation_policy(
        todo.get("continuation_policy")
    )
    if task_repository or required_write_scopes or "filesystem_write" in required_capabilities:
        requirement = "required"
        reason = "declared_repository_or_write_contract"
    elif continuation_policy == "same_agent_non_delivery":
        requirement = "not_required"
        reason = "explicit_non_delivery_without_repository_writes"
    else:
        requirement = "unknown"
        reason = "todo_write_contract_not_explicit"
    return {
        "schema_version": DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
        "todo_id": todo_id,
        "requirement": requirement,
        "source": source,
        "reason": reason,
    }


def normalize_delivery_workspace_causality(
    value: Any,
    *,
    todo_id: str | None = None,
) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("schema_version") != DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION:
        return None
    normalized_todo_id = normalize_todo_id(value.get("todo_id"))
    expected_todo_id = normalize_todo_id(todo_id)
    if not normalized_todo_id or (
        expected_todo_id and normalized_todo_id != expected_todo_id
    ):
        return None
    requirement = str(value.get("requirement") or "").strip()
    if requirement not in DELIVERY_WORKSPACE_REQUIREMENTS:
        return None
    source = str(value.get("source") or "").strip()
    reason = str(value.get("reason") or "").strip()
    if not source or not reason:
        return None
    return {
        "schema_version": DELIVERY_WORKSPACE_CAUSALITY_SCHEMA_VERSION,
        "todo_id": normalized_todo_id,
        "requirement": requirement,
        "source": source,
        "reason": reason,
    }


def delivery_workspace_causality_event_fields(
    causality: Mapping[str, Any] | None,
) -> dict[str, str]:
    normalized = normalize_delivery_workspace_causality(causality)
    if not normalized:
        return {}
    return {
        "delivery_workspace_causality_schema_version": normalized[
            "schema_version"
        ],
        "delivery_workspace_causality_todo_id": normalized["todo_id"],
        "delivery_workspace_requirement": normalized["requirement"],
        "delivery_workspace_causality_source": normalized["source"],
        "delivery_workspace_causality_reason": normalized["reason"],
    }


def delivery_workspace_causality_from_event_details(
    details: Mapping[str, Any] | None,
    *,
    todo_id: str | None,
) -> dict[str, str] | None:
    if not isinstance(details, Mapping):
        return None
    nested = normalize_delivery_workspace_causality(
        details.get("delivery_workspace_causality"), todo_id=todo_id
    )
    if nested:
        return nested
    return normalize_delivery_workspace_causality(
        {
            "schema_version": details.get(
                "delivery_workspace_causality_schema_version"
            ),
            "todo_id": details.get("delivery_workspace_causality_todo_id"),
            "requirement": details.get("delivery_workspace_requirement"),
            "source": details.get("delivery_workspace_causality_source"),
            "reason": details.get("delivery_workspace_causality_reason"),
        },
        todo_id=todo_id,
    )


def completed_todo_workspace_causality(
    status_payload: Mapping[str, Any],
    *,
    goal_id: str,
    todo_id: str,
) -> dict[str, str] | None:
    """Recover a legacy effect's causality from its exact completed Todo."""

    queue = status_payload.get("attention_queue")
    queue_items = queue.get("items") if isinstance(queue, Mapping) else []
    for queue_item in queue_items if isinstance(queue_items, list) else []:
        if not isinstance(queue_item, Mapping):
            continue
        if str(queue_item.get("goal_id") or "") != goal_id:
            continue
        project_asset = queue_item.get("project_asset")
        owners = (
            queue_item,
            project_asset if isinstance(project_asset, Mapping) else {},
        )
        for owner in owners:
            summary = owner.get("agent_todos")
            if not isinstance(summary, Mapping):
                continue
            for key in ("items", "recent_completed_advancement_items"):
                items = summary.get(key)
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, Mapping):
                        continue
                    if normalize_todo_id(item.get("todo_id")) != todo_id:
                        continue
                    return build_delivery_workspace_causality(
                        item,
                        source="completed_todo_contract_fallback",
                    )
    return None
