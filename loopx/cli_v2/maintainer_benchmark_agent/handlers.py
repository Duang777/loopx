from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loopx.application.agents import (
    WorkerBridgeActiveUserInterventionRequest,
    WorkerBridgeActiveUserSimulatorOutputRequest,
    WorkerBridgeContractRequest,
    WorkerBridgeOutcomeRequest,
    parse_active_user_simulator_output,
)
from loopx.application.benchmarks import (
    BenchmarkArtifactInspectionRequest,
    BenchmarkCandidateSourceBoundaryRequest,
    BenchmarkParityCheckRequest,
    SplitControlExecutionSeamRequest,
    parse_benchmark_command_adapters,
    parse_benchmark_parity_run,
    parse_split_control_readiness,
)
from loopx.application.errors import ValidationFailed
from loopx.application.maintenance import (
    CanaryProfilesRequest,
    CanarySmokeProfilesRequest,
)

from ..registrar import CommandOutcome
from .application import require_application_root
from .payloads import (
    active_user_intervention_payload,
    active_user_simulator_intervention_payload,
    benchmark_artifact_inspection_payload,
    benchmark_candidate_source_boundary_payload,
    benchmark_parity_check_payload,
    canary_profiles_payload,
    canary_smoke_profiles_payload,
    split_control_execution_seam_payload,
    worker_bridge_contract_payload,
    worker_bridge_outcome_payload,
)


def handle_worker_bridge_contract(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.agents.worker_bridge.contract(
        WorkerBridgeContractRequest(
            project_root=args.project_root,
            runtime_root=args.worker_bridge_runtime_root,
            python_bin=args.python_bin,
            module=args.module,
            scan_path=args.scan_path,
            benchmark_run_json=args.benchmark_run_json,
            counter_trace_json=args.counter_trace_json,
            classification=args.classification,
        )
    )
    return CommandOutcome(
        payload=worker_bridge_contract_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_worker_bridge_outcome(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.agents.worker_bridge.outcome(
        WorkerBridgeOutcomeRequest(
            worker_cli_call_total=args.worker_cli_call_total,
            required_worker_cli_call_total_min=(
                args.required_worker_cli_call_total_min
            ),
            counter_trace_present=bool(args.counter_trace_present),
            runner_return_completed=bool(args.runner_return_completed),
            official_score_completed=bool(args.official_score_completed),
            official_score_value=args.official_score_value,
            interrupted=bool(args.interrupted),
            interrupt_reason=args.interrupt_reason,
            wall_time_seconds=args.wall_time_seconds,
            wall_time_limit_seconds=args.wall_time_limit_seconds,
            side_effect_audit_passed=not bool(args.side_effect_audit_failed),
        )
    )
    return CommandOutcome(
        payload=worker_bridge_outcome_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_active_user_intervention(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.agents.worker_bridge.active_user_intervention(
        WorkerBridgeActiveUserInterventionRequest(
            seq=args.seq,
            message=args.message,
            trigger=args.trigger,
            channel=args.channel,
            created_after_worker_start=not bool(args.before_worker_start),
        )
    )
    return CommandOutcome(
        payload=active_user_intervention_payload(result),
        exit_code=0,
    )


def handle_active_user_simulator_output(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    raw = _load_json_object(
        args.simulator_output_json,
        label="--simulator-output-json",
    )
    result = root.agents.worker_bridge.active_user_simulator_output(
        WorkerBridgeActiveUserSimulatorOutputRequest(
            seq=args.seq,
            simulator_output=parse_active_user_simulator_output(raw),
            created_after_worker_start=not bool(args.before_worker_start),
        )
    )
    return CommandOutcome(
        payload=active_user_simulator_intervention_payload(result),
        exit_code=0,
    )


def handle_canary_profiles(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.maintenance.canary.profiles(
        CanaryProfilesRequest(catalog_path=args.catalog)
    )
    return CommandOutcome(
        payload=canary_profiles_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_canary_smoke_profiles(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    del args
    root = require_application_root(application)
    result = root.maintenance.canary.smoke_profiles(CanarySmokeProfilesRequest())
    return CommandOutcome(
        payload=canary_smoke_profiles_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_split_control_execution_seam(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    readiness_payload = _load_json_object(
        args.readiness_json,
        label="--readiness-json",
    )
    adapter_payload: dict[str, object] = {}
    wrapper_unwrapped = False
    if args.command_adapter_json:
        adapter_payload = _load_json_object(
            args.command_adapter_json,
            label="--command-adapter-json",
        )
    raw_adapters: object = adapter_payload
    if args.command_adapter_json and isinstance(
        adapter_payload.get("command_adapters"),
        dict,
    ):
        raw_adapters = adapter_payload["command_adapters"]
        wrapper_unwrapped = True
    result = root.benchmarks.split_control.execution_seam(
        SplitControlExecutionSeamRequest(
            readiness=parse_split_control_readiness(readiness_payload),
            command_adapters=parse_benchmark_command_adapters(raw_adapters),
            execution_mode=args.execution_mode,
        )
    )
    return CommandOutcome(
        payload=split_control_execution_seam_payload(
            result,
            command_adapter_json_read=bool(args.command_adapter_json),
            command_adapter_wrapper_unwrapped=wrapper_unwrapped,
        ),
        exit_code=0,
    )


def handle_benchmark_artifact_inspection(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.benchmarks.inspection.classify_artifacts(
        BenchmarkArtifactInspectionRequest(
            artifact_paths=tuple(args.artifact_paths),
            adapter_kind=args.adapter_kind,
            allow_public_filenames=tuple(args.allow_public_filename),
        )
    )
    return CommandOutcome(
        payload=benchmark_artifact_inspection_payload(result),
        exit_code=0,
    )


def handle_benchmark_candidate_source_boundary(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.benchmarks.inspection.candidate_source_boundary(
        BenchmarkCandidateSourceBoundaryRequest(
            source_paths=tuple(args.source_paths),
            adapter_kind=args.adapter_kind,
            allow_public_filenames=tuple(args.allow_public_filename),
        )
    )
    return CommandOutcome(
        payload=benchmark_candidate_source_boundary_payload(result),
        exit_code=1 if args.require_clean and not result.clean else 0,
    )


def handle_benchmark_parity_check(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    raw = _load_json_object(
        args.benchmark_run_json,
        label="--benchmark-run-json",
    )
    result = root.benchmarks.inspection.parity_check(
        BenchmarkParityCheckRequest(run=parse_benchmark_parity_run(raw))
    )
    return CommandOutcome(
        payload=benchmark_parity_check_payload(result),
        exit_code=0,
    )


def _load_json_object(path_text: str, *, label: str) -> dict[str, object]:
    try:
        raw = (
            sys.stdin.read()
            if path_text == "-"
            else Path(path_text).expanduser().read_text(encoding="utf-8")
        )
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailed(
            details={"field": label, "reason": "must_be_readable_json_object"}
        ) from exc
    if not isinstance(value, dict):
        raise ValidationFailed(details={"field": label, "reason": "must_be_object"})
    return value
