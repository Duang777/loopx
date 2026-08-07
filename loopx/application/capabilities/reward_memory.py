from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar

from ...capabilities.reward_memory.architecture import (
    build_reward_memory_route_packet,
    pr_3237_regression_observation,
)
from ...capabilities.reward_memory.candidate_review import (
    issue_fix_verified_contributor_candidate_fixture,
    review_reward_memory_candidate,
)
from ...capabilities.reward_memory.health import (
    build_reward_memory_corpus_health_packet,
    reward_memory_health_case,
)
from ...capabilities.reward_memory.registry import (
    build_reward_memory_corpus_registry_packet,
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
    optional_integer,
    optional_text,
    sequence,
    text,
    text_tuple,
)


ResultT = TypeVar("ResultT")
_RESOURCE = "reward_memory_fixture"
_HEALTH_CASES = frozenset(
    {
        "unavailable",
        "empty",
        "stale",
        "wrong-project",
        "wrong-surface",
        "index-unavailable",
        "retrieval-failed",
        "readback-unverified",
        "retrieval-verified",
        "applied-verified",
    }
)


@dataclass(frozen=True, slots=True)
class RewardMemoryHealthRequest:
    case: str = "retrieval-verified"

    def __post_init__(self) -> None:
        if self.case not in _HEALTH_CASES:
            raise ValidationFailed(details={"field": "case"})


@dataclass(frozen=True, slots=True)
class RewardMemoryRouteRequest:
    case: str | None = None
    behavior_status: str = "bug_confirmed"
    surface_count: int = 1
    semantic_contract_change: bool = False
    generic_boundary_for_specific_policy: bool = False
    user_visible_behavior_change: bool = False
    hot_path_or_storage_change: bool = False
    retrieval_or_memory_quality_claim: bool = False
    edge_case_complexity: str = "low"
    named_reproduction: bool = False
    named_validation: bool = False
    effect_evidence: bool = False
    ux_evidence: bool = False
    benchmark_evidence: bool = False
    performance_evidence: bool = False

    def __post_init__(self) -> None:
        if self.case not in {None, "pr-3237"}:
            raise ValidationFailed(details={"field": "case"})
        if self.behavior_status not in {"bug_confirmed", "by_design", "uncertain"}:
            raise ValidationFailed(details={"field": "behavior_status"})
        if (
            not isinstance(self.surface_count, int)
            or isinstance(self.surface_count, bool)
            or self.surface_count < 1
            or self.surface_count > 20
        ):
            raise ValidationFailed(details={"field": "surface_count"})
        if self.edge_case_complexity not in {"low", "medium", "high"}:
            raise ValidationFailed(details={"field": "edge_case_complexity"})
        for field in (
            "semantic_contract_change",
            "generic_boundary_for_specific_policy",
            "user_visible_behavior_change",
            "hot_path_or_storage_change",
            "retrieval_or_memory_quality_claim",
            "named_reproduction",
            "named_validation",
            "effect_evidence",
            "ux_evidence",
            "benchmark_evidence",
            "performance_evidence",
        ):
            if not isinstance(getattr(self, field), bool):
                raise ValidationFailed(details={"field": field})


@dataclass(frozen=True, slots=True)
class RewardMemoryScopeCheck:
    project_matches: bool
    surface_matches: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryFreshnessCheck:
    lifecycle_state: str
    source_revision_matches: bool
    freshness_window_satisfied: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryPipeline:
    provider_available: bool
    corpus_present: bool
    record_count: int
    index_required: bool
    index_present: bool
    retrieval_query_succeeded: bool
    result_readback_verified: bool
    memory_applied_with_receipt: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryHealthResult:
    schema_version: str
    corpus_id: str
    class_id: str
    health_state: str
    reason_codes: tuple[str, ...]
    scope_check: RewardMemoryScopeCheck
    freshness_check: RewardMemoryFreshnessCheck
    pipeline: RewardMemoryPipeline
    may_apply_memory: bool
    memory_patch_authority: bool
    external_write_authorized: bool
    raw_memory_captured: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class RewardMemoryRouteResult:
    schema_version: str
    case_ref: str
    decision: str
    reason_codes: tuple[str, ...]
    required_evidence: tuple[str, ...]
    missing_required_evidence: tuple[str, ...]
    pilot_authorized: bool
    meta_review_required: bool
    route_check_role: str
    live_reasoning_required: bool
    memory_patch_authority: bool
    external_write_authorized: bool
    raw_issue_or_memory_captured: bool
    ok: bool = True


