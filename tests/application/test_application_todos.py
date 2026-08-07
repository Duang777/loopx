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
    StateUnavailable,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.todos import (
    GoalTodoService,
    TodoCompletion,
    TodoItem,
    TodoUpdatePatch,
)

from .fixtures.closed_loop import (
    FIXED_UTC_TIME,
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    materialize_closed_loop_fixture,
)


def _service(fixture, *, profile: Profile = Profile.CLI) -> GoalTodoService:
    return GoalTodoService(
        context=ApplicationContext(
            registry_path=fixture.registry_path,
            runtime_root_override=str(fixture.runtime_root),
            scan_roots=(fixture.project,),
            profile=profile,
            clock=lambda: FIXED_UTC_TIME,
        ),
        goal_id=PRIMARY_GOAL_ID,
    )


def test_todo_list_and_claim_are_typed_fresh_and_path_free(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]

    listed = service.list(todo_id=todo_id)

    assert listed.goal_id == PRIMARY_GOAL_ID
    assert listed.generated_at == FIXED_UTC_TIME
    assert listed.revision.startswith("sha256:")
    assert service.list(todo_id=todo_id).revision == listed.revision
    assert len(listed.items) == 1
    assert isinstance(listed.items[0], TodoItem)
    assert listed.items[0].claimed_by == PRIMARY_AGENT_ID
    serialized = json.dumps(asdict(listed), ensure_ascii=False, sort_keys=True)
    for path in (
        fixture.root,
        fixture.project,
        fixture.registry_path,
        fixture.runtime_root,
    ):
        assert str(path) not in serialized

    cleared = service.update(
        todo_id,
        TodoUpdatePatch(clear_claim=True),
        write_context=WriteContext(
            actor=PRIMARY_AGENT_ID,
            idempotency_key="todo-clear-claim-001",
            expected_revision=listed.revision,
        ),
    )
    assert cleared.item is not None
    assert cleared.item.claimed_by is None

    claimed = service.claim(
        todo_id,
        write_context=WriteContext(
            actor=PRIMARY_AGENT_ID,
            idempotency_key="todo-claim-001",
            expected_revision=cleared.revision,
        ),
    )
    assert claimed.changed is True
    assert claimed.item is not None
    assert claimed.item.claimed_by == PRIMARY_AGENT_ID
    assert claimed.correctness.status == "pending_migration"
    assert claimed.correctness.atomic_revision_check is False
    assert claimed.correctness.idempotent_retry is False


def test_complete_preview_apply_creates_successor_and_rejects_stale_retry(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]
    completion = TodoCompletion(
        evidence="typed-application-closed-loop",
        claimed_by=PRIMARY_AGENT_ID,
        next_agent_todo="Verify the typed successor through Application history.",
        next_claimed_by=PRIMARY_AGENT_ID,
        next_task_class="advancement_task",
    )

    plan = service.preview_complete(
        todo_id,
        completion,
        actor=PRIMARY_AGENT_ID,
    )

    assert plan.changed is True
    assert plan.can_apply is True
    assert plan.plan_hash.startswith("sha256:")
    assert len(plan.successor_todo_ids) == 1
    assert plan.correctness.idempotent_retry is False

    result = service.apply_complete(
        plan,
        write_context=WriteContext(
            actor=PRIMARY_AGENT_ID,
            idempotency_key="todo-complete-001",
            expected_revision=plan.revision,
        ),
    )

    assert result.changed is True
    assert result.item is not None
    assert result.item.status == "done"
    assert result.successor_todo_ids == plan.successor_todo_ids
    successor = service.list(todo_id=result.successor_todo_ids[0])
    assert successor.items[0].status == "open"
    assert successor.items[0].claimed_by == PRIMARY_AGENT_ID

    with pytest.raises(RevisionConflict):
        service.apply_complete(
            plan,
            write_context=WriteContext(
                actor=PRIMARY_AGENT_ID,
                idempotency_key="todo-complete-001",
                expected_revision=plan.revision,
            ),
        )

    with pytest.raises(ValidationFailed) as terminal:
        service.preview_complete(
            todo_id,
            TodoCompletion(
                evidence="a fresh plan must still reject terminal state",
                claimed_by=PRIMARY_AGENT_ID,
                next_agent_todo="Do not create a second successor.",
                next_claimed_by=PRIMARY_AGENT_ID,
            ),
            actor=PRIMARY_AGENT_ID,
        )
    assert terminal.value.details == {"operation_id": "goal.todos.complete.preview"}
    assert len(service.list().items) == 4


