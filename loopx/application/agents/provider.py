from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from loopx.worker_bridge import (
    build_active_user_intervention,
    build_active_user_intervention_from_simulator_output,
    build_worker_bridge_install_contract,
    build_worker_bridge_outcome,
)

from ..errors import StateUnavailable, ValidationFailed
from .contracts import (
    WorkerBridgeActiveUserChannelContract,
    WorkerBridgeActiveUserClaimBoundary,
    WorkerBridgeActiveUserEventType,
    WorkerBridgeActiveUserEvidenceBasis,
    WorkerBridgeActiveUserIntervention,
    WorkerBridgeActiveUserInterventionRequest,
    WorkerBridgeActiveUserNoOracleAudit,
    WorkerBridgeActiveUserPublicBoundary,
    WorkerBridgeActiveUserSimulatorIntervention,
    WorkerBridgeActiveUserSimulatorKind,
    WorkerBridgeActiveUserSimulatorOutput,
    WorkerBridgeActiveUserSimulatorOutputRequest,
    WorkerBridgeAgentArguments,
    WorkerBridgeBenchmarkRunWritebackContract,
    WorkerBridgeContractRequest,
    WorkerBridgeExternalUpdateMount,
    WorkerBridgeFrequencyBudget,
    WorkerBridgeInstallBoundary,
    WorkerBridgeInstallContract,
    WorkerBridgeInstallMode,
    WorkerBridgeMount,
    WorkerBridgeOfficialScoreStatus,
    WorkerBridgeOutcome,
    WorkerBridgeOutcomeClaimBoundary,
    WorkerBridgeOutcomeRequest,
    WorkerBridgeRequiredFixedFields,
    WorkerBridgeRetryPolicy,
    WorkerBridgeRunnerReturnStatus,
    WorkerBridgeStartMarker,
    WorkerBridgeTrace,
    WorkerBridgeTracePublicness,
    WorkerBridgeValidationScopeContract,
    WorkerBridgeVisibilityPolicy,
    WorkerBridgeWallTimePolicy,
    WorkerBridgeWritebackPublicBoundary,
)


class WorkerBridgeProvider(Protocol):
    def build_contract(
        self,
        request: WorkerBridgeContractRequest,
    ) -> WorkerBridgeInstallContract: ...

    def build_outcome(
        self,
        request: WorkerBridgeOutcomeRequest,
    ) -> WorkerBridgeOutcome: ...

    def build_active_user_intervention(
        self,
        request: WorkerBridgeActiveUserInterventionRequest,
    ) -> WorkerBridgeActiveUserIntervention: ...

    def build_active_user_simulator_output(
        self,
        request: WorkerBridgeActiveUserSimulatorOutputRequest,
    ) -> WorkerBridgeActiveUserSimulatorIntervention: ...


