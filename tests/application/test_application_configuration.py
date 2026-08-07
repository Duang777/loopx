from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from loopx.application import (
    ApplicationContext,
    AuthorityDenied,
    LoopXApplication,
    Profile,
    RevisionConflict,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.configuration import (
    ConfigurationApplyResult,
    ConfigurationEffect,
    ConfigurationPlan,
    GoalConfigurationPatch,
    GoalConfigurationService,
    WriterCorrectness,
)
from loopx.history import load_registry
from loopx.paths import global_registry_path
from loopx.registry import registry_goals

from .fixtures.closed_loop import (
    FIXED_UTC_TIME,
    PRIMARY_GOAL_ID,
    ClosedLoopFixture,
    materialize_closed_loop_fixture,
)


def _service(
    fixture: ClosedLoopFixture,
    *,
    profile: Profile = Profile.CLI,
) -> GoalConfigurationService:
    context = ApplicationContext(
        registry_path=fixture.registry_path,
        runtime_root_override=str(fixture.runtime_root),
        profile=profile,
        clock=lambda: FIXED_UTC_TIME,
    )
    return LoopXApplication(context).get_goal(PRIMARY_GOAL_ID).configuration


def _goal(registry_path: Path) -> dict:
    payload = load_registry(registry_path)
    return next(
        goal
        for goal in registry_goals(payload)
        if str(goal.get("id") or "") == PRIMARY_GOAL_ID
    )


def _assert_pending_writer_correctness(correctness: WriterCorrectness) -> None:
    assert correctness.status == "pending_migration"
    assert correctness.atomic_revision_check is False
    assert correctness.idempotent_retry is False


def test_preview_returns_typed_effects_revision_and_stable_plan_hash(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    patch = GoalConfigurationPatch(
        quota_compute=0.75,
        quota_window_hours=24,
    )

    first = service.preview(patch)
    second = service.preview(patch)

    assert isinstance(first, ConfigurationPlan)
    assert first == second
    assert first.goal_id == PRIMARY_GOAL_ID
    assert first.generated_at == FIXED_UTC_TIME
    assert first.revision.startswith("sha256:")
    assert first.plan_hash.startswith("sha256:")
    assert first.plan_hash == second.plan_hash
    assert first.can_apply is True
    assert first.changed is True
    assert len(first.effects) == 1
    effect = first.effects[0]
    assert isinstance(effect, ConfigurationEffect)
    assert effect.field == "quota"
    assert isinstance(effect.before, Mapping)
    assert isinstance(effect.after, Mapping)
    assert effect.before["compute"] == 0.5
    assert effect.before["window_hours"] == 12.0
    assert effect.after["compute"] == 0.75
    assert effect.after["window_hours"] == 24.0
    _assert_pending_writer_correctness(first.correctness)


def test_apply_changes_source_and_verifies_global_sync(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    patch = GoalConfigurationPatch(
        quota_compute=0.75,
        quota_window_hours=24,
    )
    plan = service.preview(patch)

    result = service.apply(
        patch,
        plan_hash=plan.plan_hash,
        write_context=WriteContext(
            actor="application-configuration-test",
            idempotency_key="configuration-apply-001",
            expected_revision=plan.revision,
        ),
    )

    assert isinstance(result, ConfigurationApplyResult)
    assert result.goal_id == PRIMARY_GOAL_ID
    assert result.generated_at == FIXED_UTC_TIME
    assert result.previous_revision == plan.revision
    assert result.revision != plan.revision
    assert result.plan_hash == plan.plan_hash
    assert result.changed is True
    assert result.written is True
    assert result.global_sync_verified is True
    _assert_pending_writer_correctness(result.correctness)

    source_goal = _goal(fixture.registry_path)
    shared_goal = _goal(global_registry_path(fixture.runtime_root))
    assert source_goal["quota"]["compute"] == 0.75
    assert source_goal["quota"]["window_hours"] == 24.0
    assert shared_goal["quota"] == source_goal["quota"]
    assert Path(shared_goal["source_registry"]).resolve() == (
        fixture.registry_path.resolve()
    )


def test_apply_rejects_stale_revision_and_wrong_plan_hash_without_write(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    patch = GoalConfigurationPatch(quota_compute=0.75)
    plan = service.preview(patch)
    shared_registry = global_registry_path(fixture.runtime_root)
    source_before = fixture.registry_path.read_bytes()
    shared_before = shared_registry.read_bytes()

    with pytest.raises(RevisionConflict) as stale_error:
        service.apply(
            patch,
            plan_hash=plan.plan_hash,
            write_context=WriteContext(
                actor="application-configuration-test",
                idempotency_key="configuration-stale-001",
                expected_revision=f"sha256:{'0' * 64}",
            ),
        )

    assert stale_error.value.code == "revision_conflict"
    assert stale_error.value.retryable is True
    assert stale_error.value.details == {
        "goal_id": PRIMARY_GOAL_ID,
        "expected_revision": f"sha256:{'0' * 64}",
        "current_revision": plan.revision,
    }
    assert fixture.registry_path.read_bytes() == source_before
    assert shared_registry.read_bytes() == shared_before

    wrong_hash = f"sha256:{'f' * 64}"
    with pytest.raises(RevisionConflict) as hash_error:
        service.apply(
            patch,
            plan_hash=wrong_hash,
            write_context=WriteContext(
                actor="application-configuration-test",
                idempotency_key="configuration-hash-001",
                expected_revision=plan.revision,
            ),
        )

    assert hash_error.value.code == "revision_conflict"
    assert hash_error.value.retryable is True
    assert hash_error.value.details == {
        "goal_id": PRIMARY_GOAL_ID,
        "reason": "plan_hash_mismatch",
        "expected_plan_hash": wrong_hash,
        "current_plan_hash": plan.plan_hash,
    }
    assert fixture.registry_path.read_bytes() == source_before
    assert shared_registry.read_bytes() == shared_before


def test_http_read_only_denies_preview_and_apply(tmp_path: Path) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture, profile=Profile.HTTP_READ_ONLY)
    patch = GoalConfigurationPatch(quota_compute=0.75)

    with pytest.raises(AuthorityDenied) as preview_error:
        service.preview(patch)
    with pytest.raises(AuthorityDenied) as apply_error:
        service.apply(
            patch,
            plan_hash="sha256:not-evaluated",
            write_context=WriteContext(
                actor="read-only-test",
                idempotency_key="configuration-read-only-001",
                expected_revision="sha256:not-evaluated",
            ),
        )

    assert preview_error.value.code == "authority_denied"
    assert preview_error.value.details == {
        "operation_id": "goal.configuration.preview",
        "profile": "http_read_only",
    }
    assert apply_error.value.code == "authority_denied"
    assert apply_error.value.details == {
        "operation_id": "goal.configuration.apply",
        "profile": "http_read_only",
    }


def test_invalid_patch_maps_to_validation_failed_without_write(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    source_before = fixture.registry_path.read_bytes()

    with pytest.raises(ValidationFailed) as error:
        service.preview(GoalConfigurationPatch(quota_compute=-0.25))

    assert error.value.code == "validation_failed"
    assert error.value.retryable is False
    assert error.value.details == {"operation_id": "goal.configuration"}
    assert isinstance(error.value.__cause__, ValueError)
    assert fixture.registry_path.read_bytes() == source_before


def test_shared_registry_with_runtime_override_still_writes_canonical_source(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    shared_registry = global_registry_path(fixture.runtime_root)
    context = ApplicationContext(
        registry_path=shared_registry,
        runtime_root_override=str(fixture.runtime_root),
        clock=lambda: FIXED_UTC_TIME,
    )
    service = LoopXApplication(context).get_goal(PRIMARY_GOAL_ID).configuration
    patch = GoalConfigurationPatch(quota_compute=0.75)
    plan = service.preview(patch)

    result = service.apply(
        patch,
        plan_hash=plan.plan_hash,
        write_context=WriteContext(
            actor="canonical-source-test",
            idempotency_key="canonical-source-001",
            expected_revision=plan.revision,
        ),
    )

    assert result.global_sync_verified is True
    assert _goal(fixture.registry_path)["quota"]["compute"] == 0.75
    assert _goal(shared_registry)["quota"]["compute"] == 0.75


def test_configuration_patch_normalizes_mutable_inputs_and_rejects_wrong_types() -> (
    None
):
    domains = ["docs", "tests"]
    profile = {"agent_id": "codex-main-control", "nested": ["read"]}

    patch = GoalConfigurationPatch(
        allowed_domains=domains,  # type: ignore[arg-type]
        agent_profiles=[profile],  # type: ignore[arg-type]
    )
    domains.append("runtime")
    profile["nested"].append("write")

    assert patch.allowed_domains == ("docs", "tests")
    assert tuple(patch.agent_profiles or ())
    assert (patch.agent_profiles or ())[0]["nested"] == ("read",)
    with pytest.raises(ValidationFailed):
        GoalConfigurationPatch(quota_compute="not-a-number")  # type: ignore[arg-type]


def test_noop_apply_does_not_claim_global_sync_readback_verification(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    patch = GoalConfigurationPatch(quota_compute=0.5, quota_window_hours=12)
    plan = service.preview(patch)

    result = service.apply(
        patch,
        plan_hash=plan.plan_hash,
        write_context=WriteContext(
            actor="no-op-test",
            idempotency_key="configuration-noop-001",
            expected_revision=plan.revision,
        ),
    )

    assert result.changed is False
    assert result.written is False
    assert result.global_sync_verified is False
