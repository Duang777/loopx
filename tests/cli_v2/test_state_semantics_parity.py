from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from application.fixtures import (
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    materialize_closed_loop_fixture,
)
from freezegun import freeze_time

from loopx.cli import main as legacy_main
from loopx.cli_v2 import main as v2_main
from loopx.control_plane.work_items.task_lease import inspect_task_lease
from loopx.history import load_registry
from loopx.registry import registry_goals
from loopx.todos import list_goal_todos


FIXED_PARITY_TIME = "2026-01-02T03:05:00Z"


def _run_legacy(registry_path: Path, command: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = legacy_main(
            ["--format", "json", "--registry", str(registry_path), *command]
        )
    return code, json.loads(output.getvalue())


def _run_v2(registry_path: Path, command: list[str]) -> tuple[int, dict[str, object]]:
    output = io.StringIO()
    code = v2_main(
        ["--format", "json", "--registry", str(registry_path), *command],
        stdout=output,
    )
    return code, json.loads(output.getvalue())


def test_todo_update_has_isolated_state_semantics_parity(tmp_path: Path) -> None:
    legacy_fixture = materialize_closed_loop_fixture(tmp_path / "legacy")
    v2_fixture = materialize_closed_loop_fixture(tmp_path / "v2")
    todo_id = legacy_fixture.todo_ids["primary_next"]
    assert todo_id == v2_fixture.todo_ids["primary_next"]
    command = [
        "todo",
        "update",
        "--goal-id",
        PRIMARY_GOAL_ID,
        "--todo-id",
        todo_id,
        "--agent-id",
        PRIMARY_AGENT_ID,
        "--note",
        "CLI v2 isolated parity note",
    ]

    with freeze_time(FIXED_PARITY_TIME):
        legacy_code, legacy_output = _run_legacy(legacy_fixture.registry_path, command)
        v2_code, v2_output = _run_v2(v2_fixture.registry_path, command)

    assert legacy_code == v2_code == 0
    assert legacy_output["ok"] is v2_output["ok"] is True
    legacy_todo = list_goal_todos(
        registry_path=legacy_fixture.registry_path,
        runtime_root_arg=str(legacy_fixture.runtime_root),
        goal_id=PRIMARY_GOAL_ID,
        todo_id=todo_id,
    )["todos"][0]
    v2_todo = list_goal_todos(
        registry_path=v2_fixture.registry_path,
        runtime_root_arg=str(v2_fixture.runtime_root),
        goal_id=PRIMARY_GOAL_ID,
        todo_id=todo_id,
    )["todos"][0]
    assert legacy_todo == v2_todo
    assert legacy_output != v2_output  # typed semantics pass; compatibility view remains


def test_configuration_apply_has_isolated_registry_semantics_parity(
    tmp_path: Path,
) -> None:
    legacy_fixture = materialize_closed_loop_fixture(tmp_path / "legacy")
    v2_fixture = materialize_closed_loop_fixture(tmp_path / "v2")
    command = [
        "configure-goal",
        "--goal-id",
        PRIMARY_GOAL_ID,
        "--quota-compute",
        "0.75",
        "--execute",
    ]

    with freeze_time(FIXED_PARITY_TIME):
        legacy_code, legacy_output = _run_legacy(legacy_fixture.registry_path, command)
        v2_code, v2_output = _run_v2(v2_fixture.registry_path, command)

    assert legacy_code == v2_code == 0
    assert legacy_output["ok"] is v2_output["ok"] is True
    assert _goal(legacy_fixture.registry_path)["quota"] == _goal(
        v2_fixture.registry_path
    )["quota"] == {"compute": 0.75, "window_hours": 12.0}
    assert legacy_output != v2_output


def test_task_lease_release_has_isolated_state_semantics_parity(
    tmp_path: Path,
) -> None:
    legacy_fixture = materialize_closed_loop_fixture(tmp_path / "legacy")
    v2_fixture = materialize_closed_loop_fixture(tmp_path / "v2")
    todo_id = legacy_fixture.todo_ids["primary_next"]
    assert todo_id == v2_fixture.todo_ids["primary_next"]
    command = [
        "task-lease",
        "release",
        "--goal-id",
        PRIMARY_GOAL_ID,
        "--todo-id",
        todo_id,
        "--owner",
        PRIMARY_AGENT_ID,
        "--idempotency-key",
        "application-fixture-turn-001",
        "--expected-version",
        "1",
    ]

    with freeze_time(FIXED_PARITY_TIME):
        legacy_code, legacy_output = _run_legacy(legacy_fixture.registry_path, command)
        v2_code, v2_output = _run_v2(v2_fixture.registry_path, command)

    assert legacy_code == v2_code == 0
    assert legacy_output["ok"] is v2_output["ok"] is True
    legacy_lease = inspect_task_lease(
        registry_path=legacy_fixture.registry_path,
        runtime_root=legacy_fixture.runtime_root,
        goal_id=PRIMARY_GOAL_ID,
        todo_id=todo_id,
    )
    v2_lease = inspect_task_lease(
        registry_path=v2_fixture.registry_path,
        runtime_root=v2_fixture.runtime_root,
        goal_id=PRIMARY_GOAL_ID,
        todo_id=todo_id,
    )
    legacy_lease.pop("lease_path", None)
    v2_lease.pop("lease_path", None)
    assert legacy_lease == v2_lease
    assert legacy_output != v2_output


def test_quota_spend_has_isolated_event_semantics_parity(tmp_path: Path) -> None:
    legacy_fixture = materialize_closed_loop_fixture(tmp_path / "legacy")
    v2_fixture = materialize_closed_loop_fixture(tmp_path / "v2")

    def command(project: Path) -> list[str]:
        return [
            "quota",
            "spend-slot",
            "--goal-id",
            PRIMARY_GOAL_ID,
            "--agent-id",
            PRIMARY_AGENT_ID,
            "--source",
            "adapter",
            "--slots",
            "1",
            "--scan-root",
            str(project),
            "--execute",
        ]

    with freeze_time(FIXED_PARITY_TIME):
        legacy_code, legacy_output = _run_legacy(
            legacy_fixture.registry_path,
            command(legacy_fixture.project),
        )
        v2_code, v2_output = _run_v2(
            v2_fixture.registry_path,
            command(v2_fixture.project),
        )

    assert legacy_code == v2_code == 0
    assert legacy_output["ok"] is v2_output["ok"] is True
    legacy_event = _single_quota_spend_event(legacy_fixture.runtime_root)
    v2_event = _single_quota_spend_event(v2_fixture.runtime_root)
    assert legacy_event == v2_event
    assert legacy_event["quota_event"]["source"] == "adapter"
    assert legacy_event["quota_event"]["slots"] == 1
    assert legacy_output != v2_output


def _goal(registry_path: Path) -> dict[str, object]:
    return next(
        goal
        for goal in registry_goals(load_registry(registry_path))
        if goal["id"] == PRIMARY_GOAL_ID
    )


def _single_quota_spend_event(runtime_root: Path) -> dict[str, object]:
    paths = tuple(
        (runtime_root / "goals" / PRIMARY_GOAL_ID / "runs").glob(
            "*quota-slot-spent.json"
        )
    )
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))