class RewardMemoryFixtureProvider(Protocol):
    def health(self, request: RewardMemoryHealthRequest) -> RewardMemoryHealthResult: ...

    def route(self, request: RewardMemoryRouteRequest) -> RewardMemoryRouteResult: ...


class BuiltinRewardMemoryFixtureProvider:
    def health(self, request: RewardMemoryHealthRequest) -> RewardMemoryHealthResult:
        corpus, observation = reward_memory_health_case(request.case)
        return _health_result(
            build_reward_memory_corpus_health_packet(corpus, observation)
        )

    def route(self, request: RewardMemoryRouteRequest) -> RewardMemoryRouteResult:
        if request.case == "pr-3237":
            observation = pr_3237_regression_observation()
        else:
            observation = {
                "behavior_status": request.behavior_status,
                "surface_count": request.surface_count,
                "semantic_contract_change": request.semantic_contract_change,
                "generic_boundary_for_specific_policy": (
                    request.generic_boundary_for_specific_policy
                ),
                "user_visible_behavior_change": (
                    request.user_visible_behavior_change
                ),
                "hot_path_or_storage_change": request.hot_path_or_storage_change,
                "retrieval_or_memory_quality_claim": (
                    request.retrieval_or_memory_quality_claim
                ),
                "edge_case_complexity": request.edge_case_complexity,
                "named_reproduction": request.named_reproduction,
                "named_validation": request.named_validation,
                "effect_evidence": request.effect_evidence,
                "ux_evidence": request.ux_evidence,
                "benchmark_evidence": request.benchmark_evidence,
                "performance_evidence": request.performance_evidence,
            }
        return _route_result(build_reward_memory_route_packet(observation))


class RewardMemoryService:
    __slots__ = ("_provider", "_read_provider")

    def __init__(
        self,
        provider: RewardMemoryFixtureProvider | None,
        read_provider: RewardMemoryReadProvider | None = None,
    ) -> None:
        self._provider = provider
        self._read_provider = read_provider

    @classmethod
    def builtin(cls) -> RewardMemoryService:
        return cls(
            BuiltinRewardMemoryFixtureProvider(),
            BuiltinRewardMemoryReadProvider(),
        )

    def health(self, request: RewardMemoryHealthRequest) -> RewardMemoryHealthResult:
        provider = self._require_provider("health")
        return _invoke(lambda: provider.health(request))

    def route(self, request: RewardMemoryRouteRequest) -> RewardMemoryRouteResult:
        provider = self._require_provider("route")
        return _invoke(lambda: provider.route(request))

    def corpus_registry(self) -> RewardMemoryCorpusRegistryResult:
        provider = self._require_read_provider("corpus_registry")
        return _invoke(provider.corpus_registry)

    def candidate_review(
        self,
        request: RewardMemoryCandidateReviewRequest,
    ) -> RewardMemoryCandidateReviewResult:
        provider = self._require_read_provider("candidate_review")
        return _invoke(lambda: provider.candidate_review(request))

    def _require_provider(self, operation: str) -> RewardMemoryFixtureProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": f"application.capabilities.reward_memory.{operation}",
                    "provider": "reward_memory_fixture",
                }
            )
        return self._provider

    def _require_read_provider(self, operation: str) -> RewardMemoryReadProvider:
        if self._read_provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        f"application.capabilities.reward_memory.{operation}"
                    ),
                    "provider": "reward_memory_read_model",
                }
            )
        return self._read_provider


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateReviewRequest:
    case: str = "issue-fix-verified-contributor"
    decision: str = "accept"

    def __post_init__(self) -> None:
        if self.case != "issue-fix-verified-contributor":
            raise ValidationFailed(details={"field": "case"})
        if self.decision not in {"accept", "edit", "reject", "retire", "no_write"}:
            raise ValidationFailed(details={"field": "decision"})


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusScope:
    workspace_ref: str
    project_ref: str
    surface_ids: tuple[str, ...]
    user_ref: str | None
    peer_ref: str | None
    session_ref: str | None


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusFreshness:
    mode: str
    source_revision: str | None
    max_age_seconds: int | None


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusLifecycle:
    state: str
    supersedes: tuple[str, ...]
    superseded_by: str | None
    retirement_reason: str | None


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusRetrieval:
    index_required: bool
    readback_required: bool
    application_receipt_required: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusMaintenance:
    writeback_triggers: tuple[str, ...]
    closure_policy: str
    retirement_authority: str


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusPrivacy:
    visibility: str
    raw_content_in_registry: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpus:
    corpus_id: str
    class_id: str
    provider_id: str
    owner_ref: str
    source_of_truth: str
    read_authority: str
    write_authority: str
    scope: RewardMemoryCorpusScope
    freshness: RewardMemoryCorpusFreshness
    lifecycle: RewardMemoryCorpusLifecycle
    retrieval: RewardMemoryCorpusRetrieval
    maintenance: RewardMemoryCorpusMaintenance
    privacy: RewardMemoryCorpusPrivacy


