from __future__ import annotations

from loopx.application.agents import (
    WorkerBridgeActiveUserIntervention,
    WorkerBridgeActiveUserSimulatorIntervention,
    WorkerBridgeInstallContract,
    WorkerBridgeOutcome,
)
from loopx.application.benchmarks import (
    BenchmarkArtifactInspection,
    BenchmarkArtifactPolicy,
    BenchmarkCandidateSourceBoundary,
    BenchmarkParityCheck,
    SplitControlExecutionSeam,
)
from loopx.application.maintenance import (
    CanaryProfilesResult,
    CanarySmokeProfilesResult,
)


def worker_bridge_contract_payload(
    result: WorkerBridgeInstallContract,
) -> dict[str, object]:
    writeback = result.benchmark_run_writeback_contract
    active = result.active_user_intervention_channel_contract
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "bridge_surface": result.bridge_surface,
        "install_mode": result.install_mode.value,
        "runtime_policy": result.runtime_policy,
        "runtime_preflight_command": result.runtime_preflight_command,
        "project_root": result.project_root,
        "runtime_root": result.runtime_root,
        "mounts": [
            {
                "type": item.kind,
                "source": item.source,
                "target": item.target,
                "read_only": item.read_only,
            }
            for item in result.mounts
        ],
        "active_user_external_update_mount": {
            "enabled": result.active_user_external_update_mount.enabled,
            "target": result.active_user_external_update_mount.target,
            "read_only": result.active_user_external_update_mount.read_only,
            "raw_host_path_recorded": (
                result.active_user_external_update_mount.raw_host_path_recorded
            ),
        },
        "command_prefix": result.command_prefix,
        "agent_kwargs": {
            "loopx_command_prefix": result.agent_kwargs.command_prefix,
            "loopx_runtime_preflight_command": (
                result.agent_kwargs.runtime_preflight_command
            ),
            "loopx_registry_arg": result.agent_kwargs.registry_arg,
            "loopx_runtime_root_arg": result.agent_kwargs.runtime_root_arg,
            "loopx_scan_path": result.agent_kwargs.scan_path,
            "loopx_benchmark_run_json": result.agent_kwargs.benchmark_run_json,
            "loopx_benchmark_run_schema_version": (
                result.agent_kwargs.benchmark_run_schema_version
            ),
            "loopx_benchmark_run_writeback_contract": (
                result.agent_kwargs.benchmark_run_writeback_contract
            ),
            "loopx_counter_trace_json": result.agent_kwargs.counter_trace_json,
            "loopx_classification": result.agent_kwargs.classification,
            "loopx_active_user_feed_jsonl": (
                result.agent_kwargs.active_user_feed_jsonl
            ),
            "loopx_active_user_observation_json": (
                result.agent_kwargs.active_user_observation_json
            ),
            "loopx_active_user_observe_command": (
                result.agent_kwargs.active_user_observe_command
            ),
            "loopx_active_user_channel_surface": (
                result.agent_kwargs.active_user_channel_surface
            ),
        },
        "benchmark_run_writeback_contract": {
            "schema_version": writeback.schema_version,
            "benchmark_run_schema_version": writeback.benchmark_run_schema_version,
            "benchmark_run_json": writeback.benchmark_run_json,
            "counter_trace_json": writeback.counter_trace_json,
            "classification": writeback.classification,
            "required_top_level_fields": list(writeback.required_top_level_fields),
            "required_fixed_fields": {
                "real_run": writeback.required_fixed_fields.real_run,
                "submit_eligible": writeback.required_fixed_fields.submit_eligible,
                "leaderboard_evidence": (
                    writeback.required_fixed_fields.leaderboard_evidence
                ),
            },
            "required_validation_flags": list(
                writeback.required_validation_flags
            ),
            "validation_scope_contract": {
                "field": writeback.validation_scope_contract.field,
                "recommended_values": list(
                    writeback.validation_scope_contract.recommended_values
                ),
                "connectivity_is_not_case_success": (
                    writeback.validation_scope_contract.connectivity_is_not_case_success
                ),
                "legacy_unscoped_passed_validation_is_ambiguous": (
                    writeback.validation_scope_contract.legacy_unscoped_passed_validation_is_ambiguous
                ),
            },
            "claim_boundary_required_fields": list(
                writeback.claim_boundary_required_fields
            ),
            "forbidden_public_fields": list(writeback.forbidden_public_fields),
            "retry_policy": {
                "on_append_benchmark_run_schema_rejected": (
                    writeback.retry_policy.on_append_benchmark_run_schema_rejected
                ),
                "retry_payload_source": writeback.retry_policy.retry_payload_source,
                "do_not_retry_with_raw_logs_or_raw_paths": (
                    writeback.retry_policy.do_not_retry_with_raw_logs_or_raw_paths
                ),
            },
            "public_boundary": {
                "no_upload": writeback.public_boundary.no_upload,
                "submit_eligible": writeback.public_boundary.submit_eligible,
                "leaderboard_evidence": (
                    writeback.public_boundary.leaderboard_evidence
                ),
                "raw_trace_excluded": writeback.public_boundary.raw_trace_excluded,
                "raw_paths_redacted": writeback.public_boundary.raw_paths_redacted,
            },
        },
        "active_user_intervention_channel_contract": {
            "ok": active.ok,
            "schema_version": active.schema_version,
            "bridge_surface": active.bridge_surface,
            "channel_surface": active.channel_surface,
            "mode": active.mode,
            "feed_jsonl": active.feed_jsonl,
            "observation_json": active.observation_json,
            "benchmark_run_json": active.benchmark_run_json,
            "counter_trace_json": active.counter_trace_json,
            "worker_observe_command": active.worker_observe_command,
            "simulator_append_command": active.simulator_append_command,
            "worker_start_marker": {
                "kind": active.worker_start_marker.kind,
                "proof_rule": active.worker_start_marker.proof_rule,
            },
            "frequency_budget": {
                "min_interval_seconds": active.frequency_budget.min_interval_seconds,
                "max_interventions_per_task": (
                    active.frequency_budget.max_interventions_per_task
                ),
                "simulator_may_be_proactive": (
                    active.frequency_budget.simulator_may_be_proactive
                ),
                "artificial_mildness_required": (
                    active.frequency_budget.artificial_mildness_required
                ),
            },
            "visibility_policy": {
                "simulator_may_read": list(
                    active.visibility_policy.simulator_may_read
                ),
                "simulator_must_not_read": list(
                    active.visibility_policy.simulator_must_not_read
                ),
            },
            "claim_boundary": {
                "official_score_claim_allowed": (
                    active.claim_boundary.official_score_claim_allowed
                ),
                "leaderboard_claim_allowed": (
                    active.claim_boundary.leaderboard_claim_allowed
                ),
                "assisted_collaboration_claim_allowed": (
                    active.claim_boundary.assisted_collaboration_claim_allowed
                ),
                "direct_codex_chat_injection": (
                    active.claim_boundary.direct_codex_chat_injection
                ),
                "worker_pull_required": active.claim_boundary.worker_pull_required,
            },
            "public_boundary": {
                "raw_paths_recorded": active.public_boundary.raw_paths_recorded,
                "raw_transcript_recorded": (
                    active.public_boundary.raw_transcript_recorded
                ),
                "credential_values_recorded": (
                    active.public_boundary.credential_values_recorded
                ),
                "no_upload": active.public_boundary.no_upload,
            },
        },
        "trace": {
            "counter_trace_json": result.trace.counter_trace_json,
            "benchmark_run_json": result.trace.benchmark_run_json,
            "active_user_feed_jsonl": result.trace.active_user_feed_jsonl,
            "active_user_observation_json": (
                result.trace.active_user_observation_json
            ),
            "write_surface": result.trace.write_surface,
            "raw_trace_public": result.trace.raw_trace_public,
        },
        "boundary": {
            "real_run": result.boundary.real_run,
            "submit_eligible": result.boundary.submit_eligible,
            "no_upload": result.boundary.no_upload,
            "credential_values_recorded": (
                result.boundary.credential_values_recorded
            ),
            "raw_paths_required_in_public_artifacts": (
                result.boundary.raw_paths_required_in_public_artifacts
            ),
        },
    }


