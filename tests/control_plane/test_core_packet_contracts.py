from __future__ import annotations

from typing import Any, TypedDict, get_type_hints

from loopx.control_plane.quota.decision_summary import QuotaDecisionPacket
from loopx.control_plane.todos.summary_item import TodoSummaryItemDict
from loopx.control_plane.work_items.interaction_contract import (
    InteractionContractPacket,
)


def _shape_ok(packet: dict[str, Any], contract: type[TypedDict]) -> bool:
    annotations = set(get_type_hints(contract))
    required = set(getattr(contract, "__required_keys__", frozenset()))
    return required <= set(packet) and set(packet) <= annotations


def test_todo_summary_item_contract_accepts_representative_packet() -> None:
    packet: dict[str, Any] = {
        "index": 1,
        "text": "Review PR #1",
        "todo_id": "todo_abc",
        "status": "open",
        "priority": "P1",
        "task_class": "advancement_task",
        "action_kind": "review_pull_request_exact_head",
        "claimed_by": "codex-side-bypass",
        "required_capabilities": ["network"],
        "target_key": "github-pr-review:owner/repo#1@abc",
    }

    assert _shape_ok(packet, TodoSummaryItemDict)


def test_quota_decision_packet_accepts_representative_packet() -> None:
    packet: dict[str, Any] = {
        "goal_id": "loopx-meta",
        "decision": "run",
        "should_run": True,
        "effective_action": "normal_run",
        "normal_delivery_allowed": True,
        "recovery_delivery_allowed": False,
        "self_repair_allowed": False,
        "capability_repair_allowed": False,
        "workspace_repair_allowed": False,
        "capability_gate": {"action": "run"},
        "interaction_contract": {"mode": "bounded_delivery"},
        "scheduler_hint": {"recommended_interval_minutes": 3},
        "reason": "runnable work",
    }

    assert _shape_ok(packet, QuotaDecisionPacket)


def test_interaction_contract_packet_accepts_representative_packet() -> None:
    packet: dict[str, Any] = {
        "schema_version": "loopx_interaction_contract_v0",
        "mode": "bounded_delivery",
        "user_channel": {"action_required": False},
        "agent_channel": {"must_attempt": True},
        "cli_channel": {"spend_allowed_now": False},
        "fallback_policy": {"do_not_cancel_on_block": True},
    }

    assert _shape_ok(packet, InteractionContractPacket)


def test_packet_contracts_reject_unknown_keys() -> None:
    assert not _shape_ok({"unknown": True}, TodoSummaryItemDict)
    assert not _shape_ok({"unknown": True}, QuotaDecisionPacket)
    assert not _shape_ok({"unknown": True}, InteractionContractPacket)