@dataclass(frozen=True, slots=True)
class RewardMemoryClassCoverage:
    run_bound_reward: tuple[str, ...]
    hard_policy: tuple[str, ...]
    soft_preference: tuple[str, ...]
    procedural_experience: tuple[str, ...]
    working_context: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RewardMemoryRegistryMaintenanceContract:
    inventory_owner: str
    write_rule: str
    freshness_rule: str
    supersession_rule: str
    retirement_rule: str
    scope_rule: str


@dataclass(frozen=True, slots=True)
class RewardMemoryOpenVikingAlignment:
    content_source_of_truth: str
    index_role: str
    preferences: str
    trajectories: str
    experiences: str
    working_memory: str
    cases: str


@dataclass(frozen=True, slots=True)
class RewardMemoryCorpusRegistryResult:
    schema_version: str
    status: str
    registry_role: str
    corpus_count: int
    corpora: tuple[RewardMemoryCorpus, ...]
    class_coverage: RewardMemoryClassCoverage
    maintenance_contract: RewardMemoryRegistryMaintenanceContract
    openviking_alignment: RewardMemoryOpenVikingAlignment
    raw_memory_captured: bool
    registry_persisted: bool
    provider_write_performed: bool
    external_writes_performed: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateSource:
    source_kind: str
    source_ref: str
    actor_ref: str
    actor_role: str


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateScope:
    workspace_ref: str
    project_ref: str
    surface_ids: tuple[str, ...]
    revision_ref: str


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateReasoning:
    summary: str
    confidence: str


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateGuardContext:
    source_freshness: str
    conflict_state: str
    current_artifact_verified: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateLifecycle:
    state: str
    supersedes_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidatePrivacy:
    raw_content_captured: bool


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateRecord:
    schema_version: str
    target_class: str
    content_summary: str
    source: RewardMemoryCandidateSource
    scope: RewardMemoryCandidateScope
    reasoning: RewardMemoryCandidateReasoning
    guard_context: RewardMemoryCandidateGuardContext
    requested_action_scopes: tuple[str, ...]
    lifecycle: RewardMemoryCandidateLifecycle
    privacy: RewardMemoryCandidatePrivacy
    candidate_ref: str


@dataclass(frozen=True, slots=True)
class RewardMemoryAuthorityCheckpoint:
    verified: bool
    source_ref: str
    actor_ref: str
    actor_role: str
    project_ref: str
    action_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateGuard:
    passed: bool
    reason_codes: tuple[str, ...]
    rule: str
    semantic_reasoning_preserved: bool


@dataclass(frozen=True, slots=True)
class RewardMemorySharedCandidate:
    schema_version: str
    status: str
    candidate: RewardMemoryCandidateRecord
    authority_checkpoint: RewardMemoryAuthorityCheckpoint
    guard: RewardMemoryCandidateGuard
    available_review_decisions: tuple[str, ...]
    candidate_persisted: bool
    provider_write_performed: bool
    external_writes_performed: bool
    raw_content_captured: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateAdapter:
    schema_version: str
    issue_ref: str
    surface_id: str
    shared_candidate: RewardMemorySharedCandidate
    adapter_role: str
    fresh_execution_context_source: str
    provider_write_performed: bool
    external_writes_performed: bool
    raw_content_captured: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateReview:
    reviewer_ref: str
    review_ref: str
    reasoning_summary: str
    edited_content_summary: str | None


@dataclass(frozen=True, slots=True)
class RewardMemoryCandidateReviewResult:
    schema_version: str
    status: str
    requested_decision: str
    effective_decision: str
    guard_passed: bool
    review: RewardMemoryCandidateReview
    record: RewardMemoryCandidateRecord
    persistence_next_step: str
    grants_new_action_authority: bool
    provider_write_performed: bool
    external_writes_performed: bool
    raw_content_captured: bool
    adapter: RewardMemoryCandidateAdapter
    ok: bool = True


class RewardMemoryReadProvider(Protocol):
    def corpus_registry(self) -> RewardMemoryCorpusRegistryResult: ...

    def candidate_review(
        self,
        request: RewardMemoryCandidateReviewRequest,
    ) -> RewardMemoryCandidateReviewResult: ...


