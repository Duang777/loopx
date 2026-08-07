from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Protocol, TypeVar

from ...capabilities.content_ops.surface import (
    build_content_ops_exploration_plan_packet,
    build_content_ops_walkthrough_artifact_packet,
)
from ..errors import (
    ApplicationError,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from ._projection import (
    boolean,
    integer,
    mapping,
    optional_boolean,
    optional_text,
    sequence,
    text,
    text_tuple,
)


ResultT = TypeVar("ResultT")
_EXPLORATION_RESOURCE = "content_ops_exploration_plan"
_WALKTHROUGH_RESOURCE = "content_ops_walkthrough_artifact"
_ITEM_RESOURCE = "content_ops_item_create"
_ITEM_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ITEM_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ITEM_KINDS = {"article", "post", "profile_update", "reply", "repost"}


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationPlanRequest:
    scenario: str = "mixed_connector_product_workflow"
    generated_at: str = "2026-06-23T00:00:00Z"

    def __post_init__(self) -> None:
        _required_text(self.scenario, "scenario")
        _required_text(self.generated_at, "generated_at")


@dataclass(frozen=True, slots=True)
class ContentOpsApiPathCount:
    path: str
    count: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path.startswith("/api/"):
            raise ValidationFailed(details={"field": "api_path_counts.path"})
        _non_negative_integer(self.count, "api_path_counts.count")


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughRequest:
    public_handle_url: str = "https://x.com/OpenAI"
    public_source_item_id: str = "source_x_public_handle_walkthrough"
    chatview_source_item_id: str = "source_chatview_metadata_signal_walkthrough"
    channel_count: int = 0
    recent_record_count: int = 0
    report_count: int = 0
    api_request_count: int = 0
    api_path_counts: tuple[ContentOpsApiPathCount, ...] = ()
    private_preview_item_count: int = 0
    theme_signals: tuple[str, ...] = ()
    generated_at: str = "2026-06-23T00:00:00Z"

    def __post_init__(self) -> None:
        if not _is_public_https_url(self.public_handle_url):
            raise ValidationFailed(details={"field": "public_handle_url"})
        for field, value in (
            ("public_source_item_id", self.public_source_item_id),
            ("chatview_source_item_id", self.chatview_source_item_id),
            ("generated_at", self.generated_at),
        ):
            _required_text(value, field)
        for field, value in (
            ("channel_count", self.channel_count),
            ("recent_record_count", self.recent_record_count),
            ("report_count", self.report_count),
            ("api_request_count", self.api_request_count),
            ("private_preview_item_count", self.private_preview_item_count),
        ):
            _non_negative_integer(value, field)
        if not isinstance(self.api_path_counts, tuple) or not all(
            isinstance(item, ContentOpsApiPathCount)
            for item in self.api_path_counts
        ):
            raise ValidationFailed(details={"field": "api_path_counts"})
        paths = tuple(item.path for item in self.api_path_counts)
        if len(set(paths)) != len(paths):
            raise ValidationFailed(details={"field": "api_path_counts"})
        if (
            not isinstance(self.theme_signals, tuple)
            or len(self.theme_signals) > 8
            or not all(
                isinstance(item, str) and item.strip()
                for item in self.theme_signals
            )
        ):
            raise ValidationFailed(details={"field": "theme_signals"})


@dataclass(frozen=True, slots=True)
class ContentOpsItemCreateRequest:
    item_id: str
    item_kind: str
    channel: str
    content_digest: str
    content_ref: str
    source_refs: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        for field, value in (
            ("item_id", self.item_id),
            ("channel", self.channel),
            ("content_ref", self.content_ref),
        ):
            if not isinstance(value, str) or not _ITEM_TOKEN_RE.fullmatch(value):
                raise ValidationFailed(details={"field": field})
        if self.item_kind not in _ITEM_KINDS:
            raise ValidationFailed(details={"field": "item_kind"})
        if (
            not isinstance(self.content_digest, str)
            or not _ITEM_DIGEST_RE.fullmatch(self.content_digest)
        ):
            raise ValidationFailed(
                "content_digest must use sha256:<64 lowercase hex chars>",
                details={"field": "content_digest"},
            )
        if (
            not isinstance(self.source_refs, tuple)
            or not all(
                isinstance(item, str) and _ITEM_TOKEN_RE.fullmatch(item)
                for item in self.source_refs
            )
        ):
            raise ValidationFailed(details={"field": "source_refs"})
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValidationFailed(details={"field": "source_refs"})
        try:
            timestamp = datetime.fromisoformat(self.created_at)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(details={"field": "created_at"}) from exc
        if timestamp.tzinfo is None:
            raise ValidationFailed(details={"field": "created_at"})


@dataclass(frozen=True, slots=True)
class ContentOpsItem:
    schema_version: str
    item_id: str
    item_kind: str
    channel: str
    state: str
    revision: int
    content_digest: str
    content_ref: str
    source_refs: tuple[str, ...]
    approval: None
    delivery_intent: None
    delivery_receipt: None
    readback_receipt: None
    superseded_by: str | None
    terminal_reason: str | None
    last_event: None
    created_at: str
    updated_at: str
    autopublish_allowed: bool


@dataclass(frozen=True, slots=True)
class ContentOpsItemProjectionTruthContract:
    projection_is_writable: bool
    external_effect_authority: str
    autopublish_allowed: bool


@dataclass(frozen=True, slots=True)
class ContentOpsItemProjection:
    schema_version: str
    item_id: str
    item_kind: str
    channel: str
    state: str
    revision: int
    approval_present: bool
    delivery_intent_present: bool
    published_url: str | None
    readback_verified: bool
    terminal: bool
    superseded_by: str | None
    next_actions: tuple[str, ...]
    truth_contract: ContentOpsItemProjectionTruthContract


@dataclass(frozen=True, slots=True)
class ContentOpsItemCreateResult:
    schema_version: str
    item: ContentOpsItem
    projection: ContentOpsItemProjection
    external_reads_performed: bool
    external_writes_performed: bool
    autopublish_allowed: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ContentOpsNamedCount:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class ContentOpsUserGate:
    role: str
    action_kind: str
    question: str
    blocks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationLane:
    lane_id: str
    surface: str
    source_kind: str
    source_status: str
    access_mode: str
    read_status: str
    route: str
    fallback: str
    evidence_quality: str
    promotion_target: str
    requires_user_gate: bool
    user_gate: ContentOpsUserGate | None
    source_body_captured: bool
    response_payload_captured: bool
    local_path_captured: bool
    external_write_allowed: bool


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationLaneCounts:
    total: int
    user_gate_required: int
    metadata_ready: int
    blocked_until_owner_gate: int


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationFirstScreen:
    waiting_on: str
    user_action_required: bool
    agent_can_continue: bool
    top_agent_action: str
    top_user_gate: ContentOpsUserGate


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationBoundary:
    external_reads_performed: bool
    external_writes_performed: bool
    source_bodies_captured: bool
    response_payloads_captured: bool
    local_paths_captured: bool
    autopublish_allowed: bool


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationTruthContract:
    plan_is_writable: bool
    source_lanes_are_candidates: bool
    promotion_requires_target_surface_validation: bool
    private_boundary_crossing_requires_user_gate: bool


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationPlan:
    schema_version: str
    scenario: str
    generated_at: str
    selected_source_lanes: tuple[ContentOpsExplorationLane, ...]
    lane_counts: ContentOpsExplorationLaneCounts
    promotion_targets: tuple[ContentOpsNamedCount, ...]
    first_screen: ContentOpsExplorationFirstScreen
    boundary: ContentOpsExplorationBoundary
    truth_contract: ContentOpsExplorationTruthContract


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationValidation:
    schema_version: str
    ok: bool
    errors: tuple[str, ...]
    lane_count: int


@dataclass(frozen=True, slots=True)
class ContentOpsExplorationPlanResult:
    schema_version: str
    mode: str
    exploration_plan: ContentOpsExplorationPlan
    validation: ContentOpsExplorationValidation
    external_reads_performed: bool
    external_writes_performed: bool
    private_source_bodies_read: bool
    private_source_content_read: bool
    local_paths_captured: bool
    autopublish_allowed: bool
    next_safe_action: str
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughSourceCard:
    source_item_id: str
    source_status: str
    allowed_use: str
    summary: str


@dataclass(frozen=True, slots=True)
class ContentOpsPrivateOperatorPreview:
    available_in_current_operator_session: bool
    sample_record_count: int
    theme_signals: tuple[str, ...]
    stored_in_repo: bool
    source_content_recorded: bool
    response_payload_recorded: bool


@dataclass(frozen=True, slots=True)
class ContentOpsDraftGate:
    draft_id: str
    state: str
    publish_gate_id: str
    publish_status: str
    approval_required: bool
    autopublish_allowed: bool


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughOperatorArtifact:
    headline: str
    source_cards: tuple[ContentOpsWalkthroughSourceCard, ...]
    private_operator_preview: ContentOpsPrivateOperatorPreview
    draft_gate: ContentOpsDraftGate
    next_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughObservedShape:
    channel_count: int
    recent_record_count: int
    report_count: int
    api_request_count: int
    api_path_counts: tuple[ContentOpsNamedCount, ...]


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughChainStep:
    step: str
    result: str
    source_item_id: str | None
    external_write_performed: bool | None
    observed_shape: ContentOpsWalkthroughObservedShape | None
    owner_gate_required: bool | None
    waiting_on: str | None
    user_action_required: bool | None
    approval_required: bool | None
    autopublish_allowed: bool | None


@dataclass(frozen=True, slots=True)
class ContentOpsProjectionFirstScreen:
    waiting_on: str
    user_action_required: bool
    agent_can_continue: bool
    safe_side_work_available: bool
    source_review_required_count: int
    ready_to_draft_count: int
    waiting_for_feedback_count: int
    publish_decision_count: int
    next_safe_action: str


@dataclass(frozen=True, slots=True)
class ContentOpsRecordCounts:
    source_items: int
    angle_candidates: int
    draft_items: int
    feedback_signals: int
    publish_gates: int
    material_memory: int
    connector_trials: int


@dataclass(frozen=True, slots=True)
class ContentOpsConnectorTrialStats:
    count: int
    states: tuple[ContentOpsNamedCount, ...]
    access_modes: tuple[ContentOpsNamedCount, ...]
    surfaces: tuple[ContentOpsNamedCount, ...]
    ready_for_metadata_trial_count: int
    owner_gate_required_count: int


@dataclass(frozen=True, slots=True)
class ContentOpsMaterialMemoryStats:
    count: int
    reuse_boundaries: tuple[ContentOpsNamedCount, ...]


@dataclass(frozen=True, slots=True)
class ContentOpsTodoCandidate:
    role: str
    action_kind: str
    title: str
    validation_surface: str
    stop_condition: str | None
    angle_ids: tuple[str, ...] | None
    source_item_ids: tuple[str, ...] | None
    publish_gate_ids: tuple[str, ...] | None
    trial_ids: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ContentOpsSurfaceValidation:
    schema_version: str
    ok: bool
    errors: tuple[str, ...]
    record_counts: ContentOpsRecordCounts
    raw_material_key_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContentOpsProjectionTruthContract:
    projection_is_writable: bool
    write_authority: str
    source_surface_is_source_of_truth: bool
    publish_gate_required: bool
    autopublish_allowed: bool
    raw_private_material_copied: bool
    recompute_rule: str


@dataclass(frozen=True, slots=True)
class ContentOpsSurfaceProjection:
    schema_version: str
    surface_schema_version: str
    surface_id: str
    mode: str
    first_screen: ContentOpsProjectionFirstScreen
    record_counts: ContentOpsRecordCounts
    source_statuses: tuple[ContentOpsNamedCount, ...]
    draft_states: tuple[ContentOpsNamedCount, ...]
    feedback_effects: tuple[ContentOpsNamedCount, ...]
    publish_gate_statuses: tuple[ContentOpsNamedCount, ...]
    connector_trials: ContentOpsConnectorTrialStats
    material_memory: ContentOpsMaterialMemoryStats
    todo_candidates: tuple[ContentOpsTodoCandidate, ...]
    validation: ContentOpsSurfaceValidation
    truth_contract: ContentOpsProjectionTruthContract


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughPacketSummary:
    public_packet_schema_version: str
    chatview_packet_schema_version: str
    aggregation_schema_version: str
    source_item_count: int
    owner_gate_required_count: int


@dataclass(frozen=True, slots=True)
class ContentOpsWalkthroughResult:
    schema_version: str
    mode: str
    generated_at: str
    operator_artifact: ContentOpsWalkthroughOperatorArtifact
    chain_steps: tuple[ContentOpsWalkthroughChainStep, ...]
    aggregation_projection: ContentOpsSurfaceProjection
    validation: ContentOpsSurfaceValidation
    packet_summary: ContentOpsWalkthroughPacketSummary
    external_reads_performed: bool
    external_writes_performed: bool
    private_source_bodies_read: bool
    private_source_content_read: bool
    autopublish_allowed: bool
    public_repo_safe: bool
    next_safe_action: str
    ok: bool = True


class ContentOpsReadProvider(Protocol):
    def exploration_plan(
        self,
        request: ContentOpsExplorationPlanRequest,
    ) -> ContentOpsExplorationPlanResult: ...

    def walkthrough_artifact(
        self,
        request: ContentOpsWalkthroughRequest,
    ) -> ContentOpsWalkthroughResult: ...


class ContentOpsItemProvider(Protocol):
    def create_item(
        self,
        request: ContentOpsItemCreateRequest,
    ) -> ContentOpsItemCreateResult: ...


class BuiltinContentOpsReadProvider:
    def __init__(
        self,
        *,
        exploration_builder: Callable[..., Mapping[str, object]] = (
            build_content_ops_exploration_plan_packet
        ),
        walkthrough_builder: Callable[..., Mapping[str, object]] = (
            build_content_ops_walkthrough_artifact_packet
        ),
    ) -> None:
        self._exploration_builder = exploration_builder
        self._walkthrough_builder = walkthrough_builder

    def exploration_plan(
        self,
        request: ContentOpsExplorationPlanRequest,
    ) -> ContentOpsExplorationPlanResult:
        return _exploration_result(
            self._exploration_builder(
                scenario=request.scenario,
                generated_at=request.generated_at,
            )
        )

    def walkthrough_artifact(
        self,
        request: ContentOpsWalkthroughRequest,
    ) -> ContentOpsWalkthroughResult:
        return _walkthrough_result(
            self._walkthrough_builder(
                public_handle_url=request.public_handle_url,
                public_source_item_id=request.public_source_item_id,
                chatview_source_item_id=request.chatview_source_item_id,
                channel_count=request.channel_count,
                recent_record_count=request.recent_record_count,
                report_count=request.report_count,
                api_request_count=request.api_request_count,
                api_path_counts={
                    item.path: item.count for item in request.api_path_counts
                },
                private_preview_item_count=request.private_preview_item_count,
                theme_signals=request.theme_signals,
                generated_at=request.generated_at,
            )
        )


class ContentOpsService:
    __slots__ = ("_item_provider", "_provider")

    def __init__(
        self,
        provider: ContentOpsReadProvider | None,
        item_provider: ContentOpsItemProvider | None = None,
    ) -> None:
        self._provider = provider
        self._item_provider = item_provider

    @classmethod
    def builtin(cls) -> ContentOpsService:
        return cls(BuiltinContentOpsReadProvider())

    def exploration_plan(
        self,
        request: ContentOpsExplorationPlanRequest,
    ) -> ContentOpsExplorationPlanResult:
        provider = self._require_provider("exploration_plan")
        return _invoke(lambda: provider.exploration_plan(request), _EXPLORATION_RESOURCE)

    def walkthrough_artifact(
        self,
        request: ContentOpsWalkthroughRequest,
    ) -> ContentOpsWalkthroughResult:
        provider = self._require_provider("walkthrough_artifact")
        return _invoke(
            lambda: provider.walkthrough_artifact(request),
            _WALKTHROUGH_RESOURCE,
        )

    def create_item(
        self,
        request: ContentOpsItemCreateRequest,
    ) -> ContentOpsItemCreateResult:
        if self._item_provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": "application.capabilities.content_ops.create_item",
                    "provider": "content_ops_item",
                }
            )
        return _invoke(lambda: self._item_provider.create_item(request), _ITEM_RESOURCE)

    def _require_provider(self, operation: str) -> ContentOpsReadProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": f"application.capabilities.content_ops.{operation}",
                    "provider": "content_ops_read_model",
                }
            )
        return self._provider


