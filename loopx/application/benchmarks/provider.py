from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from loopx.benchmark_core import (
    build_benchmark_candidate_source_boundary,
    build_codex_app_parity_posthoc_check,
    build_split_control_remote_executor_execution_seam,
    build_split_control_remote_executor_launch_plan,
    build_split_control_remote_executor_runner_batch,
    filter_public_benchmark_artifact_paths,
)
from loopx.status import compact_benchmark_run

from ..errors import StateUnavailable, ValidationFailed
from .contracts import (
    BenchmarkArtifactBlocker,
    BenchmarkArtifactClassification,
    BenchmarkArtifactInspection,
    BenchmarkArtifactInspectionRequest,
    BenchmarkArtifactPolicy,
    BenchmarkArtifactPublicBoundary,
    BenchmarkCandidateReadBoundary,
    BenchmarkCandidateSelectionPolicy,
    BenchmarkCandidateSourceBlocker,
    BenchmarkCandidateSourceBoundary,
    BenchmarkCandidateSourceBoundaryRequest,
    BenchmarkCandidateSourceClassification,
    BenchmarkCandidateSourceKind,
    BenchmarkCommandAdapterFacts,
    BenchmarkCommandAdapterSurface,
    BenchmarkCommandMaterialization,
    BenchmarkExecutionCase,
    BenchmarkExecutionHandleContract,
    BenchmarkLocalDriverContract,
    BenchmarkLocalDriverFacts,
    BenchmarkPostLaunchEvidenceBoundary,
    BenchmarkParityCaseGoalState,
    BenchmarkParityCasePathKind,
    BenchmarkParityCheck,
    BenchmarkParityCheckRequest,
    BenchmarkParityClaimLevel,
    BenchmarkParityCliCallCounts,
    BenchmarkParityEvidenceChecks,
    BenchmarkParityEvidenceKind,
    BenchmarkParityReadBoundary,
    BenchmarkParityRequiredCall,
    BenchmarkParityRunEvidence,
    BenchmarkParitySafetyChecks,
    BenchmarkParitySafetyKind,
    BenchmarkParityStatefulLifecycleCounts,
    BenchmarkRemoteSandboxContract,
    BenchmarkRemoteSandboxFacts,
    BenchmarkResultReducer,
    BenchmarkReasonCount,
    SplitControlExecutionBoundary,
    SplitControlExecutionSeam,
    SplitControlExecutionSeamRequest,
    SplitControlReadiness,
    SplitControlReadinessBoundary,
    SplitControlReadinessMatrix,
    SplitControlRoute,
    SplitControlRouteMode,
    SplitControlRouteStatus,
)


READINESS_SCHEMA_VERSION = "benchmark_split_control_remote_executor_readiness_v0"


class SplitControlBenchmarkProvider(Protocol):
    def execution_seam(
        self,
        request: SplitControlExecutionSeamRequest,
    ) -> SplitControlExecutionSeam: ...


class CoreSplitControlBenchmarkProvider:
    """Plan-only typed adapter; it has no runner, upload, or submit capability."""

    def execution_seam(
        self,
        request: SplitControlExecutionSeamRequest,
    ) -> SplitControlExecutionSeam:
        readiness = _readiness_payload(request.readiness)
        launch_plan = build_split_control_remote_executor_launch_plan(readiness)
        runner_batch = build_split_control_remote_executor_runner_batch(
            launch_plan,
            fresh_readiness=readiness,
            execution_mode=request.execution_mode,
        )
        payload = build_split_control_remote_executor_execution_seam(
            runner_batch,
            command_adapters=_command_adapter_payload(request.command_adapters),
        )
        return _execution_seam(payload)


class BenchmarkInspectionProvider(Protocol):
    def classify_artifacts(
        self,
        request: BenchmarkArtifactInspectionRequest,
    ) -> BenchmarkArtifactInspection: ...

    def candidate_source_boundary(
        self,
        request: BenchmarkCandidateSourceBoundaryRequest,
    ) -> BenchmarkCandidateSourceBoundary: ...

    def parity_check(
        self,
        request: BenchmarkParityCheckRequest,
    ) -> BenchmarkParityCheck: ...


class CoreBenchmarkInspectionProvider:
    """Read-only/no-read benchmark inspection adapter with no execution port."""

    def classify_artifacts(
        self,
        request: BenchmarkArtifactInspectionRequest,
    ) -> BenchmarkArtifactInspection:
        return _artifact_inspection(
            filter_public_benchmark_artifact_paths(
                request.artifact_paths,
                adapter_kind=request.adapter_kind,
                extra_public_filenames=request.allow_public_filenames,
            )
        )

    def candidate_source_boundary(
        self,
        request: BenchmarkCandidateSourceBoundaryRequest,
    ) -> BenchmarkCandidateSourceBoundary:
        return _candidate_source_boundary(
            build_benchmark_candidate_source_boundary(
                request.source_paths,
                adapter_kind=request.adapter_kind,
                extra_public_filenames=request.allow_public_filenames,
            )
        )

    def parity_check(
        self,
        request: BenchmarkParityCheckRequest,
    ) -> BenchmarkParityCheck:
        run = request.run
        counts = run.cli_call_counts
        safety = run.safety_checks
        interaction: dict[str, object] = {
            "product_mode": run.product_mode,
            "loopx_cli_calls": {
                "status": counts.status,
                "quota_should_run": counts.quota_should_run,
                "todo_list": counts.todo_list,
                "history": counts.history,
                "check": counts.check,
                "todo_claim": counts.todo_claim,
                "todo_update": counts.todo_update,
                "refresh_state": counts.refresh_state,
                "quota_spend": counts.quota_spend,
                "case_result": counts.case_result,
                "total": counts.total,
            },
            "loopx_state_reads": run.state_reads,
            "loopx_state_writes": run.state_writes,
            "case_goal_state_init_required": run.case_init_required,
            "case_goal_state_initialized_before_agent": (
                run.case_initialized_before_agent
            ),
            "private_trajectory_summary_present": (
                run.trajectory_summary_present
            ),
            "raw_task_text_recorded": not safety.raw_task_text_absent,
            "reward_feedback_forwarded": (
                not safety.raw_reward_feedback_absent
            ),
            "raw_verifier_output_recorded": (
                not safety.raw_verifier_output_absent
            ),
            "raw_agent_trajectory_recorded": (
                not safety.raw_agent_trajectory_absent
            ),
        }
        if run.canonical_case_path_present:
            interaction["case_goal_state_path"] = (
                "/app/.codex/goals/typed-parity/ACTIVE_GOAL_STATE.md"
            )
        return _parity_check(
            build_codex_app_parity_posthoc_check(
                {
                    "benchmark_id": run.benchmark_id,
                    "mode": run.mode,
                    "route": run.route,
                    "interaction_counters": interaction,
                }
            )
        )


