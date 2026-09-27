"""Instance-qualified continuity: Goal recreation enforces exact instance identity.

Retire Goal A through the authorized lifecycle, create same-name Goal B, then
deliver A's delayed session binding / claim through the real entrypoints.
Verify no mutation or execution authority leaks into B.

Design owner: source-session lifetime (source_session_lifetime.ts).
Qualification: goal-immutability-coherence-defense-v0.md, Instance-qualified
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
    commit_project_session_unbinding,
    resolve_source_session_project,
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


def _fresh_registration(tmp_path: Path, goal_id: str) -> FreshSourceSessionRegistration:
    root = tmp_path / goal_id
    root.mkdir(parents=True, exist_ok=True)
    runtime_root = root / "runtime"
    return FreshSourceSessionRegistration(
        registry_path=root / ".loopx" / "registry.json",
        runtime_root=runtime_root,
        operation_id=uuid4().hex,
        project_id=f"proj-{goal_id}",
        goal_id=goal_id,
        objective="Verify instance-qualified continuity after recreation.",
        non_goals=["No real effects."],
        acceptance=["Old bindings are retired.", "New bindings succeed."],
        unknowns=[],
        next_effect="noop",
        stop_condition="test completes",
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


def _registration_and_ids(
    tmp_path: Path,
    goal_id: str,
) -> tuple[dict, str, str]:
    """Register a fresh source-session Goal and return (result, goal_id, goal_instance_id)."""
    registration = _fresh_registration(tmp_path, goal_id)
    result = register_fresh_source_session_project(registration)
    assert result["ok"] is True
    goal_ref = result["goal_ref"]
    return result, goal_ref["goal_id"], goal_ref["goal_instance_id"]


def _load_registry(result: dict) -> dict:
    """Load the registry dict from the path recorded in a service result."""
    return load_project_registry(Path(result["registry"]))


# ---------------------------------------------------------------------------
# Core instance-qualified continuity
# ---------------------------------------------------------------------------


def test_recreation_retires_old_instance_and_allows_new(tmp_path: Path):
    """After recreation, old goal_instance_id is retired; new one is current."""
    goal_id = "continuity-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    # goal_instance_id in the request is the CURRENT instance (CAS check);
    # the new instance is auto-generated.
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    assert recreation["retired_goal_ref"]["goal_instance_id"] == old_instance
    new_instance = recreation["goal_ref"]["goal_instance_id"]
    assert new_instance != old_instance

    # Old instance resolves as retired.
    registry = _load_registry(recreation)
    old_resolution = resolve_source_session_project(
        registry=registry,
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        session_id=None,
    )
    assert old_resolution["resolution"] == "retired", (
        f"old instance {old_instance} must resolve as retired, got {old_resolution['resolution']}"
    )

    # New instance resolves as current.
    new_resolution = resolve_source_session_project(
        registry=registry,
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=new_instance,
        session_id=None,
    )
    assert new_resolution["resolution"] == "current", (
        f"new instance {new_instance} must resolve as current, got {new_resolution['resolution']}"
    )


def test_stale_session_bind_rejected_after_recreation(tmp_path: Path):
    """A session bound to the old instance cannot rebind after recreation."""
    goal_id = "stale-bind-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    # Bind session S1 to old instance.
    bind_req = SessionBindingRequest(
        registry_path=Path(result["registry"]),
        session_id="s1",
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    bind_result = commit_project_session_binding(bind_req)
    assert bind_result["ok"] is True
    assert bind_result["changed"] is True

    # Recreate Goal to new instance.
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True

    # Attempting to bind S1 to old instance must fail.
    with pytest.raises(ValueError, match="stale_goal_instance"):
        commit_project_session_binding(
            SessionBindingRequest(
                registry_path=Path(result["registry"]),
                session_id="s1",
                goal_id=gid,
                goal_instance_id=old_instance,
                operation_id=uuid4().hex,
            )
        )


def test_new_session_can_bind_after_recreation(tmp_path: Path):
    """After recreation, a new session can bind to the new instance."""
    goal_id = "new-bind-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    # Bind session S1 to old instance.
    bind_req = SessionBindingRequest(
        registry_path=Path(result["registry"]),
        session_id="s1",
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    assert commit_project_session_binding(bind_req)["ok"] is True

    # Recreate.
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    # New session S2 binds to new instance successfully.
    new_bind = commit_project_session_binding(
        SessionBindingRequest(
            registry_path=Path(result["registry"]),
            session_id="s2",
            goal_id=gid,
            goal_instance_id=new_instance,
            operation_id=uuid4().hex,
        )
    )
    assert new_bind["ok"] is True
    assert new_bind["changed"] is True

    # Verify S2 resolves as current.
    registry = _load_registry(new_bind)
    resolution = resolve_source_session_project(
        registry=registry,
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=new_instance,
        session_id="s2",
    )
    assert resolution["resolution"] == "current"


def test_recreation_retires_old_session_bindings(tmp_path: Path):
    """Recreation removes session bindings tied to the old instance."""
    goal_id = "retire-bindings-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    # Bind two sessions to old instance.
    for sid in ("s1", "s2"):
        assert commit_project_session_binding(
            SessionBindingRequest(
                registry_path=Path(result["registry"]),
                session_id=sid,
                goal_id=gid,
                goal_instance_id=old_instance,
                operation_id=uuid4().hex,
            )
        )["ok"] is True

    # Recreate.
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    # Both old session IDs are recorded as retired.
    assert set(recreation["retired_session_ids"]) == {"s1", "s2"}

    # Neither old session can resolve as current with new instance.
    registry = _load_registry(recreation)
    for sid in ("s1", "s2"):
        resolution = resolve_source_session_project(
            registry=registry,
            registry_path=Path(result["registry"]),
            goal_id=gid,
            goal_instance_id=new_instance,
            session_id=sid,
        )
        assert resolution["resolution"] != "current", (
            f"retired session {sid} must not resolve as current"
        )


# ---------------------------------------------------------------------------
# Unbind continuity
# ---------------------------------------------------------------------------


def test_stale_unbind_rejected_after_recreation(tmp_path: Path):
    """An old-instance unbind is rejected after recreation."""
    goal_id = "stale-unbind-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    # Bind session S1.
    assert commit_project_session_binding(
        SessionBindingRequest(
            registry_path=Path(result["registry"]),
            session_id="s1",
            goal_id=gid,
            goal_instance_id=old_instance,
            operation_id=uuid4().hex,
        )
    )["ok"] is True

    # Recreate.
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    assert recreate_goal_instance(rec_req)["ok"] is True

    # Unbinding S1 with old instance must be rejected.
    with pytest.raises(ValueError, match="stale_goal_instance"):
        commit_project_session_unbinding(
            SessionBindingRequest(
                registry_path=Path(result["registry"]),
                session_id="s1",
                goal_id=gid,
                goal_instance_id=old_instance,
                operation_id=uuid4().hex,
            )
        )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_recreation_is_idempotent(tmp_path: Path):
    """Replaying the same recreation returns the same receipt."""
    goal_id = "idempotent-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    operation_id = uuid4().hex
    rec_req = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=operation_id,
    )

    first = recreate_goal_instance(rec_req)
    assert first["ok"] is True
    assert not first["replayed"]

    # Replay with same operation_id returns replayed result.
    second = recreate_goal_instance(rec_req)
    assert second["ok"] is True
    assert second["replayed"] is True
    assert second["goal_ref"] == first["goal_ref"]
    assert second["retired_goal_ref"] == first["retired_goal_ref"]


def test_recreation_rejects_stale_instance_after_recreation(tmp_path: Path):
    """After recreation, the old instance is retired; further recreation with it must fail."""
    goal_id = "stale-recreation-goal"
    result, gid, old_instance = _registration_and_ids(tmp_path, goal_id)

    operation_id = uuid4().hex
    rec_a = RecreateGoalRequest(
        registry_path=Path(result["registry"]),
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=operation_id,
    )
    assert recreate_goal_instance(rec_a)["ok"] is True

    # Trying to recreate again with the same old instance (now retired) must fail.
    with pytest.raises(ValueError, match="stale_goal_instance"):
        recreate_goal_instance(
            RecreateGoalRequest(
                registry_path=Path(result["registry"]),
                goal_id=gid,
                goal_instance_id=old_instance,
                operation_id=uuid4().hex,
            )
        )


# ---------------------------------------------------------------------------
# Registration is idempotent
# ---------------------------------------------------------------------------


def test_registration_is_idempotent(tmp_path: Path):
    """Re-registering the same fresh project replays, does not recreate."""
    goal_id = "registration-idempotent"
    registration = _fresh_registration(tmp_path, goal_id)

    first = register_fresh_source_session_project(registration)
    assert first["ok"] is True
    assert first["changed"] is True
    assert not first["replayed"]

    second = register_fresh_source_session_project(registration)
    assert second["ok"] is True
    assert not second["changed"]
    assert second["replayed"] is True
    assert second["goal_ref"] == first["goal_ref"]


# ---------------------------------------------------------------------------
# Session binding idempotency
# ---------------------------------------------------------------------------


def test_session_binding_is_idempotent(tmp_path: Path):
    """Rebinding the same session with the same operation_id replays."""
    goal_id = "bind-idempotent"
    result, gid, instance = _registration_and_ids(tmp_path, goal_id)

    req = SessionBindingRequest(
        registry_path=Path(result["registry"]),
        session_id="s1",
        goal_id=gid,
        goal_instance_id=instance,
        operation_id=uuid4().hex,
    )

    first = commit_project_session_binding(req)
    assert first["ok"] is True
    assert first["changed"] is True
    assert not first["replayed"]

    second = commit_project_session_binding(req)
    assert second["ok"] is True
    assert second["replayed"] is True
    # changed mirrors the original receipt; the key marker is replayed=True


def test_session_binding_rejects_operation_id_with_different_session(tmp_path: Path):
    """Reusing operation_id with different session_id must conflict."""
    goal_id = "bind-conflict"
    result, gid, instance = _registration_and_ids(tmp_path, goal_id)

    operation_id = uuid4().hex
    req_s1 = SessionBindingRequest(
        registry_path=Path(result["registry"]),
        session_id="s1",
        goal_id=gid,
        goal_instance_id=instance,
        operation_id=operation_id,
    )
    assert commit_project_session_binding(req_s1)["ok"] is True

    req_s2 = SessionBindingRequest(
        registry_path=Path(result["registry"]),
        session_id="s2",
        goal_id=gid,
        goal_instance_id=instance,
        operation_id=operation_id,
    )
    with pytest.raises((ValueError, EffectRuntimeRejected)):
        commit_project_session_binding(req_s2)