from __future__ import annotations


def split_control_readiness_fixture() -> dict[str, object]:
    return {
        "schema_version": "benchmark_split_control_remote_executor_readiness_v0",
        "route": {
            "mode": "local_agent_remote_executor",
            "status": "experimental_fallback_not_default",
            "default_for_cloud_host_runs": False,
            "allowed_use": [
                "codex_auth_cannot_live_on_execution_host",
                "shared_or_policy_restricted_execution_host",
                "local_controller_remote_docker_substrate_research",
            ],
            "not_for": [
                "default_cloud_host_or_app_server_benchmark_route",
                "new_bridge_layers_without_concrete_auth_policy_or_host_gate",
            ],
            "retirement_policy": (
                "keep durable public contracts and reducers; defer or retire "
                "transport-only bridge work once a cloud-host or app-server "
                "route has equivalent compact evidence"
            ),
            "local_agent_owns": [
                "codex_cli",
                "codex_auth",
                "loopx_state",
                "model_invocation",
                "planning_and_patch_generation",
            ],
            "remote_executor_owns": [
                "docker",
                "runner_dependencies",
                "task_data_staging",
                "bounded_command_execution",
                "compact_result_reduction",
            ],
        },
        "ready": True,
        "first_blocker": "ready_for_parallel_remote_executor_rotation",
        "local_agent": {
            "ready": True,
            "missing": [],
            "codex_auth_local_only": True,
        },
        "remote_executor": {
            "base_ready": True,
            "base_missing": [],
            "codex_available": False,
            "codex_acp_available": False,
            "node_available": False,
            "npm_available": False,
            "remote_agent_components_missing": {
                "codex_available": True,
                "codex_acp_available": True,
            },
            "remote_agent_components_blocking": False,
        },
        "benchmark_statuses": [
            {
                "benchmark_id": "terminal-bench@2.0",
                "ready_for_split_control_execution": True,
                "first_blocker": "ready",
                "blockers": [],
                "local_agent_ready": True,
                "remote_executor_base_ready": True,
                "split_control_adapter_ready": True,
                "runner_tooling_ready": True,
                "task_data_ready": True,
                "requires_remote_node": False,
                "remote_node_ready": False,
                "remote_codex_required": False,
                "remote_codex_acp_required": False,
                "remote_codex_missing_is_blocker": False,
            }
        ],
        "readiness_matrix": {
            "ready_benchmark_ids": ["terminal-bench@2.0"],
            "blocked_benchmark_ids": [],
            "next_ready_batch_benchmark_ids": ["terminal-bench@2.0"],
            "next_repair_target": None,
            "has_launchable_subset": True,
            "all_requested_benchmarks_ready": True,
        },
        "parallel_policy": {
            "max_parallel_cases": 1,
            "suggested_next_batch_size": 1,
            "parallelize_only_ready_benchmarks": True,
        },
        "boundary": {
            "codex_auth_sync_allowed": False,
            "credential_sync_allowed": False,
            "remote_codex_invocation_allowed": False,
            "remote_codex_acp_invocation_allowed": False,
            "remote_model_api_invocation_allowed": False,
            "raw_task_material_public": False,
            "upload_allowed": False,
            "submit_allowed": False,
        },
        "next_action": "launch bounded parallel remote-executor batch",
    }


def command_adapter_fixture() -> dict[str, object]:
    return {
        "command_adapters": {
            "terminal-bench@2.0": {
                "command_adapter_ready": True,
                "result_reducer_ready": True,
                "command_adapter_status": "ready",
                "entrypoint_label": "terminal_bench_fixture_surface",
                "local_driver_contract": {"ready": True},
                "remote_sandbox_contract": {"ready": True},
            }
        }
    }


def active_user_simulator_output_fixture() -> dict[str, object]:
    return {
        "schema_version": "loopx_active_user_simulator_output_v0",
        "simulator_kind": "codex_cli",
        "trigger": "public_progress_or_stall_signal",
        "message": "Inspect the public failure summary and continue safely.",
        "visible_evidence_basis": [
            "public task prompt visible to worker",
            "worker public artifacts",
            "compact LoopX status and run metadata",
        ],
        "no_oracle_audit": {
            "hidden_tests_visible": False,
            "expected_solution_visible": False,
            "benchmark_answer_key_visible": False,
            "credential_values_visible": False,
            "private_material_visible": False,
            "solution_patch_visible": False,
        },
        "controller_authored_message": False,
    }


def parity_benchmark_run_fixture() -> dict[str, object]:
    return {
        "schema_version": "benchmark_run_v0",
        "benchmark_id": "fixture@v0",
        "mode": "codex_loopx_product",
        "route": "codex_app",
        "interaction_counters": {
            "loopx_cli_calls": {
                "status": 1,
                "quota_should_run": 1,
                "todo_list": 1,
                "history": 1,
                "check": 1,
                "todo_update": 1,
                "total": 6,
            },
            "case_goal_state_path": (
                "/app/.codex/goals/fixture/ACTIVE_GOAL_STATE.md"
            ),
            "case_goal_state_init_required": True,
            "case_goal_state_initialized_before_agent": True,
            "private_trajectory_summary_present": True,
        },
    }
