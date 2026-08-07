from __future__ import annotations

import json
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from loopx.application import (
    ApplicationContext,
    CapabilityKind,
    GoalNotFound,
    GoalRouteConflict,
    LoopXApplication,
    Profile,
    StateUnavailable,
    ValidationFailed,
    WriteContext,
)


FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("values", "field"),
    [
        (
            {
                "actor": "/private/tmp/local-actor",
                "idempotency_key": "safe-key",
                "expected_revision": None,
            },
            "actor",
        ),
        (
            {
                "actor": "safe-actor",
                "idempotency_key": "to" + "ken=abcdefghijklmnop",
                "expected_revision": None,
            },
            "idempotency_key",
        ),
        (
            {
                "actor": "safe-actor",
                "idempotency_key": "safe-key",
                "expected_revision": "pass" + "word=hunter-two",
            },
            "expected_revision",
        ),
        (
            {
                "actor": None,
                "idempotency_key": "safe-key",
                "expected_revision": None,
            },
            "actor",
        ),
    ],
)
def test_write_context_rejects_private_or_invalid_identity_material(
    values: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValidationFailed) as raised:
        WriteContext(**values)  # type: ignore[arg-type]

    assert raised.value.details == {"field": field}


def _goal(
    goal_id: str,
    *,
    status: str = "active",
    domain: str = "application-foundation-fixture",
    source_registry: Path | None = None,
) -> dict[str, object]:
    goal: dict[str, object] = {
        "id": goal_id,
        "status": status,
        "domain": domain,
        "adapter": {"kind": "generic_project_goal_v0"},
    }
    if source_registry is not None:
        goal["source_registry"] = str(source_registry)
    return goal


def _write_registry(
    project: Path,
    goals: list[dict[str, object]],
    *,
    registry_role: str | None = None,
) -> Path:
    registry_path = project / ".loopx" / "registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "common_runtime_root": str(project / "runtime"),
        "goals": goals,
    }
    if registry_role is not None:
        payload["registry_role"] = registry_role
    registry_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return registry_path


def test_application_context_and_facade_list_multiple_goals(tmp_path: Path) -> None:
    registry_path = _write_registry(
        tmp_path / "project",
        [
            _goal("goal-alpha", domain="alpha"),
            _goal("goal-beta", status="paused", domain="beta"),
        ],
    )
    context = ApplicationContext(registry_path=registry_path, clock=lambda: FIXED_NOW)
    application = LoopXApplication(context)

    summaries = application.list_goals()

    assert application.context is context
    assert isinstance(summaries, tuple)
    assert [summary.goal_id for summary in summaries] == ["goal-alpha", "goal-beta"]
    assert [(summary.status, summary.domain) for summary in summaries] == [
        ("active", "alpha"),
        ("paused", "beta"),
    ]
    assert {summary.generated_at for summary in summaries} == {"2026-01-02T03:04:05Z"}
    assert all(summary.revision.startswith("sha256:") for summary in summaries)
    assert summaries[0].revision != summaries[1].revision


def test_get_goal_missing_raises_stable_typed_error(tmp_path: Path) -> None:
    registry_path = _write_registry(
        tmp_path / "project",
        [_goal("goal-present")],
    )
    application = LoopXApplication(ApplicationContext(registry_path=registry_path))

    with pytest.raises(GoalNotFound) as raised:
        application.get_goal("goal-missing")

    error = raised.value
    assert error.code == "goal_not_found"
    assert dict(error.details) == {"goal_id": "goal-missing"}
    assert error.retryable is False
    assert error.to_dict() == {
        "code": "goal_not_found",
        "message": "The requested goal was not found.",
        "details": {"goal_id": "goal-missing"},
        "retryable": False,
    }


def test_get_goal_rejects_incomplete_canonical_route(tmp_path: Path) -> None:
    registry_path = _write_registry(tmp_path / "project", [_goal("goal-alpha")])

    def incomplete_route(**_kwargs: object) -> dict[str, object]:
        return {"source_registry": str(registry_path)}

    application = LoopXApplication(
        ApplicationContext(
            registry_path=registry_path,
            resolve_goal_route=incomplete_route,
        )
    )

    with pytest.raises(GoalRouteConflict) as raised:
        application.get_goal("goal-alpha")

    assert raised.value.code == "goal_route_conflict"
    assert dict(raised.value.details) == {
        "goal_id": "goal-alpha",
        "cause": "incomplete_route",
    }
    assert raised.value.retryable is False