class CoreWorkerBridgeProvider:
    """Typed adapter over the existing pure worker-bridge builders."""

    def build_contract(
        self,
        request: WorkerBridgeContractRequest,
    ) -> WorkerBridgeInstallContract:
        payload = build_worker_bridge_install_contract(
            project_root=request.project_root,
            runtime_root=request.runtime_root,
            python_bin=request.python_bin,
            module=request.module,
            scan_path=request.scan_path,
            benchmark_run_json=request.benchmark_run_json,
            counter_trace_json=request.counter_trace_json,
            classification=request.classification,
        )
        return _install_contract(payload)

    def build_outcome(
        self,
        request: WorkerBridgeOutcomeRequest,
    ) -> WorkerBridgeOutcome:
        payload = build_worker_bridge_outcome(
            worker_loopx_cli_call_total=request.worker_cli_call_total,
            required_worker_loopx_cli_call_total_min=(
                request.required_worker_cli_call_total_min
            ),
            counter_trace_present=request.counter_trace_present,
            runner_return_completed=request.runner_return_completed,
            official_score_completed=request.official_score_completed,
            official_score_value=request.official_score_value,
            interrupted=request.interrupted,
            interrupt_reason=request.interrupt_reason,
            wall_time_seconds=request.wall_time_seconds,
            wall_time_limit_seconds=request.wall_time_limit_seconds,
            side_effect_audit_passed=request.side_effect_audit_passed,
        )
        return _outcome(payload)

    def build_active_user_intervention(
        self,
        request: WorkerBridgeActiveUserInterventionRequest,
    ) -> WorkerBridgeActiveUserIntervention:
        payload = build_active_user_intervention(
            seq=request.seq,
            message=request.message,
            trigger=request.trigger,
            channel=request.channel,
            created_after_worker_start=request.created_after_worker_start,
        )
        return _active_user_intervention(payload)

    def build_active_user_simulator_output(
        self,
        request: WorkerBridgeActiveUserSimulatorOutputRequest,
    ) -> WorkerBridgeActiveUserSimulatorIntervention:
        simulator = request.simulator_output
        audit = simulator.no_oracle_audit
        payload = build_active_user_intervention_from_simulator_output(
            seq=request.seq,
            simulator_output={
                "schema_version": simulator.schema_version,
                "simulator_kind": simulator.simulator_kind.value,
                "trigger": simulator.trigger,
                "message": simulator.message,
                "visible_evidence_basis": [
                    item.value for item in simulator.visible_evidence_basis
                ],
                "no_oracle_audit": {
                    "hidden_tests_visible": audit.hidden_tests_visible,
                    "expected_solution_visible": (
                        audit.expected_solution_visible
                    ),
                    "benchmark_answer_key_visible": (
                        audit.benchmark_answer_key_visible
                    ),
                    "credential_values_visible": (
                        audit.credential_values_visible
                    ),
                    "private_material_visible": audit.private_material_visible,
                    "solution_patch_visible": audit.solution_patch_visible,
                },
                "controller_authored_message": (
                    simulator.controller_authored_message
                ),
            },
            created_after_worker_start=request.created_after_worker_start,
        )
        return _active_user_simulator_intervention(payload)


def _install_contract(payload: Mapping[str, object]) -> WorkerBridgeInstallContract:
    _exact_keys(
        payload,
        "contract",
        {
            "ok",
            "schema_version",
            "bridge_surface",
            "install_mode",
            "runtime_policy",
            "runtime_preflight_command",
            "project_root",
            "runtime_root",
            "mounts",
            "active_user_external_update_mount",
            "command_prefix",
            "agent_kwargs",
            "benchmark_run_writeback_contract",
            "active_user_intervention_channel_contract",
            "trace",
            "boundary",
        },
    )
    mounts = _sequence(payload, "mounts")
    return WorkerBridgeInstallContract(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        bridge_surface=_text(payload, "bridge_surface"),
        install_mode=_enum(
            WorkerBridgeInstallMode,
            payload,
            "install_mode",
        ),
        runtime_policy=_text(payload, "runtime_policy"),
        runtime_preflight_command=_text(payload, "runtime_preflight_command"),
        project_root=_text(payload, "project_root"),
        runtime_root=_text(payload, "runtime_root"),
        mounts=tuple(
            _mount(_mapping(item, f"mounts[{index}]"), index=index)
            for index, item in enumerate(mounts)
        ),
        active_user_external_update_mount=_external_update_mount(
            _child(payload, "active_user_external_update_mount")
        ),
        command_prefix=_text(payload, "command_prefix"),
        agent_kwargs=_agent_arguments(_child(payload, "agent_kwargs")),
        benchmark_run_writeback_contract=_writeback_contract(
            _child(payload, "benchmark_run_writeback_contract")
        ),
        active_user_intervention_channel_contract=_active_user_contract(
            _child(payload, "active_user_intervention_channel_contract")
        ),
        trace=_trace(_child(payload, "trace")),
        boundary=_install_boundary(_child(payload, "boundary")),
    )


def _mount(payload: Mapping[str, object], *, index: int) -> WorkerBridgeMount:
    _exact_keys(payload, f"mounts[{index}]", {"type", "source", "target", "read_only"})
    return WorkerBridgeMount(
        kind=_text(payload, "type"),
        source=_text(payload, "source"),
        target=_text(payload, "target"),
        read_only=_bool(payload, "read_only"),
    )


def _external_update_mount(
    payload: Mapping[str, object],
) -> WorkerBridgeExternalUpdateMount:
    _exact_keys(
        payload,
        "active_user_external_update_mount",
        {"enabled", "target", "read_only", "raw_host_path_recorded"},
    )
    return WorkerBridgeExternalUpdateMount(
        enabled=_bool(payload, "enabled"),
        target=_optional_text(payload, "target"),
        read_only=_optional_bool(payload, "read_only"),
        raw_host_path_recorded=_bool(payload, "raw_host_path_recorded"),
    )


