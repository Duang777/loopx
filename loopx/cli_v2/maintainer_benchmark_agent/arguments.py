from __future__ import annotations

import argparse
from pathlib import Path

from loopx.cli_contract import add_subcommand_format
from loopx.worker_bridge import (
    DEFAULT_WORKER_BRIDGE_BENCHMARK_RUN_JSON,
    DEFAULT_WORKER_BRIDGE_COUNTER_TRACE_JSON,
    DEFAULT_WORKER_BRIDGE_MODULE,
    DEFAULT_WORKER_BRIDGE_PYTHON_BIN,
    DEFAULT_WORKER_BRIDGE_WALL_TIME_LIMIT_SECONDS,
    LOOPX_PROJECT_ROOT_PLACEHOLDER,
    LOOPX_RUNTIME_ROOT_PLACEHOLDER,
)


def register_arguments(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    _register_worker_bridge(subparsers)
    _register_canary(subparsers)
    _register_benchmark(subparsers)


def _register_worker_bridge(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "worker-bridge",
        help="Render runner-agnostic worker bridge/install contracts.",
    )
    commands = parser.add_subparsers(dest="worker_bridge_command")
    contract = commands.add_parser(
        "contract",
        help="Render a LoopX worker bridge/install contract.",
    )
    add_subcommand_format(contract)
    contract.add_argument(
        "--project-root",
        default=LOOPX_PROJECT_ROOT_PLACEHOLDER,
        help="Container-visible LoopX project root. Defaults to a public placeholder.",
    )
    contract.add_argument(
        "--runtime-root",
        dest="worker_bridge_runtime_root",
        default=LOOPX_RUNTIME_ROOT_PLACEHOLDER,
        help="Container-visible LoopX runtime root. Defaults to a public placeholder.",
    )
    contract.add_argument(
        "--python-bin",
        default=DEFAULT_WORKER_BRIDGE_PYTHON_BIN,
        help="Python executable inside the worker environment.",
    )
    contract.add_argument(
        "--module",
        default=DEFAULT_WORKER_BRIDGE_MODULE,
        help="LoopX CLI module import path.",
    )
    contract.add_argument(
        "--scan-path",
        help=(
            "Container-visible public scan path. Defaults to the LoopX "
            "benchmark module."
        ),
    )
    contract.add_argument(
        "--benchmark-run-json",
        default=DEFAULT_WORKER_BRIDGE_BENCHMARK_RUN_JSON,
        help="Worker-visible benchmark_run_v0 JSON write path.",
    )
    contract.add_argument(
        "--counter-trace-json",
        default=DEFAULT_WORKER_BRIDGE_COUNTER_TRACE_JSON,
        help="Worker-visible compact counter trace JSONL path.",
    )
    contract.add_argument(
        "--classification",
        default="<classification>",
        help="Classification label for worker-side compact writeback.",
    )

    outcome = commands.add_parser(
        "outcome",
        help="Render compact worker bridge evidence and runner-return outcome.",
    )
    add_subcommand_format(outcome)
    _add_worker_bridge_outcome_args(outcome)

    intervention = commands.add_parser(
        "active-user-intervention",
        help="Render one public-safe active-user simulator intervention event.",
    )
    add_subcommand_format(intervention)
    intervention.add_argument("--seq", type=int, required=True)
    intervention.add_argument("--message", required=True)
    intervention.add_argument(
        "--trigger",
        default="public_progress_or_stall_signal",
        help="Public-safe intervention trigger label.",
    )
    intervention.add_argument(
        "--channel",
        default="simulator_proactive_user_message",
        help="Public-safe intervention channel label.",
    )
    intervention.add_argument(
        "--before-worker-start",
        action="store_true",
        help="Mark this intervention as created before the worker start marker.",
    )
    intervention.add_argument(
        "--jsonl",
        action="store_true",
        help="Print compact single-line JSON for appending to an intervention feed.",
    )

    simulator_output = commands.add_parser(
        "active-user-simulator-output",
        help="Validate a Codex CLI simulator JSON output and render feed JSON.",
    )
    add_subcommand_format(simulator_output)
    simulator_output.add_argument("--seq", type=int, required=True)
    simulator_output.add_argument("--simulator-output-json", required=True)
    simulator_output.add_argument(
        "--before-worker-start",
        action="store_true",
    )
    simulator_output.add_argument("--jsonl", action="store_true")


def _add_worker_bridge_outcome_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--worker-cli-call-total",
        type=int,
        default=0,
        help="Compact count of in-worker LoopX CLI calls.",
    )
    parser.add_argument(
        "--required-worker-cli-call-total-min",
        type=int,
        default=1,
        help="Minimum worker CLI call count required to claim bridge verification.",
    )
    parser.add_argument(
        "--counter-trace-present",
        action="store_true",
        help="Whether a compact worker counter trace was observed.",
    )
    parser.add_argument(
        "--runner-return-completed",
        action="store_true",
        help="Whether the runner returned a completed case result.",
    )
    parser.add_argument(
        "--official-score-completed",
        action="store_true",
        help="Whether an official task score is available.",
    )
    parser.add_argument(
        "--official-score-value",
        type=float,
        help="Official task score value when --official-score-completed is set.",
    )
    parser.add_argument(
        "--interrupted",
        action="store_true",
        help="Whether the controller interrupted the worker run.",
    )
    parser.add_argument(
        "--interrupt-reason",
        default="",
        help="Public-safe interrupt reason label.",
    )
    parser.add_argument(
        "--wall-time-seconds",
        type=float,
        help="Observed wall time in seconds, if available.",
    )
    parser.add_argument(
        "--wall-time-limit-seconds",
        type=float,
        default=DEFAULT_WORKER_BRIDGE_WALL_TIME_LIMIT_SECONDS,
        help="Controller wall-time limit for this worker bridge outcome.",
    )
    parser.add_argument(
        "--side-effect-audit-failed",
        action="store_true",
        help="Mark the side-effect audit as failed.",
    )


