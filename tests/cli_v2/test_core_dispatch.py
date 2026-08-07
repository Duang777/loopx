from __future__ import annotations

import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import pytest

from loopx.application import GoalNotFound
from loopx.cli_v2 import main


@dataclass(frozen=True)
class _GoalSummary:
    goal_id: str
    status: str = "active"


@dataclass(frozen=True)
class _Plan:
    revision: str = "revision-one"
    plan_hash: str = "plan-hash-one"
    goal_id: str = "goal-one"
    agent_id: str = "agent-one"
    turn_key: str = "sha256:" + "1" * 64


@dataclass(frozen=True)
class _TodoList:
    revision: str = "todo-revision-one"
    goal_id: str = "goal-one"
    generated_at: str = "2026-08-07T00:00:00Z"
    items: tuple[object, ...] = ()


class _Configuration:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def preview(self, patch: object) -> _Plan:
        self.calls.append(("configuration.preview", patch))
        return _Plan()

    def apply(self, patch: object, *, plan_hash: str, write_context: object) -> dict[str, object]:
        self.calls.append(
            (
                "configuration.apply",
                (patch, plan_hash, write_context),
            )
        )
        return {"written": True, "revision": "revision-two"}


class _Todos:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def list(self, **kwargs: object) -> Any:
        self.calls.append(("todos.list", kwargs))
        return _TodoList()

    def claim(self, todo_id: str, *, write_context: object) -> dict[str, object]:
        self.calls.append(("todos.claim", (todo_id, write_context)))
        return {"todo_id": todo_id, "changed": True}

    def update(
        self,
        todo_id: str,
        patch: object,
        *,
        write_context: object,
    ) -> dict[str, object]:
        self.calls.append(("todos.update", (todo_id, patch, write_context)))
        return {"todo_id": todo_id, "changed": True}

    def preview_complete(
        self,
        todo_id: str,
        completion: object,
        *,
        actor: str,
    ) -> _Plan:
        self.calls.append(("todos.preview_complete", (todo_id, completion, actor)))
        return _Plan(revision="todo-revision-one")

    def apply_complete(self, plan: object, *, write_context: object) -> dict[str, object]:
        self.calls.append(("todos.apply_complete", (plan, write_context)))
        return {"todo_id": "todo-one", "changed": True}


class _Leases:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def inspect(self, todo_id: str) -> dict[str, object]:
        self.calls.append(("leases.inspect", todo_id))
        return {"active": False, "todo_id": todo_id}

    def acquire(self, todo_id: str, **kwargs: object) -> dict[str, object]:
        self.calls.append(("leases.acquire", (todo_id, kwargs)))
        return {"action": "acquire", "changed": True}

    def renew(self, todo_id: str, **kwargs: object) -> dict[str, object]:
        self.calls.append(("leases.renew", (todo_id, kwargs)))
        return {"action": "renew", "changed": True}

    def release(self, todo_id: str, **kwargs: object) -> dict[str, object]:
        self.calls.append(("leases.release", (todo_id, kwargs)))
        return {"action": "release", "changed": True}


class _Quota:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def should_run(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("quota.should_run", kwargs))
        return {"goal_id": "goal-one", "should_run": True}

    def preview_spend(self, **kwargs: object) -> _Plan:
        self.calls.append(("quota.preview_spend", kwargs))
        return _Plan()

    def apply_spend(self, plan: object, *, write_context: object) -> dict[str, object]:
        self.calls.append(("quota.apply_spend", (plan, write_context)))
        return {"operation": "spend", "written": True, "source": "adapter"}

    def preview_void(self, **kwargs: object) -> _Plan:
        self.calls.append(("quota.preview_void", kwargs))
        return _Plan()

    def apply_void(self, plan: object, *, write_context: object) -> dict[str, object]:
        self.calls.append(("quota.apply_void", (plan, write_context)))
        return {"operation": "void", "written": True}