def _exploration_result(
    payload: Mapping[str, object],
) -> ContentOpsExplorationPlanResult:
    resource = _EXPLORATION_RESOURCE
    plan = mapping(payload.get("exploration_plan"), resource=resource, field="exploration_plan")
    lane_counts = mapping(plan.get("lane_counts"), resource=resource, field="lane_counts")
    first_screen = mapping(plan.get("first_screen"), resource=resource, field="first_screen")
    boundary = mapping(plan.get("boundary"), resource=resource, field="boundary")
    truth = mapping(plan.get("truth_contract"), resource=resource, field="truth_contract")
    validation = mapping(payload.get("validation"), resource=resource, field="validation")
    return ContentOpsExplorationPlanResult(
        ok=boolean(payload, "ok", resource=resource),
        schema_version=text(payload, "schema_version", resource=resource),
        mode=text(payload, "mode", resource=resource),
        exploration_plan=ContentOpsExplorationPlan(
            schema_version=text(plan, "schema_version", resource=resource),
            scenario=text(plan, "scenario", resource=resource),
            generated_at=text(plan, "generated_at", resource=resource),
            selected_source_lanes=tuple(
                _exploration_lane(item, index=index)
                for index, item in enumerate(
                    sequence(
                        plan.get("selected_source_lanes"),
                        resource=resource,
                        field="selected_source_lanes",
                    )
                )
            ),
            lane_counts=ContentOpsExplorationLaneCounts(
                total=integer(lane_counts, "total", resource=resource),
                user_gate_required=integer(
                    lane_counts,
                    "user_gate_required",
                    resource=resource,
                ),
                metadata_ready=integer(
                    lane_counts,
                    "metadata_ready",
                    resource=resource,
                ),
                blocked_until_owner_gate=integer(
                    lane_counts,
                    "blocked_until_owner_gate",
                    resource=resource,
                ),
            ),
            promotion_targets=_named_counts(
                plan.get("promotion_targets"),
                resource=resource,
                field="promotion_targets",
            ),
            first_screen=ContentOpsExplorationFirstScreen(
                waiting_on=text(first_screen, "waiting_on", resource=resource),
                user_action_required=boolean(
                    first_screen,
                    "user_action_required",
                    resource=resource,
                ),
                agent_can_continue=boolean(
                    first_screen,
                    "agent_can_continue",
                    resource=resource,
                ),
                top_agent_action=text(
                    first_screen,
                    "top_agent_action",
                    resource=resource,
                ),
                top_user_gate=_user_gate(
                    first_screen.get("top_user_gate"),
                    resource=resource,
                    field="top_user_gate",
                ),
            ),
            boundary=ContentOpsExplorationBoundary(
                external_reads_performed=boolean(
                    boundary,
                    "external_reads_performed",
                    resource=resource,
                ),
                external_writes_performed=boolean(
                    boundary,
                    "external_writes_performed",
                    resource=resource,
                ),
                source_bodies_captured=boolean(
                    boundary,
                    "source_bodies_captured",
                    resource=resource,
                ),
                response_payloads_captured=boolean(
                    boundary,
                    "response_payloads_captured",
                    resource=resource,
                ),
                local_paths_captured=boolean(
                    boundary,
                    "local_paths_captured",
                    resource=resource,
                ),
                autopublish_allowed=boolean(
                    boundary,
                    "autopublish_allowed",
                    resource=resource,
                ),
            ),
            truth_contract=ContentOpsExplorationTruthContract(
                plan_is_writable=boolean(
                    truth,
                    "plan_is_writable",
                    resource=resource,
                ),
                source_lanes_are_candidates=boolean(
                    truth,
                    "source_lanes_are_candidates",
                    resource=resource,
                ),
                promotion_requires_target_surface_validation=boolean(
                    truth,
                    "promotion_requires_target_surface_validation",
                    resource=resource,
                ),
                private_boundary_crossing_requires_user_gate=boolean(
                    truth,
                    "private_boundary_crossing_requires_user_gate",
                    resource=resource,
                ),
            ),
        ),
        validation=ContentOpsExplorationValidation(
            schema_version=text(validation, "schema_version", resource=resource),
            ok=boolean(validation, "ok", resource=resource),
            errors=text_tuple(
                validation.get("errors"),
                resource=resource,
                field="validation.errors",
            ),
            lane_count=integer(validation, "lane_count", resource=resource),
        ),
        external_reads_performed=boolean(
            payload,
            "external_reads_performed",
            resource=resource,
        ),
        external_writes_performed=boolean(
            payload,
            "external_writes_performed",
            resource=resource,
        ),
        private_source_bodies_read=boolean(
            payload,
            "private_source_bodies_read",
            resource=resource,
        ),
        private_source_content_read=boolean(
            payload,
            "private_source_content_read",
            resource=resource,
        ),
        local_paths_captured=boolean(
            payload,
            "local_paths_captured",
            resource=resource,
        ),
        autopublish_allowed=boolean(
            payload,
            "autopublish_allowed",
            resource=resource,
        ),
        next_safe_action=text(payload, "next_safe_action", resource=resource),
    )


