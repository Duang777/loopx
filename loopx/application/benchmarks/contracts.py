from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationFailed


class SplitControlRouteMode(str, Enum):
    LOCAL_AGENT_REMOTE_EXECUTOR = "local_agent_remote_executor"


class SplitControlRouteStatus(str, Enum):
    EXPERIMENTAL_FALLBACK_NOT_DEFAULT = "experimental_fallback_not_default"


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value


@dataclass(frozen=True, slots=True)
class SplitControlRoute:
    status: SplitControlRouteStatus
    default_for_cloud_host_runs: bool
    local_agent_owns: tuple[str, ...]
    remote_executor_owns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SplitControlReadinessMatrix:
    next_ready_batch_benchmark_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SplitControlReadinessBoundary:
    codex_auth_sync_allowed: bool
    credential_sync_allowed: bool
    remote_codex_invocation_allowed: bool
    remote_model_api_invocation_allowed: bool
    raw_task_material_public: bool


@dataclass(frozen=True, slots=True)
class SplitControlReadiness:
    route: SplitControlRoute
    readiness_matrix: SplitControlReadinessMatrix
    boundary: SplitControlReadinessBoundary


@dataclass(frozen=True, slots=True)
class BenchmarkCommandAdapterSurface:
    remote_materializer_ready: bool


@dataclass(frozen=True, slots=True)
class BenchmarkLocalDriverFacts:
    ready: bool
    driver_label: str | None = None
    owns: tuple[str, ...] = ()
    remote_request_fields: tuple[str, ...] = ()
    keeps_local: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkRemoteSandboxFacts:
    ready: bool
    sandbox_label: str | None = None
    owns: tuple[str, ...] = ()
    allowed_actions: tuple[str, ...] = ()
    disallowed_actions: tuple[str, ...] = ()
    returns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkCommandAdapterFacts:
    benchmark_id: str
    command_adapter_ready: bool
    result_reducer_ready: bool
    command_adapter_status: str | None = None
    entrypoint_label: str | None = None
    remote_materializer_ready: bool | None = None
    surface_contract: BenchmarkCommandAdapterSurface | None = None
    local_driver_contract: BenchmarkLocalDriverFacts | None = None
    remote_sandbox_contract: BenchmarkRemoteSandboxFacts | None = None
    known_blockers: tuple[str, ...] = ()
    handle_fields: tuple[str, ...] = ()
    result_reducer_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "benchmark_id",
            _required_text(self.benchmark_id, field="benchmark_id"),
        )


@dataclass(frozen=True, slots=True)
class SplitControlExecutionSeamRequest:
    readiness: SplitControlReadiness
    command_adapters: tuple[BenchmarkCommandAdapterFacts, ...] = ()
    execution_mode: str = "compact_no_upload_dry_run"

    def __post_init__(self) -> None:
        if not isinstance(self.readiness, SplitControlReadiness):
            raise ValidationFailed(details={"field": "readiness"})
        if len({item.benchmark_id for item in self.command_adapters}) != len(
            self.command_adapters
        ):
            raise ValidationFailed(details={"field": "command_adapters"})
        object.__setattr__(
            self,
            "execution_mode",
            _required_text(self.execution_mode, field="execution_mode"),
        )


@dataclass(frozen=True, slots=True)
class BenchmarkCommandMaterialization:
    ready: bool
    adapter_facts_ready: bool
    status: str
    entrypoint_label: str
    remote_materializer_ready: bool
    shell_command_embedded: bool
    argv_embedded: bool
    host_path_embedded: bool


@dataclass(frozen=True, slots=True)
class BenchmarkLocalDriverContract:
    ready: bool
    driver_label: str
    owns: tuple[str, ...]
    remote_request_fields: tuple[str, ...]
    keeps_local: tuple[str, ...]
    credential_sync_allowed: bool
    remote_model_invocation_allowed: bool
    raw_task_text_sent_to_remote: bool
    shell_command_embedded: bool
    argv_embedded: bool


@dataclass(frozen=True, slots=True)
class BenchmarkRemoteSandboxContract:
    ready: bool
    sandbox_label: str
    owns: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    disallowed_actions: tuple[str, ...]
    returns: tuple[str, ...]
    remote_agent_runtime_allowed: bool
    remote_codex_runtime_allowed: bool
    remote_model_api_invocation_allowed: bool
    raw_logs_public: bool
    raw_trajectory_public: bool


@dataclass(frozen=True, slots=True)
class BenchmarkExecutionHandleContract:
    required_fields: tuple[str, ...]
    handle_values_may_be_private: bool
    public_handle_shape_only: bool


