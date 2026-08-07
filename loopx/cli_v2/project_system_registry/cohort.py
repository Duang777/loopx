"""Frozen T7A safe-first-batch CLI registrar."""

from __future__ import annotations

from ..registrar import CohortRegistrar, CommandBinding, SelectorMatch
from .arguments import register_arguments
from .handlers import (
    handle_archive_runtime,
    handle_backup_state,
    handle_history_index_duplicates,
    handle_history_trajectory_hygiene,
    handle_migrate_state,
    handle_project_skill_install_preview,
    handle_project_skill_status,
    handle_project_skill_uninstall_preview,
    handle_registry,
    handle_registry_boundary,
    handle_upgrade_plan,
)


def _selector(dest: str, value: str) -> tuple[SelectorMatch, ...]:
    return (SelectorMatch(dest=dest, value=value),)


PROJECT_SYSTEM_REGISTRY_COHORT = CohortRegistrar(
    cohort_id="project-system-registry",
    register_arguments=register_arguments,
    bindings=(
        CommandBinding(
            command="backup-state",
            application_operation=(
                "application.system.backup.preview|application.system.backup.apply"
            ),
            handler=handle_backup_state,
        ),
        CommandBinding(
            command="upgrade-plan",
            application_operation="application.system.upgrades.plan",
            handler=handle_upgrade_plan,
        ),
        CommandBinding(
            command="registry",
            application_operation="application.registry.inspect",
            handler=handle_registry,
        ),
        CommandBinding(
            command="registry-boundary",
            application_operation="application.registry.inspect_boundary",
            handler=handle_registry_boundary,
        ),
        CommandBinding(
            command="archive-runtime",
            application_operation=(
                "application.system.runtime_archive.preview|"
                "application.system.runtime_archive.apply"
            ),
            handler=handle_archive_runtime,
        ),
        CommandBinding(
            command="migrate-state",
            application_operation=(
                "application.system.state_migration.preview|"
                "application.system.state_migration.apply"
            ),
            handler=handle_migrate_state,
        ),
        CommandBinding(
            command="project-skill",
            selectors=_selector("project_skill_command", "status"),
            application_operation="application.projects.skills.inspect",
            handler=handle_project_skill_status,
        ),
        CommandBinding(
            command="project-skill",
            selectors=_selector("project_skill_command", "install"),
            application_operation=("application.projects.skills.install.preview"),
            handler=handle_project_skill_install_preview,
        ),
        CommandBinding(
            command="project-skill",
            selectors=_selector("project_skill_command", "uninstall"),
            application_operation=("application.projects.skills.uninstall.preview"),
            handler=handle_project_skill_uninstall_preview,
        ),
        CommandBinding(
            command="history",
            selectors=_selector("history_action", "inspect-index-duplicates"),
            application_operation=(
                "application.system.history.inspect_index_duplicates"
            ),
            handler=handle_history_index_duplicates,
        ),
        CommandBinding(
            command="history",
            selectors=_selector("history_action", "trajectory-hygiene"),
            application_operation="application.system.history.trajectory_hygiene",
            handler=handle_history_trajectory_hygiene,
        ),
    ),
)