def _agent_arguments(payload: Mapping[str, object]) -> WorkerBridgeAgentArguments:
    _exact_keys(
        payload,
        "agent_kwargs",
        {
            "loopx_command_prefix",
            "loopx_runtime_preflight_command",
            "loopx_registry_arg",
            "loopx_runtime_root_arg",
            "loopx_scan_path",
            "loopx_benchmark_run_json",
            "loopx_benchmark_run_schema_version",
            "loopx_benchmark_run_writeback_contract",
            "loopx_counter_trace_json",
            "loopx_classification",
            "loopx_active_user_feed_jsonl",
            "loopx_active_user_observation_json",
            "loopx_active_user_observe_command",
            "loopx_active_user_channel_surface",
        },
    )
    return WorkerBridgeAgentArguments(
        command_prefix=_text(payload, "loopx_command_prefix"),
        runtime_preflight_command=_text(
            payload,
            "loopx_runtime_preflight_command",
        ),
        registry_arg=_text(payload, "loopx_registry_arg"),
        runtime_root_arg=_text(payload, "loopx_runtime_root_arg"),
        scan_path=_text(payload, "loopx_scan_path"),
        benchmark_run_json=_text(payload, "loopx_benchmark_run_json"),
        benchmark_run_schema_version=_text(
            payload,
            "loopx_benchmark_run_schema_version",
        ),
        benchmark_run_writeback_contract=_text(
            payload,
            "loopx_benchmark_run_writeback_contract",
        ),
        counter_trace_json=_text(payload, "loopx_counter_trace_json"),
        classification=_text(payload, "loopx_classification"),
        active_user_feed_jsonl=_text(payload, "loopx_active_user_feed_jsonl"),
        active_user_observation_json=_text(
            payload,
            "loopx_active_user_observation_json",
        ),
        active_user_observe_command=_text(
            payload,
            "loopx_active_user_observe_command",
        ),
        active_user_channel_surface=_text(
            payload,
            "loopx_active_user_channel_surface",
        ),
    )


def _writeback_contract(
    payload: Mapping[str, object],
) -> WorkerBridgeBenchmarkRunWritebackContract:
    _exact_keys(
        payload,
        "benchmark_run_writeback_contract",
        {
            "schema_version",
            "benchmark_run_schema_version",
            "benchmark_run_json",
            "counter_trace_json",
            "classification",
            "required_top_level_fields",
            "required_fixed_fields",
            "required_validation_flags",
            "validation_scope_contract",
            "claim_boundary_required_fields",
            "forbidden_public_fields",
            "retry_policy",
            "public_boundary",
        },
    )
    fixed = _child(payload, "required_fixed_fields")
    validation = _child(payload, "validation_scope_contract")
    retry = _child(payload, "retry_policy")
    boundary = _child(payload, "public_boundary")
    _exact_keys(fixed, "required_fixed_fields", {"real_run", "submit_eligible", "leaderboard_evidence"})
    _exact_keys(
        validation,
        "validation_scope_contract",
        {
            "field",
            "recommended_values",
            "connectivity_is_not_case_success",
            "legacy_unscoped_passed_validation_is_ambiguous",
        },
    )
    _exact_keys(
        retry,
        "retry_policy",
        {
            "on_append_benchmark_run_schema_rejected",
            "retry_payload_source",
            "do_not_retry_with_raw_logs_or_raw_paths",
        },
    )
    _exact_keys(
        boundary,
        "writeback.public_boundary",
        {
            "no_upload",
            "submit_eligible",
            "leaderboard_evidence",
            "raw_trace_excluded",
            "raw_paths_redacted",
        },
    )
    return WorkerBridgeBenchmarkRunWritebackContract(
        schema_version=_text(payload, "schema_version"),
        benchmark_run_schema_version=_text(
            payload,
            "benchmark_run_schema_version",
        ),
        benchmark_run_json=_text(payload, "benchmark_run_json"),
        counter_trace_json=_text(payload, "counter_trace_json"),
        classification=_text(payload, "classification"),
        required_top_level_fields=_text_tuple(
            payload,
            "required_top_level_fields",
        ),
        required_fixed_fields=WorkerBridgeRequiredFixedFields(
            real_run=_bool(fixed, "real_run"),
            submit_eligible=_bool(fixed, "submit_eligible"),
            leaderboard_evidence=_bool(fixed, "leaderboard_evidence"),
        ),
        required_validation_flags=_text_tuple(
            payload,
            "required_validation_flags",
        ),
        validation_scope_contract=WorkerBridgeValidationScopeContract(
            field=_text(validation, "field"),
            recommended_values=_text_tuple(validation, "recommended_values"),
            connectivity_is_not_case_success=_bool(
                validation,
                "connectivity_is_not_case_success",
            ),
            legacy_unscoped_passed_validation_is_ambiguous=_bool(
                validation,
                "legacy_unscoped_passed_validation_is_ambiguous",
            ),
        ),
        claim_boundary_required_fields=_text_tuple(
            payload,
            "claim_boundary_required_fields",
        ),
        forbidden_public_fields=_text_tuple(payload, "forbidden_public_fields"),
        retry_policy=WorkerBridgeRetryPolicy(
            on_append_benchmark_run_schema_rejected=_text(
                retry,
                "on_append_benchmark_run_schema_rejected",
            ),
            retry_payload_source=_text(retry, "retry_payload_source"),
            do_not_retry_with_raw_logs_or_raw_paths=_bool(
                retry,
                "do_not_retry_with_raw_logs_or_raw_paths",
            ),
        ),
        public_boundary=WorkerBridgeWritebackPublicBoundary(
            no_upload=_bool(boundary, "no_upload"),
            submit_eligible=_bool(boundary, "submit_eligible"),
            leaderboard_evidence=_bool(boundary, "leaderboard_evidence"),
            raw_trace_excluded=_bool(boundary, "raw_trace_excluded"),
            raw_paths_redacted=_bool(boundary, "raw_paths_redacted"),
        ),
    )


