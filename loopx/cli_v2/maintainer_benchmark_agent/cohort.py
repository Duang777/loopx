from __future__ import annotations

import argparse
import json
from pathlib import Path

from loopx.application import ApplicationError
from loopx.benchmark_core import (
    render_benchmark_artifact_path_filter_markdown,
    render_benchmark_candidate_source_boundary_markdown,
    render_benchmark_parity_check_markdown,
)
from loopx.cli_contract import JsonValue, print_compatible_markdown_renderer
from loopx.worker_bridge import render_worker_bridge_install_contract_markdown

from ..registrar import (
    CohortRegistrar,
    CommandBinding,
    CommandOutcome,
    SelectorMatch,
)
from .arguments import register_arguments
from .handlers import (
    handle_active_user_intervention,
    handle_active_user_simulator_output,
    handle_benchmark_artifact_inspection,
    handle_benchmark_candidate_source_boundary,
    handle_benchmark_parity_check,
    handle_canary_profiles,
    handle_canary_smoke_profiles,
    handle_split_control_execution_seam,
    handle_worker_bridge_contract,
    handle_worker_bridge_outcome,
)


def _selector(dest: str, value: str) -> tuple[SelectorMatch, ...]:
    return (SelectorMatch(dest=dest, value=value),)


_BENCHMARK_PARITY_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_benchmark_parity_check_markdown
)
_WORKER_BRIDGE_MARKDOWN_RENDERER = print_compatible_markdown_renderer(
    render_worker_bridge_install_contract_markdown
)


def _map_benchmark_parity_error(
    error: ApplicationError,
    _args: argparse.Namespace,
    _registry_path: Path,
) -> CommandOutcome:
    reason = error.details.get("reason")
    if reason == "must_be_compactable_benchmark_run_v0":
        message = (
            "--benchmark-run-json did not contain a compactable "
            "benchmark_run_v0 object"
        )
    elif error.__cause__ is not None:
        message = str(error.__cause__)
    else:
        message = str(error)
    return CommandOutcome(
        payload={
            "ok": False,
            "codex_app_parity_posthoc_check": {
                "full_product_claim_allowed": False,
                "claim_level": "invalid_or_unreadable_compact_benchmark_run",
            },
            "error": message,
        },
        exit_code=1,
        markdown_renderer=_BENCHMARK_PARITY_MARKDOWN_RENDERER,
    )


def _render_worker_bridge_jsonl(payload: dict[str, JsonValue]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def _handle_active_user_intervention_compat(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    outcome = handle_active_user_intervention(args, application)
    if not bool(args.jsonl):
        return outcome
    # Legacy --jsonl is a command-specific presentation override, independent
    # of the global output format.
    args.format = "markdown"
    return CommandOutcome(
        payload=outcome.payload,
        exit_code=outcome.exit_code,
        markdown_renderer=_render_worker_bridge_jsonl,
    )


def _map_active_user_intervention_error(
    error: ApplicationError,
    _args: argparse.Namespace,
    _registry_path: Path,
) -> CommandOutcome:
    cause_message = str(error.__cause__) if error.__cause__ is not None else ""
    allowed_cause_messages = {
        f"{field} contains a non-public marker"
        for field in ("message", "trigger", "channel")
    }
    if cause_message in allowed_cause_messages:
        message = cause_message
    elif error.details.get("field") == "seq":
        message = "seq must be a non-negative integer"
    elif error.details.get("field") in {"message", "trigger", "channel"}:
        message = f"{error.details['field']} is required"
    else:
        message = str(error)
    return CommandOutcome(
        payload={
            "ok": False,
            "mode": "worker-bridge",
            "error": message,
        },
        exit_code=1,
        markdown_renderer=_WORKER_BRIDGE_MARKDOWN_RENDERER,
    )


MAINTAINER_BENCHMARK_AGENT_COHORT = CohortRegistrar(
    cohort_id="maintainer-benchmark-agent",
    register_arguments=register_arguments,
    bindings=(
        CommandBinding(
            command="worker-bridge",
            selectors=_selector("worker_bridge_command", "contract"),
            application_operation="application.agents.worker_bridge.contract",
            handler=handle_worker_bridge_contract,
            markdown_renderer=_WORKER_BRIDGE_MARKDOWN_RENDERER,
        ),
        CommandBinding(
            command="worker-bridge",
            selectors=_selector("worker_bridge_command", "outcome"),
            application_operation="application.agents.worker_bridge.outcome",
            handler=handle_worker_bridge_outcome,
            markdown_renderer=_WORKER_BRIDGE_MARKDOWN_RENDERER,
        ),
        CommandBinding(
            command="worker-bridge",
            selectors=_selector(
                "worker_bridge_command",
                "active-user-intervention",
            ),
            application_operation=(
                "application.agents.worker_bridge.active_user_intervention"
            ),
            handler=_handle_active_user_intervention_compat,
            markdown_renderer=_WORKER_BRIDGE_MARKDOWN_RENDERER,
            application_error_mapper=_map_active_user_intervention_error,
        ),
        CommandBinding(
            command="worker-bridge",
            selectors=_selector(
                "worker_bridge_command",
                "active-user-simulator-output",
            ),
            application_operation=(
                "application.agents.worker_bridge.active_user_simulator_output"
            ),
            handler=handle_active_user_simulator_output,
        ),
        CommandBinding(
            command="canary",
            selectors=_selector("canary_command", "profiles"),
            application_operation="application.maintenance.canary.profiles",
            handler=handle_canary_profiles,
        ),
        CommandBinding(
            command="canary",
            selectors=_selector("canary_command", "smoke-profiles"),
            application_operation="application.maintenance.canary.smoke_profiles",
            handler=handle_canary_smoke_profiles,
        ),
        CommandBinding(
            command="benchmark",
            selectors=_selector(
                "benchmark_command",
                "split-control-execution-seam",
            ),
            application_operation=(
                "application.benchmarks.split_control.execution_seam"
            ),
            handler=handle_split_control_execution_seam,
        ),
        CommandBinding(
            command="benchmark",
            selectors=_selector("benchmark_command", "parity-check"),
            application_operation=(
                "application.benchmarks.inspection.parity_check"
            ),
            handler=handle_benchmark_parity_check,
            markdown_renderer=_BENCHMARK_PARITY_MARKDOWN_RENDERER,
            application_error_mapper=_map_benchmark_parity_error,
        ),
        CommandBinding(
            command="benchmark",
            selectors=_selector("benchmark_command", "classify-artifacts"),
            application_operation=(
                "application.benchmarks.inspection.classify_artifacts"
            ),
            handler=handle_benchmark_artifact_inspection,
            markdown_renderer=print_compatible_markdown_renderer(
                render_benchmark_artifact_path_filter_markdown
            ),
        ),
        CommandBinding(
            command="benchmark",
            selectors=_selector(
                "benchmark_command",
                "candidate-source-boundary",
            ),
            application_operation=(
                "application.benchmarks.inspection.candidate_source_boundary"
            ),
            handler=handle_benchmark_candidate_source_boundary,
            markdown_renderer=print_compatible_markdown_renderer(
                render_benchmark_candidate_source_boundary_markdown
            ),
        ),
    ),
)
