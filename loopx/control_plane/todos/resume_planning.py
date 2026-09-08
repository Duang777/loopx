"""Compatibility codecs for the typed, read-only Todo resume planning owner."""

from __future__ import annotations

from typing import Any

from ..effect_runtime import EffectRuntimeRejected, effect_runtime_result
from .contract import (
    normalize_required_capabilities, normalize_required_write_scopes,
    normalize_todo_claimed_by, normalize_todo_decision_scope, normalize_todo_id,
    normalize_todo_required_decision_scopes, normalize_todo_resume_when,
    normalize_todo_status, normalize_todo_task_class, normalize_todo_excluded_agents,
)
from .projection import todo_projection_sort_key

_SOURCE_KEYS = (
    "items", "backlog_items", "first_open_items", "deferred_items",
    "deferred_resume_candidates", "resume_blocked_items", "monitor_open_items",
    "current_agent_claimed_monitor_items", "claimed_monitor_open_items",
)


def _todo_task_class(item: dict[str, Any]) -> str:
    text = " ".join(
        str(value or "")
        for value in (item.get("title"), item.get("text"))
        if str(value or "").strip()
    )
    return normalize_todo_task_class(
        item.get("task_class"),
        text=text,
        action_kind=item.get("action_kind"),
    )


def _compact_deferred_resume_item(
    item: dict[str, Any],
    *,
    text: str,
) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "index": item.get("index"),
        "text": text,
    }
    for key in (
        "schema_version",
        "todo_id",
        "role",
        "status",
        "priority",
        "title",
        "archive_state",
        "source_section",
        "task_class",
        "action_kind",
        "task_domain",
        "task_repository",
        "continuation_policy",
        "required_write_scopes",
        "required_capabilities",
        "target_capabilities",
        "decision_scope",
        "required_decision_scopes",
        "claimed_by",
        "blocks_agent",
        "excluded_agents",
        "unblocks_todo_id",
        "resume_when",
        "resume_monitor_generation",
        "resume_condition",
        "resume_ready",
        "no_followup",
        "successor_todo_ids",
        "target_key",
        "cadence",
        "next_due_at",
        "expires_at",
        "last_checked_at",
        "result_hash",
        "consecutive_no_change",
        "material_change",
        "material_change_generation",
        "max_no_change_before_replan",
        "route_continuation_replan_required",
        "route_continuation_reason",
        "route_id",
        "route_key",
        "completed_at",
        "updated_at",
        "superseded_by",
    ):
        if item.get(key) is not None:
            compact[key] = item.get(key)
    required_write_scopes = normalize_required_write_scopes(compact.get("required_write_scopes"))
    if required_write_scopes:
        compact["required_write_scopes"] = required_write_scopes
    else:
        compact.pop("required_write_scopes", None)
    decision_scope = normalize_todo_decision_scope(compact.get("decision_scope"))
    if decision_scope:
        compact["decision_scope"] = decision_scope
    else:
        compact.pop("decision_scope", None)
    required_decision_scopes = normalize_todo_required_decision_scopes(
        compact.get("required_decision_scopes")
    )
    if required_decision_scopes:
        compact["required_decision_scopes"] = required_decision_scopes
    else:
        compact.pop("required_decision_scopes", None)
    compact["task_class"] = _todo_task_class(compact)
    return compact


def _planning_item(item: dict[str, Any]) -> dict[str, Any]:
    payload = _compact_deferred_resume_item(item, text=str(item.get("text") or "").strip())
    condition = item.get("resume_condition")
    condition = condition if isinstance(condition, dict) else {}
    priority, index = todo_projection_sort_key(payload)
    ready = item.get("resume_ready")
    return {
        "payload": payload, "id": normalize_todo_id(item.get("todo_id")),
        "status": normalize_todo_status(item.get("status")),
        "claim": normalize_todo_claimed_by(item.get("claimed_by")),
        "excluded": normalize_todo_excluded_agents(item.get("excluded_agents")),
        "resume": normalize_todo_resume_when(item.get("resume_when")),
        "done": item.get("done") is True,
        "ready": ready if isinstance(ready, bool) else None,
        "ready_truthy": bool(ready), "priority": priority, "index": index,
        "target_id": normalize_todo_id(condition.get("target_todo_id") or condition.get("target")),
        "target_status": normalize_todo_status(condition.get("target_status")),
        "target_class": normalize_todo_task_class(condition.get("target_task_class"), text=""),
    }


def project_todo_resume_planning(
    value: Any, *, agent_id: str | None = None, item_limit: int = 5,
    available_capabilities: Any = None,
) -> dict[str, Any]:
    """Project one snapshot; no business write or additional authority is granted."""
    value = value if isinstance(value, dict) else {}
    sources = {}
    encoded: dict[int, dict[str, Any]] = {}
    for key in _SOURCE_KEYS:
        raw = value.get(key)
        rows = []
        for item in raw if isinstance(raw, list) else []:
            # An ignored row still makes the supplied lane nonempty. Preserve
            # that fact so malformed legacy entries cannot activate fallback.
            identity = id(item) if isinstance(item, dict) else -1
            if identity not in encoded:
                encoded[identity] = _planning_item(item if isinstance(item, dict) else {})
            rows.append(encoded[identity])
        sources[key] = rows
    try:
        result = effect_runtime_result("todo.resume_planning.project", {
            "schema_version": "todo_resume_planning_request_v0",
            "sources": sources,
            "agent_id": normalize_todo_claimed_by(agent_id), "item_limit": item_limit,
            "has_deferred_count": "deferred_count" in value,
            "has_visible_deferred_count": bool(value.get("deferred_count")),
            "deferred_count": value.get("deferred_count"),
            "available_capabilities": (
                normalize_required_capabilities(available_capabilities)
                if available_capabilities is not None else None
            ),
        })
    except EffectRuntimeRejected as exc:
        raise ValueError(str(exc)) from None
    if not isinstance(result, dict) or result.get("schema_version") != "todo_resume_planning_v0":
        raise RuntimeError("TypeScript Todo resume planning shape mismatch")
    return result