def _active_user_contract(
    payload: Mapping[str, object],
) -> WorkerBridgeActiveUserChannelContract:
    _exact_keys(
        payload,
        "active_user_intervention_channel_contract",
        {
            "ok",
            "schema_version",
            "bridge_surface",
            "channel_surface",
            "mode",
            "feed_jsonl",
            "observation_json",
            "benchmark_run_json",
            "counter_trace_json",
            "worker_observe_command",
            "simulator_append_command",
            "worker_start_marker",
            "frequency_budget",
            "visibility_policy",
            "claim_boundary",
            "public_boundary",
        },
    )
    marker = _child(payload, "worker_start_marker")
    budget = _child(payload, "frequency_budget")
    visibility = _child(payload, "visibility_policy")
    claim = _child(payload, "claim_boundary")
    boundary = _child(payload, "public_boundary")
    _exact_keys(marker, "worker_start_marker", {"kind", "proof_rule"})
    _exact_keys(
        budget,
        "frequency_budget",
        {
            "min_interval_seconds",
            "max_interventions_per_task",
            "simulator_may_be_proactive",
            "artificial_mildness_required",
        },
    )
    _exact_keys(
        visibility,
        "visibility_policy",
        {"simulator_may_read", "simulator_must_not_read"},
    )
    _exact_keys(
        claim,
        "active_user.claim_boundary",
        {
            "official_score_claim_allowed",
            "leaderboard_claim_allowed",
            "assisted_collaboration_claim_allowed",
            "direct_codex_chat_injection",
            "worker_pull_required",
        },
    )
    _exact_keys(
        boundary,
        "active_user.public_boundary",
        {
            "raw_paths_recorded",
            "raw_transcript_recorded",
            "credential_values_recorded",
            "no_upload",
        },
    )
    return WorkerBridgeActiveUserChannelContract(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        bridge_surface=_text(payload, "bridge_surface"),
        channel_surface=_text(payload, "channel_surface"),
        mode=_text(payload, "mode"),
        feed_jsonl=_text(payload, "feed_jsonl"),
        observation_json=_text(payload, "observation_json"),
        benchmark_run_json=_text(payload, "benchmark_run_json"),
        counter_trace_json=_text(payload, "counter_trace_json"),
        worker_observe_command=_text(payload, "worker_observe_command"),
        simulator_append_command=_text(payload, "simulator_append_command"),
        worker_start_marker=WorkerBridgeStartMarker(
            kind=_text(marker, "kind"),
            proof_rule=_text(marker, "proof_rule"),
        ),
        frequency_budget=WorkerBridgeFrequencyBudget(
            min_interval_seconds=_int(budget, "min_interval_seconds"),
            max_interventions_per_task=_int(
                budget,
                "max_interventions_per_task",
            ),
            simulator_may_be_proactive=_bool(
                budget,
                "simulator_may_be_proactive",
            ),
            artificial_mildness_required=_bool(
                budget,
                "artificial_mildness_required",
            ),
        ),
        visibility_policy=WorkerBridgeVisibilityPolicy(
            simulator_may_read=_text_tuple(visibility, "simulator_may_read"),
            simulator_must_not_read=_text_tuple(
                visibility,
                "simulator_must_not_read",
            ),
        ),
        claim_boundary=WorkerBridgeActiveUserClaimBoundary(
            official_score_claim_allowed=_bool(
                claim,
                "official_score_claim_allowed",
            ),
            leaderboard_claim_allowed=_bool(
                claim,
                "leaderboard_claim_allowed",
            ),
            assisted_collaboration_claim_allowed=_bool(
                claim,
                "assisted_collaboration_claim_allowed",
            ),
            direct_codex_chat_injection=_bool(
                claim,
                "direct_codex_chat_injection",
            ),
            worker_pull_required=_bool(claim, "worker_pull_required"),
        ),
        public_boundary=WorkerBridgeActiveUserPublicBoundary(
            raw_paths_recorded=_bool(boundary, "raw_paths_recorded"),
            raw_transcript_recorded=_bool(
                boundary,
                "raw_transcript_recorded",
            ),
            credential_values_recorded=_bool(
                boundary,
                "credential_values_recorded",
            ),
            no_upload=_bool(boundary, "no_upload"),
        ),
    )


