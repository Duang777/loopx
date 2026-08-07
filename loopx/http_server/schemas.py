"""Pydantic wire models for the loopback HTTP v1 adapter.

Application dataclasses deliberately remain transport independent.  These
models are the only Python source for the HTTP/OpenAPI contract.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


NonEmptyText = Annotated[str, Field(min_length=1)]


class ErrorDetail(WireModel):
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)
    retryable: bool = False


class ErrorResponse(WireModel):
    error: ErrorDetail


class HealthResponse(WireModel):
    ok: Literal[True] = True
    service: Literal["loopx-http-server"] = "loopx-http-server"
    api_version: Literal["v1"] = "v1"
    profile: Literal["read_only", "local_operator"]
    static_assets: Literal["available", "unavailable"]


class EmptyJsonRequest(WireModel):
    pass


class ControlSessionResponse(WireModel):
    control_session_id: str
    role: Literal["viewer", "operator"]
    profile: Literal["read_only", "local_operator"]
    operator_slot_occupied: bool
    can_acquire: bool
    can_takeover: bool


class OperatorConfirmationRequest(WireModel):
    confirmed: Literal[True]


class OperatorStatusResponse(WireModel):
    role: Literal["viewer", "operator"]
    profile: Literal["read_only", "local_operator"]
    operator_slot_occupied: bool
    changed: bool = False
    can_acquire: bool
    can_takeover: bool


class CapabilityUnavailableReasonResponse(WireModel):
    code: str
    message: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class CapabilityResponse(WireModel):
    capability_id: str
    scope: Literal["application", "goal"]
    kind: Literal["read", "write", "execute"]
    available: bool
    supports_preview: bool
    requires_preview: bool
    unavailable_reason: CapabilityUnavailableReasonResponse | None = None


class CapabilityListResponse(WireModel):
    profile: Literal["read_only", "local_operator"]
    capabilities: list[CapabilityResponse]


class GoalSummaryResponse(WireModel):
    goal_id: str
    status: str | None
    domain: str | None
    generated_at: str
    revision: str


class GoalListResponse(WireModel):
    generated_at: str
    revision: str
    goals: list[GoalSummaryResponse]


class GoalOverviewResponse(WireModel):
    goal_id: str
    status: str | None
    attention_status: str | None
    domain: str | None
    adapter_kind: str | None
    adapter_status: str | None
    generated_at: str
    revision: str
    route_status: str
    routed_to_source_registry: bool


class HistoryEntryResponse(WireModel):
    run_id: str
    generated_at: str
    classification: str
    agent_id: str | None
    delivery_outcome: str | None
    progress_scope: str | None
    json_available: bool
    markdown_available: bool
    artifacts_verified: bool


class HistoryPageResponse(WireModel):
    goal_id: str
    generated_at: str
    revision: str
    items: list[HistoryEntryResponse]
    total_count: int
    next_page_token: str | None


class WriteContextRequest(WireModel):
    actor: NonEmptyText
    idempotency_key: NonEmptyText
    expected_revision: str | None = None


class WriteCorrectnessResponse(WireModel):
    status: str
    atomic_revision_check: bool
    idempotent_retry: bool


class GoalConfigurationPatchRequest(WireModel):
    quota_compute: float | None = None
    quota_window_hours: float | None = None
    self_repair_enabled: bool | None = None
    self_repair_health: bool | None = None
    self_repair_waiting_projection: bool | None = None
    change_quality_enabled: bool | None = None
    change_quality_safe_fix: bool | None = None
    change_quality_strict_receipt: bool | None = None
    multi_subagent_feature: str | None = None
    orchestration_mode: str | None = None
    spawn_allowed: bool | None = None
    max_children: int | None = None
    allowed_domains: list[str] | None = None
    clear_allowed_domains: bool = False
    explore_harness_enabled: bool | None = None
    explore_harness_profile: str | None = None
    clear_explore_harness_profile: bool = False
    explore_graph_enabled: bool | None = None
    registered_agents: list[str] | None = None
    clear_registered_agents: bool = False
    agent_profiles: list[dict[str, JsonValue]] | None = None
    clear_agent_profiles: list[str] | None = None
    agent_work_modes: dict[str, str] | None = None
    clear_agent_work_modes: list[str] | None = None
    todo_lifecycle_authority: list[dict[str, JsonValue]] | None = None
    clear_todo_lifecycle_authority: list[str] | None = None
    agent_model: str | None = None
    automation_prompt_migration_ack: str | None = None
    supervisor_agent: str | None = None
    supervised_agents: list[str] | None = None
    clear_supervisor: bool = False
    write_scope: list[str] | None = None
    replace_write_scope: bool = False
    clear_write_scope: bool = False
    waiting_on: str | None = None
    clear_waiting_on: bool = False
    boundary_authority_scopes: list[str] | None = None
    boundary_authority_source: str | None = None
    boundary_authority_decision_id: str | None = None
    boundary_authority_recorded_at: str | None = None
    boundary_authority_expires_at: str | None = None
    clear_boundary_authority: bool = False
    issue_fix_reviewer_notification_config: str | None = None
    clear_issue_fix_reviewer_notification_config: bool = False
    lark_event_inbox_config: str | None = None
    clear_lark_event_inbox_config: bool = False
    lark_kanban_heartbeat_sync: bool | None = None
    reward_memory_config: str | None = None
    reward_memory_agents: list[str] | None = None
    clear_reward_memory_config: bool = False


class ConfigurationEffectResponse(WireModel):
    field: str
    before: JsonValue
    after: JsonValue


class ConfigurationPlanResponse(WireModel):
    goal_id: str
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    changed: bool
    effects: list[ConfigurationEffectResponse]
    warnings: list[str]
    correctness: WriteCorrectnessResponse


class ConfigurationApplyResultResponse(WireModel):
    goal_id: str
    generated_at: str
    previous_revision: str
    revision: str
    plan_hash: str
    changed: bool
    written: bool
    global_sync_verified: bool
    correctness: WriteCorrectnessResponse


class ConfigurationPreviewRequest(WireModel):
    patch: GoalConfigurationPatchRequest


class ConfigurationApplyRequest(WireModel):
    patch: GoalConfigurationPatchRequest
    plan_hash: NonEmptyText
    write_context: WriteContextRequest


class TodoItemResponse(WireModel):
    todo_id: str
    role: str
    status: str
    text: str | None
    task_class: str | None
    action_kind: str | None
    claimed_by: str | None
    blocks_agent: str | None
    successor_todo_ids: list[str]
    updated_at: str | None


class TodoListResponse(WireModel):
    goal_id: str
    generated_at: str
    revision: str
    items: list[TodoItemResponse]


class TodoUpdatePatchRequest(WireModel):
    text: str | None = None
    status: str | None = None
    role: str | None = None
    note: str | None = None
    evidence: str | None = None
    reason: str | None = None
    task_class: str | None = None
    action_kind: str | None = None
    claimed_by: str | None = None
    clear_claim: bool = False


class TodoCompletionRequest(WireModel):
    evidence: str | None = None
    note: str | None = None
    decision_outcome: str | None = None
    claimed_by: str | None = None
    clear_claim: bool = False
    no_followup: bool = False
    successor_todo_ids: list[str] = Field(default_factory=list)
    next_agent_todo: str | None = None
    next_user_todo: str | None = None
    next_user_task_class: str | None = None
    next_claimed_by: str | None = None
    next_task_class: str | None = None
    next_action_kind: str | None = None
    next_task_repository: str | None = None
    next_required_capabilities: list[str] = Field(default_factory=list)
    next_continuation_policy: str | None = None
    next_excluded_agents: list[str] = Field(default_factory=list)
    self_merged: bool = False


class TodoCompletionPlanResponse(WireModel):
    goal_id: str
    todo_id: str
    actor: str
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    changed: bool
    successor_todo_ids: list[str]
    completion: TodoCompletionRequest
    correctness: WriteCorrectnessResponse


class TodoMutationResultResponse(WireModel):
    goal_id: str
    todo_id: str
    generated_at: str
    revision: str
    changed: bool
    item: TodoItemResponse | None
    successor_todo_ids: list[str]
    correctness: WriteCorrectnessResponse


class TodoClaimRequest(WireModel):
    write_context: WriteContextRequest


class TodoUpdateRequest(WireModel):
    patch: TodoUpdatePatchRequest
    write_context: WriteContextRequest


class TodoCompletePreviewRequest(WireModel):
    completion: TodoCompletionRequest
    actor: NonEmptyText


class TodoCompleteApplyRequest(WireModel):
    plan: TodoCompletionPlanResponse
    write_context: WriteContextRequest


class TaskLeaseResponse(WireModel):
    goal_id: str
    todo_id: str
    owner: str
    status: str
    active: bool
    version: int
    revision: str
    write_scopes: list[str]
    acquire_ttl_seconds: int | None
    acquired_at: str | None
    updated_at: str | None
    expires_at: str | None
    released_at: str | None = None


class TaskLeaseInspectionResponse(WireModel):
    goal_id: str
    todo_id: str
    generated_at: str
    active: bool
    lease: TaskLeaseResponse | None
    constraint_reason: str | None = None


class TaskLeaseMutationResultResponse(WireModel):
    action: str
    goal_id: str
    todo_id: str
    generated_at: str
    changed: bool
    idempotent: bool
    missing: bool
    lease: TaskLeaseResponse | None
    correctness: WriteCorrectnessResponse


class LeaseAcquireRequest(WireModel):
    write_context: WriteContextRequest
    ttl_seconds: int | None = Field(default=None, ge=1)
    write_scopes: list[str] = Field(default_factory=list)


class LeaseRenewRequest(WireModel):
    write_context: WriteContextRequest
    ttl_seconds: int | None = Field(default=None, ge=1)


class LeaseReleaseRequest(WireModel):
    write_context: WriteContextRequest


class QuotaBudgetResponse(WireModel):
    compute: float
    window_hours: int
    slot_minutes: int
    allowed_slots: int
    spent_slots: int


class QuotaDecisionResponse(WireModel):
    goal_id: str
    agent_id: str | None
    generated_at: str
    revision: str
    route_status: str
    decision: str
    should_run: bool
    state: str
    effective_action: str | None
    reason: str | None
    action_required: bool
    open_count: int
    recommended_action: str | None
    selected_todo_id: str | None
    must_attempt: bool
    delivery_allowed: bool
    quiet_noop_allowed: bool
    envelope_verified: bool
    envelope_within_budget: bool
    budget: QuotaBudgetResponse


class QuotaMutationPlanResponse(WireModel):
    goal_id: str
    operation: Literal["spend", "void"]
    source: Literal["adapter", "controller", "heartbeat", "visible-goal"]
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    slots: int
    agent_id: str | None
    before: QuotaBudgetResponse
    after: QuotaBudgetResponse | None
    would_throttle: bool
    target_generated_at: str | None
    reason_summary: str | None
    reason: str | None
    correctness: WriteCorrectnessResponse


class QuotaApplyResultResponse(WireModel):
    goal_id: str
    operation: Literal["spend", "void"]
    source: Literal["adapter", "controller", "heartbeat", "visible-goal"]
    generated_at: str
    event_generated_at: str
    previous_revision: str
    revision: str
    plan_hash: str
    written: bool
    slots: int
    agent_id: str | None
    target_generated_at: str | None
    correctness: WriteCorrectnessResponse


class QuotaSpendPreviewRequest(WireModel):
    slots: int = Field(default=1, ge=1)
    agent_id: str | None = None
    source: Literal["adapter", "controller", "heartbeat", "visible-goal"] = "heartbeat"


class QuotaVoidPreviewRequest(WireModel):
    voided_run_generated_at: NonEmptyText
    reason_summary: NonEmptyText
    agent_id: str | None = None
    source: Literal["adapter", "controller", "heartbeat", "visible-goal"] = "heartbeat"


class QuotaApplyRequest(WireModel):
    plan: QuotaMutationPlanResponse
    write_context: WriteContextRequest


class TurnPlanRequestBody(WireModel):
    agent_id: NonEmptyText
    turn_instance_id: NonEmptyText
    host: Literal["codex-cli", "claude-code", "generic-cli"]
    execution_mode: Literal["interactive-visible", "isolated-headless"]
    scheduler_owner: str | None = None
    session_binding: dict[str, JsonValue] | None = None


class TurnPlanResponse(WireModel):
    goal_id: str
    agent_id: str
    generated_at: str
    revision: str
    plan_hash: str
    route: str
    canonical_route_status: str
    routed_to_source_registry: bool
    core_contract_valid: bool
    would_invoke_host: bool
    can_run: bool
    execution_authorized: bool
    executor_available: bool
    commit_coordinator_available: bool
    turn_key: str
    selected_todo_id: str | None
    unavailable_reasons: list[str]


def model_payload(model: BaseModel) -> dict[str, Any]:
    """Return plain Python values suitable for transport-neutral constructors."""

    return model.model_dump(mode="python")