def parse_split_control_readiness(value: object) -> SplitControlReadiness:
    payload = _mapping(value, "readiness")
    _exact_keys(
        payload,
        "readiness",
        {
            "schema_version",
            "route",
            "ready",
            "first_blocker",
            "local_agent",
            "remote_executor",
            "benchmark_statuses",
            "readiness_matrix",
            "parallel_policy",
            "boundary",
            "next_action",
        },
    )
    schema_version = _text(payload, "schema_version")
    if schema_version != READINESS_SCHEMA_VERSION:
        raise ValidationFailed(
            details={
                "field": "readiness.schema_version",
                "expected": READINESS_SCHEMA_VERSION,
            }
        )
    route = _parse_route(_child(payload, "route"))
    _validate_local_agent(_child(payload, "local_agent"))
    _validate_remote_executor(_child(payload, "remote_executor"))
    for index, item in enumerate(_sequence(payload, "benchmark_statuses")):
        _validate_benchmark_status(
            _mapping(item, f"benchmark_statuses[{index}]")
        )
    matrix = _parse_readiness_matrix(_child(payload, "readiness_matrix"))
    _validate_parallel_policy(_child(payload, "parallel_policy"))
    boundary = _parse_readiness_boundary(_child(payload, "boundary"))
    _bool(payload, "ready")
    _text(payload, "first_blocker")
    _text(payload, "next_action")
    return SplitControlReadiness(
        route=route,
        readiness_matrix=matrix,
        boundary=boundary,
    )


def parse_benchmark_command_adapters(
    value: object,
) -> tuple[BenchmarkCommandAdapterFacts, ...]:
    payload = _mapping(value, "command_adapters")
    adapters: list[BenchmarkCommandAdapterFacts] = []
    for benchmark_id, raw in payload.items():
        if not isinstance(benchmark_id, str) or not benchmark_id.strip():
            raise ValidationFailed(details={"field": "command_adapters.key"})
        row = _mapping(raw, f"command_adapters.{benchmark_id}")
        _allowed_keys(
            row,
            f"command_adapters.{benchmark_id}",
            required={"command_adapter_ready", "result_reducer_ready"},
            optional={
                "command_adapter_status",
                "entrypoint_label",
                "remote_materializer_ready",
                "surface_contract",
                "local_driver_contract",
                "remote_sandbox_contract",
                "known_blockers",
                "handle_fields",
                "result_reducer_label",
            },
        )
        surface = None
        if row.get("surface_contract") is not None:
            surface_payload = _child(row, "surface_contract")
            _exact_keys(
                surface_payload,
                f"command_adapters.{benchmark_id}.surface_contract",
                {"remote_materializer_ready"},
            )
            surface = BenchmarkCommandAdapterSurface(
                remote_materializer_ready=_bool(
                    surface_payload,
                    "remote_materializer_ready",
                )
            )
        local_driver = _parse_local_driver_facts(
            row.get("local_driver_contract"),
            field=f"command_adapters.{benchmark_id}.local_driver_contract",
        )
        remote_sandbox = _parse_remote_sandbox_facts(
            row.get("remote_sandbox_contract"),
            field=f"command_adapters.{benchmark_id}.remote_sandbox_contract",
        )
        adapters.append(
            BenchmarkCommandAdapterFacts(
                benchmark_id=benchmark_id,
                command_adapter_ready=_bool(row, "command_adapter_ready"),
                result_reducer_ready=_bool(row, "result_reducer_ready"),
                command_adapter_status=_optional_text(
                    row,
                    "command_adapter_status",
                ),
                entrypoint_label=_optional_text(row, "entrypoint_label"),
                remote_materializer_ready=_optional_bool(
                    row,
                    "remote_materializer_ready",
                ),
                surface_contract=surface,
                local_driver_contract=local_driver,
                remote_sandbox_contract=remote_sandbox,
                known_blockers=_optional_text_tuple(row, "known_blockers"),
                handle_fields=_optional_text_tuple(row, "handle_fields"),
                result_reducer_label=_optional_text(row, "result_reducer_label"),
            )
        )
    return tuple(adapters)


def parse_benchmark_parity_run(value: object) -> BenchmarkParityRunEvidence:
    payload = _mapping(value, "benchmark_run")
    compact = compact_benchmark_run(dict(payload))
    if not compact:
        raise ValidationFailed(
            details={
                "field": "benchmark_run",
                "reason": "must_be_compactable_benchmark_run_v0",
            }
        )
    normalized = _parity_check(build_codex_app_parity_posthoc_check(compact))
    return BenchmarkParityRunEvidence(
        benchmark_id=normalized.benchmark_id,
        mode=normalized.mode,
        route=normalized.route,
        product_mode=normalized.product_mode,
        cli_call_counts=normalized.loopx_cli_call_counts,
        state_reads=normalized.stateful_lifecycle_counts.state_reads,
        state_writes=normalized.stateful_lifecycle_counts.state_writes,
        case_init_required=normalized.case_goal_state.init_required,
        case_initialized_before_agent=(
            normalized.case_goal_state.initialized_before_agent
        ),
        canonical_case_path_present=(
            normalized.case_goal_state.canonical_path_present
        ),
        trajectory_summary_present=(
            normalized.evidence_checks.codex_cli_trajectory_summary_present
        ),
        safety_checks=normalized.safety_checks,
    )


def _parse_route(payload: Mapping[str, object]) -> SplitControlRoute:
    _exact_keys(
        payload,
        "route",
        {
            "mode",
            "status",
            "default_for_cloud_host_runs",
            "allowed_use",
            "not_for",
            "retirement_policy",
            "local_agent_owns",
            "remote_executor_owns",
        },
    )
    _enum(SplitControlRouteMode, payload, "mode")
    _text_tuple(payload, "allowed_use")
    _text_tuple(payload, "not_for")
    _text(payload, "retirement_policy")
    return SplitControlRoute(
        status=_enum(SplitControlRouteStatus, payload, "status"),
        default_for_cloud_host_runs=_bool(payload, "default_for_cloud_host_runs"),
        local_agent_owns=_text_tuple(payload, "local_agent_owns"),
        remote_executor_owns=_text_tuple(payload, "remote_executor_owns"),
    )


def _validate_local_agent(
    payload: Mapping[str, object],
) -> None:
    _exact_keys(payload, "local_agent", {"ready", "missing", "codex_auth_local_only"})
    _bool(payload, "ready")
    _text_tuple(payload, "missing")
    _bool(payload, "codex_auth_local_only")