def _trace(payload: Mapping[str, object]) -> WorkerBridgeTrace:
    _exact_keys(
        payload,
        "trace",
        {
            "counter_trace_json",
            "benchmark_run_json",
            "active_user_feed_jsonl",
            "active_user_observation_json",
            "write_surface",
            "raw_trace_public",
        },
    )
    return WorkerBridgeTrace(
        counter_trace_json=_text(payload, "counter_trace_json"),
        benchmark_run_json=_text(payload, "benchmark_run_json"),
        active_user_feed_jsonl=_text(payload, "active_user_feed_jsonl"),
        active_user_observation_json=_text(
            payload,
            "active_user_observation_json",
        ),
        write_surface=_text(payload, "write_surface"),
        raw_trace_public=_bool(payload, "raw_trace_public"),
    )


def _install_boundary(payload: Mapping[str, object]) -> WorkerBridgeInstallBoundary:
    _exact_keys(
        payload,
        "boundary",
        {
            "real_run",
            "submit_eligible",
            "no_upload",
            "credential_values_recorded",
            "raw_paths_required_in_public_artifacts",
        },
    )
    return WorkerBridgeInstallBoundary(
        real_run=_bool(payload, "real_run"),
        submit_eligible=_bool(payload, "submit_eligible"),
        no_upload=_bool(payload, "no_upload"),
        credential_values_recorded=_bool(payload, "credential_values_recorded"),
        raw_paths_required_in_public_artifacts=_bool(
            payload,
            "raw_paths_required_in_public_artifacts",
        ),
    )