def worker_bridge_outcome_payload(result: WorkerBridgeOutcome) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "bridge_surface": result.bridge_surface,
        "worker_bridge_verified": result.worker_bridge_verified,
        "runner_return_status": result.runner_return_status.value,
        "official_score_status": result.official_score_status.value,
        "worker_loopx_cli_call_total": result.worker_cli_call_total,
        "required_worker_loopx_cli_call_total_min": (
            result.required_worker_cli_call_total_min
        ),
        "counter_trace_present": result.counter_trace_present,
        "runner_return_completed": result.runner_return_completed,
        "official_score_completed": result.official_score_completed,
        "official_score_value": result.official_score_value,
        "side_effect_audit_passed": result.side_effect_audit_passed,
        "wall_time_policy": {
            "schema_version": result.wall_time_policy.schema_version,
            "kind": result.wall_time_policy.kind,
            "wall_time_seconds": result.wall_time_policy.wall_time_seconds,
            "wall_time_limit_seconds": result.wall_time_policy.wall_time_limit_seconds,
            "interrupted": result.wall_time_policy.interrupted,
            "interrupt_reason": result.wall_time_policy.interrupt_reason,
            "changes_official_benchmark_timeout": (
                result.wall_time_policy.changes_official_benchmark_timeout
            ),
            "changes_official_task_resources": (
                result.wall_time_policy.changes_official_task_resources
            ),
            "leaderboard_claim_allowed": (
                result.wall_time_policy.leaderboard_claim_allowed
            ),
        },
        "failure_attribution_labels": list(result.failure_attribution_labels),
        "claim_boundary": {
            "public_claim_allowed": result.claim_boundary.public_claim_allowed,
            "bridge_connectivity_claim_allowed": (
                result.claim_boundary.bridge_connectivity_claim_allowed
            ),
            "case_success_claim_allowed": (
                result.claim_boundary.case_success_claim_allowed
            ),
            "official_score_claim_allowed": (
                result.claim_boundary.official_score_claim_allowed
            ),
            "leaderboard_claim_allowed": (
                result.claim_boundary.leaderboard_claim_allowed
            ),
            "forbidden_claims": list(result.claim_boundary.forbidden_claims),
        },
        "next_action": result.next_action,
        "trace_publicness": result.trace_publicness.value,
        "raw_paths_recorded": result.raw_paths_recorded,
        "raw_trace_recorded": result.raw_trace_recorded,
        "credential_values_recorded": result.credential_values_recorded,
    }


