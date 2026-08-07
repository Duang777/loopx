"""Explicit CLI projections for T7A typed Application DTOs."""

from __future__ import annotations

from loopx.application.registry import (
    RegistryBoundaryResult,
    RegistryInspectionResult,
)
from loopx.application.projects import (
    ProjectSkillPreviewResult,
    ProjectSkillStatusResult,
)
from loopx.application.system import (
    IndexDuplicateInspectionResult,
    MigrationCopyProjection,
    RuntimeArchivePlan,
    RuntimeArchiveResult,
    StateBackupApplyResult,
    StateBackupPlan,
    StateMigrationPlan,
    StateMigrationResult,
    UpgradePlanResult,
    TrajectoryHygieneResult,
)
from loopx.application import WriteCorrectness


def backup_plan_payload(plan: StateBackupPlan) -> dict[str, object]:
    return {
        "title": "LoopX State Backup",
        "ok": plan.can_apply,
        "schema_version": "loopx_state_backup_application_v1",
        "mode": "state_backup",
        "dry_run": True,
        "execute_requested": False,
        "backup_id": plan.backup_id,
        "included": [
            {
                "key": item.key,
                "archive_path": item.archive_path,
                "stats": {
                    "paths": item.path_count,
                    "files": item.file_count,
                    "directories": item.directory_count,
                    "symlinks": item.symlink_count,
                    "bytes": item.byte_count,
                },
            }
            for item in plan.targets
        ],
        "summary": {
            "included_target_count": len(plan.targets),
            "missing_target_count": plan.missing_target_count,
            "warning_count": plan.warning_count,
            "logical_source_bytes": plan.logical_source_bytes,
        },
        "correctness": _correctness(plan.correctness),
    }


def backup_result_payload(result: StateBackupApplyResult) -> dict[str, object]:
    return {
        "title": "LoopX State Backup",
        "ok": result.written,
        "schema_version": "loopx_state_backup_application_v1",
        "mode": "state_backup",
        "dry_run": False,
        "execute_requested": True,
        "backup_id": result.backup_id,
        "written": result.written,
        "target_count": result.target_count,
        "archive_sha256": result.archive_sha256,
        "archive_size_bytes": result.archive_size_bytes,
        "warning_count": result.warning_count,
        "correctness": _correctness(result.correctness),
    }


def upgrade_plan_payload(result: UpgradePlanResult) -> dict[str, object]:
    return {
        "title": "LoopX Upgrade Plan",
        "ok": True,
        "schema_version": "loopx_upgrade_plan_application_v1",
        "mode": "upgrade-plan",
        "summary": {
            "managed_goal_count": result.managed_goal_count,
            "current_prompt_count": result.current_prompt_count,
            "stale_prompt_count": result.stale_prompt_count,
            "unknown_prompt_count": result.unknown_prompt_count,
            "not_installed_prompt_count": result.not_installed_prompt_count,
            "stage_deferred_goal_count": result.stage_deferred_goal_count,
            "installed_manifest_available": result.installed_manifest_available,
            "installed_manifest_entry_count": result.installed_manifest_entry_count,
            "installed_prompt_policy_warning_count": result.policy_warning_count,
            "host_loop_missing_goal_count": result.host_loop_missing_goal_count,
            "peer_runtime_automation_migration_count": (
                result.peer_runtime_migration_count
            ),
            "ready_for_default_promotion": result.ready_for_default_promotion,
        },
        "managed_heartbeats": [
            {
                "goal_id": item.goal_id,
                "requires_update": item.requires_update,
                "registered_agent_count": item.registered_agent_count,
                "host_loop_status": item.host_loop_status,
                "peer_runtime_migration_required": (
                    item.peer_runtime_migration_required
                ),
            }
            for item in result.managed_goals
        ],
        "recommended_action": result.recommended_action,
    }


def registry_payload(result: RegistryInspectionResult) -> dict[str, object]:
    return {
        "title": "LoopX Registry",
        "ok": result.ok,
        "schema_version": result.schema_version,
        "goal_count": result.goal_count,
        "status_counts": dict(result.status_counts),
        "problem_codes": list(result.problem_codes),
        "goals": [
            {
                "id": item.goal_id,
                "domain": item.domain,
                "status": item.status,
                "repo_exists": item.repo_exists,
                "state_file_exists": item.state_file_exists,
                "adapter_kind": item.adapter_kind,
                "adapter_status": item.adapter_status,
                "authority_source_count": item.authority_source_count,
            }
            for item in result.goals
        ],
    }