def _outcome(payload: Mapping[str, object]) -> WorkerBridgeOutcome:
    _exact_keys(
        payload,
        "outcome",
        {
            "ok",
            "schema_version",
            "bridge_surface",
            "worker_bridge_verified",
            "runner_return_status",
            "official_score_status",
            "worker_loopx_cli_call_total",
            "required_worker_loopx_cli_call_total_min",
            "counter_trace_present",
            "runner_return_completed",
            "official_score_completed",
            "official_score_value",
            "side_effect_audit_passed",
            "wall_time_policy",
            "failure_attribution_labels",
            "claim_boundary",
            "next_action",
            "trace_publicness",
            "raw_paths_recorded",
            "raw_trace_recorded",
            "credential_values_recorded",
        },
    )
    policy = _child(payload, "wall_time_policy")
    claim = _child(payload, "claim_boundary")
    _exact_keys(
        policy,
        "wall_time_policy",
        {
            "schema_version",
            "kind",
            "wall_time_seconds",
            "wall_time_limit_seconds",
            "interrupted",
            "interrupt_reason",
            "changes_official_benchmark_timeout",
            "changes_official_task_resources",
            "leaderboard_claim_allowed",
        },
    )
    _exact_keys(
        claim,
        "outcome.claim_boundary",
        {
            "public_claim_allowed",
            "bridge_connectivity_claim_allowed",
            "case_success_claim_allowed",
            "official_score_claim_allowed",
            "leaderboard_claim_allowed",
            "forbidden_claims",
        },
    )
    return WorkerBridgeOutcome(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        bridge_surface=_text(payload, "bridge_surface"),
        worker_bridge_verified=_bool(payload, "worker_bridge_verified"),
        runner_return_status=_enum(
            WorkerBridgeRunnerReturnStatus,
            payload,
            "runner_return_status",
        ),
        official_score_status=_enum(
            WorkerBridgeOfficialScoreStatus,
            payload,
            "official_score_status",
        ),
        worker_cli_call_total=_int(payload, "worker_loopx_cli_call_total"),
        required_worker_cli_call_total_min=_int(
            payload,
            "required_worker_loopx_cli_call_total_min",
        ),
        counter_trace_present=_bool(payload, "counter_trace_present"),
        runner_return_completed=_bool(payload, "runner_return_completed"),
        official_score_completed=_bool(payload, "official_score_completed"),
        official_score_value=_optional_number(payload, "official_score_value"),
        side_effect_audit_passed=_bool(payload, "side_effect_audit_passed"),
        wall_time_policy=WorkerBridgeWallTimePolicy(
            schema_version=_text(policy, "schema_version"),
            kind=_text(policy, "kind"),
            wall_time_seconds=_optional_number(policy, "wall_time_seconds"),
            wall_time_limit_seconds=_number(policy, "wall_time_limit_seconds"),
            interrupted=_bool(policy, "interrupted"),
            interrupt_reason=_text(policy, "interrupt_reason"),
            changes_official_benchmark_timeout=_bool(
                policy,
                "changes_official_benchmark_timeout",
            ),
            changes_official_task_resources=_bool(
                policy,
                "changes_official_task_resources",
            ),
            leaderboard_claim_allowed=_bool(
                policy,
                "leaderboard_claim_allowed",
            ),
        ),
        failure_attribution_labels=_text_tuple(
            payload,
            "failure_attribution_labels",
        ),
        claim_boundary=WorkerBridgeOutcomeClaimBoundary(
            public_claim_allowed=_text(claim, "public_claim_allowed"),
            bridge_connectivity_claim_allowed=_bool(
                claim,
                "bridge_connectivity_claim_allowed",
            ),
            case_success_claim_allowed=_bool(
                claim,
                "case_success_claim_allowed",
            ),
            official_score_claim_allowed=_bool(
                claim,
                "official_score_claim_allowed",
            ),
            leaderboard_claim_allowed=_bool(
                claim,
                "leaderboard_claim_allowed",
            ),
            forbidden_claims=_text_tuple(claim, "forbidden_claims"),
        ),
        next_action=_text(payload, "next_action"),
        trace_publicness=_enum(
            WorkerBridgeTracePublicness,
            payload,
            "trace_publicness",
        ),
        raw_paths_recorded=_bool(payload, "raw_paths_recorded"),
        raw_trace_recorded=_bool(payload, "raw_trace_recorded"),
        credential_values_recorded=_bool(
            payload,
            "credential_values_recorded",
        ),
    )


_ACTIVE_USER_INTERVENTION_KEYS = {
    "ok",
    "schema_version",
    "channel_surface",
    "seq",
    "channel",
    "type",
    "trigger",
    "message",
    "created_after_worker_start",
    "oracle_free",
    "hidden_tests_visible",
    "expected_solution_visible",
    "credential_values_visible",
    "private_material_visible",
    "official_score_claim_allowed",
    "leaderboard_claim_allowed",
}
_ACTIVE_USER_SIMULATOR_KEYS = {
    "simulator_kind",
    "simulator_output_schema_version",
    "controller_authored_message",
    "formal_treatment_eligible",
    "manual_controller_feed",
    "visible_evidence_basis",
    "no_oracle_audit",
}
_ACTIVE_USER_NO_ORACLE_AUDIT_KEYS = {
    "hidden_tests_visible",
    "expected_solution_visible",
    "benchmark_answer_key_visible",
    "credential_values_visible",
    "private_material_visible",
    "solution_patch_visible",
}