def canary_profiles_payload(result: CanaryProfilesResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "source": result.source,
        "dry_run": result.dry_run,
        "executes_checks": result.executes_checks,
        "archetype_count": result.archetype_count,
        "profile_count": result.profile_count,
        "domain_profile_count": result.domain_profile_count,
        "archetypes": [
            {
                "id": item.archetype_id,
                "name": item.name,
                "primary_question": item.primary_question,
                "trigger_surface": item.trigger_surface,
                "fixture_depth": item.fixture_depth,
                "cost_tier": item.cost_tier,
                "failure_meaning": item.failure_meaning,
            }
            for item in result.archetypes
        ],
        "profiles": [
            {
                "schema_version": item.schema_version,
                "id": item.profile_id,
                "family": item.family,
                "pattern_ids": list(item.pattern_ids),
                "default_archetypes": [
                    {"id": reference.archetype_id, "name": reference.name}
                    for reference in item.default_archetypes
                ],
                "trigger_surfaces": item.trigger_surfaces,
                "minimum_useful_fixture": item.minimum_useful_fixture,
                "failure_meaning": item.failure_meaning,
                "candidate_checks": [
                    _canary_check_payload(check) for check in item.candidate_checks
                ],
            }
            for item in result.profiles
        ],
        "domain_profiles": [
            {
                "schema_version": item.schema_version,
                "id": item.profile_id,
                "title": item.title,
                **(
                    {"quality_risk": item.quality_risk}
                    if item.quality_risk is not None
                    else {}
                ),
                "purpose": item.purpose,
                "catalog_families": list(item.catalog_families),
                "trigger_hints": list(item.trigger_hints),
                "checks": [_canary_check_payload(check) for check in item.checks],
            }
            for item in result.domain_profiles
        ],
    }


def _canary_check_payload(check: object) -> dict[str, object]:
    command = getattr(check, "command")
    reason = getattr(check, "reason")
    tier = getattr(check, "tier")
    return {
        "command": command,
        **({"tier": tier.value} if tier is not None else {}),
        "reason": reason,
    }