def test_todo_mutations_enforce_revision_and_profile(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    todo_id = fixture.todo_ids["primary_next"]
    service = _service(fixture)

    with pytest.raises(RevisionConflict):
        service.claim(
            todo_id,
            write_context=WriteContext(
                actor=PRIMARY_AGENT_ID,
                idempotency_key="todo-stale-001",
                expected_revision=f"sha256:{'0' * 64}",
            ),
        )

    read_only = _service(fixture, profile=Profile.HTTP_READ_ONLY)
    with pytest.raises(AuthorityDenied):
        read_only.claim(
            todo_id,
            write_context=WriteContext(
                actor=PRIMARY_AGENT_ID,
                idempotency_key="todo-read-only-001",
                expected_revision=None,
            ),
        )
    with pytest.raises(AuthorityDenied):
        read_only.preview_complete(
            todo_id,
            TodoCompletion(no_followup=True),
            actor=PRIMARY_AGENT_ID,
        )


def test_todo_core_actor_conflict_maps_to_stable_authority_error(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]
    revision = service.list(todo_id=todo_id).revision

    with pytest.raises(AuthorityDenied) as denied:
        service.update(
            todo_id,
            TodoUpdatePatch(note="A peer cannot mutate another owner's todo."),
            write_context=WriteContext(
                actor="codex-side-bypass",
                idempotency_key="todo-authority-denied-001",
                expected_revision=revision,
            ),
        )

    assert denied.value.details == {
        "operation_id": "goal.todos.update",
        "reason": "core_authority_denied",
    }


@pytest.mark.parametrize(
    ("filters", "field"),
    [
        ({"role": "owner"}, "role"),
        ({"status": "not-a-status"}, "status"),
        ({"todo_id": "../todo_escape"}, "todo_id"),
        ({"agent_id": "../agent"}, "agent_id"),
    ],
)
def test_todo_list_filters_fail_before_route_resolution(
    tmp_path: Path,
    filters: dict[str, str],
    field: str,
) -> None:
    service = GoalTodoService(
        context=ApplicationContext(registry_path=tmp_path / "missing-registry.json"),
        goal_id=PRIMARY_GOAL_ID,
    )

    with pytest.raises(ValidationFailed) as error:
        service.list(**filters)

    assert error.value.details == {"field": field}


def test_todo_text_projection_omits_local_paths_and_secrets(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    todo_id = fixture.todo_ids["primary_next"]
    before = service.list(todo_id=todo_id)
    path_updated = service.update(
        todo_id,
        TodoUpdatePatch(text="Inspect /etc/shadow first."),
        write_context=WriteContext(
            actor=PRIMARY_AGENT_ID,
            idempotency_key="todo-public-path-safety-001",
            expected_revision=before.revision,
        ),
    )

    assert path_updated.item is not None
    assert path_updated.item.text is None

    secret_updated = service.update(
        todo_id,
        TodoUpdatePatch(text="Use " + "to" + "ken=abcdefghijklmnop before continuing."),
        write_context=WriteContext(
            actor=PRIMARY_AGENT_ID,
            idempotency_key="todo-public-sensitive-safety-001",
            expected_revision=path_updated.revision,
        ),
    )

    assert secret_updated.item is not None
    assert secret_updated.item.text is None
    serialized = json.dumps(
        [asdict(path_updated), asdict(secret_updated)],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "/etc/shadow" not in serialized
    assert str(fixture.project) not in serialized
    assert "abcdefghijklmnop" not in serialized


def test_missing_active_state_is_retryable_state_unavailable(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    fixture.state_files[PRIMARY_GOAL_ID].unlink()

    with pytest.raises(StateUnavailable) as error:
        _service(fixture).list()

    assert error.value.code == "state_unavailable"
    assert error.value.retryable is True
    assert error.value.details == {
        "resource": "goal_todos",
        "goal_id": PRIMARY_GOAL_ID,
    }
