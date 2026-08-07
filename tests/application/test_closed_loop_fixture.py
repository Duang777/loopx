from __future__ import annotations

import json
from pathlib import Path

from loopx.control_plane.work_items.task_lease import inspect_task_lease
from loopx.history import load_registry
from loopx.registry import registry_goals

from .fixtures import (
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    SECONDARY_AGENT_ID,
    SECONDARY_GOAL_ID,
    materialize_closed_loop_fixture,
)


def _todos_by_id(payload: dict) -> dict[str, dict]:
    return {item["todo_id"]: item for item in payload["todos"] if item.get("todo_id")}


def test_materialized_fixture_characterizes_shipped_closed_loop_surfaces(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)

    registry = load_registry(fixture.registry_path)
    goals = {goal["id"]: goal for goal in registry_goals(registry)}
    assert set(goals) == {PRIMARY_GOAL_ID, SECONDARY_GOAL_ID}
    assert {goal["adapter"]["kind"] for goal in goals.values()} == {
        "generic_project_goal_v0"
    }
    assert goals[PRIMARY_GOAL_ID]["quota"] == {
        "compute": 0.5,
        "window_hours": 12.0,
    }

    primary_todos = _todos_by_id(fixture.receipts["primary_todos"])
    completed_id = fixture.todo_ids["primary_completed"]
    next_id = fixture.todo_ids["primary_next"]
    assert primary_todos[completed_id]["status"] == "done"
    assert primary_todos[completed_id]["successor_todo_ids"] == [next_id]
    assert primary_todos[next_id]["status"] == "open"
    assert primary_todos[next_id]["claimed_by"] == PRIMARY_AGENT_ID

    secondary_todos = _todos_by_id(fixture.receipts["secondary_todos"])
    assert (
        secondary_todos[fixture.todo_ids["secondary_agent"]]["claimed_by"]
        == SECONDARY_AGENT_ID
    )
    gate = secondary_todos[fixture.todo_ids["secondary_user_gate"]]
    assert gate["status"] == "open"
    assert gate["task_class"] == "user_gate"
    assert gate["blocks_agent"] == SECONDARY_AGENT_ID

    status = fixture.receipts["status"]
    assert status["ok"] is True
    assert status["goal_count"] == 2
    assert {goal["id"] for goal in status["run_history"]["goals"]} == {
        PRIMARY_GOAL_ID,
        SECONDARY_GOAL_ID,
    }
    queue = {item["goal_id"]: item for item in status["attention_queue"]["items"]}
    primary_quota = queue[PRIMARY_GOAL_ID]["quota"]
    assert primary_quota["compute"] == 0.5
    assert primary_quota["window_hours"] == 12
    assert primary_quota["slot_minutes"] == 1
    assert primary_quota["allowed_slots"] == 360
    assert primary_quota["spent_slots"] == 0
    assert primary_quota["state"] == "eligible"
    assert queue[SECONDARY_GOAL_ID]["status"] == "active_state_user_gate"
    assert queue[SECONDARY_GOAL_ID]["quota"]["state"] == "operator_gate"

    preview = fixture.receipts["configure_preview"]
    applied = fixture.receipts["configure_apply"]
    assert preview["dry_run"] is True
    assert preview["written"] is False
    assert applied["dry_run"] is False
    assert applied["written"] is True
    assert preview["before"] == applied["before"]
    assert preview["after"] == applied["after"]
    assert applied["after"]["quota"] == {"compute": 0.5, "window_hours": 12.0}

    lease = inspect_task_lease(
        registry_path=fixture.registry_path,
        runtime_root=fixture.runtime_root,
        goal_id=PRIMARY_GOAL_ID,
        todo_id=next_id,
    )
    assert lease["ok"] is True
    assert lease["active"] is True
    assert lease["lease"]["schema_version"] == "task_lease_v0"
    assert lease["lease"]["owner"] == PRIMARY_AGENT_ID
    assert lease["lease"]["status"] == "active"
    assert lease["lease"]["version"] == 1
    retry = fixture.receipts["lease_retry"]
    assert retry["ok"] is True
    assert retry["acquired"] is False
    assert retry["idempotent"] is True
    assert retry["lease"]["version"] == 1
    conflict = fixture.receipts["lease_conflict"]
    assert conflict["ok"] is False
    assert conflict["error_code"] == "todo_lease_conflict"
    stale_version = fixture.receipts["lease_stale_version"]
    assert stale_version["ok"] is False
    assert stale_version["error_code"] == "version_mismatch"
    assert stale_version["expected_version"] == 0
    assert stale_version["actual_version"] == 1

    quota = fixture.receipts["quota"]
    assert quota["schema_version"] == "loopx_turn_envelope_v0"
    assert quota["should_run"] is True
    assert quota["action"]["selected_todo"]["todo_id"] == next_id

    turn_plan = fixture.receipts["turn_plan"]
    assert turn_plan["schema_version"] == "loopx_turn_plan_v0"
    assert turn_plan["route"]["kind"] == "ready_for_host"
    assert turn_plan["route"]["selected_todo"]["todo_id"] == next_id
    assert turn_plan["effects"] == {
        "host_invoked": False,
        "quota_spent": False,
        "scheduler_acknowledged": False,
        "state_written": False,
    }
    assert turn_plan["boundary"]["read_only"] is True

    history = fixture.receipts["history"]
    assert history["run_count"] == 1
    assert history["runs"][0]["classification"] == "application_fixture_ready"
    assert history["runs"][0]["agent_id"] == PRIMARY_AGENT_ID
    assert history["runs"][0]["json_exists"] is True
    assert history["runs"][0]["markdown_exists"] is True

    for name, receipt_path in fixture.receipt_paths.items():
        assert (
            json.loads(receipt_path.read_text(encoding="utf-8"))
            == fixture.receipts[name]
        )
