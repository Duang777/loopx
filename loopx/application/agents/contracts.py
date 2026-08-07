from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationFailed


class WorkerBridgeInstallMode(str, Enum):
    SOURCE_MOUNT_READ_ONLY_PYTHONPATH = "source_mount_read_only_pythonpath"


class WorkerBridgeRunnerReturnStatus(str, Enum):
    COMPLETED = "completed"
    INTERRUPTED_AFTER_BRIDGE_SUCCESS = "interrupted_after_worker_bridge_success"
    PENDING_AFTER_BRIDGE_SUCCESS = "pending_after_worker_bridge_success"
    BRIDGE_EVIDENCE_MISSING = "worker_bridge_evidence_missing"


class WorkerBridgeOfficialScoreStatus(str, Enum):
    COMPLETED = "completed"
    BLOCKED_PENDING_RUNNER_RETURN = "blocked_pending_runner_return"
    NOT_READY = "not_ready"


class WorkerBridgeTracePublicness(str, Enum):
    COMPACT_COUNTS_ONLY = "compact_counts_only_no_raw_trace"


class WorkerBridgeActiveUserEventType(str, Enum):
    ACTIVE_USER_INSTRUCTION = "active_user_instruction"


class WorkerBridgeActiveUserSimulatorKind(str, Enum):
    CODEX_CLI = "codex_cli"


class WorkerBridgeActiveUserEvidenceBasis(str, Enum):
    PUBLIC_TASK_PROMPT = "public task prompt visible to worker"
    WORKER_PUBLIC_ARTIFACTS = "worker public artifacts"
    COMPACT_LOOPX_STATUS = "compact LoopX status and run metadata"


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value


def _bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationFailed(details={"field": field})
    return value


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationFailed(details={"field": field})
    return value


def _optional_non_negative_number(
    value: object,
    *,
    field: str,
) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValidationFailed(details={"field": field})
    return value


@dataclass(frozen=True, slots=True)
class WorkerBridgeContractRequest:
    project_root: str
    runtime_root: str
    python_bin: str
    module: str
    scan_path: str | None
    benchmark_run_json: str
    counter_trace_json: str
    classification: str

    def __post_init__(self) -> None:
        for field in (
            "project_root",
            "runtime_root",
            "python_bin",
            "module",
            "benchmark_run_json",
            "counter_trace_json",
            "classification",
        ):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field=field),
            )
        if self.scan_path is not None:
            object.__setattr__(
                self,
                "scan_path",
                _required_text(self.scan_path, field="scan_path"),
            )


@dataclass(frozen=True, slots=True)
class WorkerBridgeOutcomeRequest:
    worker_cli_call_total: int = 0
    required_worker_cli_call_total_min: int = 1
    counter_trace_present: bool = False
    runner_return_completed: bool = False
    official_score_completed: bool = False
    official_score_value: int | float | None = None
    interrupted: bool = False
    interrupt_reason: str = ""
    wall_time_seconds: int | float | None = None
    wall_time_limit_seconds: int | float = 900.0
    side_effect_audit_passed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "worker_cli_call_total",
            _non_negative_int(
                self.worker_cli_call_total,
                field="worker_cli_call_total",
            ),
        )
        object.__setattr__(
            self,
            "required_worker_cli_call_total_min",
            _non_negative_int(
                self.required_worker_cli_call_total_min,
                field="required_worker_cli_call_total_min",
            ),
        )
        for field in (
            "counter_trace_present",
            "runner_return_completed",
            "official_score_completed",
            "interrupted",
            "side_effect_audit_passed",
        ):
            object.__setattr__(
                self,
                field,
                _bool(getattr(self, field), field=field),
            )
        object.__setattr__(
            self,
            "official_score_value",
            _optional_non_negative_number(
                self.official_score_value,
                field="official_score_value",
            ),
        )
        object.__setattr__(
            self,
            "wall_time_seconds",
            _optional_non_negative_number(
                self.wall_time_seconds,
                field="wall_time_seconds",
            ),
        )
        wall_limit = _optional_non_negative_number(
            self.wall_time_limit_seconds,
            field="wall_time_limit_seconds",
        )
        if wall_limit is None or wall_limit <= 0:
            raise ValidationFailed(details={"field": "wall_time_limit_seconds"})
        object.__setattr__(self, "wall_time_limit_seconds", wall_limit)
        if not isinstance(self.interrupt_reason, str):
            raise ValidationFailed(details={"field": "interrupt_reason"})
        if self.official_score_completed != (self.official_score_value is not None):
            raise ValidationFailed(
                details={
                    "field": "official_score_value",
                    "reason": "must_match_official_score_completed",
                }
            )