class _Turns:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def plan(self, request: object) -> _Plan:
        self.calls.append(("turns.plan", request))
        return _Plan()

    def run_once(self, plan: object, **kwargs: object) -> dict[str, object]:
        self.calls.append(("turns.run_once", (plan, kwargs)))
        return {"ok": True, "status": "completed", "dry_run": not kwargs["execute"]}


class _History:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def list(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("history.list", kwargs))
        return {"goal_id": "goal-one", "items": [], "total_count": 0}


class _Goal:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.configuration = _Configuration(calls)
        self.todos = _Todos(calls)
        self.leases = _Leases(calls)
        self.quota = _Quota(calls)
        self.turns = _Turns(calls)
        self.history = _History(calls)
        self.calls = calls

    def overview(self) -> dict[str, object]:
        self.calls.append(("goal.overview", None))
        return {"goal_id": "goal-one", "status": "active"}


class _Application:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.goal = _Goal(self.calls)

    def list_goals(self) -> tuple[_GoalSummary, ...]:
        self.calls.append(("application.list_goals", None))
        return (_GoalSummary("goal-one"),)

    def get_goal(self, goal_id: str) -> _Goal:
        self.calls.append(("application.get_goal", goal_id))
        if goal_id != "goal-one":
            raise GoalNotFound(details={"goal_id": goal_id})
        return self.goal


def _run(application: _Application, *argv: str) -> tuple[int, dict[str, object]]:
    output = StringIO()
    code = main(
        ["--format", "json", "--registry", "/fixture/registry.json", *argv],
        application_factory=lambda _args, _path: application,
        stdout=output,
    )
    return code, json.loads(output.getvalue())


def test_status_and_history_dispatch_only_through_application() -> None:
    application = _Application()

    code, status = _run(application, "status", "--goal-id", "goal-one")
    assert code == 0
    assert status["application_operation"] == "goal.overview"
    assert status["result"] == {"goal_id": "goal-one", "status": "active"}

    code, history = _run(
        application,
        "history",
        "--goal-id",
        "goal-one",
        "--limit",
        "7",
    )
    assert code == 0
    assert history["application_operation"] == "goal.history.list"
    assert ("history.list", {"page_size": 7}) in application.calls


def test_configure_apply_builds_typed_patch_and_internal_preview_guard() -> None:
    application = _Application()

    code, payload = _run(
        application,
        "configure-goal",
        "--goal-id",
        "goal-one",
        "--quota-compute",
        "0.5",
        "--execute",
    )

    assert code == 0
    assert payload["application_operation"] == "goal.configuration.apply"
    preview_call = next(value for name, value in application.calls if name == "configuration.preview")
    assert preview_call.quota_compute == 0.5
    apply_call = next(value for name, value in application.calls if name == "configuration.apply")
    _, plan_hash, context = apply_call
    assert plan_hash == "plan-hash-one"
    assert context.expected_revision == "revision-one"


@pytest.mark.parametrize(
    ("argv", "expected_call"),
    (
        (("todo", "list", "--goal-id", "goal-one"), "todos.list"),
        (
            (
                "todo",
                "claim",
                "--goal-id",
                "goal-one",
                "--todo-id",
                "todo-one",
                "--claimed-by",
                "agent-one",
            ),
            "todos.claim",
        ),
        (
            (
                "todo",
                "update",
                "--goal-id",
                "goal-one",
                "--todo-id",
                "todo-one",
                "--agent-id",
                "agent-one",
                "--note",
                "bounded update",
            ),
            "todos.update",
        ),
        (
            (
                "todo",
                "complete",
                "--goal-id",
                "goal-one",
                "--todo-id",
                "todo-one",
                "--agent-id",
                "agent-one",
                "--evidence",
                "fixture evidence",
                "--no-follow-up",
            ),
            "todos.apply_complete",
        ),
    ),
)
def test_todo_variants_use_typed_services(
    argv: tuple[str, ...],
    expected_call: str,
) -> None:
    application = _Application()
    code, payload = _run(application, *argv)

    assert code == 0
    assert payload["ok"] is True
    assert any(name == expected_call for name, _value in application.calls)