def _validate_remote_executor(
    payload: Mapping[str, object],
) -> None:
    _exact_keys(
        payload,
        "remote_executor",
        {
            "base_ready",
            "base_missing",
            "codex_available",
            "codex_acp_available",
            "node_available",
            "npm_available",
            "remote_agent_components_missing",
            "remote_agent_components_blocking",
        },
    )
    missing = _child(payload, "remote_agent_components_missing")
    _exact_keys(
        missing,
        "remote_agent_components_missing",
        {"codex_available", "codex_acp_available"},
    )
    _bool(payload, "base_ready")
    _text_tuple(payload, "base_missing")
    for field in (
        "codex_available",
        "codex_acp_available",
        "node_available",
        "npm_available",
        "remote_agent_components_blocking",
    ):
        _bool(payload, field)
    _bool(missing, "codex_available")
    _bool(missing, "codex_acp_available")


def _validate_benchmark_status(
    payload: Mapping[str, object],
) -> None:
    _exact_keys(
        payload,
        "benchmark_status",
        {
            "benchmark_id",
            "ready_for_split_control_execution",
            "first_blocker",
            "blockers",
            "local_agent_ready",
            "remote_executor_base_ready",
            "split_control_adapter_ready",
            "runner_tooling_ready",
            "task_data_ready",
            "requires_remote_node",
            "remote_node_ready",
            "remote_codex_required",
            "remote_codex_acp_required",
            "remote_codex_missing_is_blocker",
        },
    )
    _text(payload, "benchmark_id")
    _text(payload, "first_blocker")
    _text_tuple(payload, "blockers")
    for field in (
        "ready_for_split_control_execution",
        "local_agent_ready",
        "remote_executor_base_ready",
        "split_control_adapter_ready",
        "runner_tooling_ready",
        "task_data_ready",
        "requires_remote_node",
        "remote_node_ready",
        "remote_codex_required",
        "remote_codex_acp_required",
        "remote_codex_missing_is_blocker",
    ):
        _bool(payload, field)


def _parse_readiness_matrix(
    payload: Mapping[str, object],
) -> SplitControlReadinessMatrix:
    _exact_keys(
        payload,
        "readiness_matrix",
        {
            "ready_benchmark_ids",
            "blocked_benchmark_ids",
            "next_ready_batch_benchmark_ids",
            "next_repair_target",
            "has_launchable_subset",
            "all_requested_benchmarks_ready",
        },
    )
    _text_tuple(payload, "ready_benchmark_ids")
    if payload.get("next_repair_target") is not None:
        repair_payload = _child(payload, "next_repair_target")
        _exact_keys(
            repair_payload,
            "next_repair_target",
            {"benchmark_id", "first_blocker", "blockers"},
        )
        _text(repair_payload, "benchmark_id")
        _text(repair_payload, "first_blocker")
        _text_tuple(repair_payload, "blockers")
    _bool(payload, "has_launchable_subset")
    _bool(payload, "all_requested_benchmarks_ready")
    _text_tuple(payload, "blocked_benchmark_ids")
    return SplitControlReadinessMatrix(
        next_ready_batch_benchmark_ids=_text_tuple(
            payload,
            "next_ready_batch_benchmark_ids",
        ),
    )


def _validate_parallel_policy(
    payload: Mapping[str, object],
) -> None:
    _exact_keys(
        payload,
        "parallel_policy",
        {
            "max_parallel_cases",
            "suggested_next_batch_size",
            "parallelize_only_ready_benchmarks",
        },
    )
    _int(payload, "max_parallel_cases")
    _int(payload, "suggested_next_batch_size")
    _bool(payload, "parallelize_only_ready_benchmarks")


def _parse_readiness_boundary(
    payload: Mapping[str, object],
) -> SplitControlReadinessBoundary:
    fields = {
        "codex_auth_sync_allowed",
        "credential_sync_allowed",
        "remote_codex_invocation_allowed",
        "remote_codex_acp_invocation_allowed",
        "remote_model_api_invocation_allowed",
        "raw_task_material_public",
        "upload_allowed",
        "submit_allowed",
    }
    _exact_keys(payload, "boundary", fields)
    for field in fields:
        _bool(payload, field)
    return SplitControlReadinessBoundary(
        codex_auth_sync_allowed=_bool(payload, "codex_auth_sync_allowed"),
        credential_sync_allowed=_bool(payload, "credential_sync_allowed"),
        remote_codex_invocation_allowed=_bool(
            payload,
            "remote_codex_invocation_allowed",
        ),
        remote_model_api_invocation_allowed=_bool(
            payload,
            "remote_model_api_invocation_allowed",
        ),
        raw_task_material_public=_bool(payload, "raw_task_material_public"),
    )


def _parse_local_driver_facts(
    value: object,
    *,
    field: str,
) -> BenchmarkLocalDriverFacts | None:
    if value is None:
        return None
    payload = _mapping(value, field)
    _allowed_keys(
        payload,
        field,
        required={"ready"},
        optional={"driver_label", "owns", "remote_request_fields", "keeps_local"},
    )
    return BenchmarkLocalDriverFacts(
        ready=_bool(payload, "ready"),
        driver_label=_optional_text(payload, "driver_label"),
        owns=_optional_text_tuple(payload, "owns"),
        remote_request_fields=_optional_text_tuple(payload, "remote_request_fields"),
        keeps_local=_optional_text_tuple(payload, "keeps_local"),
    )


def _parse_remote_sandbox_facts(
    value: object,
    *,
    field: str,
) -> BenchmarkRemoteSandboxFacts | None:
    if value is None:
        return None
    payload = _mapping(value, field)
    _allowed_keys(
        payload,
        field,
        required={"ready"},
        optional={
            "sandbox_label",
            "owns",
            "allowed_actions",
            "disallowed_actions",
            "returns",
        },
    )
    return BenchmarkRemoteSandboxFacts(
        ready=_bool(payload, "ready"),
        sandbox_label=_optional_text(payload, "sandbox_label"),
        owns=_optional_text_tuple(payload, "owns"),
        allowed_actions=_optional_text_tuple(payload, "allowed_actions"),
        disallowed_actions=_optional_text_tuple(payload, "disallowed_actions"),
        returns=_optional_text_tuple(payload, "returns"),
    )