def canary_smoke_profiles_payload(
    result: CanarySmokeProfilesResult,
) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "source": result.source,
        "profile_count": result.profile_count,
        "profiles": [
            {
                "id": item.profile_id,
                "suite": item.suite.value,
                "modules": list(item.modules),
                "exclude_modules": list(item.exclude_modules),
                "description": item.description,
            }
            for item in result.profiles
        ],
        "executes_checks": result.executes_checks,
        "writes_evidence": result.writes_evidence,
        "creates_runtime_contract": result.creates_runtime_contract,
        "note": result.note,
    }


def split_control_execution_seam_payload(
    result: SplitControlExecutionSeam,
    *,
    command_adapter_json_read: bool,
    command_adapter_wrapper_unwrapped: bool,
) -> dict[str, object]:
    evidence_boundary = result.post_launch_evidence_boundary
    return {
        "schema_version": result.schema_version,
        "source_schema_version": result.source_schema_version,
        "route_status": result.route_status.value,
        "default_for_cloud_host_runs": result.default_for_cloud_host_runs,
        "ready_to_execute": result.ready_to_execute,
        "ready_to_spend": result.ready_to_spend,
        "blockers": list(result.blockers),
        "missing_command_adapter_ids": list(result.missing_command_adapter_ids),
        "missing_remote_materializer_ids": list(
            result.missing_remote_materializer_ids
        ),
        "missing_result_reducer_ids": list(result.missing_result_reducer_ids),
        "planned_benchmark_ids": list(result.planned_benchmark_ids),
        "execution_cases": [
            {
                "benchmark_id": item.benchmark_id,
                "route": item.route.value,
                "execution_mode": item.execution_mode,
                "command_label": item.command_label,
                "ready_to_execute_remote_command": (
                    item.ready_to_execute_remote_command
                ),
                "blockers": list(item.blockers),
                "command_materialization": {
                    "ready": item.command_materialization.ready,
                    "adapter_facts_ready": (
                        item.command_materialization.adapter_facts_ready
                    ),
                    "status": item.command_materialization.status,
                    "entrypoint_label": item.command_materialization.entrypoint_label,
                    "remote_materializer_ready": (
                        item.command_materialization.remote_materializer_ready
                    ),
                    "shell_command_embedded": (
                        item.command_materialization.shell_command_embedded
                    ),
                    "argv_embedded": item.command_materialization.argv_embedded,
                    "host_path_embedded": (
                        item.command_materialization.host_path_embedded
                    ),
                },
                "local_driver_contract": {
                    "ready": item.local_driver_contract.ready,
                    "driver_label": item.local_driver_contract.driver_label,
                    "owns": list(item.local_driver_contract.owns),
                    "remote_request_fields": list(
                        item.local_driver_contract.remote_request_fields
                    ),
                    "keeps_local": list(item.local_driver_contract.keeps_local),
                    "credential_sync_allowed": (
                        item.local_driver_contract.credential_sync_allowed
                    ),
                    "remote_model_invocation_allowed": (
                        item.local_driver_contract.remote_model_invocation_allowed
                    ),
                    "raw_task_text_sent_to_remote": (
                        item.local_driver_contract.raw_task_text_sent_to_remote
                    ),
                    "shell_command_embedded": (
                        item.local_driver_contract.shell_command_embedded
                    ),
                    "argv_embedded": item.local_driver_contract.argv_embedded,
                },
                "remote_sandbox_contract": {
                    "ready": item.remote_sandbox_contract.ready,
                    "sandbox_label": item.remote_sandbox_contract.sandbox_label,
                    "owns": list(item.remote_sandbox_contract.owns),
                    "allowed_actions": list(
                        item.remote_sandbox_contract.allowed_actions
                    ),
                    "disallowed_actions": list(
                        item.remote_sandbox_contract.disallowed_actions
                    ),
                    "returns": list(item.remote_sandbox_contract.returns),
                    "remote_agent_runtime_allowed": (
                        item.remote_sandbox_contract.remote_agent_runtime_allowed
                    ),
                    "remote_codex_runtime_allowed": (
                        item.remote_sandbox_contract.remote_codex_runtime_allowed
                    ),
                    "remote_model_api_invocation_allowed": (
                        item.remote_sandbox_contract.remote_model_api_invocation_allowed
                    ),
                    "raw_logs_public": item.remote_sandbox_contract.raw_logs_public,
                    "raw_trajectory_public": (
                        item.remote_sandbox_contract.raw_trajectory_public
                    ),
                },
                "execution_handle_contract": {
                    "required_fields": list(
                        item.execution_handle_contract.required_fields
                    ),
                    "handle_values_may_be_private": (
                        item.execution_handle_contract.handle_values_may_be_private
                    ),
                    "public_handle_shape_only": (
                        item.execution_handle_contract.public_handle_shape_only
                    ),
                },
                "result_reducer": {
                    "ready": item.result_reducer.ready,
                    "label": item.result_reducer.label,
                    "accepted_public_fields": list(
                        item.result_reducer.accepted_public_fields
                    ),
                    "raw_values_copied": item.result_reducer.raw_values_copied,
                },
                "remote_executor_allowed_actions": list(
                    item.remote_executor_allowed_actions
                ),
                "remote_executor_disallowed_actions": list(
                    item.remote_executor_disallowed_actions
                ),
                "raw_material_allowed": item.raw_material_allowed,
                "upload_allowed": item.upload_allowed,
                "submit_allowed": item.submit_allowed,
            }
            for item in result.execution_cases
        ],
        "post_launch_evidence": [],
        "post_launch_evidence_boundary": {
            "public_result_fields": list(evidence_boundary.public_result_fields),
            "raw_result_key_hits": {},
            "unexpected_case_ids": list(evidence_boundary.unexpected_case_ids),
            "unsafe_flags": {},
            "violations": list(evidence_boundary.violations),
            "raw_result_values_copied": (
                evidence_boundary.raw_result_values_copied
            ),
        },
        "boundary": {
            "codex_auth_stays_local": result.boundary.codex_auth_stays_local,
            "credential_sync_allowed": result.boundary.credential_sync_allowed,
            "remote_codex_invocation_allowed": (
                result.boundary.remote_codex_invocation_allowed
            ),
            "remote_model_api_invocation_allowed": (
                result.boundary.remote_model_api_invocation_allowed
            ),
            "raw_task_material_public": result.boundary.raw_task_material_public,
            "upload_allowed": result.boundary.upload_allowed,
            "submit_allowed": result.boundary.submit_allowed,
            "fresh_readiness_recheck_required": (
                result.boundary.fresh_readiness_recheck_required
            ),
            "raw_task_text_public": result.boundary.raw_task_text_public,
            "raw_logs_public": result.boundary.raw_logs_public,
            "raw_trajectory_public": result.boundary.raw_trajectory_public,
            "shell_commands_embedded": result.boundary.shell_commands_embedded,
            "argv_embedded": result.boundary.argv_embedded,
            "local_paths_embedded": result.boundary.local_paths_embedded,
            "remote_paths_embedded": result.boundary.remote_paths_embedded,
        },
        "next_action": result.next_action,
        "ok": True,
        "dry_run": True,
        "read_boundary": {
            "compact_only": True,
            "readiness_json_read": True,
            "command_adapter_json_read": command_adapter_json_read,
            "command_adapter_wrapper_unwrapped": (
                command_adapter_wrapper_unwrapped
            ),
            "raw_task_text_read": False,
            "raw_logs_read": False,
            "trajectory_read": False,
            "shell_commands_read": False,
            "docker_invoked": False,
            "model_api_invoked": False,
            "upload_invoked": False,
            "submit_invoked": False,
        },
    }