@dataclass(frozen=True, slots=True)
class BenchmarkResultReducer:
    ready: bool
    label: str
    accepted_public_fields: tuple[str, ...]
    raw_values_copied: bool


@dataclass(frozen=True, slots=True)
class BenchmarkExecutionCase:
    benchmark_id: str
    route: SplitControlRouteMode
    execution_mode: str
    command_label: str
    ready_to_execute_remote_command: bool
    blockers: tuple[str, ...]
    command_materialization: BenchmarkCommandMaterialization
    local_driver_contract: BenchmarkLocalDriverContract
    remote_sandbox_contract: BenchmarkRemoteSandboxContract
    execution_handle_contract: BenchmarkExecutionHandleContract
    result_reducer: BenchmarkResultReducer
    remote_executor_allowed_actions: tuple[str, ...]
    remote_executor_disallowed_actions: tuple[str, ...]
    raw_material_allowed: bool
    upload_allowed: bool
    submit_allowed: bool


@dataclass(frozen=True, slots=True)
class BenchmarkPostLaunchEvidenceBoundary:
    public_result_fields: tuple[str, ...]
    unexpected_case_ids: tuple[str, ...]
    violations: tuple[str, ...]
    raw_result_values_copied: bool


@dataclass(frozen=True, slots=True)
class SplitControlExecutionBoundary:
    codex_auth_stays_local: bool
    credential_sync_allowed: bool
    remote_codex_invocation_allowed: bool
    remote_model_api_invocation_allowed: bool
    raw_task_material_public: bool
    upload_allowed: bool
    submit_allowed: bool
    fresh_readiness_recheck_required: bool
    raw_task_text_public: bool
    raw_logs_public: bool
    raw_trajectory_public: bool
    shell_commands_embedded: bool
    argv_embedded: bool
    local_paths_embedded: bool
    remote_paths_embedded: bool


@dataclass(frozen=True, slots=True)
class SplitControlExecutionSeam:
    schema_version: str
    source_schema_version: str
    route_status: SplitControlRouteStatus
    default_for_cloud_host_runs: bool
    ready_to_execute: bool
    ready_to_spend: bool
    blockers: tuple[str, ...]
    missing_command_adapter_ids: tuple[str, ...]
    missing_remote_materializer_ids: tuple[str, ...]
    missing_result_reducer_ids: tuple[str, ...]
    planned_benchmark_ids: tuple[str, ...]
    execution_cases: tuple[BenchmarkExecutionCase, ...]
    post_launch_evidence_boundary: BenchmarkPostLaunchEvidenceBoundary
    boundary: SplitControlExecutionBoundary
    next_action: str


class BenchmarkArtifactBlocker(str, Enum):
    RAW_PRIVATE_SURFACE = "raw_private_surface"
    PRIVATE_OR_LOCAL_MANIFEST = "private_or_local_manifest"
    NOT_COMPACT_PUBLIC_ARTIFACT = "not_compact_public_artifact"


class BenchmarkCandidateSourceKind(str, Enum):
    PUBLIC_DOC = "public_doc"
    PUBLIC_REGRESSION = "public_regression"
    ACTIVE_STATE_SUMMARY = "active_state_summary"
    COMPACT_PUBLIC_ARTIFACT = "compact_public_artifact"
    BLOCKED_PRIVATE_RUNNER_SURFACE = "blocked_private_runner_surface"
    BLOCKED_RAW_ARTIFACT = "blocked_raw_artifact"
    BLOCKED_UNREGISTERED_SOURCE = "blocked_unregistered_source"


class BenchmarkCandidateSourceBlocker(str, Enum):
    PRIVATE_RUNNER_ARTIFACT_ROOT_OR_RAW_CHILD = (
        "private_runner_artifact_root_or_raw_child"
    )
    RAW_BENCHMARK_ARTIFACT_SURFACE = "raw_benchmark_artifact_surface"
    UNREGISTERED_CANDIDATE_SOURCE = "unregistered_candidate_source"


class BenchmarkParityClaimLevel(str, Enum):
    BASELINE_OR_ABLATION = "baseline_or_ablation_no_product_claim"
    FULL_PRODUCT_PATH = "full_product_path_evidence_present"
    UNSAFE_OR_LEAKY = "unsafe_or_leaky_artifact"
    SURROGATE_MISSING_EVIDENCE = (
        "product_mode_surrogate_missing_posthoc_evidence"
    )