def parse_active_user_simulator_output(
    payload: object,
) -> WorkerBridgeActiveUserSimulatorOutput:
    value = _input_mapping(payload, "simulator_output")
    _input_exact_keys(
        value,
        "simulator_output",
        {
            "schema_version",
            "simulator_kind",
            "trigger",
            "message",
            "visible_evidence_basis",
            "no_oracle_audit",
            "controller_authored_message",
        },
    )
    schema_version = _input_text(value, "schema_version")
    if schema_version != "loopx_active_user_simulator_output_v0":
        raise ValidationFailed(
            details={"field": "simulator_output.schema_version"}
        )
    simulator_kind = _input_enum(
        WorkerBridgeActiveUserSimulatorKind,
        value,
        "simulator_kind",
    )
    evidence = _input_sequence(value, "visible_evidence_basis")
    if not evidence:
        raise ValidationFailed(
            details={"field": "simulator_output.visible_evidence_basis"}
        )
    evidence_basis = tuple(
        _input_enum_value(
            WorkerBridgeActiveUserEvidenceBasis,
            item,
            f"visible_evidence_basis[{index}]",
        )
        for index, item in enumerate(evidence)
    )
    audit = _input_mapping(value.get("no_oracle_audit"), "no_oracle_audit")
    _input_exact_keys(
        audit,
        "no_oracle_audit",
        _ACTIVE_USER_NO_ORACLE_AUDIT_KEYS,
    )
    return WorkerBridgeActiveUserSimulatorOutput(
        schema_version=schema_version,
        simulator_kind=simulator_kind,
        trigger=_input_text(value, "trigger"),
        message=_input_text(value, "message"),
        visible_evidence_basis=evidence_basis,
        no_oracle_audit=_active_user_input_audit(audit),
        controller_authored_message=_input_bool(
            value,
            "controller_authored_message",
        ),
    )


def _active_user_intervention(
    payload: Mapping[str, object],
    *,
    additional_keys: set[str] | None = None,
) -> WorkerBridgeActiveUserIntervention:
    _exact_keys(
        payload,
        "active_user_intervention",
        _ACTIVE_USER_INTERVENTION_KEYS | (additional_keys or set()),
    )
    return WorkerBridgeActiveUserIntervention(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        channel_surface=_text(payload, "channel_surface"),
        seq=_int(payload, "seq"),
        channel=_text(payload, "channel"),
        event_type=_enum(WorkerBridgeActiveUserEventType, payload, "type"),
        trigger=_text(payload, "trigger"),
        message=_text(payload, "message"),
        created_after_worker_start=_bool(
            payload,
            "created_after_worker_start",
        ),
        oracle_free=_bool(payload, "oracle_free"),
        hidden_tests_visible=_bool(payload, "hidden_tests_visible"),
        expected_solution_visible=_bool(payload, "expected_solution_visible"),
        credential_values_visible=_bool(
            payload,
            "credential_values_visible",
        ),
        private_material_visible=_bool(payload, "private_material_visible"),
        official_score_claim_allowed=_bool(
            payload,
            "official_score_claim_allowed",
        ),
        leaderboard_claim_allowed=_bool(
            payload,
            "leaderboard_claim_allowed",
        ),
    )


def _active_user_simulator_intervention(
    payload: Mapping[str, object],
) -> WorkerBridgeActiveUserSimulatorIntervention:
    intervention = _active_user_intervention(
        payload,
        additional_keys=_ACTIVE_USER_SIMULATOR_KEYS,
    )
    audit = _child(payload, "no_oracle_audit")
    _exact_keys(
        audit,
        "active_user_intervention.no_oracle_audit",
        _ACTIVE_USER_NO_ORACLE_AUDIT_KEYS,
    )
    return WorkerBridgeActiveUserSimulatorIntervention(
        intervention=intervention,
        simulator_kind=_enum(
            WorkerBridgeActiveUserSimulatorKind,
            payload,
            "simulator_kind",
        ),
        simulator_output_schema_version=_text(
            payload,
            "simulator_output_schema_version",
        ),
        controller_authored_message=_bool(
            payload,
            "controller_authored_message",
        ),
        formal_treatment_eligible=_bool(
            payload,
            "formal_treatment_eligible",
        ),
        manual_controller_feed=_bool(payload, "manual_controller_feed"),
        visible_evidence_basis=_enum_tuple(
            WorkerBridgeActiveUserEvidenceBasis,
            payload,
            "visible_evidence_basis",
        ),
        no_oracle_audit=_active_user_audit(audit),
    )