def active_user_intervention_payload(
    result: WorkerBridgeActiveUserIntervention,
) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "channel_surface": result.channel_surface,
        "seq": result.seq,
        "channel": result.channel,
        "type": result.event_type.value,
        "trigger": result.trigger,
        "message": result.message,
        "created_after_worker_start": result.created_after_worker_start,
        "oracle_free": result.oracle_free,
        "hidden_tests_visible": result.hidden_tests_visible,
        "expected_solution_visible": result.expected_solution_visible,
        "credential_values_visible": result.credential_values_visible,
        "private_material_visible": result.private_material_visible,
        "official_score_claim_allowed": result.official_score_claim_allowed,
        "leaderboard_claim_allowed": result.leaderboard_claim_allowed,
    }


def active_user_simulator_intervention_payload(
    result: WorkerBridgeActiveUserSimulatorIntervention,
) -> dict[str, object]:
    payload = active_user_intervention_payload(result.intervention)
    audit = result.no_oracle_audit
    payload.update(
        {
            "simulator_kind": result.simulator_kind.value,
            "simulator_output_schema_version": (
                result.simulator_output_schema_version
            ),
            "controller_authored_message": result.controller_authored_message,
            "formal_treatment_eligible": result.formal_treatment_eligible,
            "manual_controller_feed": result.manual_controller_feed,
            "visible_evidence_basis": [
                item.value for item in result.visible_evidence_basis
            ],
            "no_oracle_audit": {
                "hidden_tests_visible": audit.hidden_tests_visible,
                "expected_solution_visible": audit.expected_solution_visible,
                "benchmark_answer_key_visible": (
                    audit.benchmark_answer_key_visible
                ),
                "credential_values_visible": audit.credential_values_visible,
                "private_material_visible": audit.private_material_visible,
                "solution_patch_visible": audit.solution_patch_visible,
            },
        }
    )
    return payload