def _exploration_lane(value: object, *, index: int) -> ContentOpsExplorationLane:
    resource = _EXPLORATION_RESOURCE
    item = mapping(value, resource=resource, field=f"selected_source_lanes[{index}]")
    user_gate = (
        None
        if item.get("user_gate") is None
        else _user_gate(
            item.get("user_gate"),
            resource=resource,
            field=f"selected_source_lanes[{index}].user_gate",
        )
    )
    return ContentOpsExplorationLane(
        lane_id=text(item, "lane_id", resource=resource),
        surface=text(item, "surface", resource=resource),
        source_kind=text(item, "source_kind", resource=resource),
        source_status=text(item, "source_status", resource=resource),
        access_mode=text(item, "access_mode", resource=resource),
        read_status=text(item, "read_status", resource=resource),
        route=text(item, "route", resource=resource),
        fallback=text(item, "fallback", resource=resource),
        evidence_quality=text(item, "evidence_quality", resource=resource),
        promotion_target=text(item, "promotion_target", resource=resource),
        requires_user_gate=boolean(item, "requires_user_gate", resource=resource),
        user_gate=user_gate,
        source_body_captured=boolean(
            item,
            "source_body_captured",
            resource=resource,
        ),
        response_payload_captured=boolean(
            item,
            "response_payload_captured",
            resource=resource,
        ),
        local_path_captured=boolean(item, "local_path_captured", resource=resource),
        external_write_allowed=boolean(
            item,
            "external_write_allowed",
            resource=resource,
        ),
    )