class BuiltinRewardMemoryReadProvider:
    def __init__(
        self,
        *,
        registry_builder: Callable[[], Mapping[str, object]] = (
            build_reward_memory_corpus_registry_packet
        ),
        candidate_fixture_builder: Callable[[], Mapping[str, object]] = (
            issue_fix_verified_contributor_candidate_fixture
        ),
        candidate_reducer: Callable[..., Mapping[str, object]] = (
            review_reward_memory_candidate
        ),
    ) -> None:
        self._registry_builder = registry_builder
        self._candidate_fixture_builder = candidate_fixture_builder
        self._candidate_reducer = candidate_reducer

    def corpus_registry(self) -> RewardMemoryCorpusRegistryResult:
        return _registry_result(self._registry_builder())

    def candidate_review(
        self,
        request: RewardMemoryCandidateReviewRequest,
    ) -> RewardMemoryCandidateReviewResult:
        adapter = self._candidate_fixture_builder()
        candidate = mapping(
            adapter.get("shared_candidate"),
            resource=_RESOURCE,
            field="adapter.shared_candidate",
        )
        review: dict[str, object] = {
            "decision": request.decision,
            "reviewer_ref": "github:user:maintainer",
            "review_ref": f"review:fixture:{request.decision}",
            "reasoning_summary": (
                "The compact evidence and scope were reviewed."
            ),
        }
        if request.decision == "edit":
            review["edited_content_summary"] = (
                "Keep focused fixes within the affected module unless "
                "current evidence requires a broader surface."
            )
        if request.decision == "retire":
            candidate = self._candidate_reducer(
                candidate,
                review
                | {
                    "decision": "accept",
                    "review_ref": "review:fixture:accept-before-retire",
                },
            )
        payload = dict(self._candidate_reducer(candidate, review))
        payload["adapter"] = adapter
        return _candidate_review_result(payload)


def _registry_result(
    payload: Mapping[str, object],
) -> RewardMemoryCorpusRegistryResult:
    coverage = mapping(
        payload.get("class_coverage"),
        resource=_RESOURCE,
        field="class_coverage",
    )
    maintenance = mapping(
        payload.get("maintenance_contract"),
        resource=_RESOURCE,
        field="maintenance_contract",
    )
    provider_alignment = mapping(
        payload.get("provider_alignment"),
        resource=_RESOURCE,
        field="provider_alignment",
    )
    openviking = mapping(
        provider_alignment.get("openviking"),
        resource=_RESOURCE,
        field="provider_alignment.openviking",
    )
    return RewardMemoryCorpusRegistryResult(
        ok=boolean(payload, "ok", resource=_RESOURCE),
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        status=text(payload, "status", resource=_RESOURCE),
        registry_role=text(payload, "registry_role", resource=_RESOURCE),
        corpus_count=integer(payload, "corpus_count", resource=_RESOURCE),
        corpora=tuple(
            _corpus(item, index=index)
            for index, item in enumerate(
                sequence(payload.get("corpora"), resource=_RESOURCE, field="corpora")
            )
        ),
        class_coverage=RewardMemoryClassCoverage(
            run_bound_reward=text_tuple(
                coverage.get("run_bound_reward"),
                resource=_RESOURCE,
                field="class_coverage.run_bound_reward",
            ),
            hard_policy=text_tuple(
                coverage.get("hard_policy"),
                resource=_RESOURCE,
                field="class_coverage.hard_policy",
            ),
            soft_preference=text_tuple(
                coverage.get("soft_preference"),
                resource=_RESOURCE,
                field="class_coverage.soft_preference",
            ),
            procedural_experience=text_tuple(
                coverage.get("procedural_experience"),
                resource=_RESOURCE,
                field="class_coverage.procedural_experience",
            ),
            working_context=text_tuple(
                coverage.get("working_context"),
                resource=_RESOURCE,
                field="class_coverage.working_context",
            ),
        ),
        maintenance_contract=RewardMemoryRegistryMaintenanceContract(
            inventory_owner=text(maintenance, "inventory_owner", resource=_RESOURCE),
            write_rule=text(maintenance, "write_rule", resource=_RESOURCE),
            freshness_rule=text(maintenance, "freshness_rule", resource=_RESOURCE),
            supersession_rule=text(
                maintenance,
                "supersession_rule",
                resource=_RESOURCE,
            ),
            retirement_rule=text(
                maintenance,
                "retirement_rule",
                resource=_RESOURCE,
            ),
            scope_rule=text(maintenance, "scope_rule", resource=_RESOURCE),
        ),
        openviking_alignment=RewardMemoryOpenVikingAlignment(
            content_source_of_truth=text(
                openviking,
                "content_source_of_truth",
                resource=_RESOURCE,
            ),
            index_role=text(openviking, "index_role", resource=_RESOURCE),
            preferences=text(openviking, "preferences", resource=_RESOURCE),
            trajectories=text(openviking, "trajectories", resource=_RESOURCE),
            experiences=text(openviking, "experiences", resource=_RESOURCE),
            working_memory=text(openviking, "working_memory", resource=_RESOURCE),
            cases=text(openviking, "cases", resource=_RESOURCE),
        ),
        raw_memory_captured=boolean(
            payload,
            "raw_memory_captured",
            resource=_RESOURCE,
        ),
        registry_persisted=boolean(
            payload,
            "registry_persisted",
            resource=_RESOURCE,
        ),
        provider_write_performed=boolean(
            payload,
            "provider_write_performed",
            resource=_RESOURCE,
        ),
        external_writes_performed=boolean(
            payload,
            "external_writes_performed",
            resource=_RESOURCE,
        ),
    )