@dataclass(frozen=True, slots=True)
class WorkerBridgeMount:
    kind: str
    source: str
    target: str
    read_only: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeExternalUpdateMount:
    enabled: bool
    target: str | None
    read_only: bool | None
    raw_host_path_recorded: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeAgentArguments:
    command_prefix: str
    runtime_preflight_command: str
    registry_arg: str
    runtime_root_arg: str
    scan_path: str
    benchmark_run_json: str
    benchmark_run_schema_version: str
    benchmark_run_writeback_contract: str
    counter_trace_json: str
    classification: str
    active_user_feed_jsonl: str
    active_user_observation_json: str
    active_user_observe_command: str
    active_user_channel_surface: str


@dataclass(frozen=True, slots=True)
class WorkerBridgeRequiredFixedFields:
    real_run: bool
    submit_eligible: bool
    leaderboard_evidence: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeValidationScopeContract:
    field: str
    recommended_values: tuple[str, ...]
    connectivity_is_not_case_success: bool
    legacy_unscoped_passed_validation_is_ambiguous: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeRetryPolicy:
    on_append_benchmark_run_schema_rejected: str
    retry_payload_source: str
    do_not_retry_with_raw_logs_or_raw_paths: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeWritebackPublicBoundary:
    no_upload: bool
    submit_eligible: bool
    leaderboard_evidence: bool
    raw_trace_excluded: bool
    raw_paths_redacted: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeBenchmarkRunWritebackContract:
    schema_version: str
    benchmark_run_schema_version: str
    benchmark_run_json: str
    counter_trace_json: str
    classification: str
    required_top_level_fields: tuple[str, ...]
    required_fixed_fields: WorkerBridgeRequiredFixedFields
    required_validation_flags: tuple[str, ...]
    validation_scope_contract: WorkerBridgeValidationScopeContract
    claim_boundary_required_fields: tuple[str, ...]
    forbidden_public_fields: tuple[str, ...]
    retry_policy: WorkerBridgeRetryPolicy
    public_boundary: WorkerBridgeWritebackPublicBoundary


@dataclass(frozen=True, slots=True)
class WorkerBridgeStartMarker:
    kind: str
    proof_rule: str


@dataclass(frozen=True, slots=True)
class WorkerBridgeFrequencyBudget:
    min_interval_seconds: int
    max_interventions_per_task: int
    simulator_may_be_proactive: bool
    artificial_mildness_required: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeVisibilityPolicy:
    simulator_may_read: tuple[str, ...]
    simulator_must_not_read: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserClaimBoundary:
    official_score_claim_allowed: bool
    leaderboard_claim_allowed: bool
    assisted_collaboration_claim_allowed: bool
    direct_codex_chat_injection: bool
    worker_pull_required: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserPublicBoundary:
    raw_paths_recorded: bool
    raw_transcript_recorded: bool
    credential_values_recorded: bool
    no_upload: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserChannelContract:
    ok: bool
    schema_version: str
    bridge_surface: str
    channel_surface: str
    mode: str
    feed_jsonl: str
    observation_json: str
    benchmark_run_json: str
    counter_trace_json: str
    worker_observe_command: str
    simulator_append_command: str
    worker_start_marker: WorkerBridgeStartMarker
    frequency_budget: WorkerBridgeFrequencyBudget
    visibility_policy: WorkerBridgeVisibilityPolicy
    claim_boundary: WorkerBridgeActiveUserClaimBoundary
    public_boundary: WorkerBridgeActiveUserPublicBoundary


@dataclass(frozen=True, slots=True)
class WorkerBridgeTrace:
    counter_trace_json: str
    benchmark_run_json: str
    active_user_feed_jsonl: str
    active_user_observation_json: str
    write_surface: str
    raw_trace_public: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeInstallBoundary:
    real_run: bool
    submit_eligible: bool
    no_upload: bool
    credential_values_recorded: bool
    raw_paths_required_in_public_artifacts: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeInstallContract:
    ok: bool
    schema_version: str
    bridge_surface: str
    install_mode: WorkerBridgeInstallMode
    runtime_policy: str
    runtime_preflight_command: str
    project_root: str
    runtime_root: str
    mounts: tuple[WorkerBridgeMount, ...]
    active_user_external_update_mount: WorkerBridgeExternalUpdateMount
    command_prefix: str
    agent_kwargs: WorkerBridgeAgentArguments
    benchmark_run_writeback_contract: WorkerBridgeBenchmarkRunWritebackContract
    active_user_intervention_channel_contract: WorkerBridgeActiveUserChannelContract
    trace: WorkerBridgeTrace
    boundary: WorkerBridgeInstallBoundary