def _active_user_audit(
    payload: Mapping[str, object],
) -> WorkerBridgeActiveUserNoOracleAudit:
    return WorkerBridgeActiveUserNoOracleAudit(
        hidden_tests_visible=_bool(payload, "hidden_tests_visible"),
        expected_solution_visible=_bool(payload, "expected_solution_visible"),
        benchmark_answer_key_visible=_bool(
            payload,
            "benchmark_answer_key_visible",
        ),
        credential_values_visible=_bool(payload, "credential_values_visible"),
        private_material_visible=_bool(payload, "private_material_visible"),
        solution_patch_visible=_bool(payload, "solution_patch_visible"),
    )


def _active_user_input_audit(
    payload: Mapping[str, object],
) -> WorkerBridgeActiveUserNoOracleAudit:
    return WorkerBridgeActiveUserNoOracleAudit(
        hidden_tests_visible=_input_bool(payload, "hidden_tests_visible"),
        expected_solution_visible=_input_bool(
            payload,
            "expected_solution_visible",
        ),
        benchmark_answer_key_visible=_input_bool(
            payload,
            "benchmark_answer_key_visible",
        ),
        credential_values_visible=_input_bool(
            payload,
            "credential_values_visible",
        ),
        private_material_visible=_input_bool(
            payload,
            "private_material_visible",
        ),
        solution_patch_visible=_input_bool(payload, "solution_patch_visible"),
    )


def _invalid(field: str) -> StateUnavailable:
    return StateUnavailable(details={"resource": "worker_bridge", "field": field})


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(field)
    return value


def _child(payload: Mapping[str, object], field: str) -> Mapping[str, object]:
    return _mapping(payload.get(field), field)


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
    value = payload.get(field)
    if value is None:
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


def _number(payload: Mapping[str, object], field: str) -> int | float:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(field)
    return value


def _optional_number(
    payload: Mapping[str, object],
    field: str,
) -> int | float | None:
    if payload.get(field) is None:
        return None
    return _number(payload, field)


def _text_tuple(payload: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = _sequence(payload, field)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise _invalid(f"{field}[{index}]")
        result.append(value)
    return tuple(result)


def _enum_tuple(
    enum_type: type[EnumT],
    payload: Mapping[str, object],
    field: str,
) -> tuple[EnumT, ...]:
    values = _sequence(payload, field)
    return tuple(
        _enum_value(enum_type, value, f"{field}[{index}]")
        for index, value in enumerate(values)
    )


def _exact_keys(
    payload: Mapping[str, object],
    field: str,
    expected: set[str],
) -> None:
    actual = set(payload)
    if actual != expected:
        raise StateUnavailable(
            details={
                "resource": "worker_bridge",
                "field": field,
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            }
        )


EnumT = TypeVar("EnumT")


def _enum(
    enum_type: type[EnumT],
    payload: Mapping[str, object],
    field: str,
) -> EnumT:
    value = _text(payload, field)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _invalid(field) from exc


def _enum_value(
    enum_type: type[EnumT],
    value: object,
    field: str,
) -> EnumT:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field)
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _invalid(field) from exc


def _input_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise ValidationFailed(details={"field": field, "reason": "must_be_object"})
    return value


def _input_sequence(
    payload: Mapping[str, object],
    field: str,
) -> Sequence[object]:
    value = payload.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationFailed(details={"field": field, "reason": "must_be_array"})
    return value


def _input_text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field, "reason": "must_be_text"})
    return value


def _input_bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ValidationFailed(details={"field": field, "reason": "must_be_bool"})
    return value


def _input_enum(
    enum_type: type[EnumT],
    payload: Mapping[str, object],
    field: str,
) -> EnumT:
    return _input_enum_value(enum_type, _input_text(payload, field), field)


def _input_enum_value(
    enum_type: type[EnumT],
    value: object,
    field: str,
) -> EnumT:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field, "reason": "must_be_text"})
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValidationFailed(
            details={"field": field, "reason": "unsupported_value"}
        ) from exc


def _input_exact_keys(
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
