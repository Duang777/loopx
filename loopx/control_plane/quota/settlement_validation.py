"""Todo validation authority checks for quota settlement."""

from __future__ import annotations

from typing import Any

from ..todos.completion_validation_projection import (
    pending_completion_validation_todo,
)
from ..todos.contract import normalize_todo_id


def _is_qualified_semantic_replan_writeback(
    delivery_run: dict[str, Any] | None,
    *,
    todo_id: str,
) -> bool:
    """Recognize the durable proof that an open Todo changed its path.

    The refresh path writes this acknowledgement only after typed replan
    qualification.  Spend may trust it only through the exact Turn settlement
    readback; callers must not pass an unrelated latest run.
    """

    if not isinstance(delivery_run, dict):
        return False
    settlement_identity = delivery_run.get("settlement_identity")
    if (
        normalize_todo_id(delivery_run.get("todo_id")) != todo_id
        or not isinstance(settlement_identity, dict)
        or normalize_todo_id(settlement_identity.get("todo_id")) != todo_id
    ):
        return False
    ack = delivery_run.get("autonomous_replan_ack")
    if (
        not isinstance(ack, dict)
        or ack.get("schema_version") != "autonomous_replan_ack_v0"
        or ack.get("recorded") is not True
    ):
        return False
    semantic_delta = ack.get("semantic_delta")
    if (
        isinstance(semantic_delta, dict)
        and semantic_delta.get("schema_version") == "replan_semantic_delta_v0"
        and semantic_delta.get("accepted") is True
    ):
        return True
    delta_contract = ack.get("delta_contract")
    return bool(
        isinstance(delta_contract, dict)
        and delta_contract.get("schema_version") == "repair_delta_contract_v0"
        and delta_contract.get("delta_present") is True
    )


def completion_validation_spend_error(
    status_payload: dict[str, Any],
    *,
    goal_id: str,
    todo_id: str | None,
    agent_id: str | None,
    selected_todo: dict[str, Any] | None,
    delivery_run: dict[str, Any] | None = None,
) -> str | None:
    """Explain why one requested settlement still lacks validation authority."""

    normalized_todo_id = normalize_todo_id(todo_id)
    if not normalized_todo_id:
        return None
    if _is_qualified_semantic_replan_writeback(
        delivery_run,
        todo_id=normalized_todo_id,
    ):
        return None
    summaries: list[dict[str, Any]] = []
    if (
        selected_todo
        and normalize_todo_id(selected_todo.get("todo_id")) == normalized_todo_id
    ):
        summaries.append({"items": [selected_todo]})
    queue = status_payload.get("attention_queue")
    queue_items = queue.get("items") if isinstance(queue, dict) else []
    queue_item = next(
        (
            item
            for item in queue_items if isinstance(queue_items, list)
            if isinstance(item, dict) and item.get("goal_id") == goal_id
        ),
        {},
    )
    project_asset = (
        queue_item.get("project_asset")
        if isinstance(queue_item.get("project_asset"), dict)
        else {}
    )
    for owner in (queue_item, project_asset):
        summary = owner.get("agent_todos")
        if isinstance(summary, dict):
            summaries.append(summary)
    if any(
        pending_completion_validation_todo(
            summary,
            todo_id=normalized_todo_id,
            agent_id=agent_id,
        )
        is not None
        for summary in summaries
    ):
        return (
            "quota spend is blocked until controller-declared completion "
            f"validation durably completes todo {normalized_todo_id}"
        )
    return None