def _corpus(value: object, *, index: int) -> RewardMemoryCorpus:
    item = mapping(value, resource=_RESOURCE, field=f"corpora[{index}]")
    scope = mapping(item.get("scope"), resource=_RESOURCE, field=f"corpora[{index}].scope")
    freshness = mapping(item.get("freshness"), resource=_RESOURCE, field=f"corpora[{index}].freshness")
    lifecycle = mapping(item.get("lifecycle"), resource=_RESOURCE, field=f"corpora[{index}].lifecycle")
    retrieval = mapping(item.get("retrieval"), resource=_RESOURCE, field=f"corpora[{index}].retrieval")
    maintenance = mapping(item.get("maintenance"), resource=_RESOURCE, field=f"corpora[{index}].maintenance")
    privacy = mapping(item.get("privacy"), resource=_RESOURCE, field=f"corpora[{index}].privacy")
    return RewardMemoryCorpus(
        corpus_id=text(item, "corpus_id", resource=_RESOURCE),
        class_id=text(item, "class_id", resource=_RESOURCE),
        provider_id=text(item, "provider_id", resource=_RESOURCE),
        owner_ref=text(item, "owner_ref", resource=_RESOURCE),
        source_of_truth=text(item, "source_of_truth", resource=_RESOURCE),
        read_authority=text(item, "read_authority", resource=_RESOURCE),
        write_authority=text(item, "write_authority", resource=_RESOURCE),
        scope=RewardMemoryCorpusScope(
            workspace_ref=text(scope, "workspace_ref", resource=_RESOURCE),
            project_ref=text(scope, "project_ref", resource=_RESOURCE),
            surface_ids=text_tuple(
                scope.get("surface_ids"),
                resource=_RESOURCE,
                field=f"corpora[{index}].scope.surface_ids",
            ),
            user_ref=optional_text(scope, "user_ref", resource=_RESOURCE),
            peer_ref=optional_text(scope, "peer_ref", resource=_RESOURCE),
            session_ref=optional_text(scope, "session_ref", resource=_RESOURCE),
        ),
        freshness=RewardMemoryCorpusFreshness(
            mode=text(freshness, "mode", resource=_RESOURCE),
            source_revision=optional_text(
                freshness,
                "source_revision",
                resource=_RESOURCE,
            ),
            max_age_seconds=optional_integer(
                freshness,
                "max_age_seconds",
                resource=_RESOURCE,
            ),
        ),
        lifecycle=RewardMemoryCorpusLifecycle(
            state=text(lifecycle, "state", resource=_RESOURCE),
            supersedes=text_tuple(
                lifecycle.get("supersedes"),
                resource=_RESOURCE,
                field=f"corpora[{index}].lifecycle.supersedes",
            ),
            superseded_by=optional_text(
                lifecycle,
                "superseded_by",
                resource=_RESOURCE,
            ),
            retirement_reason=optional_text(
                lifecycle,
                "retirement_reason",
                resource=_RESOURCE,
            ),
        ),
        retrieval=RewardMemoryCorpusRetrieval(
            index_required=boolean(retrieval, "index_required", resource=_RESOURCE),
            readback_required=boolean(
                retrieval,
                "readback_required",
                resource=_RESOURCE,
            ),
            application_receipt_required=boolean(
                retrieval,
                "application_receipt_required",
                resource=_RESOURCE,
            ),
        ),
        maintenance=RewardMemoryCorpusMaintenance(
            writeback_triggers=text_tuple(
                maintenance.get("writeback_triggers"),
                resource=_RESOURCE,
                field=f"corpora[{index}].maintenance.writeback_triggers",
            ),
            closure_policy=text(
                maintenance,
                "closure_policy",
                resource=_RESOURCE,
            ),
            retirement_authority=text(
                maintenance,
                "retirement_authority",
                resource=_RESOURCE,
            ),
        ),
        privacy=RewardMemoryCorpusPrivacy(
            visibility=text(privacy, "visibility", resource=_RESOURCE),
            raw_content_in_registry=boolean(
                privacy,
                "raw_content_in_registry",
                resource=_RESOURCE,
            ),
        ),
    )


