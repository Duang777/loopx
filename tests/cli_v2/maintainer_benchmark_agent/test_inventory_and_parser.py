from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from loopx import __version__
from loopx.cli import build_parser as build_legacy_parser
from loopx.cli_contract import build_root_parser
from loopx.cli_v2.maintainer_benchmark_agent import (
    MAINTAINER_BENCHMARK_AGENT_COHORT,
)
from loopx.cli_v2.registrar import CommandRegistry


REPOSITORY_ROOT = Path(__file__).parents[3]
SHARD_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "cli_v2_parity"
    / "maintainer-benchmark-agent.json"
)
OWNER_COUNTS = Counter(
    {"agent": 49, "canary": 15, "benchmark": 49, "maintenance": 24}
)
RISK_COUNTS = Counter({"R0": 12, "R1": 69, "R2": 18, "R3": 38})
WIRED_COMMANDS = {
    "worker-bridge contract": "application.agents.worker_bridge.contract",
    "worker-bridge outcome": "application.agents.worker_bridge.outcome",
    "worker-bridge active-user-intervention": (
        "application.agents.worker_bridge.active_user_intervention"
    ),
    "worker-bridge active-user-simulator-output": (
        "application.agents.worker_bridge.active_user_simulator_output"
    ),
    "canary profiles": "application.maintenance.canary.profiles",
    "canary smoke-profiles": "application.maintenance.canary.smoke_profiles",
    "benchmark split-control-execution-seam": (
        "application.benchmarks.split_control.execution_seam"
    ),
    "benchmark parity-check": (
        "application.benchmarks.inspection.parity_check"
    ),
    "benchmark classify-artifacts": (
        "application.benchmarks.inspection.classify_artifacts"
    ),
    "benchmark candidate-source-boundary": (
        "application.benchmarks.inspection.candidate_source_boundary"
    ),
}
EXTERNAL_CORE_BINDINGS = {
    "turn plan": "goal.turn.plan",
    "turn run-once": "goal.turn.run_once",
}
SECOND_BATCH_COMMANDS = {
    "worker-bridge active-user-intervention",
    "worker-bridge active-user-simulator-output",
    "benchmark parity-check",
    "benchmark classify-artifacts",
    "benchmark candidate-source-boundary",
}
DEPTH_CLOSED_COMMANDS = {
    "benchmark candidate-source-boundary",
    "benchmark classify-artifacts",
    "benchmark parity-check",
    "worker-bridge active-user-intervention",
    "worker-bridge contract",
    "worker-bridge outcome",
}
SUCCESS_ONLY_DEPTH_CLOSED_COMMANDS = {"worker-bridge contract"}
EVIDENCE = re.compile(
    r"^owner=(agent|canary|benchmark|maintenance); "
    r"side_effect_risk=(R[0-3]):"
    r"(pure_builder|bounded_read_or_fixture|local_state_write|"
    r"external_process_network_repo_or_job); legacy_callsite=(loopx(?:\.[a-z_]+)+)$"
)


def _shard() -> dict[str, object]:
    return json.loads(SHARD_PATH.read_text(encoding="utf-8"))


def _cohort_parser():
    parser, subparsers = build_root_parser(
        description="T7C parser parity fixture",
        version=f"loopx {__version__}",
    )
    MAINTAINER_BENCHMARK_AGENT_COHORT.register_arguments(subparsers)
    return parser


def test_all_137_rows_have_durable_owner_risk_and_legacy_callsite_evidence() -> None:
    rows = _shard()["commands"]
    assert isinstance(rows, list)
    assert len(rows) == 137
    owners: Counter[str] = Counter()
    risks: Counter[str] = Counter()
    for row in rows:
        evidence = row.get("evidence")
        assert isinstance(evidence, list) and evidence, row["command"]
        match = EVIDENCE.fullmatch(str(evidence[0]))
        assert match, row["command"]
        owner, risk, _label, callsite = match.groups()
        owners[owner] += 1
        risks[risk] += 1
        module_path = REPOSITORY_ROOT / (callsite.replace(".", "/") + ".py")
        assert module_path.is_file(), (row["command"], module_path)
    assert owners == OWNER_COUNTS
    assert risks == RISK_COUNTS