def _user_gate(
    value: object,
    *,
    resource: str,
    field: str,
) -> ContentOpsUserGate:
    item = mapping(value, resource=resource, field=field)
    return ContentOpsUserGate(
        role=text(item, "role", resource=resource),
        action_kind=text(item, "action_kind", resource=resource),
        question=text(item, "question", resource=resource),
        blocks=text_tuple(item.get("blocks"), resource=resource, field=f"{field}.blocks"),
    )


def _walkthrough_result(payload: Mapping[str, object]) -> ContentOpsWalkthroughResult:
    resource = _WALKTHROUGH_RESOURCE
    operator = mapping(payload.get("operator_artifact"), resource=resource, field="operator_artifact")
    preview = mapping(operator.get("private_operator_preview"), resource=resource, field="private_operator_preview")
    draft_gate = mapping(operator.get("draft_gate"), resource=resource, field="draft_gate")
    packet_summary = mapping(payload.get("packet_summary"), resource=resource, field="packet_summary")
    return ContentOpsWalkthroughResult(
        ok=boolean(payload, "ok", resource=resource),
        schema_version=text(payload, "schema_version", resource=resource),
        mode=text(payload, "mode", resource=resource),
        generated_at=text(payload, "generated_at", resource=resource),
        operator_artifact=ContentOpsWalkthroughOperatorArtifact(
            headline=text(operator, "headline", resource=resource),
            source_cards=tuple(
                _source_card(item, index=index)
                for index, item in enumerate(
                    sequence(operator.get("source_cards"), resource=resource, field="source_cards")
                )
            ),
            private_operator_preview=ContentOpsPrivateOperatorPreview(
                available_in_current_operator_session=boolean(
                    preview,
                    "available_in_current_operator_session",
                    resource=resource,
                ),
                sample_record_count=integer(preview, "sample_record_count", resource=resource),
                theme_signals=text_tuple(
                    preview.get("theme_signals"),
                    resource=resource,
                    field="theme_signals",
                ),
                stored_in_repo=boolean(preview, "stored_in_repo", resource=resource),
                source_content_recorded=boolean(
                    preview,
                    "source_content_recorded",
                    resource=resource,
                ),
                response_payload_recorded=boolean(
                    preview,
                    "response_payload_recorded",
                    resource=resource,
                ),
            ),
            draft_gate=ContentOpsDraftGate(
                draft_id=text(draft_gate, "draft_id", resource=resource),
                state=text(draft_gate, "state", resource=resource),
                publish_gate_id=text(draft_gate, "publish_gate_id", resource=resource),
                publish_status=text(draft_gate, "publish_status", resource=resource),
                approval_required=boolean(draft_gate, "approval_required", resource=resource),
                autopublish_allowed=boolean(draft_gate, "autopublish_allowed", resource=resource),
            ),
            next_actions=text_tuple(
                operator.get("next_actions"),
                resource=resource,
                field="next_actions",
            ),
        ),
        chain_steps=tuple(
            _chain_step(item, index=index)
            for index, item in enumerate(
                sequence(payload.get("chain_steps"), resource=resource, field="chain_steps")
            )
        ),
        aggregation_projection=_surface_projection(
            payload.get("aggregation_projection")
        ),
        validation=_surface_validation(payload.get("validation"), field="validation"),
        packet_summary=ContentOpsWalkthroughPacketSummary(
            public_packet_schema_version=text(
                packet_summary,
                "public_packet_schema_version",
                resource=resource,
            ),
            chatview_packet_schema_version=text(
                packet_summary,
                "chatview_packet_schema_version",
                resource=resource,
            ),
            aggregation_schema_version=text(
                packet_summary,
                "aggregation_schema_version",
                resource=resource,
            ),
            source_item_count=integer(packet_summary, "source_item_count", resource=resource),
            owner_gate_required_count=integer(
                packet_summary,
                "owner_gate_required_count",
                resource=resource,
            ),
        ),
        external_reads_performed=boolean(payload, "external_reads_performed", resource=resource),
        external_writes_performed=boolean(payload, "external_writes_performed", resource=resource),
        private_source_bodies_read=boolean(payload, "private_source_bodies_read", resource=resource),
        private_source_content_read=boolean(payload, "private_source_content_read", resource=resource),
        autopublish_allowed=boolean(payload, "autopublish_allowed", resource=resource),
        public_repo_safe=boolean(payload, "public_repo_safe", resource=resource),
        next_safe_action=text(payload, "next_safe_action", resource=resource),
    )


