from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from loopx import __version__
from loopx.cli import build_parser as build_legacy_parser
from loopx.cli_contract import build_root_parser
from loopx.cli_v2.capability_extension_presentation import (
    CAPABILITY_EXTENSION_PRESENTATION_COHORT,
)
from loopx.cli_v2.registrar import CommandRegistry


REPOSITORY_ROOT = Path(__file__).parents[3]
SHARD_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "cli_v2_parity"
    / "capability-extension-presentation.json"
)
OWNER_BY_TOP_LEVEL = {
    "capability": "loopx/cli_commands/capability.py",
    "extension": "loopx/cli_commands/extension.py",
    "content-ops": "loopx/capabilities/content_ops/cli.py",
    "decision-context": "loopx/capabilities/decision_context/cli.py",
    "material-lifecycle": "loopx/capabilities/material_lifecycle/cli.py",
    "reward-memory": "loopx/capabilities/reward_memory/cli.py",
    "periodic-report": "loopx/capabilities/periodic_report/cli.py",
    "semantic-preference": "loopx/capabilities/semantic_preference/cli.py",
    "value-connectors": "loopx/capabilities/value_connectors/cli.py",
    "presentation": "loopx/cli_commands/presentation.py",
    "lark-inbox": "loopx/cli_commands/lark_inbox.py",
    "lark-kanban": "loopx/cli_commands/lark_kanban.py",
    "explore": "loopx/cli_commands/explore.py",
}
EXPECTED_COUNTS = {
    "capability": 2,
    "extension": 9,
    "content-ops": 11,
    "decision-context": 4,
    "material-lifecycle": 4,
    "reward-memory": 10,
    "periodic-report": 4,
    "semantic-preference": 5,
    "value-connectors": 5,
    "presentation": 3,
    "lark-inbox": 8,
    "lark-kanban": 12,
    "explore": 14,
}
WIRED_COMMANDS = {
    "capability list": "application.capabilities.catalog.list",
    "capability show": "application.capabilities.catalog.get",
    "content-ops exploration-plan": (
        "application.capabilities.content_ops.exploration_plan"
    ),
    "content-ops walkthrough-artifact": (
        "application.capabilities.content_ops.walkthrough_artifact"
    ),
    "content-ops item-create": (
        "application.capabilities.content_ops.create_item"
    ),
    "decision-context architecture": (
        "application.capabilities.decision_context.describe_architecture"
    ),
    "decision-context inspect-profile": (
        "application.capabilities.decision_context.inspect_profile"
    ),
    "material-lifecycle architecture": (
        "application.capabilities.material_lifecycle.describe_architecture"
    ),
    "material-lifecycle skill-status": (
        "application.capabilities.material_lifecycle.inspect_skill"
    ),
    "reward-memory health-check": (
        "application.capabilities.reward_memory.health"
    ),
    "reward-memory corpus-registry": (
        "application.capabilities.reward_memory.corpus_registry"
    ),
    "reward-memory candidate-review": (
        "application.capabilities.reward_memory.candidate_review"
    ),
    "reward-memory route-check": "application.capabilities.reward_memory.route",
    "semantic-preference receipt": (
        "application.capabilities.semantic_preference.application_receipt"
    ),
    "semantic-preference maintenance-receipt": (
        "application.capabilities.semantic_preference.maintenance_receipt"
    ),
    "value-connectors install-check": (
        "application.capabilities.value_connectors.install_check"
    ),
    "value-connectors source-map": (
        "application.capabilities.value_connectors.source_map"
    ),
    "extension init": "application.extensions.initialize",
    "extension list": "application.extensions.list",
    "extension install": "application.extensions.install",
    "extension upgrade": "application.extensions.upgrade",
    "extension enable": "application.extensions.enable",
    "extension disable": "application.extensions.disable",
    "extension rollback": "application.extensions.rollback",
    "extension doctor": "application.extensions.doctor",
    "extension run": "application.extensions.run",
    "presentation package": "application.presentations.package",
    "presentation rollback": "application.presentations.rollback",
    "presentation verify-readback": "application.presentations.verify_readback",
}
MIGRATED_COMMANDS = {
    "content-ops exploration-plan",
    "content-ops item-create",
    "content-ops walkthrough-artifact",
    "decision-context architecture",
    "decision-context inspect-profile",
    "material-lifecycle architecture",
}
SUCCESS_ONLY_MIGRATED_COMMANDS = {
    "decision-context architecture",
    "material-lifecycle architecture",
}


def _shard() -> dict[str, object]:
    return json.loads(SHARD_PATH.read_text(encoding="utf-8"))


def _cohort_parser():
    parser, subparsers = build_root_parser(
        description="T7B parser parity fixture",
        version=f"loopx {__version__}",
    )
    CAPABILITY_EXTENSION_PRESENTATION_COHORT.register_arguments(subparsers)
    return parser


def test_all_91_rows_have_one_durable_owner() -> None:
    rows = _shard()["commands"]
    assert isinstance(rows, list)
    assert len(rows) == 91
    prefixes = Counter(str(row["command"]).split()[0] for row in rows)
    assert prefixes == Counter(EXPECTED_COUNTS)
    assert set(prefixes) == set(OWNER_BY_TOP_LEVEL)
    for row in rows:
        owner = OWNER_BY_TOP_LEVEL[str(row["command"]).split()[0]]
        assert (REPOSITORY_ROOT / owner).is_file(), row["command"]