def test_typed_manifest_rows_cover_cohort_and_external_core_bindings() -> None:
    registry = CommandRegistry((MAINTAINER_BENCHMARK_AGENT_COHORT,))
    actual = {
        f"{binding.command} {binding.selectors[0].value}": (
            binding.application_operation
        )
        for binding in registry.bindings
    }
    assert actual == WIRED_COMMANDS
    rows = {
        row["command"]: {**_shard()["defaults"], **row}
        for row in _shard()["commands"]
    }
    assert {
        command: row["application_operation"]
        for command, row in rows.items()
        if row["application_operation"] is not None
    } == {**WIRED_COMMANDS, **EXTERNAL_CORE_BINDINGS}
    for command, row in rows.items():
        if command not in WIRED_COMMANDS and command not in EXTERNAL_CORE_BINDINGS:
            assert row["migration_status"] == "pending"
            continue
        if command in EXTERNAL_CORE_BINDINGS:
            assert row["migration_status"] == "pending_migration"
            assert row["state_side_effect_comparison"] is False
            assert row["output_coverage"] == ["json", "stdout", "exit_code"]
            expected_scenarios = ["success"]
            if command == "turn run-once":
                expected_scenarios = ["success", "dry_run", "write"]
            assert row["scenario_coverage"] == expected_scenarios
            assert any(
                "legacy_external_differential_missing" in item
                for item in row["evidence"]
            )
            continue
        if command in DEPTH_CLOSED_COMMANDS:
            assert row["migration_status"] == "migrated"
            if command in SUCCESS_ONLY_DEPTH_CLOSED_COMMANDS:
                assert row["scenario_coverage"] == ["success"]
                assert "no_legal_failure_surface" in row["evidence"]
            else:
                assert row["scenario_coverage"] == ["success", "error"]
            assert row["output_coverage"] == [
                "json",
                "markdown",
                "stdout",
                "stderr",
                "exit_code",
            ]
            assert row["state_side_effect_comparison"] is True
            assert "typed_semantics_passed; cli_compatibility_view_missing" not in row[
                "evidence"
            ]
            assert "typed_semantics_and_cli_compatibility_passed" in row[
                "evidence"
            ]
            continue
        assert row["migration_status"] == "pending_migration"
        assert row["scenario_coverage"] == ["success"]
        expected_output = ["json", "stdout", "exit_code"]
        if command in SECOND_BATCH_COMMANDS:
            expected_output = ["json", "stdout", "stderr", "exit_code"]
        assert row["output_coverage"] == expected_output
        assert row["state_side_effect_comparison"] is True
        assert "typed_semantics_passed; cli_compatibility_view_missing" in row[
            "evidence"
        ]


def test_selected_argparse_namespaces_match_legacy_contract() -> None:
    legacy = build_legacy_parser()
    cohort = _cohort_parser()
    cases = (
        ["worker-bridge", "contract"],
        [
            "worker-bridge",
            "contract",
            "--project-root",
            "/workspace/loopx",
            "--runtime-root",
            "/runtime/loopx",
            "--python-bin",
            "python3",
            "--module",
            "loopx.cli",
            "--scan-path",
            "/workspace/loopx/loopx/benchmark.py",
            "--classification",
            "fixture",
        ],
        [
            "worker-bridge",
            "outcome",
            "--worker-cli-call-total",
            "2",
            "--counter-trace-present",
            "--runner-return-completed",
            "--official-score-completed",
            "--official-score-value",
            "1",
        ],
        [
            "worker-bridge",
            "active-user-intervention",
            "--seq",
            "7",
            "--message",
            "Inspect public evidence.",
            "--trigger",
            "public_progress_or_stall_signal",
            "--channel",
            "codex_cli_user_simulator",
            "--before-worker-start",
            "--jsonl",
        ],
        [
            "worker-bridge",
            "active-user-simulator-output",
            "--seq",
            "8",
            "--simulator-output-json",
            "simulator.json",
            "--before-worker-start",
            "--jsonl",
        ],
        ["canary", "profiles"],
        ["canary", "profiles", "--catalog", "catalog.md"],
        ["canary", "smoke-profiles"],
        [
            "benchmark",
            "split-control-execution-seam",
            "--readiness-json",
            "readiness.json",
            "--command-adapter-json",
            "adapters.json",
            "--execution-mode",
            "fixture_no_upload",
        ],
        [
            "benchmark",
            "parity-check",
            "--benchmark-run-json",
            "benchmark-run.json",
        ],
        [
            "benchmark",
            "classify-artifacts",
            "result.compact.json",
            "trajectory.json",
            "--adapter-kind",
            "terminal-bench",
            "--allow-public-filename",
            "summary.json",
        ],
        [
            "benchmark",
            "candidate-source-boundary",
            "docs/benchmark.md",
            "tasks/task.md",
            "--adapter-kind",
            "agents-last-exam",
            "--allow-public-filename",
            "summary.json",
            "--require-clean",
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