def _readiness_payload(value: SplitControlReadiness) -> dict[str, object]:
    return {
        "route": {
            "status": value.route.status.value,
            "default_for_cloud_host_runs": value.route.default_for_cloud_host_runs,
            "local_agent_owns": list(value.route.local_agent_owns),
            "remote_executor_owns": list(value.route.remote_executor_owns),
        },
        "readiness_matrix": {
            "next_ready_batch_benchmark_ids": list(
                value.readiness_matrix.next_ready_batch_benchmark_ids
            ),
        },
        "boundary": {
            "codex_auth_sync_allowed": value.boundary.codex_auth_sync_allowed,
            "credential_sync_allowed": value.boundary.credential_sync_allowed,
            "remote_codex_invocation_allowed": (
                value.boundary.remote_codex_invocation_allowed
            ),
            "remote_model_api_invocation_allowed": (
                value.boundary.remote_model_api_invocation_allowed
            ),
            "raw_task_material_public": value.boundary.raw_task_material_public,
        },
    }


def _command_adapter_payload(
    adapters: tuple[BenchmarkCommandAdapterFacts, ...],
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for item in adapters:
        row: dict[str, object] = {
            "command_adapter_ready": item.command_adapter_ready,
            "result_reducer_ready": item.result_reducer_ready,
            "known_blockers": list(item.known_blockers),
            "handle_fields": list(item.handle_fields),
        }
        if item.command_adapter_status is not None:
            row["command_adapter_status"] = item.command_adapter_status
        if item.entrypoint_label is not None:
            row["entrypoint_label"] = item.entrypoint_label
        if item.remote_materializer_ready is not None:
            row["remote_materializer_ready"] = item.remote_materializer_ready
        if item.surface_contract is not None:
            row["surface_contract"] = {
                "remote_materializer_ready": (
                    item.surface_contract.remote_materializer_ready
                )
            }
        if item.local_driver_contract is not None:
            local = item.local_driver_contract
            row["local_driver_contract"] = {
                "ready": local.ready,
                **(
                    {"driver_label": local.driver_label}
                    if local.driver_label is not None
                    else {}
                ),
                "owns": list(local.owns),
                "remote_request_fields": list(local.remote_request_fields),
                "keeps_local": list(local.keeps_local),
            }
        if item.remote_sandbox_contract is not None:
            remote = item.remote_sandbox_contract
            row["remote_sandbox_contract"] = {
                "ready": remote.ready,
                **(
                    {"sandbox_label": remote.sandbox_label}
                    if remote.sandbox_label is not None
                    else {}
                ),
                "owns": list(remote.owns),
                "allowed_actions": list(remote.allowed_actions),
                "disallowed_actions": list(remote.disallowed_actions),
                "returns": list(remote.returns),
            }
        if item.result_reducer_label is not None:
            row["result_reducer_label"] = item.result_reducer_label
        payload[item.benchmark_id] = row
    return payload


def _execution_seam(payload: Mapping[str, object]) -> SplitControlExecutionSeam:
    _provider_exact_keys(
        payload,
        "execution_seam",
        {
            "schema_version",
            "source_schema_version",
            "route_status",
            "default_for_cloud_host_runs",
            "ready_to_execute",
            "ready_to_spend",
            "blockers",
            "missing_command_adapter_ids",
            "missing_remote_materializer_ids",
            "missing_result_reducer_ids",
            "planned_benchmark_ids",
            "execution_cases",
            "post_launch_evidence",
            "post_launch_evidence_boundary",
            "boundary",
            "next_action",
        },
    )
    cases = tuple(
        _execution_case(_mapping(item, f"execution_cases[{index}]"))
        for index, item in enumerate(_sequence(payload, "execution_cases"))
    )
    if _sequence(payload, "post_launch_evidence"):
        raise _invalid("post_launch_evidence")
    return SplitControlExecutionSeam(
        schema_version=_text(payload, "schema_version"),
        source_schema_version=_text(payload, "source_schema_version"),
        route_status=_enum(SplitControlRouteStatus, payload, "route_status"),
        default_for_cloud_host_runs=_bool(payload, "default_for_cloud_host_runs"),
        ready_to_execute=_bool(payload, "ready_to_execute"),
        ready_to_spend=_bool(payload, "ready_to_spend"),
        blockers=_text_tuple(payload, "blockers"),
        missing_command_adapter_ids=_text_tuple(
            payload,
            "missing_command_adapter_ids",
        ),
        missing_remote_materializer_ids=_text_tuple(
            payload,
            "missing_remote_materializer_ids",
        ),
        missing_result_reducer_ids=_text_tuple(
            payload,
            "missing_result_reducer_ids",
        ),
        planned_benchmark_ids=_text_tuple(payload, "planned_benchmark_ids"),
        execution_cases=cases,
        post_launch_evidence_boundary=_post_launch_boundary(
            _child(payload, "post_launch_evidence_boundary")
        ),
        boundary=_execution_boundary(_child(payload, "boundary")),
        next_action=_text(payload, "next_action"),
    )


def _execution_case(payload: Mapping[str, object]) -> BenchmarkExecutionCase:
    _provider_exact_keys(
        payload,
        "execution_case",
        {
            "benchmark_id",
            "route",
            "execution_mode",
            "command_label",
            "ready_to_execute_remote_command",
            "blockers",
            "command_materialization",
            "local_driver_contract",
            "remote_sandbox_contract",
            "execution_handle_contract",
            "result_reducer",
            "remote_executor_allowed_actions",
            "remote_executor_disallowed_actions",
            "raw_material_allowed",
            "upload_allowed",
            "submit_allowed",
        },
    )
    materialization = _child(payload, "command_materialization")
    local = _child(payload, "local_driver_contract")
    remote = _child(payload, "remote_sandbox_contract")
    handle = _child(payload, "execution_handle_contract")
    reducer = _child(payload, "result_reducer")
    _provider_exact_keys(
        materialization,
        "command_materialization",
        {
            "ready",
            "adapter_facts_ready",
            "status",
            "entrypoint_label",
            "remote_materializer_ready",
            "shell_command_embedded",
            "argv_embedded",
            "host_path_embedded",
        },
    )
    _provider_exact_keys(
        local,
        "local_driver_contract",
        {
            "ready",
            "driver_label",
            "owns",
            "remote_request_fields",
            "keeps_local",
            "credential_sync_allowed",
            "remote_model_invocation_allowed",
            "raw_task_text_sent_to_remote",
            "shell_command_embedded",
            "argv_embedded",
        },
    )
    _provider_exact_keys(
        remote,
        "remote_sandbox_contract",
        {
            "ready",
            "sandbox_label",
            "owns",
            "allowed_actions",
            "disallowed_actions",
            "returns",
            "remote_agent_runtime_allowed",
            "remote_codex_runtime_allowed",
            "remote_model_api_invocation_allowed",
            "raw_logs_public",
            "raw_trajectory_public",
        },
    )
    _provider_exact_keys(
        handle,
        "execution_handle_contract",
        {
            "required_fields",
            "handle_values_may_be_private",
            "public_handle_shape_only",
        },
    )
    _provider_exact_keys(
        reducer,
        "result_reducer",
        {"ready", "label", "accepted_public_fields", "raw_values_copied"},
    )
    return BenchmarkExecutionCase(
        benchmark_id=_text(payload, "benchmark_id"),
        route=_enum(SplitControlRouteMode, payload, "route"),
        execution_mode=_text(payload, "execution_mode"),
        command_label=_text(payload, "command_label"),
        ready_to_execute_remote_command=_bool(
            payload,
            "ready_to_execute_remote_command",
        ),
        blockers=_text_tuple(payload, "blockers"),
        command_materialization=BenchmarkCommandMaterialization(
            ready=_bool(materialization, "ready"),
            adapter_facts_ready=_bool(materialization, "adapter_facts_ready"),
            status=_text(materialization, "status"),
            entrypoint_label=_text(materialization, "entrypoint_label"),
            remote_materializer_ready=_bool(
                materialization,
                "remote_materializer_ready",
            ),
            shell_command_embedded=_bool(
                materialization,
                "shell_command_embedded",
            ),
            argv_embedded=_bool(materialization, "argv_embedded"),
            host_path_embedded=_bool(materialization, "host_path_embedded"),
        ),
        local_driver_contract=BenchmarkLocalDriverContract(
            ready=_bool(local, "ready"),
            driver_label=_text(local, "driver_label"),
            owns=_text_tuple(local, "owns"),
            remote_request_fields=_text_tuple(local, "remote_request_fields"),
            keeps_local=_text_tuple(local, "keeps_local"),
            credential_sync_allowed=_bool(local, "credential_sync_allowed"),
            remote_model_invocation_allowed=_bool(
                local,
                "remote_model_invocation_allowed",
            ),
            raw_task_text_sent_to_remote=_bool(
                local,
                "raw_task_text_sent_to_remote",
            ),
            shell_command_embedded=_bool(local, "shell_command_embedded"),
            argv_embedded=_bool(local, "argv_embedded"),
        ),
        remote_sandbox_contract=BenchmarkRemoteSandboxContract(
            ready=_bool(remote, "ready"),
            sandbox_label=_text(remote, "sandbox_label"),
            owns=_text_tuple(remote, "owns"),
            allowed_actions=_text_tuple(remote, "allowed_actions"),
            disallowed_actions=_text_tuple(remote, "disallowed_actions"),
            returns=_text_tuple(remote, "returns"),
            remote_agent_runtime_allowed=_bool(
                remote,
                "remote_agent_runtime_allowed",
            ),
            remote_codex_runtime_allowed=_bool(
                remote,
                "remote_codex_runtime_allowed",
            ),
            remote_model_api_invocation_allowed=_bool(
                remote,
                "remote_model_api_invocation_allowed",
            ),
            raw_logs_public=_bool(remote, "raw_logs_public"),
            raw_trajectory_public=_bool(remote, "raw_trajectory_public"),
        ),
        execution_handle_contract=BenchmarkExecutionHandleContract(
            required_fields=_text_tuple(handle, "required_fields"),
            handle_values_may_be_private=_bool(
                handle,
                "handle_values_may_be_private",
            ),
            public_handle_shape_only=_bool(handle, "public_handle_shape_only"),
        ),
        result_reducer=BenchmarkResultReducer(
            ready=_bool(reducer, "ready"),
            label=_text(reducer, "label"),
            accepted_public_fields=_text_tuple(
                reducer,
                "accepted_public_fields",
            ),
            raw_values_copied=_bool(reducer, "raw_values_copied"),
        ),
        remote_executor_allowed_actions=_text_tuple(
            payload,
            "remote_executor_allowed_actions",
        ),
        remote_executor_disallowed_actions=_text_tuple(
            payload,
            "remote_executor_disallowed_actions",
        ),
        raw_material_allowed=_bool(payload, "raw_material_allowed"),
        upload_allowed=_bool(payload, "upload_allowed"),
        submit_allowed=_bool(payload, "submit_allowed"),
    )


def _post_launch_boundary(
    payload: Mapping[str, object],
) -> BenchmarkPostLaunchEvidenceBoundary:
    _provider_exact_keys(
        payload,
        "post_launch_evidence_boundary",
        {
            "public_result_fields",
            "raw_result_key_hits",
            "unexpected_case_ids",
            "unsafe_flags",
            "violations",
            "raw_result_values_copied",
        },
    )
    if _child(payload, "raw_result_key_hits"):
        raise _invalid("raw_result_key_hits")
    if _child(payload, "unsafe_flags"):
        raise _invalid("unsafe_flags")
    return BenchmarkPostLaunchEvidenceBoundary(
        public_result_fields=_text_tuple(payload, "public_result_fields"),
        unexpected_case_ids=_text_tuple(payload, "unexpected_case_ids"),
        violations=_text_tuple(payload, "violations"),
        raw_result_values_copied=_bool(payload, "raw_result_values_copied"),
    )


def _execution_boundary(
    payload: Mapping[str, object],
) -> SplitControlExecutionBoundary:
    _provider_exact_keys(
        payload,
        "boundary",
        {
            "codex_auth_stays_local",
            "credential_sync_allowed",
            "remote_codex_invocation_allowed",
            "remote_model_api_invocation_allowed",
            "raw_task_material_public",
            "upload_allowed",
            "submit_allowed",
            "fresh_readiness_recheck_required",
            "raw_task_text_public",
            "raw_logs_public",
            "raw_trajectory_public",
            "shell_commands_embedded",
            "argv_embedded",
            "local_paths_embedded",
            "remote_paths_embedded",
        },
    )
    return SplitControlExecutionBoundary(
        codex_auth_stays_local=_bool(payload, "codex_auth_stays_local"),
        credential_sync_allowed=_bool(payload, "credential_sync_allowed"),
        remote_codex_invocation_allowed=_bool(
            payload,
            "remote_codex_invocation_allowed",
        ),
        remote_model_api_invocation_allowed=_bool(
            payload,
            "remote_model_api_invocation_allowed",
        ),
        raw_task_material_public=_bool(payload, "raw_task_material_public"),
        upload_allowed=_bool(payload, "upload_allowed"),
        submit_allowed=_bool(payload, "submit_allowed"),
        fresh_readiness_recheck_required=_bool(
            payload,
            "fresh_readiness_recheck_required",
        ),
        raw_task_text_public=_bool(payload, "raw_task_text_public"),
        raw_logs_public=_bool(payload, "raw_logs_public"),
        raw_trajectory_public=_bool(payload, "raw_trajectory_public"),
        shell_commands_embedded=_bool(payload, "shell_commands_embedded"),
        argv_embedded=_bool(payload, "argv_embedded"),
        local_paths_embedded=_bool(payload, "local_paths_embedded"),
        remote_paths_embedded=_bool(payload, "remote_paths_embedded"),
    )


def _artifact_inspection(
    payload: Mapping[str, object],
) -> BenchmarkArtifactInspection:
    _provider_exact_keys(
        payload,
        "artifact_inspection",
        {
            "schema_version",
            "path_recorded",
            "allowed_to_read_count",
            "blocked_count",
            "allowed_artifact_basenames",
            "blocked_artifact_basenames",
            "blocked_reasons",
            "classifications",
            "artifact_policy",
            "public_boundary",
        },
    )
    return BenchmarkArtifactInspection(
        schema_version=_text(payload, "schema_version"),
        path_recorded=_bool(payload, "path_recorded"),
        allowed_to_read_count=_non_negative_provider_int(
            payload,
            "allowed_to_read_count",
        ),
        blocked_count=_non_negative_provider_int(payload, "blocked_count"),
        allowed_artifact_basenames=_string_tuple(
            payload,
            "allowed_artifact_basenames",
        ),
        blocked_artifact_basenames=_string_tuple(
            payload,
            "blocked_artifact_basenames",
        ),
        blocked_reasons=_reason_counts(_child(payload, "blocked_reasons")),
        classifications=tuple(
            _artifact_classification(
                _provider_mapping(item, f"classifications[{index}]")
            )
            for index, item in enumerate(_sequence(payload, "classifications"))
        ),
        artifact_policy=_artifact_policy(_child(payload, "artifact_policy")),
        public_boundary=_artifact_public_boundary(
            _child(payload, "public_boundary")
        ),
    )


def _artifact_classification(
    payload: Mapping[str, object],
) -> BenchmarkArtifactClassification:
    _provider_exact_keys(
        payload,
        "artifact_classification",
        {
            "schema_version",
            "path_recorded",
            "basename",
            "public_compact_candidate",
            "private_raw_surface",
            "first_blocker",
            "allowed_to_read",
            "recommended_action",
            "artifact_policy",
        },
    )
    return BenchmarkArtifactClassification(
        schema_version=_text(payload, "schema_version"),
        path_recorded=_bool(payload, "path_recorded"),
        basename=_string(payload, "basename"),
        public_compact_candidate=_bool(
            payload,
            "public_compact_candidate",
        ),
        private_raw_surface=_bool(payload, "private_raw_surface"),
        first_blocker=_optional_empty_enum(
            BenchmarkArtifactBlocker,
            payload,
            "first_blocker",
        ),
        allowed_to_read=_bool(payload, "allowed_to_read"),
        recommended_action=_text(payload, "recommended_action"),
        artifact_policy=_artifact_policy(_child(payload, "artifact_policy")),
    )


def _artifact_policy(payload: Mapping[str, object]) -> BenchmarkArtifactPolicy:
    _provider_exact_keys(
        payload,
        "artifact_policy",
        {
            "adapter_kind",
            "registry_backed",
            "public_filename_allowlist_count",
            "raw_private_marker_count",
        },
    )
    return BenchmarkArtifactPolicy(
        adapter_kind=_text(payload, "adapter_kind"),
        registry_backed=_bool(payload, "registry_backed"),
        public_filename_allowlist_count=_non_negative_provider_int(
            payload,
            "public_filename_allowlist_count",
        ),
        raw_private_marker_count=_non_negative_provider_int(
            payload,
            "raw_private_marker_count",
        ),
    )


def _artifact_public_boundary(
    payload: Mapping[str, object],
) -> BenchmarkArtifactPublicBoundary:
    _provider_exact_keys(
        payload,
        "artifact_public_boundary",
        {
            "full_paths_recorded",
            "raw_task_text_read",
            "trajectory_or_origin_log_read",
            "intended_use",
        },
    )
    return BenchmarkArtifactPublicBoundary(
        full_paths_recorded=_bool(payload, "full_paths_recorded"),
        raw_task_text_read=_bool(payload, "raw_task_text_read"),
        trajectory_or_origin_log_read=_bool(
            payload,
            "trajectory_or_origin_log_read",
        ),
        intended_use=_text(payload, "intended_use"),
    )


def _candidate_source_boundary(
    payload: Mapping[str, object],
) -> BenchmarkCandidateSourceBoundary:
    _provider_exact_keys(
        payload,
        "candidate_source_boundary",
        {
            "schema_version",
            "path_recorded",
            "allowed_source_count",
            "blocked_source_count",
            "clean",
            "allowed_source_basenames",
            "blocked_source_basenames",
            "blocked_reasons",
            "classifications",
            "candidate_selection_policy",
            "read_boundary",
            "next_action",
        },
    )
    return BenchmarkCandidateSourceBoundary(
        schema_version=_text(payload, "schema_version"),
        path_recorded=_bool(payload, "path_recorded"),
        allowed_source_count=_non_negative_provider_int(
            payload,
            "allowed_source_count",
        ),
        blocked_source_count=_non_negative_provider_int(
            payload,
            "blocked_source_count",
        ),
        clean=_bool(payload, "clean"),
        allowed_source_basenames=_string_tuple(
            payload,
            "allowed_source_basenames",
        ),
        blocked_source_basenames=_string_tuple(
            payload,
            "blocked_source_basenames",
        ),
        blocked_reasons=_reason_counts(_child(payload, "blocked_reasons")),
        classifications=tuple(
            _candidate_source_classification(
                _provider_mapping(item, f"classifications[{index}]")
            )
            for index, item in enumerate(_sequence(payload, "classifications"))
        ),
        candidate_selection_policy=_candidate_selection_policy(
            _child(payload, "candidate_selection_policy")
        ),
        read_boundary=_candidate_read_boundary(
            _child(payload, "read_boundary")
        ),
        next_action=_text(payload, "next_action"),
    )


def _candidate_source_classification(
    payload: Mapping[str, object],
) -> BenchmarkCandidateSourceClassification:
    _provider_exact_keys(
        payload,
        "candidate_source_classification",
        {
            "schema_version",
            "path_recorded",
            "basename",
            "source_kind",
            "allowed_for_candidate_selection",
            "first_blocker",
            "recommended_action",
            "artifact_allowed_to_read",
        },
    )
    return BenchmarkCandidateSourceClassification(
        schema_version=_text(payload, "schema_version"),
        path_recorded=_bool(payload, "path_recorded"),
        basename=_string(payload, "basename"),
        source_kind=_enum(
            BenchmarkCandidateSourceKind,
            payload,
            "source_kind",
        ),
        allowed_for_candidate_selection=_bool(
            payload,
            "allowed_for_candidate_selection",
        ),
        first_blocker=_optional_empty_enum(
            BenchmarkCandidateSourceBlocker,
            payload,
            "first_blocker",
        ),
        recommended_action=_text(payload, "recommended_action"),
        artifact_allowed_to_read=_bool(
            payload,
            "artifact_allowed_to_read",
        ),
    )


def _candidate_selection_policy(
    payload: Mapping[str, object],
) -> BenchmarkCandidateSelectionPolicy:
    _provider_exact_keys(
        payload,
        "candidate_selection_policy",
        {
            "allowed_source_kinds",
            "disallowed_source_kinds",
            "safe_private_artifact_glob",
        },
    )
    return BenchmarkCandidateSelectionPolicy(
        allowed_source_kinds=_text_tuple(payload, "allowed_source_kinds"),
        disallowed_source_kinds=_text_tuple(
            payload,
            "disallowed_source_kinds",
        ),
        safe_private_artifact_glob=_text(
            payload,
            "safe_private_artifact_glob",
        ),
    )


def _candidate_read_boundary(
    payload: Mapping[str, object],
) -> BenchmarkCandidateReadBoundary:
    _provider_exact_keys(
        payload,
        "candidate_read_boundary",
        {
            "files_opened",
            "raw_artifacts_read",
            "task_text_read",
            "trajectory_read",
            "codex_transcript_read",
            "local_paths_recorded",
        },
    )
    return BenchmarkCandidateReadBoundary(
        files_opened=_bool(payload, "files_opened"),
        raw_artifacts_read=_bool(payload, "raw_artifacts_read"),
        task_text_read=_bool(payload, "task_text_read"),
        trajectory_read=_bool(payload, "trajectory_read"),
        codex_transcript_read=_bool(payload, "codex_transcript_read"),
        local_paths_recorded=_bool(payload, "local_paths_recorded"),
    )


def _parity_check(payload: Mapping[str, object]) -> BenchmarkParityCheck:
    _provider_exact_keys(
        payload,
        "parity_check",
        {
            "schema_version",
            "parity_target",
            "benchmark_id",
            "mode",
            "route",
            "product_mode",
            "evidence_checks",
            "safety_checks",
            "loopx_cli_call_counts",
            "stateful_lifecycle_counts",
            "missing_required_cli_calls",
            "case_goal_state",
            "missing_evidence",
            "safety_failures",
            "full_product_claim_allowed",
            "claim_level",
            "read_boundary",
        },
    )
    return BenchmarkParityCheck(
        schema_version=_text(payload, "schema_version"),
        parity_target=_text(payload, "parity_target"),
        benchmark_id=_string(payload, "benchmark_id"),
        mode=_string(payload, "mode"),
        route=_string(payload, "route"),
        product_mode=_bool(payload, "product_mode"),
        evidence_checks=_parity_evidence_checks(
            _child(payload, "evidence_checks")
        ),
        safety_checks=_parity_safety_checks(_child(payload, "safety_checks")),
        loopx_cli_call_counts=_parity_call_counts(
            _child(payload, "loopx_cli_call_counts")
        ),
        stateful_lifecycle_counts=_parity_state_counts(
            _child(payload, "stateful_lifecycle_counts")
        ),
        missing_required_cli_calls=_enum_tuple_from_sequence(
            BenchmarkParityRequiredCall,
            _sequence(payload, "missing_required_cli_calls"),
            "missing_required_cli_calls",
        ),
        case_goal_state=_parity_case_goal_state(
            _child(payload, "case_goal_state")
        ),
        missing_evidence=_enum_tuple_from_sequence(
            BenchmarkParityEvidenceKind,
            _sequence(payload, "missing_evidence"),
            "missing_evidence",
        ),
        safety_failures=_enum_tuple_from_sequence(
            BenchmarkParitySafetyKind,
            _sequence(payload, "safety_failures"),
            "safety_failures",
        ),
        full_product_claim_allowed=_bool(
            payload,
            "full_product_claim_allowed",
        ),
        claim_level=_enum(BenchmarkParityClaimLevel, payload, "claim_level"),
        read_boundary=_parity_read_boundary(_child(payload, "read_boundary")),
    )


def _parity_evidence_checks(
    payload: Mapping[str, object],
) -> BenchmarkParityEvidenceChecks:
    _provider_exact_keys(
        payload,
        "parity_evidence_checks",
        {item.value for item in BenchmarkParityEvidenceKind},
    )
    return BenchmarkParityEvidenceChecks(
        canonical_case_active_state_path=_bool(
            payload,
            BenchmarkParityEvidenceKind.CANONICAL_CASE_ACTIVE_STATE_PATH.value,
        ),
        case_active_state_initialized_before_agent=_bool(
            payload,
            BenchmarkParityEvidenceKind.CASE_ACTIVE_STATE_INITIALIZED.value,
        ),
        loopx_cli_trace_present=_bool(
            payload,
            BenchmarkParityEvidenceKind.LOOPX_CLI_TRACE_PRESENT.value,
        ),
        required_loopx_cli_calls_present=_bool(
            payload,
            BenchmarkParityEvidenceKind.REQUIRED_LOOPX_CLI_CALLS_PRESENT.value,
        ),
        stateful_loopx_lifecycle_observed=_bool(
            payload,
            BenchmarkParityEvidenceKind.STATEFUL_LOOPX_LIFECYCLE_OBSERVED.value,
        ),
        codex_cli_trajectory_summary_present=_bool(
            payload,
            BenchmarkParityEvidenceKind.CODEX_CLI_TRAJECTORY_SUMMARY_PRESENT.value,
        ),
    )


def _parity_safety_checks(
    payload: Mapping[str, object],
) -> BenchmarkParitySafetyChecks:
    _provider_exact_keys(
        payload,
        "parity_safety_checks",
        {item.value for item in BenchmarkParitySafetyKind},
    )
    return BenchmarkParitySafetyChecks(
        raw_task_text_absent=_bool(
            payload,
            BenchmarkParitySafetyKind.RAW_TASK_TEXT_ABSENT.value,
        ),
        raw_reward_feedback_absent=_bool(
            payload,
            BenchmarkParitySafetyKind.RAW_REWARD_FEEDBACK_ABSENT.value,
        ),
        raw_verifier_output_absent=_bool(
            payload,
            BenchmarkParitySafetyKind.RAW_VERIFIER_OUTPUT_ABSENT.value,
        ),
        raw_agent_trajectory_absent=_bool(
            payload,
            BenchmarkParitySafetyKind.RAW_AGENT_TRAJECTORY_ABSENT.value,
        ),
    )


def _parity_call_counts(
    payload: Mapping[str, object],
) -> BenchmarkParityCliCallCounts:
    fields = {
        "status",
        "quota_should_run",
        "todo_list",
        "history",
        "check",
        "todo_claim",
        "todo_update",
        "refresh_state",
        "quota_spend",
        "case_result",
        "total",
    }
    _provider_exact_keys(payload, "parity_call_counts", fields)
    values = {
        field: _non_negative_provider_int(payload, field) for field in fields
    }
    return BenchmarkParityCliCallCounts(**values)


def _parity_state_counts(
    payload: Mapping[str, object],
) -> BenchmarkParityStatefulLifecycleCounts:
    _provider_exact_keys(payload, "parity_state_counts", {"state_reads", "state_writes"})
    return BenchmarkParityStatefulLifecycleCounts(
        state_reads=_non_negative_provider_int(payload, "state_reads"),
        state_writes=_non_negative_provider_int(payload, "state_writes"),
    )


def _parity_case_goal_state(
    payload: Mapping[str, object],
) -> BenchmarkParityCaseGoalState:
    _provider_exact_keys(
        payload,
        "parity_case_goal_state",
        {
            "init_required",
            "initialized_before_agent",
            "canonical_path_present",
            "path_kind",
        },
    )
    return BenchmarkParityCaseGoalState(
        init_required=_bool(payload, "init_required"),
        initialized_before_agent=_bool(payload, "initialized_before_agent"),
        canonical_path_present=_bool(payload, "canonical_path_present"),
        path_kind=_enum(BenchmarkParityCasePathKind, payload, "path_kind"),
    )


def _parity_read_boundary(
    payload: Mapping[str, object],
) -> BenchmarkParityReadBoundary:
    _provider_exact_keys(
        payload,
        "parity_read_boundary",
        {
            "compact_benchmark_run_only",
            "raw_task_text_read",
            "raw_logs_read",
            "raw_trajectory_read",
            "verifier_output_read",
            "credentials_read",
            "local_paths_recorded",
        },
    )
    return BenchmarkParityReadBoundary(
        compact_benchmark_run_only=_bool(
            payload,
            "compact_benchmark_run_only",
        ),
        raw_task_text_read=_bool(payload, "raw_task_text_read"),
        raw_logs_read=_bool(payload, "raw_logs_read"),
        raw_trajectory_read=_bool(payload, "raw_trajectory_read"),
        verifier_output_read=_bool(payload, "verifier_output_read"),
        credentials_read=_bool(payload, "credentials_read"),
        local_paths_recorded=_bool(payload, "local_paths_recorded"),
    )


def _reason_counts(
    payload: Mapping[str, object],
) -> tuple[BenchmarkReasonCount, ...]:
    counts: list[BenchmarkReasonCount] = []
    for reason, raw_count in payload.items():
        if not isinstance(reason, str) or not reason.strip():
            raise _invalid("blocked_reasons.key")
        if (
            isinstance(raw_count, bool)
            or not isinstance(raw_count, int)
            or raw_count <= 0
        ):
            raise _invalid(f"blocked_reasons.{reason}")
        counts.append(BenchmarkReasonCount(reason=reason, count=raw_count))
    return tuple(counts)


def _non_negative_provider_int(
    payload: Mapping[str, object],
    field: str,
) -> int:
    value = _int(payload, field)
    if value < 0:
        raise _invalid(field)
    return value


def _string(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise _invalid(field)
    return value


def _string_tuple(
    payload: Mapping[str, object],
    field: str,
) -> tuple[str, ...]:
    values = _sequence(payload, field)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str):
            raise _invalid(f"{field}[{index}]")
        result.append(value)
    return tuple(result)


def _optional_empty_enum(
    enum_type: type[EnumT],
    payload: Mapping[str, object],
    field: str,
) -> EnumT | None:
    value = _string(payload, field)
    if not value:
        return None
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _invalid(field) from exc


def _enum_tuple_from_sequence(
    enum_type: type[EnumT],
    values: Sequence[object],
    field: str,
) -> tuple[EnumT, ...]:
    result: list[EnumT] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise _invalid(f"{field}[{index}]")
        try:
            result.append(enum_type(value))
        except ValueError as exc:
            raise _invalid(f"{field}[{index}]") from exc
    return tuple(result)


def _invalid(field: str) -> StateUnavailable:
    return StateUnavailable(details={"resource": "benchmark", "field": field})


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationFailed(details={"field": field})
    return value


def _child(payload: Mapping[str, object], field: str) -> Mapping[str, object]:
    value = payload.get(field)
    if not isinstance(value, Mapping):
        raise _invalid(field)
    return value


def _sequence(payload: Mapping[str, object], field: str) -> Sequence[object]:
    value = payload.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid(field)
    return value


def _text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field)
    return value