@dataclass(frozen=True, slots=True)
class WorkerBridgeWallTimePolicy:
    schema_version: str
    kind: str
    wall_time_seconds: int | float | None
    wall_time_limit_seconds: int | float
    interrupted: bool
    interrupt_reason: str
    changes_official_benchmark_timeout: bool
    changes_official_task_resources: bool
    leaderboard_claim_allowed: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeOutcomeClaimBoundary:
    public_claim_allowed: str
    bridge_connectivity_claim_allowed: bool
    case_success_claim_allowed: bool
    official_score_claim_allowed: bool
    leaderboard_claim_allowed: bool
    forbidden_claims: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkerBridgeOutcome:
    ok: bool
    schema_version: str
    bridge_surface: str
    worker_bridge_verified: bool
    runner_return_status: WorkerBridgeRunnerReturnStatus
    official_score_status: WorkerBridgeOfficialScoreStatus
    worker_cli_call_total: int
    required_worker_cli_call_total_min: int
    counter_trace_present: bool
    runner_return_completed: bool
    official_score_completed: bool
    official_score_value: int | float | None
    side_effect_audit_passed: bool
    wall_time_policy: WorkerBridgeWallTimePolicy
    failure_attribution_labels: tuple[str, ...]
    claim_boundary: WorkerBridgeOutcomeClaimBoundary
    next_action: str
    trace_publicness: WorkerBridgeTracePublicness
    raw_paths_recorded: bool
    raw_trace_recorded: bool
    credential_values_recorded: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserInterventionRequest:
    seq: int
    message: str
    trigger: str = "public_progress_or_stall_signal"
    channel: str = "simulator_proactive_user_message"
    created_after_worker_start: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "seq", _non_negative_int(self.seq, field="seq"))
        for field in ("message", "trigger", "channel"):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field=field),
            )
        object.__setattr__(
            self,
            "created_after_worker_start",
            _bool(
                self.created_after_worker_start,
                field="created_after_worker_start",
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserNoOracleAudit:
    hidden_tests_visible: bool
    expected_solution_visible: bool
    benchmark_answer_key_visible: bool
    credential_values_visible: bool
    private_material_visible: bool
    solution_patch_visible: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserSimulatorOutput:
    schema_version: str
    simulator_kind: WorkerBridgeActiveUserSimulatorKind
    trigger: str
    message: str
    visible_evidence_basis: tuple[WorkerBridgeActiveUserEvidenceBasis, ...]
    no_oracle_audit: WorkerBridgeActiveUserNoOracleAudit
    controller_authored_message: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserSimulatorOutputRequest:
    seq: int
    simulator_output: WorkerBridgeActiveUserSimulatorOutput
    created_after_worker_start: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "seq", _non_negative_int(self.seq, field="seq"))
        if not isinstance(
            self.simulator_output,
            WorkerBridgeActiveUserSimulatorOutput,
        ):
            raise ValidationFailed(details={"field": "simulator_output"})
        object.__setattr__(
            self,
            "created_after_worker_start",
            _bool(
                self.created_after_worker_start,
                field="created_after_worker_start",
            ),
        )


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserIntervention:
    ok: bool
    schema_version: str
    channel_surface: str
    seq: int
    channel: str
    event_type: WorkerBridgeActiveUserEventType
    trigger: str
    message: str
    created_after_worker_start: bool
    oracle_free: bool
    hidden_tests_visible: bool
    expected_solution_visible: bool
    credential_values_visible: bool
    private_material_visible: bool
    official_score_claim_allowed: bool
    leaderboard_claim_allowed: bool


@dataclass(frozen=True, slots=True)
class WorkerBridgeActiveUserSimulatorIntervention:
    intervention: WorkerBridgeActiveUserIntervention
    simulator_kind: WorkerBridgeActiveUserSimulatorKind
    simulator_output_schema_version: str
    controller_authored_message: bool
    formal_treatment_eligible: bool
    manual_controller_feed: bool
    visible_evidence_basis: tuple[WorkerBridgeActiveUserEvidenceBasis, ...]
    no_oracle_audit: WorkerBridgeActiveUserNoOracleAudit
