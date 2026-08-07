from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Mapping

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
from loopx.application.system import (
    RuntimeArchiveRequest,
    RuntimeArchiveService,
    StateBackupRequest,
    StateBackupService,
    StateMigrationRequest,
    StateMigrationService,
    UpgradePlanRequest,
    UpgradePlanService,
)
from loopx.application.system.root import SystemProviders, SystemServices


def _write_context() -> WriteContext:
    return WriteContext(
        actor="fixture-agent",
        idempotency_key="fixture-operation-one",
        expected_revision=None,
    )


class _BackupProvider:
    def __init__(self) -> None:
        self.byte_count = 7
        self.apply_calls = 0

    def preview(self, request: StateBackupRequest) -> Mapping[str, object]:
        return {
            "ok": True,
            "backup_id": request.backup_id or "backup-one",
            "included": [
                {
                    "key": "runtime_root",
                    "archive_path": "runtime-root",
                    "stats": {
                        "paths": 2,
                        "files": 1,
                        "directories": 1,
                        "symlinks": 0,
                        "bytes": self.byte_count,
                    },
                }
            ],
            "summary": {
                "missing_target_count": 0,
                "warning_count": 0,
                "logical_source_bytes": self.byte_count,
            },
        }

    def apply(self, provider_plan: Mapping[str, object]) -> Mapping[str, object]:
        self.apply_calls += 1
        return {
            **provider_plan,
            "ok": True,
            "dry_run": False,
            "execution": {
                "archive_sha256": "a" * 64,
                "archive_size_bytes": 5,
            },
        }


def test_backup_apply_repreviews_and_rejects_forged_or_stale_plan(
    tmp_path: Path,
) -> None:
    provider = _BackupProvider()
    service = StateBackupService(profile=Profile.CLI, provider=provider)
    plan = service.preview(StateBackupRequest(project=tmp_path / "project"))

    with pytest.raises(RevisionConflict):
        service.apply(
            replace(plan, plan_hash="sha256:" + "f" * 64),
            write_context=_write_context(),
        )
    assert provider.apply_calls == 0

    provider.byte_count = 8
    with pytest.raises(RevisionConflict):
        service.apply(plan, write_context=_write_context())
    assert provider.apply_calls == 0


def test_backup_success_uses_dedicated_projection_and_no_pseudo_revision(
    tmp_path: Path,
) -> None:
    provider = _BackupProvider()
    service = StateBackupService(profile=Profile.CLI, provider=provider)
    plan = service.preview(StateBackupRequest(project=tmp_path / "project"))
    result = service.apply(plan, write_context=_write_context())

    assert plan.correctness.atomic_revision_check is False
    assert result.written is True
    assert result.archive_sha256 == "a" * 64
    assert not hasattr(plan, "details")
    assert not hasattr(result, "details")

    with pytest.raises(ValidationFailed) as error:
        service.apply(
            plan,
            write_context=WriteContext(
                actor="fixture-agent",
                idempotency_key="fixture-operation-two",
                expected_revision=plan.plan_hash,
            ),
        )
    assert "writer_has_no_atomic_revision_contract" in str(
        getattr(error.value, "details", {})
    )


def test_backup_malformed_required_count_fails_closed(tmp_path: Path) -> None:
    provider = _BackupProvider()
    provider.byte_count = "broken"  # type: ignore[assignment]
    service = StateBackupService(profile=Profile.CLI, provider=provider)

    with pytest.raises(StateUnavailable) as error:
        service.preview(StateBackupRequest(project=tmp_path / "project"))
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "target.stats.bytes"


def test_private_system_preview_requires_cli_authority(tmp_path: Path) -> None:
    service = StateBackupService(
        profile=Profile.HTTP_LOCAL_OPERATOR,
        provider=_BackupProvider(),
    )
    with pytest.raises(AuthorityDenied):
        service.preview(StateBackupRequest(project=tmp_path / "project"))


class _ArchiveProvider:
    def __init__(self) -> None:
        self.source = "runtime/goals/goal-one"
        self.apply_calls = 0

    def archive(self, **kwargs: object) -> Mapping[str, object]:
        execute = bool(kwargs["execute"])
        if execute:
            self.apply_calls += 1
        return {
            "ok": True,
            "goal_id": "goal-one",
            "registry_member": False,
            "source": self.source,
            "archive_path": "archive/goal-one-stamp",
            "archived": execute,
        }


