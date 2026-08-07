"""Public-safe state tree shared by application-boundary characterizations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from examples.control_plane.todo_lifecycle_fixtures import (
    GOAL_ID as TODO_FIXTURE_GOAL_ID,
    run_cli,
    run_cli_error,
    write_fixture,
)
from loopx.control_plane.testing.canary_harness import write_fixture_registry
from loopx.control_plane.turn_driver import build_loopx_turn_plan
from loopx.status import collect_status


PRIMARY_GOAL_ID = TODO_FIXTURE_GOAL_ID
SECONDARY_GOAL_ID = "application-user-gated-goal"
PRIMARY_AGENT_ID = "codex-main-control"
SECONDARY_AGENT_ID = "codex-side-bypass"

FIXED_LOCAL_TIME = "2026-01-02T03:04:05+00:00"
FIXED_UTC_TIME = "2026-01-02T03:04:05Z"
FIXED_LEASE_DATETIME = datetime(2099, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

PRIMARY_COMPLETED_TODO = "Publish one validated public fixture state."
PRIMARY_NEXT_TODO = "Read back the public fixture through the application boundary."
SECONDARY_AGENT_TODO = "Prepare the bounded handoff after owner approval."
SECONDARY_USER_TODO = "Approve the bounded public fixture handoff."


@dataclass(frozen=True)
class ClosedLoopFixture:
    root: Path
    project: Path
    runtime_root: Path
    registry_path: Path
    state_files: dict[str, Path]
    todo_ids: dict[str, str]
    receipt_paths: dict[str, Path]
    receipts: dict[str, dict[str, Any]]


def _write_secondary_goal(
    *,
    root: Path,
    project: Path,
    runtime_root: Path,
    registry_path: Path,
) -> Path:
    state_file = (
        project / ".codex" / "goals" / SECONDARY_GOAL_ID / "ACTIVE_GOAL_STATE.md"
    )
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        "---\n"
        "status: active\n"
        f"updated_at: {FIXED_LOCAL_TIME}\n"
        "---\n\n"
        "# Active Goal State\n\n"
        "## Objective\n\n"
        "Exercise one public-safe user-gated application lane.\n\n"
        "## User Todo\n\n"
        "## Agent Todo\n",
        encoding="utf-8",
    )

    staging_registry = root / "secondary-registry.json"
    write_fixture_registry(
        project=project,
        runtime_root=runtime_root,
        registry_path=staging_registry,
        goal_id=SECONDARY_GOAL_ID,
        domain="application-user-gated-fixture",
        adapter_kind="generic_project_goal_v0",
        registered_agents=[SECONDARY_AGENT_ID],
        quota_allowed_slots=12,
    )
    secondary_payload = json.loads(staging_registry.read_text(encoding="utf-8"))
    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    registry_payload["goals"].append(secondary_payload["goals"][0])
    registry_path.write_text(
        json.dumps(registry_payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    staging_registry.unlink()
    return state_file


def _write_receipt(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def materialize_closed_loop_fixture(root: Path) -> ClosedLoopFixture:
    """Materialize one deterministic state tree via shipped helpers and CLI paths.

    The fixture stops at a read-only Turn plan. Host execution and the run-once
    commit path intentionally remain outside this T1 characterization.
    """

    registry_path, primary_state_file = write_fixture(root)
    project = registry_path.parent.parent
    registry_payload = json.loads(registry_path.read_text(encoding="utf-8"))
    runtime_root = Path(registry_payload["common_runtime_root"])
    secondary_state_file = _write_secondary_goal(
        root=root,
        project=project,
        runtime_root=runtime_root,
        registry_path=registry_path,
    )

    with (
        patch("loopx.todos.now_local", return_value=FIXED_LOCAL_TIME),
        patch("loopx.state_refresh.now_local", return_value=FIXED_LOCAL_TIME),
        patch("loopx.configure_goal._now_iso", return_value=FIXED_LOCAL_TIME),
        patch("loopx.global_registry.now_local", return_value=FIXED_LOCAL_TIME),
        patch("loopx.rollout_event_log._now_iso", return_value=FIXED_UTC_TIME),
        patch(
            "loopx.control_plane.work_items.task_lease.now_utc",
            return_value=FIXED_LEASE_DATETIME,
        ),
    ):
        primary_added = run_cli(
            registry_path,
            "todo",
            "add",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--role",
            "agent",
            "--text",
            PRIMARY_COMPLETED_TODO,
            "--task-class",
            "advancement_task",
            "--action-kind",
            "fixture_publish",
            "--claimed-by",
            PRIMARY_AGENT_ID,
        )
        primary_completed = run_cli(
            registry_path,
            "todo",
            "complete",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--todo-id",
            str(primary_added["todo_id"]),
            "--claimed-by",
            PRIMARY_AGENT_ID,
            "--agent-id",
            PRIMARY_AGENT_ID,
            "--evidence",
            "public-fixture-characterization",
            "--next-agent-todo",
            PRIMARY_NEXT_TODO,
            "--next-claimed-by",
            PRIMARY_AGENT_ID,
        )
        primary_next = primary_completed["next_todos"][0]

        secondary_added = run_cli(
            registry_path,
            "todo",
            "add",
            "--goal-id",
            SECONDARY_GOAL_ID,
            "--role",
            "agent",
            "--text",
            SECONDARY_AGENT_TODO,
            "--task-class",
            "advancement_task",
            "--claimed-by",
            SECONDARY_AGENT_ID,
        )
        secondary_gate = run_cli(
            registry_path,
            "todo",
            "add",
            "--goal-id",
            SECONDARY_GOAL_ID,
            "--role",
            "user",
            "--text",
            SECONDARY_USER_TODO,
            "--task-class",
            "user_gate",
            "--agent-id",
            SECONDARY_AGENT_ID,
        )

        configure_preview = run_cli(
            registry_path,
            "configure-goal",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--quota-compute",
            "0.5",
            "--quota-window-hours",
            "12",
        )
        configure_apply = run_cli(
            registry_path,
            "configure-goal",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--quota-compute",
            "0.5",
            "--quota-window-hours",
            "12",
            "--execute",
        )

        history_append = run_cli(
            registry_path,
            "refresh-state",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--classification",
            "application_fixture_ready",
            "--recommended-action",
            PRIMARY_NEXT_TODO,
            "--agent-id",
            PRIMARY_AGENT_ID,
            "--progress-scope",
            "agent_lane",
            "--no-global-sync",
            "--suppress-external-sinks",
        )
        lease = run_cli(
            registry_path,
            "task-lease",
            "acquire",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--todo-id",
            str(primary_next["todo_id"]),
            "--owner",
            PRIMARY_AGENT_ID,
            "--idempotency-key",
            "application-fixture-turn-001",
            "--ttl-seconds",
            "3600",
            "--write-scope",
            "tests/application/**",
        )
        lease_retry = run_cli(
            registry_path,
            "task-lease",
            "acquire",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--todo-id",
            str(primary_next["todo_id"]),
            "--owner",
            PRIMARY_AGENT_ID,
            "--idempotency-key",
            "application-fixture-turn-001",
            "--ttl-seconds",
            "3600",
            "--write-scope",
            "tests/application/**",
        )
        lease_conflict = run_cli_error(
            registry_path,
            "task-lease",
            "acquire",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--todo-id",
            str(primary_next["todo_id"]),
            "--owner",
            PRIMARY_AGENT_ID,
            "--idempotency-key",
            "application-fixture-turn-duplicate",
            "--ttl-seconds",
            "3600",
            "--write-scope",
            "tests/application/**",
        )
        lease_stale_version = run_cli_error(
            registry_path,
            "task-lease",
            "renew",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--todo-id",
            str(primary_next["todo_id"]),
            "--owner",
            PRIMARY_AGENT_ID,
            "--idempotency-key",
            "application-fixture-turn-001",
            "--expected-version",
            "0",
        )
        quota = run_cli(
            registry_path,
            "quota",
            "should-run",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--agent-id",
            PRIMARY_AGENT_ID,
            "--codex-app",
            "--turn-envelope",
        )

    turn_plan = build_loopx_turn_plan(
        quota,
        host="codex-cli",
        execution_mode="interactive-visible",
        turn_instance_id="application-fixture-turn-001",
    )
    history = run_cli(
        registry_path,
        "history",
        "--goal-id",
        PRIMARY_GOAL_ID,
        "--limit",
        "5",
    )
    primary_todos = run_cli(
        registry_path,
        "todo",
        "list",
        "--goal-id",
        PRIMARY_GOAL_ID,
    )
    secondary_todos = run_cli(
        registry_path,
        "todo",
        "list",
        "--goal-id",
        SECONDARY_GOAL_ID,
    )
    status = collect_status(
        registry_path=registry_path,
        runtime_root_override=str(runtime_root),
        scan_roots=[project],
        limit=5,
    )

    receipts = {
        "configure_preview": configure_preview,
        "configure_apply": configure_apply,
        "history_append": history_append,
        "history": history,
        "lease": lease,
        "lease_conflict": lease_conflict,
        "lease_retry": lease_retry,
        "lease_stale_version": lease_stale_version,
        "primary_todos": primary_todos,
        "quota": quota,
        "secondary_todos": secondary_todos,
        "status": status,
        "turn_plan": turn_plan,
    }
    receipt_root = root / "receipts"
    receipt_paths = {
        name: _write_receipt(receipt_root / f"{name}.json", receipt)
        for name, receipt in receipts.items()
    }

    return ClosedLoopFixture(
        root=root,
        project=project,
        runtime_root=runtime_root,
        registry_path=registry_path,
        state_files={
            PRIMARY_GOAL_ID: primary_state_file,
            SECONDARY_GOAL_ID: secondary_state_file,
        },
        todo_ids={
            "primary_completed": str(primary_added["todo_id"]),
            "primary_next": str(primary_next["todo_id"]),
            "secondary_agent": str(secondary_added["todo_id"]),
            "secondary_user_gate": str(secondary_gate["todo_id"]),
        },
        receipt_paths=receipt_paths,
        receipts=receipts,
    )
