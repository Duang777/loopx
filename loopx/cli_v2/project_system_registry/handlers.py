"""Typed CLI v2 handlers for the safe first T7A batch."""

from __future__ import annotations

import argparse
from pathlib import Path

from loopx.application import ApplicationError, WriteContext
from loopx.application.projects import ProjectSkillStatusRequest
from loopx.application.registry import RegistryBoundaryRequest
from loopx.application.system import (
    IndexDuplicateInspectionRequest,
    RuntimeArchiveRequest,
    StateBackupRequest,
    StateMigrationRequest,
    TrajectoryHygieneRequest,
    UpgradePlanRequest,
    parse_mapping_entries,
)

from ..registrar import CommandOutcome
from .application import require_application_root, require_project_services
from .payloads import (
    backup_plan_payload,
    backup_result_payload,
    index_duplicate_inspection_payload,
    project_skill_status_payload,
    project_skill_preview_payload,
    registry_boundary_payload,
    registry_payload,
    runtime_archive_plan_payload,
    runtime_archive_result_payload,
    state_migration_plan_payload,
    state_migration_result_payload,
    trajectory_hygiene_payload,
    upgrade_plan_payload,
)


def handle_backup_state(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    request = StateBackupRequest(
        project=Path(args.project),
        runtime_root=Path(args.runtime_root) if args.runtime_root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        backup_id=args.backup_id,
        include_automations=not bool(args.no_automations),
        include_skills=not bool(args.no_skills),
        include_registry_projects=not bool(args.current_project_only),
    )
    plan = root.system.backup.preview(request)
    if not args.execute:
        payload = backup_plan_payload(plan)
        return CommandOutcome(payload=payload, exit_code=0 if plan.can_apply else 1)
    result = root.system.backup.apply(
        plan,
        write_context=_write_context(
            operation="application.system.backup.apply",
            plan_hash=plan.plan_hash,
        ),
    )
    payload = backup_result_payload(result)
    return CommandOutcome(payload=payload, exit_code=0 if result.written else 1)


def handle_upgrade_plan(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.system.upgrades.plan(
        UpgradePlanRequest(
            goal_ids=tuple(args.goal_id),
            installed_manifest=(
                Path(args.installed_manifest) if args.installed_manifest else None
            ),
            cli_bin=args.cli_bin,
            modes=tuple(args.mode),
        )
    )
    return CommandOutcome(payload=upgrade_plan_payload(result))


def handle_registry(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    del args
    root = require_application_root(application)
    result = root.registry.inspection.inspect()
    return CommandOutcome(
        payload=registry_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_registry_boundary(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.registry.inspection.inspect_boundary(
        RegistryBoundaryRequest(
            path=Path(args.path) if args.path else None,
            require_not_tracked=bool(args.require_not_tracked),
            require_gitignored=bool(args.require_gitignored),
        )
    )
    return CommandOutcome(
        payload=registry_boundary_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_archive_runtime(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    plan = root.system.runtime_archive.preview(
        RuntimeArchiveRequest(
            goal_id=args.goal_id,
            archive_root=Path(args.archive_root) if args.archive_root else None,
            allow_registered=bool(args.allow_registered),
        )
    )
    if not args.execute:
        payload = runtime_archive_plan_payload(plan)
        return CommandOutcome(payload=payload, exit_code=0 if plan.can_apply else 1)
    result = root.system.runtime_archive.apply(
        plan,
        write_context=_write_context(
            operation="application.system.runtime_archive.apply",
            plan_hash=plan.plan_hash,
        ),
    )
    payload = runtime_archive_result_payload(result)
    return CommandOutcome(payload=payload, exit_code=0 if result.archived else 1)


def handle_migrate_state(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    request = StateMigrationRequest(
        legacy_registry=Path(args.legacy_registry),
        legacy_runtime_root=Path(args.legacy_runtime_root),
        target_runtime_root=(
            Path(args.target_runtime_root) if args.target_runtime_root else None
        ),
        goal_ids=tuple(args.goal_id or ()),
        all_goals=bool(args.all_goals),
        goal_id_map=parse_mapping_entries(tuple(args.goal_id_map), field="goal_id_map"),
        path_map=parse_mapping_entries(tuple(args.path_map), field="path_map"),
        copy_active_state=bool(args.copy_active_state),
        copy_runtime=bool(args.copy_runtime),
        sync_global=not bool(args.no_global_sync),
    )
    plan = root.system.state_migration.preview(request)
    if not args.execute:
        payload = state_migration_plan_payload(plan)
        return CommandOutcome(payload=payload, exit_code=0 if plan.can_apply else 1)
    result = root.system.state_migration.apply(
        plan,
        write_context=_write_context(
            operation="application.system.state_migration.apply",
            plan_hash=plan.plan_hash,
        ),
    )
    payload = state_migration_result_payload(result)
    ok = result.wrote_project_registry and not result.partial_global_sync
    return CommandOutcome(payload=payload, exit_code=0 if ok else 1)


def handle_project_skill_status(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    projects = require_project_services(application)
    result = projects.skills.inspect(
        ProjectSkillStatusRequest(
            project=Path(args.project),
            skill_id=args.skill,
            surfaces=tuple(args.surface or ("codex",)),
        )
    )
    return CommandOutcome(payload=project_skill_status_payload(result))


def handle_project_skill_install_preview(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    return _handle_project_skill_preview(
        args,
        application,
        action="install",
    )


def handle_project_skill_uninstall_preview(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    return _handle_project_skill_preview(
        args,
        application,
        action="uninstall",
    )


def _handle_project_skill_preview(
    args: argparse.Namespace,
    application: object,
    *,
    action: str,
) -> CommandOutcome:
    if bool(args.execute):
        return CommandOutcome(
            payload={
                "title": "LoopX CLI v2",
                "ok": False,
                "schema_version": "loopx_cli_v2_result_v1",
                "error": {
                    "code": "cli_v2_pending_migration",
                    "message": (
                        f"project-skill {action} --execute is not migrated; "
                        "the typed Application surface is preview-only."
                    ),
                    "details": {"command": f"project-skill {action}"},
                    "retryable": False,
                },
            },
            exit_code=2,
        )
    try:
        projects = require_project_services(application)
        request = ProjectSkillStatusRequest(
            project=Path(args.project),
            skill_id=args.skill,
            surfaces=tuple(args.surface or ("codex",)),
        )
        result = (
            projects.skills.preview_install(request)
            if action == "install"
            else projects.skills.preview_uninstall(request)
        )
    except ApplicationError as exc:
        return CommandOutcome(
            payload={
                "ok": False,
                "status": "blocked",
                "skill_id": args.skill,
                "error": str(exc),
                "surfaces": [],
            },
            exit_code=2,
        )
    return CommandOutcome(payload=project_skill_preview_payload(result))


def handle_history_index_duplicates(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.system.history_diagnostics.inspect_index_duplicates(
        IndexDuplicateInspectionRequest(
            goal_id=args.goal_id,
            limit=args.limit,
        )
    )
    return CommandOutcome(payload=index_duplicate_inspection_payload(result))


def handle_history_trajectory_hygiene(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.system.history_diagnostics.trajectory_hygiene(
        TrajectoryHygieneRequest(
            goal_id=args.goal_id,
            limit=args.limit,
        )
    )
    return CommandOutcome(payload=trajectory_hygiene_payload(result))


def _write_context(*, operation: str, plan_hash: str) -> WriteContext:
    digest = plan_hash.removeprefix("sha256:")
    return WriteContext(
        actor="loopx-cli-v2",
        idempotency_key=f"cli-v2:{operation}:{digest}",
        expected_revision=None,
    )