class BenchmarkParityEvidenceKind(str, Enum):
    CANONICAL_CASE_ACTIVE_STATE_PATH = "canonical_case_active_state_path"
    CASE_ACTIVE_STATE_INITIALIZED = (
        "case_active_state_initialized_before_agent"
    )
    LOOPX_CLI_TRACE_PRESENT = "loopx_cli_trace_present"
    REQUIRED_LOOPX_CLI_CALLS_PRESENT = "required_loopx_cli_calls_present"
    STATEFUL_LOOPX_LIFECYCLE_OBSERVED = (
        "stateful_loopx_lifecycle_observed"
    )
    CODEX_CLI_TRAJECTORY_SUMMARY_PRESENT = (
        "codex_cli_trajectory_summary_present"
    )


class BenchmarkParitySafetyKind(str, Enum):
    RAW_TASK_TEXT_ABSENT = "raw_task_text_absent"
    RAW_REWARD_FEEDBACK_ABSENT = "raw_reward_feedback_absent"
    RAW_VERIFIER_OUTPUT_ABSENT = "raw_verifier_output_absent"
    RAW_AGENT_TRAJECTORY_ABSENT = "raw_agent_trajectory_absent"


class BenchmarkParityRequiredCall(str, Enum):
    STATUS = "status"
    QUOTA_SHOULD_RUN = "quota_should_run"
    TODO_LIST = "todo_list"
    HISTORY = "history"
    CHECK = "check"


class BenchmarkParityCasePathKind(str, Enum):
    CANONICAL = "canonical_app_goal_state"
    MISSING_OR_NONCANONICAL = "missing_or_noncanonical"


@dataclass(frozen=True, slots=True)
class BenchmarkReasonCount:
    reason: str
    count: int


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactInspectionRequest:
    artifact_paths: tuple[str, ...]
    adapter_kind: str = "default"
    allow_public_filenames: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_paths, tuple) or not self.artifact_paths or any(
            not isinstance(item, str) or not item.strip()
            for item in self.artifact_paths
        ):
            raise ValidationFailed(details={"field": "artifact_paths"})
        object.__setattr__(
            self,
            "adapter_kind",
            _required_text(self.adapter_kind, field="adapter_kind"),
        )
        if not isinstance(self.allow_public_filenames, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.allow_public_filenames
        ):
            raise ValidationFailed(
                details={"field": "allow_public_filenames"}
            )


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactPolicy:
    adapter_kind: str
    registry_backed: bool
    public_filename_allowlist_count: int
    raw_private_marker_count: int


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactClassification:
    schema_version: str
    path_recorded: bool
    basename: str
    public_compact_candidate: bool
    private_raw_surface: bool
    first_blocker: BenchmarkArtifactBlocker | None
    allowed_to_read: bool
    recommended_action: str
    artifact_policy: BenchmarkArtifactPolicy


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactPublicBoundary:
    full_paths_recorded: bool
    raw_task_text_read: bool
    trajectory_or_origin_log_read: bool
    intended_use: str


@dataclass(frozen=True, slots=True)
class BenchmarkArtifactInspection:
    schema_version: str
    path_recorded: bool
    allowed_to_read_count: int
    blocked_count: int
    allowed_artifact_basenames: tuple[str, ...]
    blocked_artifact_basenames: tuple[str, ...]
    blocked_reasons: tuple[BenchmarkReasonCount, ...]
    classifications: tuple[BenchmarkArtifactClassification, ...]
    artifact_policy: BenchmarkArtifactPolicy
    public_boundary: BenchmarkArtifactPublicBoundary


@dataclass(frozen=True, slots=True)
class BenchmarkCandidateSourceBoundaryRequest:
    source_paths: tuple[str, ...]
    adapter_kind: str = "default"
    allow_public_filenames: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.source_paths, tuple) or not self.source_paths or any(
            not isinstance(item, str) or not item.strip()
            for item in self.source_paths
        ):
            raise ValidationFailed(details={"field": "source_paths"})
        object.__setattr__(
            self,
            "adapter_kind",
            _required_text(self.adapter_kind, field="adapter_kind"),
        )
        if not isinstance(self.allow_public_filenames, tuple) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.allow_public_filenames
        ):
            raise ValidationFailed(
                details={"field": "allow_public_filenames"}
            )


@dataclass(frozen=True, slots=True)
class BenchmarkCandidateSourceClassification:
    schema_version: str
    path_recorded: bool
    basename: str
    source_kind: BenchmarkCandidateSourceKind
    allowed_for_candidate_selection: bool
    first_blocker: BenchmarkCandidateSourceBlocker | None
    recommended_action: str
    artifact_allowed_to_read: bool