def _candidate_review_result(
    payload: Mapping[str, object],
) -> RewardMemoryCandidateReviewResult:
    review = mapping(payload.get("review"), resource=_RESOURCE, field="review")
    return RewardMemoryCandidateReviewResult(
        ok=boolean(payload, "ok", resource=_RESOURCE),
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        status=text(payload, "status", resource=_RESOURCE),
        requested_decision=text(payload, "requested_decision", resource=_RESOURCE),
        effective_decision=text(payload, "effective_decision", resource=_RESOURCE),
        guard_passed=boolean(payload, "guard_passed", resource=_RESOURCE),
        review=RewardMemoryCandidateReview(
            reviewer_ref=text(review, "reviewer_ref", resource=_RESOURCE),
            review_ref=text(review, "review_ref", resource=_RESOURCE),
            reasoning_summary=text(
                review,
                "reasoning_summary",
                resource=_RESOURCE,
            ),
            edited_content_summary=optional_text(
                review,
                "edited_content_summary",
                resource=_RESOURCE,
            ),
        ),
        record=_candidate_record(payload.get("record"), field="record"),
        persistence_next_step=text(
            payload,
            "persistence_next_step",
            resource=_RESOURCE,
        ),
        grants_new_action_authority=boolean(
            payload,
            "grants_new_action_authority",
            resource=_RESOURCE,
        ),
        provider_write_performed=boolean(
            payload,
            "provider_write_performed",
            resource=_RESOURCE,
        ),
        external_writes_performed=boolean(
            payload,
            "external_writes_performed",
            resource=_RESOURCE,
        ),
        raw_content_captured=boolean(
            payload,
            "raw_content_captured",
            resource=_RESOURCE,
        ),
        adapter=_candidate_adapter(payload.get("adapter")),
    )


def _candidate_adapter(value: object) -> RewardMemoryCandidateAdapter:
    item = mapping(value, resource=_RESOURCE, field="adapter")
    shared = mapping(
        item.get("shared_candidate"),
        resource=_RESOURCE,
        field="adapter.shared_candidate",
    )
    checkpoint = mapping(
        shared.get("authority_checkpoint"),
        resource=_RESOURCE,
        field="adapter.shared_candidate.authority_checkpoint",
    )
    guard = mapping(
        shared.get("guard"),
        resource=_RESOURCE,
        field="adapter.shared_candidate.guard",
    )
    return RewardMemoryCandidateAdapter(
        ok=boolean(item, "ok", resource=_RESOURCE),
        schema_version=text(item, "schema_version", resource=_RESOURCE),
        issue_ref=text(item, "issue_ref", resource=_RESOURCE),
        surface_id=text(item, "surface_id", resource=_RESOURCE),
        shared_candidate=RewardMemorySharedCandidate(
            ok=boolean(shared, "ok", resource=_RESOURCE),
            schema_version=text(shared, "schema_version", resource=_RESOURCE),
            status=text(shared, "status", resource=_RESOURCE),
            candidate=_candidate_record(
                shared.get("candidate"),
                field="adapter.shared_candidate.candidate",
            ),
            authority_checkpoint=RewardMemoryAuthorityCheckpoint(
                verified=boolean(checkpoint, "verified", resource=_RESOURCE),
                source_ref=text(checkpoint, "source_ref", resource=_RESOURCE),
                actor_ref=text(checkpoint, "actor_ref", resource=_RESOURCE),
                actor_role=text(checkpoint, "actor_role", resource=_RESOURCE),
                project_ref=text(checkpoint, "project_ref", resource=_RESOURCE),
                action_scopes=text_tuple(
                    checkpoint.get("action_scopes"),
                    resource=_RESOURCE,
                    field="authority_checkpoint.action_scopes",
                ),
            ),
            guard=RewardMemoryCandidateGuard(
                passed=boolean(guard, "passed", resource=_RESOURCE),
                reason_codes=text_tuple(
                    guard.get("reason_codes"),
                    resource=_RESOURCE,
                    field="guard.reason_codes",
                ),
                rule=text(guard, "rule", resource=_RESOURCE),
                semantic_reasoning_preserved=boolean(
                    guard,
                    "semantic_reasoning_preserved",
                    resource=_RESOURCE,
                ),
            ),
            available_review_decisions=text_tuple(
                shared.get("available_review_decisions"),
                resource=_RESOURCE,
                field="available_review_decisions",
            ),
            candidate_persisted=boolean(
                shared,
                "candidate_persisted",
                resource=_RESOURCE,
            ),
            provider_write_performed=boolean(
                shared,
                "provider_write_performed",
                resource=_RESOURCE,
            ),
            external_writes_performed=boolean(
                shared,
                "external_writes_performed",
                resource=_RESOURCE,
            ),
            raw_content_captured=boolean(
                shared,
                "raw_content_captured",
                resource=_RESOURCE,
            ),
        ),
        adapter_role=text(item, "adapter_role", resource=_RESOURCE),
        fresh_execution_context_source=text(
            item,
            "fresh_execution_context_source",
            resource=_RESOURCE,
        ),
        provider_write_performed=boolean(
            item,
            "provider_write_performed",
            resource=_RESOURCE,
        ),
        external_writes_performed=boolean(
            item,
            "external_writes_performed",
            resource=_RESOURCE,
        ),
        raw_content_captured=boolean(
            item,
            "raw_content_captured",
            resource=_RESOURCE,
        ),
    )