def benchmark_artifact_inspection_payload(
    result: BenchmarkArtifactInspection,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "path_recorded": result.path_recorded,
        "allowed_to_read_count": result.allowed_to_read_count,
        "blocked_count": result.blocked_count,
        "allowed_artifact_basenames": list(
            result.allowed_artifact_basenames
        ),
        "blocked_artifact_basenames": list(
            result.blocked_artifact_basenames
        ),
        "blocked_reasons": {
            item.reason: item.count for item in result.blocked_reasons
        },
        "classifications": [
            {
                "schema_version": item.schema_version,
                "path_recorded": item.path_recorded,
                "basename": item.basename,
                "public_compact_candidate": item.public_compact_candidate,
                "private_raw_surface": item.private_raw_surface,
                "first_blocker": (
                    item.first_blocker.value if item.first_blocker else ""
                ),
                "allowed_to_read": item.allowed_to_read,
                "recommended_action": item.recommended_action,
                "artifact_policy": _artifact_policy_payload(
                    item.artifact_policy
                ),
            }
            for item in result.classifications
        ],
        "artifact_policy": _artifact_policy_payload(result.artifact_policy),
        "public_boundary": {
            "full_paths_recorded": result.public_boundary.full_paths_recorded,
            "raw_task_text_read": result.public_boundary.raw_task_text_read,
            "trajectory_or_origin_log_read": (
                result.public_boundary.trajectory_or_origin_log_read
            ),
            "intended_use": result.public_boundary.intended_use,
        },
    }


def _artifact_policy_payload(
    policy: BenchmarkArtifactPolicy,
) -> dict[str, object]:
    return {
        "adapter_kind": policy.adapter_kind,
        "registry_backed": policy.registry_backed,
        "public_filename_allowlist_count": (
            policy.public_filename_allowlist_count
        ),
        "raw_private_marker_count": policy.raw_private_marker_count,
    }


def benchmark_candidate_source_boundary_payload(
    result: BenchmarkCandidateSourceBoundary,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "path_recorded": result.path_recorded,
        "allowed_source_count": result.allowed_source_count,
        "blocked_source_count": result.blocked_source_count,
        "clean": result.clean,
        "allowed_source_basenames": list(result.allowed_source_basenames),
        "blocked_source_basenames": list(result.blocked_source_basenames),
        "blocked_reasons": {
            item.reason: item.count for item in result.blocked_reasons
        },
        "classifications": [
            {
                "schema_version": item.schema_version,
                "path_recorded": item.path_recorded,
                "basename": item.basename,
                "source_kind": item.source_kind.value,
                "allowed_for_candidate_selection": (
                    item.allowed_for_candidate_selection
                ),
                "first_blocker": (
                    item.first_blocker.value if item.first_blocker else ""
                ),
                "recommended_action": item.recommended_action,
                "artifact_allowed_to_read": item.artifact_allowed_to_read,
            }
            for item in result.classifications
        ],
        "candidate_selection_policy": {
            "allowed_source_kinds": list(
                result.candidate_selection_policy.allowed_source_kinds
            ),
            "disallowed_source_kinds": list(
                result.candidate_selection_policy.disallowed_source_kinds
            ),
            "safe_private_artifact_glob": (
                result.candidate_selection_policy.safe_private_artifact_glob
            ),
        },
        "read_boundary": {
            "files_opened": result.read_boundary.files_opened,
            "raw_artifacts_read": result.read_boundary.raw_artifacts_read,
            "task_text_read": result.read_boundary.task_text_read,
            "trajectory_read": result.read_boundary.trajectory_read,
            "codex_transcript_read": result.read_boundary.codex_transcript_read,
            "local_paths_recorded": result.read_boundary.local_paths_recorded,
        },
        "next_action": result.next_action,
    }