def registry_boundary_payload(result: RegistryBoundaryResult) -> dict[str, object]:
    return {
        "title": "LoopX Registry Boundary",
        "ok": result.ok,
        "schema_version": "loopx_registry_boundary_application_v1",
        "path_label": result.path_label,
        "exists": result.exists,
        "classification": result.classification,
        "boundary_kind": result.boundary_kind,
        "goal_count": result.goal_count,
        "authority_source_count": result.authority_source_count,
        "private_marker_count": result.private_marker_count,
        "git": {
            "available": result.git_available,
            "inside_worktree": result.inside_worktree,
            "tracked": result.tracked,
            "ignored": result.ignored,
        },
        "should_be_gitignored": result.should_be_gitignored,
        "github_push_allowed": result.github_push_allowed,
        "risks": list(result.risks),
    }


def runtime_archive_plan_payload(plan: RuntimeArchivePlan) -> dict[str, object]:
    return {
        "title": "LoopX Runtime Archive",
        "ok": plan.can_apply,
        "schema_version": "loopx_runtime_archive_application_v1",
        "goal_id": plan.goal_id,
        "dry_run": True,
        "registry_member": plan.registry_member,
        "archived": False,
        "correctness": _correctness(plan.correctness),
    }


def runtime_archive_result_payload(
    result: RuntimeArchiveResult,
) -> dict[str, object]:
    return {
        "title": "LoopX Runtime Archive",
        "ok": result.archived,
        "schema_version": "loopx_runtime_archive_application_v1",
        "goal_id": result.goal_id,
        "dry_run": False,
        "registry_member": result.registry_member,
        "archived": result.archived,
        "archive_name": result.archive_name,
        "correctness": _correctness(result.correctness),
    }


def state_migration_plan_payload(plan: StateMigrationPlan) -> dict[str, object]:
    return {
        "title": "LoopX State Migration",
        "ok": plan.can_apply,
        "schema_version": "loopx_state_migration_application_v1",
        "dry_run": True,
        "execute": False,
        "selected_goal_ids": list(plan.selected_goal_ids),
        "migrated_goal_ids": list(plan.migrated_goal_ids),
        "project_registry_goal_count": plan.target_registry_goal_count,
        "active_state": _copy_projection(plan.active_state),
        "runtime_goals": _copy_projection(plan.runtime_goals),
        "correctness": _correctness(plan.correctness),
    }


def state_migration_result_payload(
    result: StateMigrationResult,
) -> dict[str, object]:
    return {
        "title": "LoopX State Migration",
        "ok": result.wrote_project_registry and not result.partial_global_sync,
        "schema_version": "loopx_state_migration_application_v1",
        "dry_run": False,
        "execute": True,
        "migrated_goal_ids": list(result.migrated_goal_ids),
        "wrote_project_registry": result.wrote_project_registry,
        "active_state": _copy_projection(result.active_state),
        "runtime_goals": _copy_projection(result.runtime_goals),
        "global_sync": {
            "attempted_count": result.global_sync_attempted_count,
            "verified": result.global_sync_verified,
            "partial": result.partial_global_sync,
        },
        "correctness": _correctness(result.correctness),
    }


def project_skill_status_payload(
    result: ProjectSkillStatusResult,
) -> dict[str, object]:
    return {
        "title": "LoopX Project Skill",
        "ok": True,
        "schema_version": "loopx_project_skill_status_application_v1",
        "skill_id": result.skill_id,
        "source_label": result.source_label,
        "source_digest": result.source_digest,
        "project_connected": result.project_connected,
        "status": result.aggregate_status,
        "managed": result.managed,
        "surfaces": [
            {
                "surface": item.surface,
                "target_label": item.target_label,
                "status": item.status,
                "managed": item.managed,
                "target_exists": item.target_exists,
                "installed_digest": item.installed_digest,
                "recorded_source_digest": item.recorded_source_digest,
                "installed_matches_source": item.installed_matches_source,
                "marker_matches_source": item.marker_matches_source,
            }
            for item in result.surfaces
        ],
    }


