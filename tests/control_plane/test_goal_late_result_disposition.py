"""Late-result disposition: delayed results are traceable to their original instance.

When an old request's result arrives after instance replacement, the system
must preserve the original lineage and not silently attach the result to the
new instance. Retired instances track their successors; receipts remain
attributable to the instance that generated them.

Design owner: handoff and Effect recovery owners (R3).
Qualification: goal-immutability-coherence-defense-v0.md, Recoverable
late-result disposition slice.
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
        objective="Verify late-result disposition after instance replacement.",
        non_goals=["No real effects."],
        acceptance=["Old receipts are traceable.", "New instance is clean."],
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


def _registration_and_paths(
    tmp_path: Path,
    goal_id: str,
) -> tuple[dict, Path, str, str]:
    registration = _fresh_registration(tmp_path, goal_id)
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
# Retired instance tracking
# ---------------------------------------------------------------------------


def test_retired_instances_tracks_old_to_new_lineage(tmp_path: Path):
    """After recreation, retired_goal_instances records the old→new mapping.

    A delayed result for the old instance can be traced to its successor
    through the retired_goal_instances list."""
    goal_id = "late-result-lineage"
    result, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    registry = load_project_registry(registry_path)
    retired = registry.get("retired_goal_instances", [])
    assert isinstance(retired, list)
    assert len(retired) == 1

    entry = retired[0]
    assert entry["goal_ref"]["goal_id"] == gid
    assert entry["goal_ref"]["goal_instance_id"] == old_instance
    assert entry["successor_goal_ref"]["goal_id"] == gid
    assert entry["successor_goal_ref"]["goal_instance_id"] == new_instance
    assert entry["operation_id"] == rec_req.operation_id
    assert isinstance(entry["retired_at"], str)


def test_retired_instances_preserved_across_sequential_recreations(
    tmp_path: Path,
):
    """Multiple recreations accumulate retired entries without losing lineage.

    Each retirement records the correct predecessor → successor mapping."""
    goal_id = "sequential-recreations"
    _, registry_path, gid, instance_0 = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    # First recreation: instance_0 → instance_1
    rec_1 = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=instance_0,
        operation_id=uuid4().hex,
    )
    r1 = recreate_goal_instance(rec_1)
    assert r1["ok"] is True
    instance_1 = r1["goal_ref"]["goal_instance_id"]

    # Second recreation: instance_1 → instance_2
    rec_2 = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=instance_1,
        operation_id=uuid4().hex,
    )
    r2 = recreate_goal_instance(rec_2)
    assert r2["ok"] is True
    instance_2 = r2["goal_ref"]["goal_instance_id"]

    registry = load_project_registry(registry_path)
    retired = registry.get("retired_goal_instances", [])

    assert len(retired) == 2

    # First retirement: 0 → 1
    assert retired[0]["goal_ref"]["goal_instance_id"] == instance_0
    assert retired[0]["successor_goal_ref"]["goal_instance_id"] == instance_1

    # Second retirement: 1 → 2
    assert retired[1]["goal_ref"]["goal_instance_id"] == instance_1
    assert retired[1]["successor_goal_ref"]["goal_instance_id"] == instance_2

    # Current goal is instance_2.
    current = next(
        g for g in registry["goals"] if g["id"] == gid
    )
    assert current["goal_instance_id"] == instance_2


def test_retired_instance_sessions_recorded_in_retire_receipt(
    tmp_path: Path,
):
    """Session bindings active at retirement time are recorded in session_receipts.

    A delayed result from a retired session can be traced through the
    session_receipts list back to the retirement operation."""
    goal_id = "retire-receipt"
    _, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    # Bind two sessions.
    for sid in ("s1", "s2"):
        assert commit_project_session_binding(
            SessionBindingRequest(
                registry_path=registry_path,
                session_id=sid,
                goal_id=gid,
                goal_instance_id=old_instance,
                operation_id=uuid4().hex,
            )
        )["ok"] is True

    operation_id = uuid4().hex
    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=operation_id,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    assert set(recreation["retired_session_ids"]) == {"s1", "s2"}

    registry = load_project_registry(registry_path)
    session_receipts = registry.get("session_receipts", [])

    # Find the retirement receipt for this operation_id.
    retire_receipts = [
        r for r in session_receipts
        if r.get("operation_id") == operation_id
        and r.get("operation") == "retire_bindings"
    ]
    assert len(retire_receipts) == 1
    retire_receipt = retire_receipts[0]

    assert retire_receipt["schema_version"] == (
        "loopx_source_session_retirement_receipt_v1"
    )
    assert retire_receipt["retired_goal_ref"]["goal_id"] == gid
    assert retire_receipt["retired_goal_ref"]["goal_instance_id"] == old_instance
    assert set(retire_receipt["session_ids"]) == {"s1", "s2"}


def test_lifetime_receipts_record_recreation_event(tmp_path: Path):
    """Each recreation generates a lifetime_receipt with the old→new mapping.

    This is the authoritative record for reconciling late results."""
    goal_id = "lifetime-receipt"
    _, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    operation_id = uuid4().hex
    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=operation_id,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    registry = load_project_registry(registry_path)
    lifetime_receipts = registry.get("lifetime_receipts", [])

    # Find the recreation receipt (the second receipt, after creation).
    recreation_receipts = [
        r for r in lifetime_receipts
        if r.get("schema_version") == "loopx_goal_recreation_receipt_v1"
    ]
    assert len(recreation_receipts) == 1
    receipt = recreation_receipts[0]

    assert receipt["operation_id"] == operation_id
    assert receipt["retired_goal_ref"]["goal_instance_id"] == old_instance
    assert receipt["new_goal_ref"]["goal_instance_id"] == new_instance
    assert isinstance(receipt["committed_at"], str)


# ---------------------------------------------------------------------------
# Old receipts are not auto-rebound to new instance
# ---------------------------------------------------------------------------


def test_session_receipts_not_rebound_to_new_instance(tmp_path: Path):
    """After recreation, old session receipts stay on the retired instance.

    The new instance starts with no session bindings; old bindings are not
    silently transferred."""
    goal_id = "no-rebind"
    _, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    # Bind session S1.
    bind_req = SessionBindingRequest(
        registry_path=registry_path,
        session_id="s1",
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    assert commit_project_session_binding(bind_req)["ok"] is True

    # Recreate.
    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=uuid4().hex,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    registry = load_project_registry(registry_path)

    # No session binding references the new instance.
    for binding in registry.get("session_bindings", []):
        bound_instance = binding.get("foreground_goal_ref", {}).get(
            "goal_instance_id"
        )
        assert bound_instance != new_instance, (
            f"new instance {new_instance} must not inherit old session bindings"
        )

    # The old binding is no longer present (retirement removed it).
    old_binding_ids = [
        b["session_id"] for b in registry.get("session_bindings", [])
    ]
    assert "s1" not in old_binding_ids


# ---------------------------------------------------------------------------
# Receipt traceability across the full lifecycle
# ---------------------------------------------------------------------------


def test_full_receipt_trail_spans_registration_and_recreation(tmp_path: Path):
    """The complete receipt trail is available from registration through recreation.

    A recovery process can walk creation_receipt → recreation_receipt to
    reconstruct the full instance lineage."""
    goal_id = "receipt-trail"
    _, registry_path, gid, old_instance = _registration_and_paths(
        tmp_path,
        goal_id,
    )

    recreation_op = uuid4().hex
    rec_req = RecreateGoalRequest(
        registry_path=registry_path,
        goal_id=gid,
        goal_instance_id=old_instance,
        operation_id=recreation_op,
    )
    recreation = recreate_goal_instance(rec_req)
    assert recreation["ok"] is True
    new_instance = recreation["goal_ref"]["goal_instance_id"]

    registry = load_project_registry(registry_path)
    lifetime_receipts = registry.get("lifetime_receipts", [])

    # First receipt is the creation.
    creation_receipts = [
        r for r in lifetime_receipts
        if r.get("schema_version") == "loopx_goal_creation_receipt_v1"
    ]
    assert len(creation_receipts) == 1
    creation = creation_receipts[0]
    assert creation["goal_ref"]["goal_instance_id"] == old_instance

    # Second receipt is the recreation.
    recreation_receipts = [
        r for r in lifetime_receipts
        if r.get("schema_version") == "loopx_goal_recreation_receipt_v1"
    ]
    assert len(recreation_receipts) == 1
    rec_receipt = recreation_receipts[0]
    assert rec_receipt["retired_goal_ref"]["goal_instance_id"] == old_instance
    assert rec_receipt["new_goal_ref"]["goal_instance_id"] == new_instance

    # The creation receipt's instance is the one retired by the recreation receipt.
    assert creation["goal_ref"]["goal_instance_id"] == rec_receipt["retired_goal_ref"]["goal_instance_id"]

    # A late result for old_instance can trace: creation → recreation → successor.
    retired_entry = registry["retired_goal_instances"][0]
    assert retired_entry["goal_ref"]["goal_instance_id"] == old_instance
    assert retired_entry["successor_goal_ref"]["goal_instance_id"] == new_instance