from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import pytest

from loopx.application import ApplicationContext, Profile
from loopx.application.registry import RegistryProviders, RegistryServices
from loopx.application.system import (
    IndexDuplicateInspectionRequest,
    RuntimeArchiveRequest,
    StateBackupRequest,
    StateMigrationRequest,
    SystemProviders,
    SystemServices,
    TrajectoryHygieneRequest,
    UpgradePlanRequest,
)
from loopx.cli_v2.entrypoint import main
from loopx.cli_v2.project_system_registry import PROJECT_SYSTEM_REGISTRY_COHORT


class _BackupProvider:
    def __init__(self) -> None:
        self.preview_calls = 0
        self.apply_calls = 0

    def preview(self, request: StateBackupRequest) -> Mapping[str, object]:
        self.preview_calls += 1
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
                        "bytes": 8,
                    },
                }
            ],
            "summary": {
                "missing_target_count": 0,
                "warning_count": 0,
                "logical_source_bytes": 8,
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
                "archive_size_bytes": 12,
            },
        }


class _UpgradeProvider:
    def build(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: UpgradePlanRequest,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root_override, request
        return {
            "ok": True,
            "summary": {
                "managed_goal_count": 0,
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


class _ArchiveProvider:
    def __init__(self) -> None:
        self.execute_calls = 0

    def archive(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: RuntimeArchiveRequest,
        execute: bool,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root_override
        self.execute_calls += int(execute)
        return {
            "ok": True,
            "goal_id": request.goal_id,
            "registry_member": False,
            "source": f"runtime/goals/{request.goal_id}",
            "archive_path": f"archive/{request.goal_id}-stamp",
            "archived": execute,
        }


class _MigrationProvider:
    def __init__(self) -> None:
        self.execute_calls = 0

    def goal_ids(self, registry_path: Path) -> tuple[str, ...]:
        del registry_path
        return ("goal-one",)

    def migrate(
        self,
        *,
        target_registry_path: Path,
        target_runtime_root: Path,
        request: StateMigrationRequest,
        goal_ids: tuple[str, ...],
        execute: bool,
    ) -> Mapping[str, object]:
        del target_registry_path, target_runtime_root, request
        self.execute_calls += int(execute)
        return {
            "ok": True,
            "selected_goal_ids": list(goal_ids),
            "migrated_goal_ids": list(goal_ids),
            "project_registry_goal_count": len(goal_ids),
            "wrote_project_registry": execute,
            "active_state": [],
            "runtime_goals": [],
        }

    def sync_goal(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root
        return {"ok": True, "synced_goal_ids": [goal_id]}


class _HistoryProvider:
    def __init__(self) -> None:
        self.index_requests: list[IndexDuplicateInspectionRequest] = []
        self.trajectory_calls = 0

    def inspect_index_duplicates(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: IndexDuplicateInspectionRequest,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root_override
        self.index_requests.append(request)
        return {
            "ok": True,
            "goal_filter": request.goal_id,
            "checked_goal_count": 0,
            "raw_index_records": 0,
            "duplicate_group_count": 0,
            "duplicate_row_count": 0,
            "groups": [],
            "truncated": False,
            "limit": request.limit,
        }

    def trajectory_hygiene(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: TrajectoryHygieneRequest,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root_override, request
        self.trajectory_calls += 1
        raise AssertionError("invalid trajectory request reached the provider")


class _RegistryProvider:
    def inspect(self, path: Path) -> Mapping[str, object]:
        del path
        return {
            "ok": True,
            "schema_version": "0.1",
            "goal_count": 1,
            "status_counts": {"active": 1},
            "problem_diagnostics": [],
            "goals": [
                {
                    "id": "goal-one",
                    "domain": "fixture",
                    "status": "active",
                    "repo_exists": True,
                    "state_file_exists": True,
                    "adapter_kind": "read_only",
                    "adapter_status": "ready",
                    "authority_source_count": 0,
                }
            ],
        }

    def inspect_boundary(self, path: Path) -> Mapping[str, object]:
        return {
            "ok": True,
            "exists": True,
            "path_label": path.name,
            "classification": "project_local_private_registry",
            "boundary_kind": "project_local_private_registry",
            "goal_count": 1,
            "authority_source_count": 0,
            "private_marker_count": 0,
            "git": {
                "available": False,
                "inside_worktree": False,
                "tracked": False,
                "ignored": False,
            },
            "should_be_gitignored": True,
            "github_push_allowed": False,
            "risks": [],
        }


@dataclass(frozen=True)
class _ApplicationRoot:
    system: SystemServices
    registry: RegistryServices


@dataclass
class _Fixture:
    root: _ApplicationRoot
    backup: _BackupProvider
    archive: _ArchiveProvider
    migration: _MigrationProvider
    history: _HistoryProvider


@pytest.fixture
def application_fixture(tmp_path: Path) -> _Fixture:
    backup = _BackupProvider()
    archive = _ArchiveProvider()
    migration = _MigrationProvider()
    history = _HistoryProvider()
    context = ApplicationContext(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=str(tmp_path / "runtime"),
        profile=Profile.CLI,
    )
    root = _ApplicationRoot(
        system=SystemServices(
            context=context,
            providers=SystemProviders(
                state_backup=backup,
                upgrade_plan=_UpgradeProvider(),
                runtime_archive=archive,
                state_migration=migration,
                history_diagnostics=history,
            ),
        ),
        registry=RegistryServices(
            context=context,
            providers=RegistryProviders(inspection=_RegistryProvider()),
        ),
    )
    return _Fixture(
        root=root,
        backup=backup,
        archive=archive,
        migration=migration,
        history=history,
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes | str | None]]:
    snapshot: dict[str, tuple[str, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        label = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[label] = ("symlink", str(path.readlink()))
        elif path.is_file():
            snapshot[label] = ("file", path.read_bytes())
        elif path.is_dir():
            snapshot[label] = ("directory", None)
    return snapshot


def test_trajectory_hygiene_missing_goal_id_fails_before_provider_access(
    application_fixture: _Fixture,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            "--format",
            "json",
            "history",
            "trajectory-hygiene",
        ],
        application_factory=lambda _args, _path: application_fixture.root,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 1
    assert stderr.getvalue() == ""
    assert json.loads(stdout.getvalue()) == {
        "title": "LoopX CLI v2",
        "ok": False,
        "schema_version": "loopx_cli_v2_result_v1",
        "application_operation": (
            "application.system.history.trajectory_hygiene"
        ),
        "error": {
            "code": "validation_failed",
            "message": "The application request is invalid.",
            "details": {"field": "goal_id"},
            "retryable": False,
        },
    }
    assert application_fixture.history.trajectory_calls == 0
    assert application_fixture.history.index_requests == []
    assert _tree_snapshot(tmp_path) == before


def test_index_duplicate_inspection_still_allows_no_goal_id(
    application_fixture: _Fixture,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    before = _tree_snapshot(tmp_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    exit_code = main(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            "--format",
            "json",
            "history",
            "inspect-index-duplicates",
            "--limit",
            "3",
        ],
        application_factory=lambda _args, _path: application_fixture.root,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=stdout,
        stderr=stderr,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert stderr.getvalue() == ""
    assert payload["goal_filter"] is None
    assert payload["limit"] == 3
    assert payload["groups"] == []
    assert len(application_fixture.history.index_requests) == 1
    request = application_fixture.history.index_requests[0]
    assert request.goal_id is None
    assert request.limit == 3
    assert application_fixture.history.trajectory_calls == 0
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("argv", "expected_title"),
    (
        (["backup-state", "--backup-id", "backup-one"], "LoopX State Backup"),
        (["upgrade-plan"], "LoopX Upgrade Plan"),
        (["registry"], "LoopX Registry"),
        (["registry-boundary"], "LoopX Registry Boundary"),
        (
            ["archive-runtime", "--goal-id", "goal-one"],
            "LoopX Runtime Archive",
        ),
        (
            ["migrate-state", "--goal-id", "goal-one", "--no-global-sync"],
            "LoopX State Migration",
        ),
    ),
)
def test_safe_batch_dispatches_only_through_typed_application_services(
    argv: list[str],
    expected_title: str,
    application_fixture: _Fixture,
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    exit_code = main(
        ["--registry", str(tmp_path / "registry.json"), "--format", "json", *argv],
        application_factory=lambda _args, _path: application_fixture.root,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert payload["title"] == expected_title
    assert "request" not in payload
    assert str(tmp_path) not in output.getvalue()


@pytest.mark.parametrize(
    ("argv", "expected_heading"),
    (
        (["backup-state", "--backup-id", "backup-one"], "# LoopX State Backup"),
        (["upgrade-plan"], "# LoopX Upgrade Plan"),
        (["registry"], "# LoopX Registry"),
        (["registry-boundary"], "# LoopX Registry Boundary"),
        (
            ["archive-runtime", "--goal-id", "goal-one"],
            "# LoopX Runtime Archive",
        ),
        (
            ["migrate-state", "--goal-id", "goal-one", "--no-global-sync"],
            "# LoopX State Migration",
        ),
    ),
)
def test_safe_batch_markdown_renders_the_typed_projection(
    argv: list[str],
    expected_heading: str,
    application_fixture: _Fixture,
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    exit_code = main(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            "--format",
            "markdown",
            *argv,
        ],
        application_factory=lambda _args, _path: application_fixture.root,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=output,
    )

    assert exit_code == 0
    assert output.getvalue().startswith(expected_heading)
    assert str(tmp_path) not in output.getvalue()


@pytest.mark.parametrize(
    "argv",
    (
        ["backup-state", "--backup-id", "backup-one", "--execute"],
        ["archive-runtime", "--goal-id", "goal-one", "--execute"],
        [
            "migrate-state",
            "--goal-id",
            "goal-one",
            "--no-global-sync",
            "--execute",
        ],
    ),
)
def test_writer_handlers_repreview_then_apply_without_a_pseudo_revision(
    argv: list[str],
    application_fixture: _Fixture,
    tmp_path: Path,
) -> None:
    output = io.StringIO()
    exit_code = main(
        ["--registry", str(tmp_path / "registry.json"), "--format", "json", *argv],
        application_factory=lambda _args, _path: application_fixture.root,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=output,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert payload["correctness"] == {
        "status": "pending_migration",
        "atomic_revision_check": False,
        "idempotent_retry": False,
    }

    if argv[0] == "backup-state":
        assert application_fixture.backup.preview_calls == 2
        assert application_fixture.backup.apply_calls == 1
    elif argv[0] == "archive-runtime":
        assert application_fixture.archive.execute_calls == 1
    else:
        assert application_fixture.migration.execute_calls == 1