def _source_card(value: object, *, index: int) -> ContentOpsWalkthroughSourceCard:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field=f"source_cards[{index}]")
    return ContentOpsWalkthroughSourceCard(
        source_item_id=text(item, "source_item_id", resource=resource),
        source_status=text(item, "source_status", resource=resource),
        allowed_use=text(item, "allowed_use", resource=resource),
        summary=text(item, "summary", resource=resource),
    )


def _chain_step(value: object, *, index: int) -> ContentOpsWalkthroughChainStep:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field=f"chain_steps[{index}]")
    raw_shape = item.get("observed_shape")
    shape = None
    if raw_shape is not None:
        observed = mapping(raw_shape, resource=resource, field=f"chain_steps[{index}].observed_shape")
        shape = ContentOpsWalkthroughObservedShape(
            channel_count=integer(observed, "channel_count", resource=resource),
            recent_record_count=integer(observed, "recent_record_count", resource=resource),
            report_count=integer(observed, "report_count", resource=resource),
            api_request_count=integer(observed, "api_request_count", resource=resource),
            api_path_counts=_named_counts(
                observed.get("api_path_counts"),
                resource=resource,
                field="api_path_counts",
            ),
        )
    return ContentOpsWalkthroughChainStep(
        step=text(item, "step", resource=resource),
        result=text(item, "result", resource=resource),
        source_item_id=optional_text(item, "source_item_id", resource=resource),
        external_write_performed=optional_boolean(
            item,
            "external_write_performed",
            resource=resource,
        ),
        observed_shape=shape,
        owner_gate_required=optional_boolean(item, "owner_gate_required", resource=resource),
        waiting_on=optional_text(item, "waiting_on", resource=resource),
        user_action_required=optional_boolean(item, "user_action_required", resource=resource),
        approval_required=optional_boolean(item, "approval_required", resource=resource),
        autopublish_allowed=optional_boolean(item, "autopublish_allowed", resource=resource),
    )