def test_first_four_batches_registry_is_exactly_the_29_owned_root_callsites() -> None:
    registry = CommandRegistry((CAPABILITY_EXTENSION_PRESENTATION_COHORT,))
    actual = {
        f"{binding.command} {binding.selectors[0].value}": (
            binding.application_operation
        )
        for binding in registry.bindings
    }
    assert actual == WIRED_COMMANDS


def test_manifest_truthfully_distinguishes_wired_and_owner_mapped_rows() -> None:
    shard = _shard()
    defaults = shard["defaults"]
    rows = {
        row["command"]: {**defaults, **row}
        for row in shard["commands"]
    }
    assert {
        command
        for command, row in rows.items()
        if row["migration_status"] == "migrated"
    } == MIGRATED_COMMANDS
    assert {
        command: row["application_operation"]
        for command, row in rows.items()
        if row["application_operation"] is not None
    } == WIRED_COMMANDS
    for command, operation in WIRED_COMMANDS.items():
        row = rows[command]
        assert operation == row["application_operation"]
        if command in MIGRATED_COMMANDS:
            assert row["migration_status"] == "migrated"
            assert row["state_side_effect_comparison"] is True
            assert {"json", "markdown", "stdout", "stderr", "exit_code"} <= set(
                row["output_coverage"]
            )
            assert "success" in row["scenario_coverage"]
            if command in SUCCESS_ONLY_MIGRATED_COMMANDS:
                assert row["scenario_coverage"] == ["success"]
                assert "no_legal_failure_surface" in row["evidence"]
            else:
                assert "error" in row["scenario_coverage"]
            assert (
                "typed_semantics_passed; cli_compatibility_view_missing"
                not in row["evidence"]
            )
        else:
            assert row["migration_status"] == "pending_migration"
            assert row["state_side_effect_comparison"] is False
            assert "typed_semantics_passed; cli_compatibility_view_missing" in row[
                "evidence"
            ]
            assert "json" in row["output_coverage"]
            assert "markdown" not in row["output_coverage"]
    assert all(
        row["application_operation"] is None
        for command, row in rows.items()
        if command not in WIRED_COMMANDS
    )
    assert all(
        row["migration_status"] == "pending"
        for command, row in rows.items()
        if command not in WIRED_COMMANDS
    )


def test_selected_argparse_namespaces_match_legacy_contract() -> None:
    legacy = build_legacy_parser()
    cohort = _cohort_parser()
    cases = (
        ["capability", "list", "--extension-manifest", "extension.json"],
        ["capability", "show", "issue-fix"],
        ["extension", "init", "sample", "--destination", "packages/sample"],
        ["extension", "list", "--state-file", "state.json"],
        ["extension", "install", "--manifest", "extension.json"],
        ["extension", "upgrade", "--manifest", "extension.json", "--execute"],
        ["extension", "enable", "sample"],
        ["extension", "disable", "sample", "--execute"],
        ["extension", "rollback", "sample"],
        ["extension", "doctor", "sample", "--execute"],
        ["extension", "run", "sample", "--input-json", "request.json"],
        [
            "presentation",
            "package",
            "--site-dir",
            "site",
            "--output-dir",
            "published",
            "--site-id",
            "demo",
            "--desktop-visual-check",
            "passed",
            "--mobile-visual-check",
            "passed",
            "--link-check",
            "passed",
        ],
        ["presentation", "rollback", "--output-dir", "published"],
        ["presentation", "verify-readback", "--output-dir", "published"],
        ["decision-context", "architecture"],
        [
            "decision-context",
            "inspect-profile",
            "--goal-id",
            "goal_fixture",
            "--agent-id",
            "agent_fixture",
        ],
        [
            "content-ops",
            "exploration-plan",
            "--scenario",
            "public_fixture",
        ],
        [
            "content-ops",
            "walkthrough-artifact",
            "--channel-count",
            "1",
            "--recent-record-count",
            "2",
            "--report-count",
            "3",
            "--api-request-count",
            "4",
            "--api-path-count",
            "/api/channels=1",
            "--theme-signal",
            "agent workflows",
        ],
        [
            "content-ops",
            "item-create",
            "--item-id",
            "item_fixture",
            "--item-kind",
            "post",
            "--channel",
            "x_public",
            "--content-digest",
            "sha256:" + "a" * 64,
            "--content-ref",
            "artifact:fixture",
            "--source-ref",
            "source_fixture",
            "--created-at",
            "2026-06-23T00:00:00+00:00",
        ],
        ["material-lifecycle", "architecture"],
        ["material-lifecycle", "skill-status", "--project", "."],
        ["reward-memory", "health-check", "--case", "empty"],
        ["reward-memory", "corpus-registry"],
        [
            "reward-memory",
            "candidate-review",
            "--decision",
            "edit",
        ],
        [
            "reward-memory",
            "route-check",
            "--case",
            "pr-3237",
        ],
        [
            "semantic-preference",
            "receipt",
            "--surface",
            "pr_review.reply",
            "--application-id",
            "application:fixture",
            "--outcome",
            "applied",
            "--preference-ref",
            "preference:fixture",
        ],
        [
            "semantic-preference",
            "maintenance-receipt",
            "--trigger",
            "explicit_feedback",
            "--outcome",
            "verified",
            "--corpus-id",
            "fixture_corpus",
        ],
        [
            "value-connectors",
            "install-check",
            "--connector",
            "github_public_channel",
        ],
        [
            "value-connectors",
            "source-map",
            "--connector",
            "github_public_channel",
        ],
    )
    ignored = {"registry", "capability_operation_parser"}
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