def _candidate_record(value: object, *, field: str) -> RewardMemoryCandidateRecord:
    item = mapping(value, resource=_RESOURCE, field=field)
    source = mapping(item.get("source"), resource=_RESOURCE, field=f"{field}.source")
    scope = mapping(item.get("scope"), resource=_RESOURCE, field=f"{field}.scope")
    reasoning = mapping(item.get("reasoning"), resource=_RESOURCE, field=f"{field}.reasoning")
    guard = mapping(item.get("guard_context"), resource=_RESOURCE, field=f"{field}.guard_context")
    lifecycle = mapping(item.get("lifecycle"), resource=_RESOURCE, field=f"{field}.lifecycle")
    privacy = mapping(item.get("privacy"), resource=_RESOURCE, field=f"{field}.privacy")
    return RewardMemoryCandidateRecord(
        schema_version=text(item, "schema_version", resource=_RESOURCE),
        target_class=text(item, "target_class", resource=_RESOURCE),
        content_summary=text(item, "content_summary", resource=_RESOURCE),
        source=RewardMemoryCandidateSource(
            source_kind=text(source, "source_kind", resource=_RESOURCE),
            source_ref=text(source, "source_ref", resource=_RESOURCE),
            actor_ref=text(source, "actor_ref", resource=_RESOURCE),
            actor_role=text(source, "actor_role", resource=_RESOURCE),
        ),
        scope=RewardMemoryCandidateScope(
            workspace_ref=text(scope, "workspace_ref", resource=_RESOURCE),
            project_ref=text(scope, "project_ref", resource=_RESOURCE),
            surface_ids=text_tuple(
                scope.get("surface_ids"),
                resource=_RESOURCE,
                field=f"{field}.scope.surface_ids",
            ),
            revision_ref=text(scope, "revision_ref", resource=_RESOURCE),
        ),
        reasoning=RewardMemoryCandidateReasoning(
            summary=text(reasoning, "summary", resource=_RESOURCE),
            confidence=text(reasoning, "confidence", resource=_RESOURCE),
        ),
        guard_context=RewardMemoryCandidateGuardContext(
            source_freshness=text(guard, "source_freshness", resource=_RESOURCE),
            conflict_state=text(guard, "conflict_state", resource=_RESOURCE),
            current_artifact_verified=boolean(
                guard,
                "current_artifact_verified",
                resource=_RESOURCE,
            ),
        ),
        requested_action_scopes=text_tuple(
            item.get("requested_action_scopes"),
            resource=_RESOURCE,
            field=f"{field}.requested_action_scopes",
        ),
        lifecycle=RewardMemoryCandidateLifecycle(
            state=text(lifecycle, "state", resource=_RESOURCE),
            supersedes_refs=text_tuple(
                lifecycle.get("supersedes_refs"),
                resource=_RESOURCE,
                field=f"{field}.lifecycle.supersedes_refs",
            ),
        ),
        privacy=RewardMemoryCandidatePrivacy(
            raw_content_captured=boolean(
                privacy,
                "raw_content_captured",
                resource=_RESOURCE,
            )
        ),
        candidate_ref=text(item, "candidate_ref", resource=_RESOURCE),
    )