def _surface_projection(value: object) -> ContentOpsSurfaceProjection:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field="aggregation_projection")
    first = mapping(item.get("first_screen"), resource=resource, field="first_screen")
    trials = mapping(item.get("connector_trials"), resource=resource, field="connector_trials")
    memory = mapping(item.get("material_memory"), resource=resource, field="material_memory")
    truth = mapping(item.get("truth_contract"), resource=resource, field="truth_contract")
    return ContentOpsSurfaceProjection(
        schema_version=text(item, "schema_version", resource=resource),
        surface_schema_version=text(item, "surface_schema_version", resource=resource),
        surface_id=text(item, "surface_id", resource=resource),
        mode=text(item, "mode", resource=resource),
        first_screen=ContentOpsProjectionFirstScreen(
            waiting_on=text(first, "waiting_on", resource=resource),
            user_action_required=boolean(first, "user_action_required", resource=resource),
            agent_can_continue=boolean(first, "agent_can_continue", resource=resource),
            safe_side_work_available=boolean(first, "safe_side_work_available", resource=resource),
            source_review_required_count=integer(first, "source_review_required_count", resource=resource),
            ready_to_draft_count=integer(first, "ready_to_draft_count", resource=resource),
            waiting_for_feedback_count=integer(first, "waiting_for_feedback_count", resource=resource),
            publish_decision_count=integer(first, "publish_decision_count", resource=resource),
            next_safe_action=text(first, "next_safe_action", resource=resource),
        ),
        record_counts=_record_counts(item.get("record_counts"), field="record_counts"),
        source_statuses=_named_counts(item.get("source_statuses"), resource=resource, field="source_statuses"),
        draft_states=_named_counts(item.get("draft_states"), resource=resource, field="draft_states"),
        feedback_effects=_named_counts(item.get("feedback_effects"), resource=resource, field="feedback_effects"),
        publish_gate_statuses=_named_counts(item.get("publish_gate_statuses"), resource=resource, field="publish_gate_statuses"),
        connector_trials=ContentOpsConnectorTrialStats(
            count=integer(trials, "count", resource=resource),
            states=_named_counts(trials.get("states"), resource=resource, field="connector_trials.states"),
            access_modes=_named_counts(trials.get("access_modes"), resource=resource, field="connector_trials.access_modes"),
            surfaces=_named_counts(trials.get("surfaces"), resource=resource, field="connector_trials.surfaces"),
            ready_for_metadata_trial_count=integer(trials, "ready_for_metadata_trial_count", resource=resource),
            owner_gate_required_count=integer(trials, "owner_gate_required_count", resource=resource),
        ),
        material_memory=ContentOpsMaterialMemoryStats(
            count=integer(memory, "count", resource=resource),
            reuse_boundaries=_named_counts(memory.get("reuse_boundaries"), resource=resource, field="material_memory.reuse_boundaries"),
        ),
        todo_candidates=tuple(
            _todo_candidate(candidate, index=index)
            for index, candidate in enumerate(
                sequence(item.get("todo_candidates"), resource=resource, field="todo_candidates")
            )
        ),
        validation=_surface_validation(item.get("validation"), field="projection.validation"),
        truth_contract=ContentOpsProjectionTruthContract(
            projection_is_writable=boolean(truth, "projection_is_writable", resource=resource),
            write_authority=text(truth, "write_authority", resource=resource),
            source_surface_is_source_of_truth=boolean(truth, "source_surface_is_source_of_truth", resource=resource),
            publish_gate_required=boolean(truth, "publish_gate_required", resource=resource),
            autopublish_allowed=boolean(truth, "autopublish_allowed", resource=resource),
            raw_private_material_copied=boolean(truth, "raw_private_material_copied", resource=resource),
            recompute_rule=text(truth, "recompute_rule", resource=resource),
        ),
    )