def _optional_text(payload: Mapping[str, object], field: str) -> str | None:
    if payload.get(field) is None:
        return None
    return _text(payload, field)


def _bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise _invalid(field)
    return value


def _optional_bool(payload: Mapping[str, object], field: str) -> bool | None:
    if payload.get(field) is None:
        return None
    return _bool(payload, field)


def _int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field)
    return value


def _text_tuple(payload: Mapping[str, object], field: str) -> tuple[str, ...]:
    return _text_sequence(_sequence(payload, field), field)


def _optional_text_tuple(
    payload: Mapping[str, object],
    field: str,
) -> tuple[str, ...]:
    if payload.get(field) is None:
        return ()
    return _text_tuple(payload, field)


def _text_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid(field)
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise _invalid(f"{field}[{index}]")
        result.append(item)
    return tuple(result)


EnumT = TypeVar("EnumT")


def _enum(
    enum_type: type[EnumT],
    payload: Mapping[str, object],
    field: str,
) -> EnumT:
    try:
        return enum_type(_text(payload, field))
    except ValueError as exc:
        raise _invalid(field) from exc


def _exact_keys(
    payload: Mapping[str, object],
    field: str,
    expected: set[str],
) -> None:
    actual = set(payload)
    if actual != expected:
        raise ValidationFailed(
            details={
                "field": field,
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            }
        )


def _allowed_keys(
    payload: Mapping[str, object],
    field: str,
    *,
    required: set[str],
    optional: set[str],
) -> None:
    actual = set(payload)
    if not required <= actual or actual - required - optional:
        raise ValidationFailed(
            details={
                "field": field,
                "missing": sorted(required - actual),
                "unknown": sorted(actual - required - optional),
            }
        )


def _provider_exact_keys(
    payload: Mapping[str, object],
    field: str,
    expected: set[str],
) -> None:
    actual = set(payload)
    if actual != expected:
        raise StateUnavailable(
            details={
                "resource": "benchmark",
                "field": field,
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            }
        )


def _provider_mapping(
    value: object,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(field)
    return value