def _health_result(payload: Mapping[str, object]) -> RewardMemoryHealthResult:
    scope = mapping(payload.get("scope_check"), resource=_RESOURCE, field="scope_check")
    freshness = mapping(
        payload.get("freshness_check"),
        resource=_RESOURCE,
        field="freshness_check",
    )
    pipeline = mapping(payload.get("pipeline"), resource=_RESOURCE, field="pipeline")
    return RewardMemoryHealthResult(
        ok=boolean(payload, "ok", resource=_RESOURCE),
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        corpus_id=text(payload, "corpus_id", resource=_RESOURCE),
        class_id=text(payload, "class_id", resource=_RESOURCE),
        health_state=text(payload, "health_state", resource=_RESOURCE),
        reason_codes=text_tuple(
            payload.get("reason_codes"),
            resource=_RESOURCE,
            field="reason_codes",
        ),
        scope_check=RewardMemoryScopeCheck(
            project_matches=boolean(scope, "project_matches", resource=_RESOURCE),
            surface_matches=boolean(scope, "surface_matches", resource=_RESOURCE),
        ),
        freshness_check=RewardMemoryFreshnessCheck(
            lifecycle_state=text(freshness, "lifecycle_state", resource=_RESOURCE),
            source_revision_matches=boolean(
                freshness,
                "source_revision_matches",
                resource=_RESOURCE,
            ),
            freshness_window_satisfied=boolean(
                freshness,
                "freshness_window_satisfied",
                resource=_RESOURCE,
            ),
        ),
        pipeline=RewardMemoryPipeline(
            provider_available=boolean(
                pipeline,
                "provider_available",
                resource=_RESOURCE,
            ),
            corpus_present=boolean(pipeline, "corpus_present", resource=_RESOURCE),
            record_count=integer(pipeline, "record_count", resource=_RESOURCE),
            index_required=boolean(pipeline, "index_required", resource=_RESOURCE),
            index_present=boolean(pipeline, "index_present", resource=_RESOURCE),
            retrieval_query_succeeded=boolean(
                pipeline,
                "retrieval_query_succeeded",
                resource=_RESOURCE,
            ),
            result_readback_verified=boolean(
                pipeline,
                "result_readback_verified",
                resource=_RESOURCE,
            ),
            memory_applied_with_receipt=boolean(
                pipeline,
                "memory_applied_with_receipt",
                resource=_RESOURCE,
            ),
        ),
        may_apply_memory=boolean(payload, "may_apply_memory", resource=_RESOURCE),
        memory_patch_authority=boolean(
            payload,
            "memory_patch_authority",
            resource=_RESOURCE,
        ),
        external_write_authorized=boolean(
            payload,
            "external_write_authorized",
            resource=_RESOURCE,
        ),
        raw_memory_captured=boolean(
            payload,
            "raw_memory_captured",
            resource=_RESOURCE,
        ),
    )


def _route_result(payload: Mapping[str, object]) -> RewardMemoryRouteResult:
    return RewardMemoryRouteResult(
        ok=boolean(payload, "ok", resource=_RESOURCE),
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        case_ref=text(payload, "case_ref", resource=_RESOURCE),
        decision=text(payload, "decision", resource=_RESOURCE),
        reason_codes=text_tuple(
            payload.get("reason_codes"),
            resource=_RESOURCE,
            field="reason_codes",
        ),
        required_evidence=text_tuple(
            payload.get("required_evidence"),
            resource=_RESOURCE,
            field="required_evidence",
        ),
        missing_required_evidence=text_tuple(
            payload.get("missing_required_evidence"),
            resource=_RESOURCE,
            field="missing_required_evidence",
        ),
        pilot_authorized=boolean(payload, "pilot_authorized", resource=_RESOURCE),
        meta_review_required=boolean(
            payload,
            "meta_review_required",
            resource=_RESOURCE,
        ),
        route_check_role=text(payload, "route_check_role", resource=_RESOURCE),
        live_reasoning_required=boolean(
            payload,
            "live_reasoning_required",
            resource=_RESOURCE,
        ),
        memory_patch_authority=boolean(
            payload,
            "memory_patch_authority",
            resource=_RESOURCE,
        ),
        external_write_authorized=boolean(
            payload,
            "external_write_authorized",
            resource=_RESOURCE,
        ),
        raw_issue_or_memory_captured=boolean(
            payload,
            "raw_issue_or_memory_captured",
            resource=_RESOURCE,
        ),
    )


def _invoke(call: Callable[[], ResultT]) -> ResultT:
    try:
        return call()
    except ApplicationError:
        raise
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    except OSError as exc:
        raise StateUnavailable(
            details={"resource": _RESOURCE, "cause": type(exc).__name__}
        ) from exc