def _todo_candidate(value: object, *, index: int) -> ContentOpsTodoCandidate:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field=f"todo_candidates[{index}]")
    return ContentOpsTodoCandidate(
        role=text(item, "role", resource=resource),
        action_kind=text(item, "action_kind", resource=resource),
        title=text(item, "title", resource=resource),
        validation_surface=text(item, "validation_surface", resource=resource),
        stop_condition=optional_text(item, "stop_condition", resource=resource),
        angle_ids=_optional_text_tuple(item, "angle_ids", resource=resource),
        source_item_ids=_optional_text_tuple(item, "source_item_ids", resource=resource),
        publish_gate_ids=_optional_text_tuple(item, "publish_gate_ids", resource=resource),
        trial_ids=_optional_text_tuple(item, "trial_ids", resource=resource),
    )


def _surface_validation(value: object, *, field: str) -> ContentOpsSurfaceValidation:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field=field)
    return ContentOpsSurfaceValidation(
        schema_version=text(item, "schema_version", resource=resource),
        ok=boolean(item, "ok", resource=resource),
        errors=text_tuple(item.get("errors"), resource=resource, field=f"{field}.errors"),
        record_counts=_record_counts(item.get("record_counts"), field=f"{field}.record_counts"),
        raw_material_key_names=text_tuple(
            item.get("raw_material_key_names"),
            resource=resource,
            field=f"{field}.raw_material_key_names",
        ),
    )


