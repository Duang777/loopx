from __future__ import annotations

import pytest

from loopx.control_plane.coordination.coordination_state_contract import (
    CoordinationStateContractError,
    TODO_CANONICAL_READ_RECORD_FIELDS,
    TODO_CANONICAL_REQUIRED_READ_FIELDS,
    canonical_record_fields,
    TODO_DOMAIN_RECORD_FIELDS,
    TODO_DOMAIN_ITEM_SCHEMA_VERSION,
    TODO_PROJECTION_METADATA_FIELDS,
)


def test_required_fields_are_declared_by_the_record_contract() -> None:
    assert set(TODO_CANONICAL_REQUIRED_READ_FIELDS) <= set(
        TODO_CANONICAL_READ_RECORD_FIELDS
    )


def test_domain_projection_split_keeps_archival_as_a_task_fact() -> None:
    from loopx.control_plane.coordination.local_authority import (
        canonical_todo_summary_fields,
    )
    from loopx.control_plane.todos.todo_summary import (
        todo_item_is_succession_tracked_completion,
    )

    assert "archive_state" in TODO_DOMAIN_RECORD_FIELDS
    assert set(TODO_PROJECTION_METADATA_FIELDS) == {"source_section", "index"}
    assert not set(TODO_PROJECTION_METADATA_FIELDS) & set(TODO_DOMAIN_RECORD_FIELDS)
    todo = {
        "schema_version": TODO_DOMAIN_ITEM_SCHEMA_VERSION,
        "todo_id": "todo_native", "role": "agent", "status": "done",
        "done": True, "text": "Keep durable lifecycle semantics",
        "archive_state": "active", "task_class": "advancement_task",
        "claimed_by": "agent-a",
    }
    assert todo_item_is_succession_tracked_completion(todo)
    assert not todo_item_is_succession_tracked_completion({**todo, "archive_state": "archive"})
    summary = canonical_todo_summary_fields([todo])
    assert summary["agent_todos"]["source_section"] == "Agent Todo"
    assert "source_section" not in todo and "index" not in todo
    archived = {**todo, "todo_id": "todo_archived", "archive_state": "archive"}
    with_archive = canonical_todo_summary_fields([todo, archived])
    assert with_archive["agent_todos"]["done_count"] == summary["agent_todos"]["done_count"]
    assert with_archive["agent_todos"]["archived_advancement_done_count"] == 1


def test_record_validation_rejects_required_fields_outside_declared_fields() -> None:
    with pytest.raises(
        CoordinationStateContractError,
        match="required fields are absent from fields: role",
    ):
        canonical_record_fields(
            {"todo_id": "todo_contract"},
            fields=("todo_id",),
            required_fields=("todo_id", "role"),
            label="test record",
            reject_unknown=True,
        )