def test_runtime_archive_repreview_rejects_changed_source_projection(
    tmp_path: Path,
) -> None:
    provider = _ArchiveProvider()
    service = RuntimeArchiveService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=str(tmp_path / "runtime"),
        profile=Profile.CLI,
        provider=provider,
    )
    plan = service.preview(RuntimeArchiveRequest(goal_id="goal-one"))
    provider.source = ""

    with pytest.raises(StateUnavailable):
        service.apply(plan, write_context=_write_context())
    assert provider.apply_calls == 0


class _MigrationProvider:
    def __init__(self) -> None:
        self.target_count = 1
        self.execute_calls = 0
        self.sync_ok = True

    def goal_ids(self, registry_path: Path) -> tuple[str, ...]:
        return ("goal-one",)

    def migrate(self, **kwargs: object) -> Mapping[str, object]:
        execute = bool(kwargs["execute"])
        if execute:
            self.execute_calls += 1
        return {
            "ok": True,
            "selected_goal_ids": ["goal-one"],
            "migrated_goal_ids": ["goal-one"],
            "project_registry_goal_count": self.target_count,
            "wrote_project_registry": execute,
            "active_state": [],
            "runtime_goals": [],
        }

    def sync_goal(self, **kwargs: object) -> Mapping[str, object]:
        return {"ok": self.sync_ok, "synced_goal_ids": [kwargs["goal_id"]]}


def test_state_migration_repreview_detects_stale_plan_before_write(
    tmp_path: Path,
) -> None:
    provider = _MigrationProvider()
    service = StateMigrationService(
        registry_path=tmp_path / "target-registry.json",
        runtime_root_override=str(tmp_path / "runtime"),
        profile=Profile.CLI,
        provider=provider,
    )
    request = StateMigrationRequest(
        legacy_registry=tmp_path / "legacy.json",
        goal_ids=("goal-one",),
    )
    plan = service.preview(request)
    provider.target_count = 2

    with pytest.raises(RevisionConflict):
        service.apply(plan, write_context=_write_context())
    assert provider.execute_calls == 0


def test_state_migration_projects_partial_global_sync_without_raw_payload(
    tmp_path: Path,
) -> None:
    provider = _MigrationProvider()
    provider.sync_ok = False
    service = StateMigrationService(
        registry_path=tmp_path / "target-registry.json",
        runtime_root_override=str(tmp_path / "runtime"),
        profile=Profile.CLI,
        provider=provider,
    )
    plan = service.preview(
        StateMigrationRequest(
            legacy_registry=tmp_path / "legacy.json",
            goal_ids=("goal-one",),
        )
    )
    result = service.apply(plan, write_context=_write_context())

    assert result.wrote_project_registry is True
    assert result.global_sync_verified is False
    assert result.partial_global_sync is True
    assert not hasattr(result, "details")


class _UpgradeProvider:
    def __init__(self, *, malformed: bool = False) -> None:
        self.malformed = malformed

    def build(self, **kwargs: object) -> Mapping[str, object]:
        return {
            "ok": True,
            "summary": {
                "managed_goal_count": "bad" if self.malformed else 0,
                "current_prompt_count": 0,
                "stale_prompt_count": 0,
                "unknown_prompt_count": 0,
                "not_installed_prompt_count": 0,
                "stage_deferred_goal_count": 0,
                "installed_manifest_available": False,
                "installed_manifest_entry_count": 0,
                "installed_prompt_policy_warning_count": 0,
                "host_loop_missing_goal_count": 0,
                "peer_runtime_automation_migration_count": 0,
                "ready_for_default_promotion": False,
            },
            "managed_heartbeats": [],
            "recommended_action": "No managed heartbeat matched.",
        }


def test_upgrade_plan_malformed_provider_count_fails_closed(tmp_path: Path) -> None:
    service = UpgradePlanService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_UpgradeProvider(malformed=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.plan(UpgradePlanRequest())
    assert error.value.details["cause"] == "invalid_payload"


def test_system_root_accessor_preserves_injected_provider_ports(tmp_path: Path) -> None:
    backup_provider = _BackupProvider()
    context = ApplicationContext(
        registry_path=tmp_path / "registry.json",
        profile=Profile.CLI,
    )
    services = SystemServices(
        context=context,
        providers=SystemProviders(state_backup=backup_provider),
    )
    assert services.backup.provider is backup_provider
