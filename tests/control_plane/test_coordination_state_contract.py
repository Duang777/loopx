from __future__ import annotations

import pytest

from loopx.control_plane.coordination.coordination_state_contract import (
    CoordinationStateContractError,
    TODO_CANONICAL_READ_RECORD_FIELDS,
    TODO_CANONICAL_REQUIRED_READ_FIELDS,
    canonical_record_fields,
)


def test_required_fields_are_declared_by_the_record_contract() -> None:
    assert set(TODO_CANONICAL_REQUIRED_READ_FIELDS) <= set(
        TODO_CANONICAL_READ_RECORD_FIELDS
    )


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
