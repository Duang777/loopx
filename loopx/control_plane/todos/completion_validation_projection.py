"""Public-safe projection for controller-declared Todo completion validation."""

from __future__ import annotations

from typing import Any

from .contract import (
    TODO_STATUS_DONE,
    normalize_todo_claimed_by,
    normalize_todo_id,
)


def project_completion_validation_authority(item: dict[str, Any]) -> dict[str, Any]:
    """Replace private validation execution details with one authority marker."""

    projected = dict(item)
    command = str(projected.pop("validation_command", "") or "").strip()
    argv = projected.pop("validation_command_argv", None)
    projected.pop("validation_label", None)
    projected.pop("validation_timeout_seconds", None)
    argv_declared = argv is not None and str(argv).strip() != ""
    if command or argv_declared:
        projected["completion_validation_required"] = True
    return projected


def pending_completion_validation_todo(
    todo_summary: dict[str, Any] | None,
    *,
    todo_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    """Return a projected open Todo whose controller validation is required.

    Two scopes, because the caller either names the Todo or only names a lane:

    - Exact scope (``todo_id`` given): the settlement binds that Todo, so its
      claim state is irrelevant and an unclaimed Todo still fences.
    - Lane scope (only ``agent_id`` given): the fence exists so an agent cannot
      claim accountable evidence while *its own* controller-validated Todo is
      open. An unclaimed Todo owns no lane, so it is nobody's own work and must
      not fence a different lane's writeback.
    """

    if not isinstance(todo_summary, dict):
        return None
    expected_todo_id = normalize_todo_id(todo_id)
    expected_agent_id = normalize_todo_claimed_by(agent_id)
    lane_scoped = not expected_todo_id and bool(expected_agent_id)
    items = todo_summary.get("items")
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_todo_id = normalize_todo_id(item.get("todo_id"))
        if expected_todo_id and item_todo_id != expected_todo_id:
            continue
        item_agent_id = normalize_todo_claimed_by(item.get("claimed_by"))
        if lane_scoped:
            if item_agent_id != expected_agent_id:
                continue
        elif (
            expected_agent_id
            and item_agent_id
            and item_agent_id != expected_agent_id
        ):
            continue
        if item.get("completion_validation_required") is not True:
            continue
        if item.get("done") is True or item.get("status") == TODO_STATUS_DONE:
            continue
        return item
    return None
