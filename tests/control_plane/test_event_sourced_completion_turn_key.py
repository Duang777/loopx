from __future__ import annotations

import pytest

from loopx.control_plane.todos.completion_fence import completed_todo_replay
from loopx.event_sourced_state import (
    TODO_ADDED,
    TODO_COMPLETED,
    build_state_projection,
    make_state_event,
    render_todo_markdown,
)

GOAL_ID = "fixture-event-goal"
TODO_ID = "todo_fixture_event_0001"
TURN_A = "turn-a"
TURN_B = "turn-b"


def _added_event() -> dict:
    return make_state_event(
        event_id="added-1",
        goal_id=GOAL_ID,
        event_type=TODO_ADDED,
        refs={"todo_id": TODO_ID},
        payload={
            "role": "agent",
            "text": "fixture event todo",
            "priority": "P2",
            "claimed_by": "codex-side-bypass",
        },
        recorded_at="2026-08-15T00:00:00Z",
        producer="loopx.todo.add",
    )


def _completed_event(*, turn_key: str) -> dict:
    return make_state_event(
        event_id="completed-1",
        goal_id=GOAL_ID,
        event_type=TODO_COMPLETED,
        refs={"todo_id": TODO_ID},
        payload={
            "completed_at": "2026-08-15T00:01:00Z",
            "updated_at": "2026-08-15T00:01:00Z",
            "evidence": "fixture done",
            "no_followup": "true",
            "completion_turn_key": turn_key,
        },
        recorded_at="2026-08-15T00:01:00Z",
        producer="loopx.todo.complete",
        actor_agent_id="codex-side-bypass",
    )


def _projected_todo() -> dict:
    projection = build_state_projection(
        [_added_event(), _completed_event(turn_key=TURN_A)],
        goal_id=GOAL_ID,
    )
    items = projection["agent_todos"]["items"]
    assert len(items) == 1
    return items[0]


def _replay(todo: dict, *, turn_key: str) -> dict:
    result = completed_todo_replay(
        todo=todo,
        goal_id=GOAL_ID,
        todo_id=TODO_ID,
        completion_turn_key=turn_key,
        handoff_mode="goal",
        mutation_authority={"agent_id": "codex-side-bypass"},
        state_file="ACTIVE_GOAL_STATE.md",
        project=None,
        dry_run=False,
    )
    assert result is not None
    return result


def test_event_projection_preserves_completion_turn_key() -> None:
    todo = _projected_todo()
    assert todo["status"] == "done"
    assert todo["completion_turn_key"] == TURN_A


def test_same_turn_replay_is_idempotent_after_event_projection() -> None:
    todo = _projected_todo()
    receipt = _replay(todo, turn_key=TURN_A)
    assert receipt["idempotent_replay"] is True
    assert receipt["changed"] is False
    assert receipt["completed"] is True


def test_different_turn_replay_fails_closed_after_event_projection() -> None:
    todo = _projected_todo()
    with pytest.raises(ValueError, match="different completion_turn_key"):
        _replay(todo, turn_key=TURN_B)


def test_event_projection_markdown_renders_completion_turn_key() -> None:
    todo = _projected_todo()
    rendered = "\n".join(render_todo_markdown(todo))
    assert f"completion_turn_key={TURN_A}" in rendered