def _record_counts(value: object, *, field: str) -> ContentOpsRecordCounts:
    resource = _WALKTHROUGH_RESOURCE
    item = mapping(value, resource=resource, field=field)
    return ContentOpsRecordCounts(
        source_items=integer(item, "source_items", resource=resource),
        angle_candidates=integer(item, "angle_candidates", resource=resource),
        draft_items=integer(item, "draft_items", resource=resource),
        feedback_signals=integer(item, "feedback_signals", resource=resource),
        publish_gates=integer(item, "publish_gates", resource=resource),
        material_memory=integer(item, "material_memory", resource=resource),
        connector_trials=integer(item, "connector_trials", resource=resource),
    )


def _named_counts(
    value: object,
    *,
    resource: str,
    field: str,
) -> tuple[ContentOpsNamedCount, ...]:
    items = mapping(value, resource=resource, field=field)
    result: list[ContentOpsNamedCount] = []
    for name, raw_count in items.items():
        if not isinstance(name, str) or not name:
            raise StateUnavailable(details={"resource": resource, "field": field})
        result.append(
            ContentOpsNamedCount(
                name=name,
                count=integer({"count": raw_count}, "count", resource=resource),
            )
        )
    return tuple(result)


def _optional_text_tuple(
    item: Mapping[str, object],
    field: str,
    *,
    resource: str,
) -> tuple[str, ...] | None:
    if item.get(field) is None:
        return None
    return text_tuple(item.get(field), resource=resource, field=field)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value


def _is_public_https_url(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    prefix = "https://"
    if not value.startswith(prefix) or "?" in value or "#" in value:
        return False
    authority = value[len(prefix) :].split("/", 1)[0]
    if not authority or "@" in authority or any(char.isspace() for char in authority):
        return False
    if authority.startswith("["):
        return "]" in authority
    host = authority.rsplit(":", 1)[0] if ":" in authority else authority
    return bool(host.strip("."))


def _non_negative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValidationFailed(details={"field": field})
    return value


def _invoke(call: Callable[[], ResultT], resource: str) -> ResultT:
    try:
        return call()
    except ApplicationError:
        raise
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    except OSError as exc:
        raise StateUnavailable(
            details={"resource": resource, "cause": type(exc).__name__}
        ) from exc
