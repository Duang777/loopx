"""Behavior-preserving argparse shapes for the first T7A command batch."""

from __future__ import annotations

import argparse

from loopx.application.projects import PROJECT_SKILL_SURFACES
from loopx.application.system import LEGACY_GLOBAL_REGISTRY, LEGACY_RUNTIME_ROOT
from loopx.cli_contract import add_subcommand_format


def register_arguments(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    _register_backup_state(subparsers)
    _register_upgrade_plan(subparsers)
    subparsers.add_parser(
        "registry",
        help="Inspect registry goals and adapter declarations.",
    )
    _register_registry_boundary(subparsers)
    _register_archive_runtime(subparsers)
    _register_migrate_state(subparsers)
    _register_project_skill(subparsers)
    _register_history_if_missing(subparsers)


def _register_backup_state(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "backup-state",
        help="Preview or create a private local archive of LoopX state.",
    )
    add_subcommand_format(parser)
    parser.add_argument("--project", default=".")
    parser.add_argument("--output-dir")
    parser.add_argument("--backup-id")
    parser.add_argument("--no-automations", action="store_true")
    parser.add_argument("--no-skills", action="store_true")
    parser.add_argument("--current-project-only", action="store_true")
    parser.add_argument("--execute", action="store_true")


def _register_upgrade_plan(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "upgrade-plan",
        help=(
            "Plan local default upgrade propagation for managed heartbeat "
            "automations."
        ),
    )
    add_subcommand_format(parser)
    parser.add_argument("--goal-id", action="append", default=[])
    parser.add_argument("--installed-manifest")
    parser.add_argument("--cli-bin", default="loopx")
    parser.add_argument(
        "--mode",
        action="append",
        choices=["thin", "brief", "compact"],
        default=[],
    )


def _register_registry_boundary(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "registry-boundary",
        help=(
            "Classify a registry file as local-only, global-local, public "
            "projection, or public fixture."
        ),
    )
    parser.add_argument("--path")
    parser.add_argument("--require-not-tracked", action="store_true")
    parser.add_argument("--require-gitignored", action="store_true")


def _register_archive_runtime(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "archive-runtime",
        help=(
            "Move an obsolete runtime goal directory into the archive area. "
            "Defaults to dry-run."
        ),
    )
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--archive-root")
    parser.add_argument("--allow-registered", action="store_true")
    parser.add_argument("--execute", action="store_true")


def _register_migrate_state(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "migrate-state",
        help=(
            "One-shot migration from a legacy Goal Harness registry/runtime "
            "into LoopX state."
        ),
    )
    parser.add_argument(
        "--legacy-registry",
        default=str(LEGACY_GLOBAL_REGISTRY),
    )
    parser.add_argument(
        "--legacy-runtime-root",
        default=str(LEGACY_RUNTIME_ROOT),
    )
    parser.add_argument("--target-runtime-root")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--goal-id", action="append")
    selector.add_argument("--all-goals", action="store_true")
    parser.add_argument("--goal-id-map", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--path-map", action="append", default=[], metavar="OLD=NEW")
    parser.add_argument("--copy-active-state", action="store_true")
    parser.add_argument("--copy-runtime", action="store_true")
    parser.add_argument("--no-global-sync", action="store_true")
    parser.add_argument("--execute", action="store_true")


def _register_project_skill(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "project-skill",
        help="Manage release-owned skills in project-local agent host directories.",
    )
    commands = parser.add_subparsers(dest="project_skill_command", required=True)
    for command in ("status", "install", "uninstall"):
        operation = commands.add_parser(command)
        operation.add_argument("--project", default=".")
        operation.add_argument("--skill", required=True)
        operation.add_argument(
            "--surface",
            action="append",
            choices=PROJECT_SKILL_SURFACES,
        )
        if command != "status":
            operation.add_argument("--execute", action="store_true")
        add_subcommand_format(operation)


def _register_history_if_missing(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    if "history" in subparsers.choices:
        return
    parser = subparsers.add_parser(
        "history",
        help="Read compact run history from the shared runtime root.",
    )
    parser.add_argument(
        "history_action",
        nargs="?",
        choices=[
            "append-benchmark-run",
            "append-benchmark-result",
            "append-benchmark-comparison",
            "append-benchmark-learning-ledger",
            "append-benchmark-report",
            "append-agents-last-exam-result-report",
            "append-active-user-assisted-pilot",
            "inspect-index-duplicates",
            "repair-index-duplicates",
            "rebuild-index-collisions",
            "trajectory-hygiene",
        ],
    )
    parser.add_argument("--goal-id")
    parser.add_argument("--limit", type=int, default=10)
    for option in (
        "benchmark-run-json",
        "benchmark-result-json",
        "benchmark-comparison-json",
        "benchmark-learning-ledger-json",
        "benchmark-report-json",
        "agents-last-exam-run-dir",
        "report-id",
        "active-user-pilot-json",
        "review-plan-json",
        "classification",
        "recommended-action",
    ):
        parser.add_argument(f"--{option}")
    parser.add_argument(
        "--delivery-batch-scale",
        choices=("test_only", "single_surface", "multi_surface", "implementation"),
    )
    parser.add_argument(
        "--delivery-outcome",
        choices=(
            "surface_only",
            "outcome_gap",
            "outcome_progress",
            "primary_goal_outcome",
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--no-global-sync", action="store_true")