def project_skill_preview_payload(
    result: ProjectSkillPreviewResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": result.schema_version,
        "skill_id": result.skill_id,
        "delivery": result.delivery,
        "project": str(result.project),
        "project_connected": result.project_connected,
        "source": str(result.source),
        "source_digest": result.source_digest,
        "status": result.aggregate_status,
        "surfaces": [
            {
                "surface": item.surface,
                "target": str(item.target),
                "status": item.status,
                "managed": item.managed,
                "installed_digest": item.installed_digest,
                "recorded_source_digest": item.recorded_source_digest,
            }
            for item in result.surfaces
        ],
        "managed": result.managed,
    }
    if len(result.surfaces) == 1:
        surface = result.surfaces[0]
        payload.update(
            {
                "surface": surface.surface,
                "target": str(surface.target),
                "installed_digest": surface.installed_digest,
                "recorded_source_digest": surface.recorded_source_digest,
            }
        )
    payload.update(
        {
            "operation": result.action,
            "mode": result.mode,
            "changed": result.changed,
            "changed_surfaces": list(result.changed_surfaces),
        }
    )
    return payload


def index_duplicate_inspection_payload(
    result: IndexDuplicateInspectionResult,
) -> dict[str, object]:
    return {
        "title": "LoopX History Index Duplicate Inspection",
        "ok": True,
        "schema_version": "loopx_history_index_duplicates_application_v1",
        "goal_filter": result.goal_filter,
        "checked_goal_count": result.checked_goal_count,
        "raw_index_record_count": result.raw_index_record_count,
        "duplicate_group_count": result.duplicate_group_count,
        "duplicate_row_count": result.duplicate_row_count,
        "groups": [
            {
                "goal_id": item.goal_id,
                "duplicate_kind": item.duplicate_kind,
                "severity": item.severity,
                "raw_row_count": item.raw_row_count,
                "duplicate_row_count": item.duplicate_row_count,
                "line_count": item.line_count,
                "reward_overlay_row_count": item.reward_overlay_row_count,
                "classification_count": item.classification_count,
                "json_artifact_available": item.json_artifact_available,
                "markdown_artifact_available": item.markdown_artifact_available,
            }
            for item in result.groups
        ],
        "truncated": result.truncated,
        "limit": result.limit,
    }


def trajectory_hygiene_payload(
    result: TrajectoryHygieneResult,
) -> dict[str, object]:
    return {
        "title": "LoopX Trajectory Hygiene",
        "ok": True,
        "schema_version": "loopx_trajectory_hygiene_application_v1",
        "goal_filter": result.goal_filter,
        "sample": {
            "compact_history_row_count": result.compact_history_row_count,
            "goal_count": result.goal_count,
            "source": result.source,
        },
        "channel_counts": {item.channel: item.count for item in result.channel_counts},
        "metrics": {
            "controller_event_ratio": result.metrics.controller_event_ratio,
            "compact_controller_char_ratio": (
                result.metrics.compact_controller_char_ratio
            ),
            "non_material_event_ratio": result.metrics.non_material_event_ratio,
            "learning_candidate_count": result.metrics.learning_candidate_count,
            "learning_action_coverage": result.metrics.learning_action_coverage,
            "learning_outcome_coverage": result.metrics.learning_outcome_coverage,
            "decision_anchor_coverage": result.metrics.decision_anchor_coverage,
            "duplicate_learning_action_ratio": (
                result.metrics.duplicate_learning_action_ratio
            ),
        },
        "training_boundary": {
            "raw_session_read": result.training_boundary.raw_session_read,
            "raw_trajectory_read": result.training_boundary.raw_trajectory_read,
            "run_artifact_read": result.training_boundary.run_artifact_read,
            "compact_index_only": result.training_boundary.compact_index_only,
            "seed_model_training_eligible": (
                result.training_boundary.seed_model_training_eligible
            ),
        },
    }


def _copy_projection(value: MigrationCopyProjection) -> dict[str, object]:
    return {
        "selected_count": value.selected_count,
        "copy_requested": value.copy_requested,
        "copied_count": value.copied_count,
        "skipped_count": value.skipped_count,
    }


def _correctness(value: WriteCorrectness) -> dict[str, object]:
    return {
        "status": value.status,
        "atomic_revision_check": value.atomic_revision_check,
        "idempotent_retry": value.idempotent_retry,
    }