def _register_canary(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "canary",
        help="Plan or run catalog-informed canary profiles and smoke suites.",
    )
    commands = parser.add_subparsers(dest="canary_command", required=True)
    profiles = commands.add_parser(
        "profiles",
        help="List canary profiles derived from the interaction-pattern catalog matrix.",
    )
    add_subcommand_format(profiles)
    profiles.add_argument("--catalog", type=Path)
    smoke_profiles = commands.add_parser(
        "smoke-profiles",
        help="List named smoke-suite profiles used by CLI, pytest facade, and automation.",
    )
    add_subcommand_format(smoke_profiles)


def _register_benchmark(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "benchmark",
        help="Benchmark runner skeletons. Current public surface is fixture-only and no-run by default.",
    )
    commands = parser.add_subparsers(dest="benchmark_command", required=True)
    seam = commands.add_parser(
        "split-control-execution-seam",
        help=(
            "Build the public-safe execution seam from split-control readiness "
            "and command-adapter facts. This does not execute benchmarks."
        ),
    )
    add_subcommand_format(seam)
    seam.add_argument("--readiness-json", required=True)
    seam.add_argument("--command-adapter-json")
    seam.add_argument(
        "--execution-mode",
        default="compact_no_upload_dry_run",
    )

    parity = commands.add_parser(
        "parity-check",
        help=(
            "Posthoc-check whether a compact benchmark_run_v0 has enough "
            "public-safe evidence to support Codex App product-path attribution."
        ),
    )
    add_subcommand_format(parity)
    parity.add_argument(
        "--benchmark-run-json",
        required=True,
        help="Path to a compact benchmark_run_v0 JSON object. Use '-' to read stdin.",
    )

    artifacts = commands.add_parser(
        "classify-artifacts",
        help=(
            "Classify benchmark artifact paths before reading them. The classifier "
            "returns basenames and blocker reasons only; it does not read files or "
            "echo host directories."
        ),
    )
    add_subcommand_format(artifacts)
    artifacts.add_argument(
        "artifact_paths",
        nargs="+",
        help="Candidate benchmark artifact paths to classify without reading.",
    )
    artifacts.add_argument(
        "--adapter-kind",
        default="default",
        help=(
            "Benchmark adapter artifact policy key. Unknown values fall back to "
            "default without recording paths."
        ),
    )
    artifacts.add_argument(
        "--allow-public-filename",
        action="append",
        default=[],
        help=(
            "Additional public compact basename to allow for this classification "
            "run. Only the basename is used and values are filtered."
        ),
    )

    sources = commands.add_parser(
        "candidate-source-boundary",
        help=(
            "Classify candidate-selection source paths before using them. This "
            "does not read files or echo host paths; it blocks raw runner roots, "
            "trial directories, task bodies, trajectories, and Codex transcripts."
        ),
    )
    add_subcommand_format(sources)
    sources.add_argument(
        "source_paths",
        nargs="+",
        help="Candidate-selection source paths to classify without reading.",
    )
    sources.add_argument(
        "--adapter-kind",
        default="default",
        help="Benchmark adapter artifact policy key for compact artifact allowlists.",
    )
    sources.add_argument(
        "--allow-public-filename",
        action="append",
        default=[],
        help=(
            "Additional compact/public basename to allow for this classification "
            "run. Only the basename is used and values are filtered."
        ),
    )
    sources.add_argument(
        "--require-clean",
        action="store_true",
        help="Return non-zero if any source is blocked.",
    )