def benchmark_parity_check_payload(
    result: BenchmarkParityCheck,
) -> dict[str, object]:
    evidence = result.evidence_checks
    safety = result.safety_checks
    calls = result.loopx_cli_call_counts
    return {
        "ok": True,
        "codex_app_parity_posthoc_check": {
            "schema_version": result.schema_version,
            "parity_target": result.parity_target,
            "benchmark_id": result.benchmark_id,
            "mode": result.mode,
            "route": result.route,
            "product_mode": result.product_mode,
            "evidence_checks": {
                "canonical_case_active_state_path": (
                    evidence.canonical_case_active_state_path
                ),
                "case_active_state_initialized_before_agent": (
                    evidence.case_active_state_initialized_before_agent
                ),
                "loopx_cli_trace_present": evidence.loopx_cli_trace_present,
                "required_loopx_cli_calls_present": (
                    evidence.required_loopx_cli_calls_present
                ),
                "stateful_loopx_lifecycle_observed": (
                    evidence.stateful_loopx_lifecycle_observed
                ),
                "codex_cli_trajectory_summary_present": (
                    evidence.codex_cli_trajectory_summary_present
                ),
            },
            "safety_checks": {
                "raw_task_text_absent": safety.raw_task_text_absent,
                "raw_reward_feedback_absent": (
                    safety.raw_reward_feedback_absent
                ),
                "raw_verifier_output_absent": safety.raw_verifier_output_absent,
                "raw_agent_trajectory_absent": (
                    safety.raw_agent_trajectory_absent
                ),
            },
            "loopx_cli_call_counts": {
                "status": calls.status,
                "quota_should_run": calls.quota_should_run,
                "todo_list": calls.todo_list,
                "history": calls.history,
                "check": calls.check,
                "todo_claim": calls.todo_claim,
                "todo_update": calls.todo_update,
                "refresh_state": calls.refresh_state,
                "quota_spend": calls.quota_spend,
                "case_result": calls.case_result,
                "total": calls.total,
            },
            "stateful_lifecycle_counts": {
                "state_reads": result.stateful_lifecycle_counts.state_reads,
                "state_writes": result.stateful_lifecycle_counts.state_writes,
            },
            "missing_required_cli_calls": [
                item.value for item in result.missing_required_cli_calls
            ],
            "case_goal_state": {
                "init_required": result.case_goal_state.init_required,
                "initialized_before_agent": (
                    result.case_goal_state.initialized_before_agent
                ),
                "canonical_path_present": (
                    result.case_goal_state.canonical_path_present
                ),
                "path_kind": result.case_goal_state.path_kind.value,
            },
            "missing_evidence": [
                item.value for item in result.missing_evidence
            ],
            "safety_failures": [
                item.value for item in result.safety_failures
            ],
            "full_product_claim_allowed": result.full_product_claim_allowed,
            "claim_level": result.claim_level.value,
            "read_boundary": {
                "compact_benchmark_run_only": (
                    result.read_boundary.compact_benchmark_run_only
                ),
                "raw_task_text_read": result.read_boundary.raw_task_text_read,
                "raw_logs_read": result.read_boundary.raw_logs_read,
                "raw_trajectory_read": (
                    result.read_boundary.raw_trajectory_read
                ),
                "verifier_output_read": (
                    result.read_boundary.verifier_output_read
                ),
                "credentials_read": result.read_boundary.credentials_read,
                "local_paths_recorded": (
                    result.read_boundary.local_paths_recorded
                ),
            },
        },
    }