@dataclass(frozen=True, slots=True)
class BenchmarkCandidateSelectionPolicy:
    allowed_source_kinds: tuple[str, ...]
    disallowed_source_kinds: tuple[str, ...]
    safe_private_artifact_glob: str


@dataclass(frozen=True, slots=True)
class BenchmarkCandidateReadBoundary:
    files_opened: bool
    raw_artifacts_read: bool
    task_text_read: bool
    trajectory_read: bool
    codex_transcript_read: bool
    local_paths_recorded: bool


@dataclass(frozen=True, slots=True)
class BenchmarkCandidateSourceBoundary:
    schema_version: str
    path_recorded: bool
    allowed_source_count: int
    blocked_source_count: int
    clean: bool
    allowed_source_basenames: tuple[str, ...]
    blocked_source_basenames: tuple[str, ...]
    blocked_reasons: tuple[BenchmarkReasonCount, ...]
    classifications: tuple[BenchmarkCandidateSourceClassification, ...]
    candidate_selection_policy: BenchmarkCandidateSelectionPolicy
    read_boundary: BenchmarkCandidateReadBoundary
    next_action: str


@dataclass(frozen=True, slots=True)
class BenchmarkParityCliCallCounts:
    status: int = 0
    quota_should_run: int = 0
    todo_list: int = 0
    history: int = 0
    check: int = 0
    todo_claim: int = 0
    todo_update: int = 0
    refresh_state: int = 0
    quota_spend: int = 0
    case_result: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class BenchmarkParitySafetyChecks:
    raw_task_text_absent: bool
    raw_reward_feedback_absent: bool
    raw_verifier_output_absent: bool
    raw_agent_trajectory_absent: bool


@dataclass(frozen=True, slots=True)
class BenchmarkParityRunEvidence:
    benchmark_id: str
    mode: str
    route: str
    product_mode: bool
    cli_call_counts: BenchmarkParityCliCallCounts
    state_reads: int
    state_writes: int
    case_init_required: bool
    case_initialized_before_agent: bool
    canonical_case_path_present: bool
    trajectory_summary_present: bool
    safety_checks: BenchmarkParitySafetyChecks


@dataclass(frozen=True, slots=True)
class BenchmarkParityCheckRequest:
    run: BenchmarkParityRunEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.run, BenchmarkParityRunEvidence):
            raise ValidationFailed(details={"field": "run"})


@dataclass(frozen=True, slots=True)
class BenchmarkParityEvidenceChecks:
    canonical_case_active_state_path: bool
    case_active_state_initialized_before_agent: bool
    loopx_cli_trace_present: bool
    required_loopx_cli_calls_present: bool
    stateful_loopx_lifecycle_observed: bool
    codex_cli_trajectory_summary_present: bool


@dataclass(frozen=True, slots=True)
class BenchmarkParityStatefulLifecycleCounts:
    state_reads: int
    state_writes: int


@dataclass(frozen=True, slots=True)
class BenchmarkParityCaseGoalState:
    init_required: bool
    initialized_before_agent: bool
    canonical_path_present: bool
    path_kind: BenchmarkParityCasePathKind


@dataclass(frozen=True, slots=True)
class BenchmarkParityReadBoundary:
    compact_benchmark_run_only: bool
    raw_task_text_read: bool
    raw_logs_read: bool
    raw_trajectory_read: bool
    verifier_output_read: bool
    credentials_read: bool
    local_paths_recorded: bool


@dataclass(frozen=True, slots=True)
class BenchmarkParityCheck:
    schema_version: str
    parity_target: str
    benchmark_id: str
    mode: str
    route: str
    product_mode: bool
    evidence_checks: BenchmarkParityEvidenceChecks
    safety_checks: BenchmarkParitySafetyChecks
    loopx_cli_call_counts: BenchmarkParityCliCallCounts
    stateful_lifecycle_counts: BenchmarkParityStatefulLifecycleCounts
    missing_required_cli_calls: tuple[BenchmarkParityRequiredCall, ...]
    case_goal_state: BenchmarkParityCaseGoalState
    missing_evidence: tuple[BenchmarkParityEvidenceKind, ...]
    safety_failures: tuple[BenchmarkParitySafetyKind, ...]
    full_product_claim_allowed: bool
    claim_level: BenchmarkParityClaimLevel
    read_boundary: BenchmarkParityReadBoundary
