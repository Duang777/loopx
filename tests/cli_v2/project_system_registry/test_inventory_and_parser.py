from __future__ import annotations

import json
from pathlib import Path

from loopx import __version__
from loopx.cli import build_parser as build_legacy_parser
from loopx.cli_contract import build_root_parser
from loopx.cli_v2.project_system_registry import PROJECT_SYSTEM_REGISTRY_COHORT
from loopx.cli_v2.registrar import CommandRegistry


REPOSITORY_ROOT = Path(__file__).parents[3]
SHARD_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "cli_v2_parity"
    / "project-system-registry.json"
)
WIRED_COMMANDS = {
    "backup-state": (
        "application.system.backup.preview|application.system.backup.apply"
    ),
    "upgrade-plan": "application.system.upgrades.plan",
    "registry": "application.registry.inspect",
    "registry-boundary": "application.registry.inspect_boundary",
    "archive-runtime": (
        "application.system.runtime_archive.preview|"
        "application.system.runtime_archive.apply"
    ),
    "migrate-state": (
        "application.system.state_migration.preview|"
        "application.system.state_migration.apply"
    ),
    "project-skill status": "application.projects.skills.inspect",
    "project-skill install": "application.projects.skills.install.preview",
    "project-skill uninstall": "application.projects.skills.uninstall.preview",
    "history inspect-index-duplicates": (
        "application.system.history.inspect_index_duplicates"
    ),
    "history trajectory-hygiene": ("application.system.history.trajectory_hygiene"),
}


def _cohort_parser():
    parser, subparsers = build_root_parser(
        description="T7A parser parity fixture",
        version=f"loopx {__version__}",
    )
    PROJECT_SYSTEM_REGISTRY_COHORT.register_arguments(subparsers)
    return parser


def test_safe_batches_registry_has_exactly_eleven_typed_bindings() -> None:
    registry = CommandRegistry((PROJECT_SYSTEM_REGISTRY_COHORT,))
    actual = {
        _binding_label(binding): binding.application_operation
        for binding in registry.bindings
    }
    assert actual == WIRED_COMMANDS


def _binding_label(binding) -> str:
    if not binding.selectors:
        return binding.command
    assert len(binding.selectors) == 1
    return f"{binding.command} {binding.selectors[0].value}"


def test_selected_argparse_namespaces_match_legacy_contract() -> None:
    legacy = build_legacy_parser()
    cohort = _cohort_parser()
    cases = (
        ["backup-state"],
        [
            "backup-state",
            "--project",
            "project",
            "--output-dir",
            "out",
            "--backup-id",
            "backup-one",
            "--no-automations",
            "--no-skills",
            "--current-project-only",
            "--execute",
            "--format",
            "json",
        ],
        ["upgrade-plan"],
        [
            "upgrade-plan",
            "--goal-id",
            "goal-one",
            "--installed-manifest",
            "manifest.json",
            "--cli-bin",
            "loopx-dev",
            "--mode",
            "brief",
            "--mode",
            "compact",
            "--format",
            "json",
        ],
        ["registry"],
        [
            "registry-boundary",
            "--path",
            "registry.json",
            "--require-not-tracked",
            "--require-gitignored",
        ],
        [
            "archive-runtime",
            "--goal-id",
            "goal-one",
            "--archive-root",
            "archive",
            "--allow-registered",
            "--execute",
        ],
        ["migrate-state", "--goal-id", "goal-one"],
        [
            "migrate-state",
            "--all-goals",
            "--legacy-registry",
            "legacy.json",
            "--legacy-runtime-root",
            "legacy-runtime",
            "--target-runtime-root",
            "target-runtime",
            "--goal-id-map",
            "old=new",
            "--path-map",
            "before=after",
            "--copy-active-state",
            "--copy-runtime",
            "--no-global-sync",
            "--execute",
        ],
        [
            "project-skill",
            "status",
            "--project",
            "project",
            "--skill",
            "loopx-material",
            "--surface",
            "codex",
            "--surface",
            "claude-code",
            "--format",
            "json",
        ],
        [
            "project-skill",
            "install",
            "--project",
            "project",
            "--skill",
            "loopx-material",
            "--surface",
            "codex",
            "--execute",
            "--format",
            "json",
        ],
        [
            "project-skill",
            "uninstall",
            "--project",
            "project",
            "--skill",
            "loopx-material",
            "--surface",
            "claude-code",
            "--format",
            "json",
        ],
        [
            "history",
            "inspect-index-duplicates",
            "--goal-id",
            "goal-one",
            "--limit",
            "4",
        ],
        [
            "history",
            "trajectory-hygiene",
            "--goal-id",
            "goal-one",
            "--limit",
            "5",
        ],
    )
    ignored = {"registry"}
    for argv in cases:
        legacy_values = {
            key: value
            for key, value in vars(legacy.parse_args(argv)).items()
            if key not in ignored
        }
        cohort_values = {
            key: value
            for key, value in vars(cohort.parse_args(argv)).items()
            if key not in ignored
        }
        assert cohort_values == legacy_values, argv


def test_safe_batch_manifest_truthfully_keeps_external_parity_pending() -> None:
    payload = json.loads(SHARD_PATH.read_text(encoding="utf-8"))
    rows = {
        row["command"]: {**payload["defaults"], **row} for row in payload["commands"]
    }
    for command, operation in WIRED_COMMANDS.items():
        row = rows[command]
        assert row["application_operation"] == operation
        assert row["migration_status"] == "pending_migration"
        assert "success" in row["scenario_coverage"]
        assert {"json", "stdout", "exit_code"} <= set(row["output_coverage"])
        if command.startswith("project-skill ") and command != "project-skill status":
            assert "stderr" in row["output_coverage"]
            assert (
                "preview_external_parity_passed; execute_and_markdown_pending"
                in row["evidence"]
            )
        else:
            assert "markdown" in row["output_coverage"]
            assert (
                "typed_semantics_passed; full_external_parity_missing"
                in row["evidence"]
            )