@pytest.mark.parametrize("source_state", ["missing", "goal_absent"])
def test_get_goal_rejects_absent_canonical_source_route(
    tmp_path: Path,
    source_state: str,
) -> None:
    source_registry = tmp_path / "source" / ".loopx" / "registry.json"
    if source_state == "goal_absent":
        _write_registry(tmp_path / "source", [_goal("different-goal")])
    registry_path = _write_registry(
        tmp_path / "global",
        [_goal("goal-alpha", source_registry=source_registry)],
        registry_role="global-local",
    )
    application = LoopXApplication(ApplicationContext(registry_path=registry_path))

    with pytest.raises(GoalRouteConflict) as raised:
        application.get_goal("goal-alpha")

    assert raised.value.code == "goal_route_conflict"
    assert raised.value.details["goal_id"] == "goal-alpha"
    assert raised.value.retryable is False


def test_get_goal_runtime_override_does_not_bypass_declared_source(
    tmp_path: Path,
) -> None:
    missing_source = tmp_path / "source" / ".loopx" / "registry.json"
    registry_path = _write_registry(
        tmp_path / "global",
        [_goal("goal-alpha", source_registry=missing_source)],
        registry_role="global-local",
    )
    application = LoopXApplication(
        ApplicationContext(
            registry_path=registry_path,
            runtime_root_override=str(tmp_path / "runtime-override"),
        )
    )

    with pytest.raises(GoalRouteConflict) as raised:
        application.get_goal("goal-alpha")

    assert raised.value.code == "goal_route_conflict"
    assert raised.value.details["goal_id"] == "goal-alpha"


def test_get_goal_maps_unreadable_canonical_source_to_state_unavailable(
    tmp_path: Path,
) -> None:
    source_registry = tmp_path / "source" / ".loopx" / "registry.json"
    source_registry.parent.mkdir(parents=True)
    source_registry.write_text("{not-json\n", encoding="utf-8")
    registry_path = _write_registry(
        tmp_path / "global",
        [_goal("goal-alpha", source_registry=source_registry)],
        registry_role="global-local",
    )
    application = LoopXApplication(ApplicationContext(registry_path=registry_path))

    with pytest.raises(StateUnavailable) as raised:
        application.get_goal("goal-alpha")

    assert raised.value.code == "state_unavailable"
    assert raised.value.details["goal_id"] == "goal-alpha"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("profile", "writes_available", "execution_available"),
    [
        (Profile.CLI, True, True),
        (Profile.HTTP_READ_ONLY, False, False),
        (Profile.HTTP_LOCAL_OPERATOR, True, False),
    ],
)
def test_capability_availability_respects_application_profile(
    tmp_path: Path,
    profile: Profile,
    writes_available: bool,
    execution_available: bool,
) -> None:
    executor = SimpleNamespace(execute=lambda _request: None)
    envelope_source = SimpleNamespace(load_turn_envelope=lambda **_kwargs: {})
    coordinator = SimpleNamespace(
        validate_task=lambda *_args: {},
        writeback=lambda *_args: {},
        spend=lambda *_args: {},
        schedule=lambda *_args: {},
    )
    context = ApplicationContext(
        registry_path=tmp_path / "registry.json",
        profile=profile,
        turn_envelope_source=envelope_source,
        turn_executor=executor,
        turn_commit_coordinator=coordinator,
    )
    descriptions = {
        item.capability_id: item
        for item in LoopXApplication(context).describe_capabilities()
    }

    assert context.writes_available is writes_available
    assert context.execution_available is execution_available
    assert set(descriptions) == {
        "application.describe_capabilities",
        "application.get_goal",
        "application.list_goals",
        "goal.configuration.apply",
        "goal.configuration.preview",
        "goal.history.list",
        "goal.lease.acquire",
        "goal.lease.inspect",
        "goal.lease.release",
        "goal.lease.renew",
        "goal.overview",
        "goal.quota.should_run",
        "goal.quota.spend.apply",
        "goal.quota.spend.preview",
        "goal.quota.void.apply",
        "goal.quota.void.preview",
        "goal.status",
        "goal.todos.claim",
        "goal.todos.complete.apply",
        "goal.todos.complete.preview",
        "goal.todos.list",
        "goal.todos.update",
        "goal.turn.plan",
        "goal.turn.run_once",
    }
    for capability_id in (
        "application.list_goals",
        "application.get_goal",
        "application.describe_capabilities",
        "goal.status",
        "goal.overview",
        "goal.todos.list",
        "goal.lease.inspect",
        "goal.quota.should_run",
        "goal.history.list",
        "goal.turn.plan",
    ):
        assert descriptions[capability_id].available is True
        assert descriptions[capability_id].kind is CapabilityKind.READ
    for capability_id in (
        "goal.configuration.preview",
        "goal.configuration.apply",
        "goal.todos.claim",
        "goal.todos.update",
        "goal.todos.complete.preview",
        "goal.todos.complete.apply",
        "goal.lease.acquire",
        "goal.lease.renew",
        "goal.lease.release",
        "goal.quota.spend.preview",
        "goal.quota.spend.apply",
        "goal.quota.void.preview",
        "goal.quota.void.apply",
    ):
        description = descriptions[capability_id]
        assert description.kind is CapabilityKind.WRITE
        assert description.available is writes_available
        if writes_available:
            assert description.unavailable_reason is None
        else:
            assert description.unavailable_reason is not None
            assert description.unavailable_reason.code == "profile_read_only"
            assert dict(description.unavailable_reason.details) == {
                "profile": "http_read_only"
            }
    turn_run = descriptions["goal.turn.run_once"]
    assert turn_run.kind is CapabilityKind.EXECUTE
    assert turn_run.available is execution_available
    assert turn_run.supports_preview is True
    assert turn_run.requires_preview is True
    if execution_available:
        assert turn_run.unavailable_reason is None
    else:
        assert turn_run.unavailable_reason is not None
        assert turn_run.unavailable_reason.code == "profile_execution_denied"
        assert dict(turn_run.unavailable_reason.details) == {"profile": profile.value}


