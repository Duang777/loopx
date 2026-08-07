from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from loopx.application import (
    ApplicationContext,
    AuthorityDenied,
    Profile,
    RevisionConflict,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.leases import (
    GoalLeaseService,
    TaskLease,
    TaskLeaseInspection,
    TaskLeaseMutationResult,
)
from loopx.control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)

from .fixtures.closed_loop import (
    FIXED_UTC_TIME,
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    ClosedLoopFixture,
    materialize_closed_loop_fixture,
)


def _service(
    fixture: ClosedLoopFixture,
    *,
    profile: Profile = Profile.CLI,
    runtime_root_override: Path | None = None,
    resolve_goal_route=resolve_goal_source_runtime_route,
) -> GoalLeaseService:
    return GoalLeaseService(
        context=ApplicationContext(
            registry_path=fixture.registry_path,
            runtime_root_override=str(runtime_root_override or fixture.runtime_root),
            profile=profile,
            clock=lambda: FIXED_UTC_TIME,
            resolve_goal_route=resolve_goal_route,
        ),
        goal_id=PRIMARY_GOAL_ID,
    )


def _existing_lease_context(
    fixture: ClosedLoopFixture,
    *,
    revision: str | None,
    idempotency_key: str = "application-fixture-turn-001",
) -> WriteContext:
    del fixture
    return WriteContext(
        actor=PRIMARY_AGENT_ID,
        idempotency_key=idempotency_key,
        expected_revision=revision,
    )


def test_inspect_returns_frozen_path_free_lease_projection(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    todo_id = fixture.todo_ids["primary_next"]

    inspection = _service(fixture).inspect(todo_id)

    assert isinstance(inspection, TaskLeaseInspection)
    assert inspection.goal_id == PRIMARY_GOAL_ID
    assert inspection.todo_id == todo_id
    assert inspection.generated_at == FIXED_UTC_TIME
    assert inspection.active is True
    assert isinstance(inspection.lease, TaskLease)
    assert inspection.lease.owner == PRIMARY_AGENT_ID
    assert inspection.lease.version == 1
    assert inspection.lease.revision == "task_lease_v0:1"
    assert inspection.lease.write_scopes == ("tests/application/**",)
    assert inspection.lease.active is True
    assert not hasattr(inspection, "__dict__")
    assert not hasattr(inspection.lease, "__dict__")

    serialized = json.dumps(asdict(inspection), sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "lease_path" not in serialized
    assert "idempotency_key" not in serialized


def test_acquire_preserves_core_replay_and_conflict_semantics(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]
    revision = service.inspect(todo_id).lease
    assert revision is not None

    replay = service.acquire(
        todo_id,
        write_context=_existing_lease_context(
            fixture,
            revision=revision.revision,
        ),
        ttl_seconds=3600,
        write_scopes=("tests/application/**",),
    )

    assert isinstance(replay, TaskLeaseMutationResult)
    assert replay.action == "acquire"
    assert replay.changed is False
    assert replay.idempotent is True
    assert replay.missing is False
    assert replay.lease == revision
    assert replay.correctness.status == "core_enforced"
    assert replay.correctness.atomic_revision_check is True
    assert replay.correctness.idempotent_retry is True

    with pytest.raises(RevisionConflict) as conflict:
        service.acquire(
            todo_id,
            write_context=_existing_lease_context(
                fixture,
                revision=revision.revision,
                idempotency_key="competing-turn-001",
            ),
            ttl_seconds=3600,
            write_scopes=("tests/application/**",),
        )

    assert conflict.value.details == {
        "operation_id": "goal.lease.acquire",
        "core_code": "todo_lease_conflict",
        "current_owner": PRIMARY_AGENT_ID,
        "current_version": 1,
    }
    assert str(tmp_path) not in json.dumps(dict(conflict.value.details))
    assert service.inspect(todo_id).lease == revision


def test_renew_and_release_use_core_compare_and_swap_versions(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]

    with pytest.raises(RevisionConflict) as stale:
        service.renew(
            todo_id,
            write_context=_existing_lease_context(
                fixture,
                revision="task_lease_v0:0",
            ),
            ttl_seconds=600,
        )

    assert stale.value.details == {
        "operation_id": "goal.lease.renew",
        "core_code": "version_mismatch",
        "expected_version": 0,
        "actual_version": 1,
    }
    assert service.inspect(todo_id).lease.version == 1

    renewed = service.renew(
        todo_id,
        write_context=_existing_lease_context(
            fixture,
            revision="task_lease_v0:1",
        ),
        ttl_seconds=600,
    )
    assert renewed.changed is True
    assert renewed.idempotent is False
    assert renewed.lease is not None
    assert renewed.lease.version == 2
    assert renewed.lease.revision == "task_lease_v0:2"
    assert renewed.correctness.atomic_revision_check is True
    assert renewed.correctness.idempotent_retry is False

    released = service.release(
        todo_id,
        write_context=_existing_lease_context(
            fixture,
            revision=renewed.lease.revision,
        ),
    )
    assert released.action == "release"
    assert released.changed is True
    assert released.lease is not None
    assert released.lease.status == "released"
    assert released.lease.active is False
    assert released.lease.revision == "task_lease_v0:2"
    assert service.inspect(todo_id).lease is None
    assert service.inspect(todo_id).active is False


def test_invalid_revision_and_read_only_profile_fail_before_writes(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    todo_id = fixture.todo_ids["primary_next"]
    writable = _service(fixture)

    with pytest.raises(ValidationFailed) as invalid:
        writable.renew(
            todo_id,
            write_context=_existing_lease_context(
                fixture,
                revision="sha256:not-a-lease-version",
            ),
        )
    assert invalid.value.details == {
        "field": "write_context.expected_revision",
        "expected_format": "task_lease_v0:<version>",
    }
    assert writable.inspect(todo_id).lease.version == 1

    read_only = _service(fixture, profile=Profile.HTTP_READ_ONLY)
    assert read_only.inspect(todo_id).active is True
    with pytest.raises(AuthorityDenied) as denied:
        read_only.release(
            todo_id,
            write_context=_existing_lease_context(
                fixture,
                revision="task_lease_v0:1",
            ),
        )
    assert denied.value.details == {
        "operation_id": "goal.lease.release",
        "profile": "http_read_only",
    }
    assert writable.inspect(todo_id).lease.version == 1


def test_route_ignores_runtime_override_until_downstream_lease_target(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    todo_id = fixture.todo_ids["primary_next"]
    seen_route_overrides: list[str | None] = []

    def recording_resolver(**kwargs):
        seen_route_overrides.append(kwargs.get("runtime_root_override"))
        return resolve_goal_source_runtime_route(**kwargs)

    alternate_runtime = tmp_path / "alternate-runtime"
    inspection = _service(
        fixture,
        runtime_root_override=alternate_runtime,
        resolve_goal_route=recording_resolver,
    ).inspect(todo_id)

    assert seen_route_overrides == [None]
    assert inspection.active is False
    assert inspection.lease is None
    assert _service(fixture).inspect(todo_id).active is True
