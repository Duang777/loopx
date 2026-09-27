"""Constraint continuity: Goal constraints are recoverable from the canonical registry.

After context loss (e.g. Agent restart, stale cached configuration), the
Agent must recover authoritative constraints from the registry rather than
relying on stale in-memory state. The registry is the canonical owner for
source-session Goals.

Design owner: direction-baseline and governed-amendment RFCs (R4).
Qualification: goal-immutability-coherence-defense-v0.md, Constraint
continuity slice.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from loopx.control_plane.effect_runtime import EffectRuntimeRejected
from loopx.control_plane.goals.source_session_binding import (
    SessionBindingRequest,
    commit_project_session_binding,
)
from loopx.control_plane.goals.source_session_recreation import (
    RecreateGoalRequest,
    recreate_goal_instance,
)
from loopx.control_plane.goals.source_session_registration import (
    FreshSourceSessionRegistration,
    register_fresh_source_session_project,
)
from loopx.control_plane.projects.registry_codec import (
    load_project_registry,
)


def _fresh_registration(
    tmp_path: Path,
    goal_id: str,
    *,
    objective: str | None = None,
    acceptance: list[str] | None = None,
    non_goals: list[str] | None = None,
    next_effect: str | None = None,
    stop_condition: str | None = None,
) -> FreshSourceSessionRegistration:
    root = tmp_path / goal_id
    root.mkdir(parents=True, exist_ok=True)
    runtime_root = root / "runtime"
    return FreshSourceSessionRegistration(
        registry_path=root / ".loopx" / "registry.json",
        runtime_root=runtime_root,
        operation_id=uuid4().hex,
        project_id=f"proj-{goal_id}",
        goal_id=goal_id,
        objective=objective or "Verify constraint continuity after context loss.",
        acceptance=acceptance or ["Constraints are recoverable."],
        non_goals=non_goals or ["No real effects."],
        unknowns=[],
        next_effect=next_effect or "noop",
        stop_condition=stop_condition or "test completes",
        project_record={"project_id": f"proj-{goal_id}", "display_name": goal_id},
        goal_record={
            "id": goal_id,
            "display_name": goal_id,
            "status": "active",
            "project_id": f"proj-{goal_id}",
            "quota": {"compute": 1, "allowed_slots": 1, "spent_slots": 0},
        },
        state_file=root / "GOAL_STATE.md",
    )


def _read_goal_from_registry(
    registry_path: Path,
    goal_id: str,
) -> dict:
    """Read the goal record for *goal_id* from the project registry."""
    registry = load_project_registry(registry_path)
    for candidate in registry.get("goals", []):
        if candidate.get("id") == goal_id:
            return candidate
    raise ValueError(f"Goal {goal_id!r} not found in registry")


def _registration_and_paths(
    tmp_path: Path,
    goal_id: str,
    **kwargs,
) -> tuple[dict, Path, str, str]:
    """Register a fresh source-session Goal and return (result, registry_path, goal_id, goal_instance_id)."""
    registration = _fresh_registration(tmp_path, goal_id, **kwargs)
    result = register_fresh_source_session_project(registration)
    assert result["ok"] is True
    goal_ref = result["goal_ref"]
    return (
        result,
        Path(result["registry"]),
        goal_ref["goal_id"],
        goal_ref["goal_instance_id"],
    )


# ---------------------------------------------------------------------------
# Registry constraint readback
# ---------------------------------------------------------------------------


def test_registry_stores_goal_record_fields(tmp_path: Path):
    """Registration writes goal_record fields to the project registry.

    The registry is the canonical constraint owner. After registration,
    goal_record fields (id, display_name, status, project_id, quota) are
    readable from the registry JSON."""
    goal_id = "registry-readback"
    result, registry_path, gid, instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    goal = _read_goal_from_registry(registry_path, gid)
    assert goal["id"] == gid
    assert goal["display_name"] == goal_id
    assert goal["status"] == "active"
    assert goal["project_id"] == f"proj-{goal_id}"
    assert goal["goal_instance_id"] == instance
    assert goal["execution_authority"] is False
    assert isinstance(goal["quota"], dict)
    assert goal["quota"]["compute"] == 1


def test_goal_record_preserved_after_recreation(tmp_path: Path):
    """After recreation, the new instance retains the same goal_record fields.

    An Agent that cached constraints from the old instance can safely restart
    because the canonical registry still holds the same constraint values."""
    goal_id = "constraint-recreation"
    result, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    before = _read_goal_from_registry(registry_path, gid)

    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]
    assert new_instance != old_instance

    after = _read_goal_from_registry(registry_path, gid)

    # Instance identity changes...
    assert after["goal_instance_id"] == new_instance
    assert after["goal_instance_id"] != before["goal_instance_id"]

    # ...but constraint fields are preserved.
    assert after["id"] == before["id"]
    assert after["display_name"] == before["display_name"]
    assert after["status"] == before["status"]
    assert after["project_id"] == before["project_id"]
    assert after["quota"] == before["quota"]
    assert after["execution_authority"] is False


def test_constraints_recoverable_after_state_file_loss(tmp_path: Path):
    """Deleting the state_file (simulating context loss) does not erase registry constraints.

    An Agent that loses its working state can re-read the registry and recover
    the same constraints. The registry is the canonical owner; the state_file
    is a working copy."""
    goal_id = "context-loss"
    registration = _fresh_registration(tmp_path, goal_id)
    result = register_fresh_source_session_project(registration)
    assert result["ok"] is True
    registry_path = Path(result["registry"])
    gid = result["goal_ref"]["goal_id"]

    constraints_before = _read_goal_from_registry(registry_path, gid)

    # Simulate context loss by deleting the state file.
    state_file = registration.state_file
    if state_file.exists():
        state_file.unlink()

    # Re-read from registry -- constraints must be intact.
    constraints_after = _read_goal_from_registry(registry_path, gid)
    assert constraints_after == constraints_before, (
        "constraints must be recoverable from registry after state_file loss"
    )


# ---------------------------------------------------------------------------
# Readback consistency
# ---------------------------------------------------------------------------


def test_registry_readback_is_consistent(tmp_path: Path):
    """Repeated registry reads return the same goal_record.

    No drift occurs between reads when no mutation has been performed."""
    goal_id = "consistent-readback"
    _, registry_path, gid, _instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    first = _read_goal_from_registry(registry_path, gid)
    second = _read_goal_from_registry(registry_path, gid)
    third = _read_goal_from_registry(registry_path, gid)

    assert first == second == third


def test_registry_readback_unchanged_after_binding(tmp_path: Path):
    """Session binding does not alter the goal_record in the registry.

    Binding is a separate concern; the Goal's constraints must remain
    untouched by session lifecycle operations."""
    goal_id = "bind-preserves"
    _, registry_path, gid, instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    before = _read_goal_from_registry(registry_path, gid)

    # Bind a session -- should not change goal_record fields.
    bind_result = commit_project_session_binding(
        SessionBindingRequest(
            registry_path=registry_path,
            session_id="s1",
            goal_id=gid,
            goal_instance_id=instance,
            operation_id=uuid4().hex,
        )
    )
    assert bind_result["ok"] is True

    after = _read_goal_from_registry(registry_path, gid)
    assert after == before, (
        "session binding must not alter goal_record in registry"
    )


# ---------------------------------------------------------------------------
# Multi-Goal isolation
# ---------------------------------------------------------------------------


def test_independent_goal_constraints_do_not_interfere(tmp_path: Path):
    """Two Goals with different constraints coexist without cross-contamination.

    Registering Goal B does not alter the registry state of Goal A."""
    # Register Goal A.
    _, registry_a, gid_a, instance_a = _registration_and_paths(
        tmp_path,
        "goal-a",
        objective="Goal A objective",
        acceptance=["A acceptance"],
        non_goals=["A non-goal"],
    )

    # Register Goal B with different constraints.
    _, registry_b, gid_b, instance_b = _registration_and_paths(
        tmp_path,
        "goal-b",
        objective="Goal B objective",
        acceptance=["B acceptance"],
        non_goals=["B non-goal"],
    )

    # Read each Goal's record independently.
    goal_a = _read_goal_from_registry(registry_a, gid_a)
    goal_b = _read_goal_from_registry(registry_b, gid_b)

    # Each Goal has its own identity.
    assert goal_a["id"] == gid_a
    assert goal_b["id"] == gid_b
    assert goal_a["id"] != goal_b["id"]
    assert goal_a["goal_instance_id"] == instance_a
    assert goal_b["goal_instance_id"] == instance_b
    assert goal_a["goal_instance_id"] != goal_b["goal_instance_id"]

    # Goal A's record is only in registry_a.
    with pytest.raises(ValueError, match="not found"):
        _read_goal_from_registry(registry_b, gid_a)

    # Goal B's record is only in registry_b.
    with pytest.raises(ValueError, match="not found"):
        _read_goal_from_registry(registry_a, gid_b)


def test_registry_constraints_unchanged_by_other_goal_operations(tmp_path: Path):
    """Operations on Goal B do not change Goal A's registry record."""
    # Register both Goals.
    _, registry_a, gid_a, instance_a = _registration_and_paths(
        tmp_path,
        "goal-a",
    )
    _, registry_b, gid_b, instance_b = _registration_and_paths(
        tmp_path,
        "goal-b",
    )

    before_a = _read_goal_from_registry(registry_a, gid_a)
    before_b = _read_goal_from_registry(registry_b, gid_b)

    # Recreate Goal B.
    rec_req = RecreateGoalRequest(
        registry_path=registry_b,
        goal_id=gid_b,
        goal_instance_id=instance_b,
        operation_id=uuid4().hex,
    )
    assert recreate_goal_instance(rec_req)["ok"] is True

    # Goal A's record must be unchanged.
    after_a = _read_goal_from_registry(registry_a, gid_a)
    assert after_a == before_a, (
        "Goal B recreation must not modify Goal A's record"
    )