def test_turn_plan_capability_requires_an_explicit_envelope_source(
    tmp_path: Path,
) -> None:
    context = ApplicationContext(registry_path=tmp_path / "registry.json")

    descriptions = {
        item.capability_id: item
        for item in LoopXApplication(context).describe_capabilities()
    }

    turn_plan = descriptions["goal.turn.plan"]
    turn_run = descriptions["goal.turn.run_once"]
    assert turn_plan.available is False
    assert turn_plan.unavailable_reason is not None
    assert turn_plan.unavailable_reason.code == "turn_envelope_source_unavailable"
    assert turn_run.available is False
    assert turn_run.kind is CapabilityKind.EXECUTE
    assert turn_run.unavailable_reason is not None
    assert turn_run.unavailable_reason.code == "turn_envelope_source_unavailable"
    assert context.executor_available is False
    assert context.execution_available is False


def test_turn_execution_capability_reports_missing_provider(
    tmp_path: Path,
) -> None:
    envelope_source = SimpleNamespace(load_turn_envelope=lambda **_kwargs: {})
    executor = SimpleNamespace(execute=lambda _request: None)

    missing_executor = ApplicationContext(
        registry_path=tmp_path / "missing-executor.json",
        turn_envelope_source=envelope_source,
    )
    missing_coordinator = ApplicationContext(
        registry_path=tmp_path / "missing-coordinator.json",
        turn_envelope_source=envelope_source,
        turn_executor=executor,
    )

    executor_capability = {
        item.capability_id: item
        for item in LoopXApplication(missing_executor).describe_capabilities()
    }["goal.turn.run_once"]
    coordinator_capability = {
        item.capability_id: item
        for item in LoopXApplication(missing_coordinator).describe_capabilities()
    }["goal.turn.run_once"]
    assert executor_capability.unavailable_reason is not None
    assert executor_capability.unavailable_reason.code == "executor_unavailable"
    assert dict(executor_capability.unavailable_reason.details) == {
        "provider": "turn_executor"
    }
    assert coordinator_capability.unavailable_reason is not None
    assert (
        coordinator_capability.unavailable_reason.code
        == "commit_coordinator_unavailable"
    )
    assert dict(coordinator_capability.unavailable_reason.details) == {
        "provider": "turn_commit_coordinator"
    }


@pytest.mark.parametrize(
    ("field", "provider"),
    [
        ("turn_envelope_source", SimpleNamespace()),
        ("turn_executor", SimpleNamespace()),
        (
            "turn_commit_coordinator",
            SimpleNamespace(
                validate_task=lambda *_args: {},
                writeback=lambda *_args: {},
                spend=lambda *_args: {},
            ),
        ),
    ],
)
def test_application_context_rejects_incomplete_turn_providers(
    tmp_path: Path,
    field: str,
    provider: object,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        ApplicationContext(
            registry_path=tmp_path / "registry.json",
            **{field: provider},
        )

    assert error.value.details["field"] == field


def test_goal_handle_keeps_identity_without_mutable_registry_payload(
    tmp_path: Path,
) -> None:
    registry_path = _write_registry(tmp_path / "project", [_goal("goal-alpha")])
    context = ApplicationContext(registry_path=registry_path)

    handle = LoopXApplication(context).get_goal("goal-alpha")

    assert [field.name for field in fields(handle)] == ["context", "goal_id"]
    assert handle.context is context
    assert handle.goal_id == "goal-alpha"
    assert type(handle.configuration).__name__ == "GoalConfigurationService"
    assert type(handle.todos).__name__ == "GoalTodoService"
    assert type(handle.leases).__name__ == "GoalLeaseService"
    assert type(handle.quota).__name__ == "GoalQuotaService"
    assert type(handle.turns).__name__ == "GoalTurnService"
    assert type(handle.history).__name__ == "GoalHistoryService"
    assert not hasattr(handle, "__dict__")
    assert not any(
        isinstance(getattr(handle, field.name), (dict, list, set))
        for field in fields(handle)
    )