def test_lease_and_quota_writes_preserve_cli_cas_and_source() -> None:
    application = _Application()

    code, _ = _run(
        application,
        "task-lease",
        "acquire",
        "--goal-id",
        "goal-one",
        "--todo-id",
        "todo-one",
        "--owner",
        "agent-one",
        "--idempotency-key",
        "lease-one",
        "--expected-version",
        "3",
    )
    assert code == 0
    lease_args = next(value for name, value in application.calls if name == "leases.acquire")
    assert lease_args[1]["write_context"].expected_revision == "task_lease_v0:3"

    code, quota = _run(
        application,
        "quota",
        "spend-slot",
        "--goal-id",
        "goal-one",
        "--agent-id",
        "agent-one",
        "--source",
        "adapter",
        "--execute",
    )
    assert code == 0
    assert quota["result"]["source"] == "adapter"
    preview = next(value for name, value in application.calls if name == "quota.preview_spend")
    assert preview["source"] == "adapter"


def test_turn_execute_passes_explicit_authority_to_run_once() -> None:
    application = _Application()

    code, payload = _run(
        application,
        "turn",
        "run-once",
        "--goal-id",
        "goal-one",
        "--agent-id",
        "agent-one",
        "--turn-instance-id",
        "turn-one",
        "--project",
        "/fixture/project",
        "--execute",
    )

    assert code == 0
    assert payload["application_operation"] == "goal.turn.run_once"
    _plan, kwargs = next(value for name, value in application.calls if name == "turns.run_once")
    assert kwargs["execute"] is True
    assert kwargs["retry_failed"] is False
    assert kwargs["write_context"].actor == "agent-one"
    assert kwargs["write_context"].idempotency_key == "turn-one"
    assert kwargs["write_context"].expected_revision == "revision-one"


def test_turn_plan_and_dry_run_use_the_typed_turn_service() -> None:
    application = _Application()
    common = (
        "--goal-id",
        "goal-one",
        "--agent-id",
        "agent-one",
        "--turn-instance-id",
        "turn-one",
    )

    code, planned = _run(application, "turn", "plan", *common)

    assert code == 0
    assert planned["application_operation"] == "goal.turn.plan"
    request = next(value for name, value in application.calls if name == "turns.plan")
    assert ("application.get_goal", "goal-one") in application.calls
    assert request.agent_id == "agent-one"
    assert request.turn_instance_id == "turn-one"

    code, dry_run = _run(
        application,
        "turn",
        "run-once",
        *common,
        "--project",
        "/fixture/project",
    )

    assert code == 0
    assert dry_run["application_operation"] == "goal.turn.run_once"
    _plan, kwargs = [
        value for name, value in application.calls if name == "turns.run_once"
    ][-1]
    assert kwargs["execute"] is False
    assert kwargs["write_context"].idempotency_key == "turn-one"


def test_pending_variant_never_constructs_application() -> None:
    called = False
    output = StringIO()

    def factory(_args: object, _path: Path) -> _Application:
        nonlocal called
        called = True
        return _Application()

    code = main(
        [
            "--format",
            "json",
            "--registry",
            "/fixture/registry.json",
            "todo",
            "add",
            "--goal-id",
            "goal-one",
            "--role",
            "agent",
            "--text",
            "pending",
        ],
        application_factory=factory,
        stdout=output,
    )

    assert code == 2
    assert called is False
    assert json.loads(output.getvalue())["error"]["code"] == "cli_v2_pending_migration"


def test_application_error_maps_to_stable_exit_and_payload() -> None:
    application = _Application()

    code, payload = _run(application, "status", "--goal-id", "missing")

    assert code == 1
    assert payload["error"]["code"] == "goal_not_found"
    assert payload["error"]["details"] == {"goal_id": "missing"}
