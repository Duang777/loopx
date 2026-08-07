from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from loopx.application.capabilities import (
    CapabilityCatalogResult,
    CapabilityDetailResult,
    CapabilityProviderState,
    ContentOpsExplorationPlanResult,
    ContentOpsItemCreateResult,
    ContentOpsWalkthroughResult,
    DecisionContextArchitectureResult,
    DecisionContextInspectProfileResult,
    MaterialLifecycleArchitectureResult,
    MaterialLifecycleSkillStatusResult,
    OutcomeCapabilityContract,
    RewardMemoryHealthResult,
    RewardMemoryCandidateReviewResult,
    RewardMemoryCorpusRegistryResult,
    RewardMemoryRouteResult,
    SemanticPreferenceApplicationReceiptResult,
    SemanticPreferenceMaintenanceReceiptResult,
    ValueConnectorInstallCheckResult,
    ValueConnectorSourceMapResult,
)
from loopx.application.capabilities.content_ops import (
    ContentOpsRecordCounts,
    ContentOpsSurfaceProjection,
    ContentOpsSurfaceValidation,
    ContentOpsTodoCandidate,
    ContentOpsUserGate,
    ContentOpsWalkthroughChainStep,
)
from loopx.application.capabilities.reward_memory import (
    RewardMemoryCandidateAdapter,
    RewardMemoryCandidateRecord,
    RewardMemoryCorpus,
)
from loopx.application.extensions import (
    ExtensionDoctorResult,
    ExtensionInitResult,
    ExtensionInstallResult,
    ExtensionListResult,
    ExtensionRollbackResult,
    ExtensionResult,
    ExtensionRunResult,
    ExtensionToggleResult,
)
from loopx.application.presentations import (
    PresentationPackageResult,
    PresentationPublisher,
    PresentationReadbackResult,
    PresentationRollbackResult,
)


def capability_catalog_payload(result: CapabilityCatalogResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "capabilities": [
            {
                "id": item.capability_id,
                "title": item.title,
                "status": item.status,
                "origin": item.origin,
                "visibility": item.visibility,
                "provider_id": item.provider_id,
                "provider_state": _provider_state(item.provider_state),
                "real_world_anchor": item.real_world_anchor,
                "entry_command": item.entry_command,
                "implemented_protocol_count": item.implemented_protocol_count,
                "implementation_provider_count": item.implementation_provider_count,
                "smoke_count": item.smoke_count,
                "next_real_step": item.next_real_step,
            }
            for item in result.capabilities
        ],
        "providers": [
            {
                "id": provider.provider_id,
                "origin": provider.origin,
                **_provider_state(provider.state),
            }
            for provider in result.providers
        ],
    }


def capability_detail_payload(result: CapabilityDetailResult) -> dict[str, object]:
    item = result.capability
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "capability": {
            "id": item.capability_id,
            "origin": item.origin,
            "visibility": item.visibility,
            "provider_id": item.provider_id,
            "title": item.title,
            "status": item.status,
            "default_enabled": item.default_enabled,
            "real_world_anchor": item.real_world_anchor,
            "user_value": item.user_value,
            "entry_command": item.entry_command,
            "commands": [asdict(command) for command in item.commands],
            "implemented_protocols": [
                asdict(protocol) for protocol in item.implemented_protocols
            ],
            "smokes": list(item.smokes),
            "docs": list(item.docs),
            "boundaries": list(item.boundaries),
            "next_real_step": item.next_real_step,
            "provider_state": _provider_state(item.provider_state),
        },
    }


def decision_context_architecture_payload(
    result: DecisionContextArchitectureResult,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "status": result.status,
        "capability": _outcome_capability(result.capability),
        "packet_schemas": list(result.packet_schemas),
        "source_schemas": list(result.source_schemas),
        "assembly_schemas": list(result.assembly_schemas),
        "provider_boundaries": {
            "decision_source_provider": (
                result.provider_boundaries.decision_source_provider
            ),
            "context_provider": result.provider_boundaries.context_provider,
            "provider_failure_policy": (
                result.provider_boundaries.provider_failure_policy
            ),
        },
        "lifecycle": list(result.lifecycle),
        "invariants": list(result.invariants),
        "next_stage": result.next_stage,
    }


def decision_context_inspect_profile_payload(
    result: DecisionContextInspectProfileResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "capability_id": result.capability_id,
        "scope": result.scope,
        "default_enabled": result.default_enabled,
        "goal_id": result.goal_id,
        "agent_id": result.agent_id,
        "profile_configured": result.profile_configured,
        "enabled": result.enabled,
        "configured_for_agent": result.configured_for_agent,
        "available": result.available,
        "source_count": result.source_count,
        "source_provider_count": result.source_provider_count,
        "runtime_bound_provider_count": result.runtime_bound_provider_count,
        "context_provider_configured": result.context_provider_configured,
        "automatic_capture": result.automatic_capture,
        "fail_open": result.fail_open,
        "external_writes_performed": result.external_writes_performed,
        "raw_content_captured": result.raw_content_captured,
        "private_locator_captured": result.private_locator_captured,
        "credentials_captured": result.credentials_captured,
        "status": result.status,
    }
    if result.source_providers is not None:
        payload["source_providers"] = [
            {
                "adapter": item.adapter,
                "adapter_registered": item.adapter_registered,
                "runtime_bound": item.runtime_bound,
                "private_config_captured": item.private_config_captured,
            }
            for item in result.source_providers
        ]
    if result.reason_code is not None:
        payload["reason_code"] = result.reason_code
    if result.unavailable_adapter_count is not None:
        payload["unavailable_adapter_count"] = result.unavailable_adapter_count
    return payload


def material_lifecycle_architecture_payload(
    result: MaterialLifecycleArchitectureResult,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "status": result.status,
        "capability": _outcome_capability(result.capability),
        "contract_schemas": list(result.contract_schemas),
        "sibling_capabilities": {
            "decision_context": result.sibling_capabilities.decision_context,
            "reward_memory": result.sibling_capabilities.reward_memory,
            "content_ops": result.sibling_capabilities.content_ops,
        },
        "provider_boundaries": {
            "raw_material_store": result.provider_boundaries.raw_material_store,
            "inventory_provider": result.provider_boundaries.inventory_provider,
            "migration_adapter": result.provider_boundaries.migration_adapter,
            "decision_policy": result.provider_boundaries.decision_policy,
            "exploration_provider": result.provider_boundaries.exploration_provider,
            "candidate_intake_adapter": (
                result.provider_boundaries.candidate_intake_adapter
            ),
            "ranking_settlement": result.provider_boundaries.ranking_settlement,
        },
        "lifecycle": list(result.lifecycle),
        "invariants": list(result.invariants),
        "next_stage": result.next_stage,
    }


def material_lifecycle_skill_status_payload(
    result: MaterialLifecycleSkillStatusResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": result.schema_version,
        "skill_id": result.skill_id,
        "delivery": result.delivery,
        "project": result.project,
        "project_connected": result.project_connected,
        "source": result.source,
        "source_digest": result.source_digest,
        "status": result.status,
        "surfaces": [
            {
                "surface": item.surface,
                "target": item.target,
                "status": item.status,
                "managed": item.managed,
                "installed_digest": item.installed_digest,
                "recorded_source_digest": item.recorded_source_digest,
            }
            for item in result.surfaces
        ],
        "managed": result.managed,
    }
    if result.surface is not None:
        payload.update(
            {
                "surface": result.surface,
                "target": result.target,
                "installed_digest": result.installed_digest,
                "recorded_source_digest": result.recorded_source_digest,
            }
        )
    return payload


def content_ops_item_create_payload(
    result: ContentOpsItemCreateResult,
) -> dict[str, object]:
    item = result.item
    projection = result.projection
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "item": {
            "schema_version": item.schema_version,
            "item_id": item.item_id,
            "item_kind": item.item_kind,
            "channel": item.channel,
            "state": item.state,
            "revision": item.revision,
            "content_digest": item.content_digest,
            "content_ref": item.content_ref,
            "source_refs": list(item.source_refs),
            "approval": item.approval,
            "delivery_intent": item.delivery_intent,
            "delivery_receipt": item.delivery_receipt,
            "readback_receipt": item.readback_receipt,
            "superseded_by": item.superseded_by,
            "terminal_reason": item.terminal_reason,
            "last_event": item.last_event,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "autopublish_allowed": item.autopublish_allowed,
        },
        "projection": {
            "schema_version": projection.schema_version,
            "item_id": projection.item_id,
            "item_kind": projection.item_kind,
            "channel": projection.channel,
            "state": projection.state,
            "revision": projection.revision,
            "approval_present": projection.approval_present,
            "delivery_intent_present": projection.delivery_intent_present,
            "published_url": projection.published_url,
            "readback_verified": projection.readback_verified,
            "terminal": projection.terminal,
            "superseded_by": projection.superseded_by,
            "next_actions": list(projection.next_actions),
            "truth_contract": {
                "projection_is_writable": (
                    projection.truth_contract.projection_is_writable
                ),
                "external_effect_authority": (
                    projection.truth_contract.external_effect_authority
                ),
                "autopublish_allowed": (
                    projection.truth_contract.autopublish_allowed
                ),
            },
        },
        "external_reads_performed": result.external_reads_performed,
        "external_writes_performed": result.external_writes_performed,
        "autopublish_allowed": result.autopublish_allowed,
    }


def content_ops_exploration_plan_payload(
    result: ContentOpsExplorationPlanResult,
) -> dict[str, object]:
    plan = result.exploration_plan
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "mode": result.mode,
        "exploration_plan": {
            "schema_version": plan.schema_version,
            "scenario": plan.scenario,
            "generated_at": plan.generated_at,
            "selected_source_lanes": [
                {
                    "lane_id": lane.lane_id,
                    "surface": lane.surface,
                    "source_kind": lane.source_kind,
                    "source_status": lane.source_status,
                    "access_mode": lane.access_mode,
                    "read_status": lane.read_status,
                    "route": lane.route,
                    "fallback": lane.fallback,
                    "evidence_quality": lane.evidence_quality,
                    "promotion_target": lane.promotion_target,
                    "requires_user_gate": lane.requires_user_gate,
                    **(
                        {"user_gate": _content_ops_user_gate(lane.user_gate)}
                        if lane.user_gate is not None
                        else {}
                    ),
                    "source_body_captured": lane.source_body_captured,
                    "response_payload_captured": lane.response_payload_captured,
                    "local_path_captured": lane.local_path_captured,
                    "external_write_allowed": lane.external_write_allowed,
                }
                for lane in plan.selected_source_lanes
            ],
            "lane_counts": {
                "total": plan.lane_counts.total,
                "user_gate_required": plan.lane_counts.user_gate_required,
                "metadata_ready": plan.lane_counts.metadata_ready,
                "blocked_until_owner_gate": (
                    plan.lane_counts.blocked_until_owner_gate
                ),
            },
            "promotion_targets": {
                item.name: item.count for item in plan.promotion_targets
            },
            "first_screen": {
                "waiting_on": plan.first_screen.waiting_on,
                "user_action_required": plan.first_screen.user_action_required,
                "agent_can_continue": plan.first_screen.agent_can_continue,
                "top_agent_action": plan.first_screen.top_agent_action,
                "top_user_gate": _content_ops_user_gate(
                    plan.first_screen.top_user_gate
                ),
            },
            "boundary": {
                "external_reads_performed": (
                    plan.boundary.external_reads_performed
                ),
                "external_writes_performed": (
                    plan.boundary.external_writes_performed
                ),
                "source_bodies_captured": plan.boundary.source_bodies_captured,
                "response_payloads_captured": (
                    plan.boundary.response_payloads_captured
                ),
                "local_paths_captured": plan.boundary.local_paths_captured,
                "autopublish_allowed": plan.boundary.autopublish_allowed,
            },
            "truth_contract": {
                "plan_is_writable": plan.truth_contract.plan_is_writable,
                "source_lanes_are_candidates": (
                    plan.truth_contract.source_lanes_are_candidates
                ),
                "promotion_requires_target_surface_validation": (
                    plan.truth_contract.promotion_requires_target_surface_validation
                ),
                "private_boundary_crossing_requires_user_gate": (
                    plan.truth_contract.private_boundary_crossing_requires_user_gate
                ),
            },
        },
        "validation": {
            "schema_version": result.validation.schema_version,
            "ok": result.validation.ok,
            "errors": list(result.validation.errors),
            "lane_count": result.validation.lane_count,
        },
        "external_reads_performed": result.external_reads_performed,
        "external_writes_performed": result.external_writes_performed,
        "private_source_bodies_read": result.private_source_bodies_read,
        "private_source_content_read": result.private_source_content_read,
        "local_paths_captured": result.local_paths_captured,
        "autopublish_allowed": result.autopublish_allowed,
        "next_safe_action": result.next_safe_action,
    }


def content_ops_walkthrough_payload(
    result: ContentOpsWalkthroughResult,
) -> dict[str, object]:
    operator = result.operator_artifact
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "mode": result.mode,
        "generated_at": result.generated_at,
        "operator_artifact": {
            "headline": operator.headline,
            "source_cards": [
                {
                    "source_item_id": card.source_item_id,
                    "source_status": card.source_status,
                    "allowed_use": card.allowed_use,
                    "summary": card.summary,
                }
                for card in operator.source_cards
            ],
            "private_operator_preview": {
                "available_in_current_operator_session": (
                    operator.private_operator_preview.available_in_current_operator_session
                ),
                "sample_record_count": (
                    operator.private_operator_preview.sample_record_count
                ),
                "theme_signals": list(
                    operator.private_operator_preview.theme_signals
                ),
                "stored_in_repo": operator.private_operator_preview.stored_in_repo,
                "source_content_recorded": (
                    operator.private_operator_preview.source_content_recorded
                ),
                "response_payload_recorded": (
                    operator.private_operator_preview.response_payload_recorded
                ),
            },
            "draft_gate": {
                "draft_id": operator.draft_gate.draft_id,
                "state": operator.draft_gate.state,
                "publish_gate_id": operator.draft_gate.publish_gate_id,
                "publish_status": operator.draft_gate.publish_status,
                "approval_required": operator.draft_gate.approval_required,
                "autopublish_allowed": operator.draft_gate.autopublish_allowed,
            },
            "next_actions": list(operator.next_actions),
        },
        "chain_steps": [
            _content_ops_chain_step(step) for step in result.chain_steps
        ],
        "aggregation_projection": _content_ops_projection(
            result.aggregation_projection
        ),
        "validation": _content_ops_validation(result.validation),
        "packet_summary": {
            "public_packet_schema_version": (
                result.packet_summary.public_packet_schema_version
            ),
            "chatview_packet_schema_version": (
                result.packet_summary.chatview_packet_schema_version
            ),
            "aggregation_schema_version": (
                result.packet_summary.aggregation_schema_version
            ),
            "source_item_count": result.packet_summary.source_item_count,
            "owner_gate_required_count": (
                result.packet_summary.owner_gate_required_count
            ),
        },
        "external_reads_performed": result.external_reads_performed,
        "external_writes_performed": result.external_writes_performed,
        "private_source_bodies_read": result.private_source_bodies_read,
        "private_source_content_read": result.private_source_content_read,
        "autopublish_allowed": result.autopublish_allowed,
        "public_repo_safe": result.public_repo_safe,
        "next_safe_action": result.next_safe_action,
    }


def reward_memory_corpus_registry_payload(
    result: RewardMemoryCorpusRegistryResult,
) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "status": result.status,
        "registry_role": result.registry_role,
        "corpus_count": result.corpus_count,
        "corpora": [_reward_memory_corpus(item) for item in result.corpora],
        "class_coverage": {
            "run_bound_reward": list(result.class_coverage.run_bound_reward),
            "hard_policy": list(result.class_coverage.hard_policy),
            "soft_preference": list(result.class_coverage.soft_preference),
            "procedural_experience": list(
                result.class_coverage.procedural_experience
            ),
            "working_context": list(result.class_coverage.working_context),
        },
        "maintenance_contract": {
            "inventory_owner": result.maintenance_contract.inventory_owner,
            "write_rule": result.maintenance_contract.write_rule,
            "freshness_rule": result.maintenance_contract.freshness_rule,
            "supersession_rule": result.maintenance_contract.supersession_rule,
            "retirement_rule": result.maintenance_contract.retirement_rule,
            "scope_rule": result.maintenance_contract.scope_rule,
        },
        "provider_alignment": {
            "openviking": {
                "content_source_of_truth": (
                    result.openviking_alignment.content_source_of_truth
                ),
                "index_role": result.openviking_alignment.index_role,
                "preferences": result.openviking_alignment.preferences,
                "trajectories": result.openviking_alignment.trajectories,
                "experiences": result.openviking_alignment.experiences,
                "working_memory": result.openviking_alignment.working_memory,
                "cases": result.openviking_alignment.cases,
            }
        },
        "raw_memory_captured": result.raw_memory_captured,
        "registry_persisted": result.registry_persisted,
        "provider_write_performed": result.provider_write_performed,
        "external_writes_performed": result.external_writes_performed,
    }


def reward_memory_candidate_review_payload(
    result: RewardMemoryCandidateReviewResult,
) -> dict[str, object]:
    review: dict[str, object] = {
        "reviewer_ref": result.review.reviewer_ref,
        "review_ref": result.review.review_ref,
        "reasoning_summary": result.review.reasoning_summary,
    }
    if result.review.edited_content_summary is not None:
        review["edited_content_summary"] = result.review.edited_content_summary
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "status": result.status,
        "requested_decision": result.requested_decision,
        "effective_decision": result.effective_decision,
        "guard_passed": result.guard_passed,
        "review": review,
        "record": _reward_memory_candidate_record(result.record),
        "persistence_next_step": result.persistence_next_step,
        "grants_new_action_authority": result.grants_new_action_authority,
        "provider_write_performed": result.provider_write_performed,
        "external_writes_performed": result.external_writes_performed,
        "raw_content_captured": result.raw_content_captured,
        "adapter": _reward_memory_candidate_adapter(result.adapter),
    }


def value_connector_source_map_payload(
    result: ValueConnectorSourceMapResult,
) -> dict[str, object]:
    evidence = result.generic_evidence_card_schema
    projection = result.projection
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "mode": result.mode,
        "connector": result.connector,
        "external_reads_performed": result.external_reads_performed,
        "external_writes_performed": result.external_writes_performed,
        "account_signup_performed": result.account_signup_performed,
        "restricted_material_recorded": result.restricted_material_recorded,
        "private_source_content_read": result.private_source_content_read,
        "autopublish_allowed": result.autopublish_allowed,
        "source_profiles": [
            {
                "schema_version": profile.schema_version,
                "connector_id": profile.connector_id,
                "status": profile.status,
                "route_type": profile.route_type,
                "boundary": profile.boundary,
                "safe_uses": list(profile.safe_uses),
                "commands": list(profile.commands),
                "evidence_schema": profile.evidence_schema,
                "maturity_hint": profile.maturity_hint,
                "external_reads_allowed": profile.external_reads_allowed,
                "external_writes_allowed": profile.external_writes_allowed,
                "write_gate": profile.write_gate,
                "stop_conditions": list(profile.stop_conditions),
                "outcome_capability_id": profile.outcome_capability_id,
                "provider_binding_state": profile.provider_binding_state,
                "provider_module": profile.provider_module,
            }
            for profile in result.source_profiles
        ],
        "action_gated_profiles": [
            {
                "connector_id": profile.connector_id,
                "boundary": profile.boundary,
                "purpose": profile.purpose,
                "safe_prepare_command": profile.safe_prepare_command,
                "write_gate": profile.write_gate,
                "outcome_capability_id": profile.outcome_capability_id,
                "provider_binding_state": profile.provider_binding_state,
                "provider_module": profile.provider_module,
            }
            for profile in result.action_gated_profiles
        ],
        "generic_evidence_card_schema": {
            "schema_version": evidence.schema_version,
            "connector_id": evidence.connector_id,
            "channel": evidence.channel,
            "backend": evidence.backend,
            "query_or_target": evidence.query_or_target,
            "title": evidence.title,
            "url": evidence.url,
            "summary": evidence.summary,
            "boundary": evidence.boundary,
            "operation": evidence.operation,
            "observed_at": evidence.observed_at,
            "confidence": evidence.confidence,
            "maturity_score": evidence.maturity_score,
            "maturity_reason": evidence.maturity_reason,
            "claims_supported": list(evidence.claims_supported),
            "forbidden_next_actions": list(evidence.forbidden_next_actions),
        },
        "maturity_scale": [
            {"score": level.score, "meaning": level.meaning}
            for level in result.maturity_scale
        ],
        "projection": {
            "schema_version": projection.schema_version,
            "agent_can_start_without_docs": projection.agent_can_start_without_docs,
            "recommended_first_command": projection.recommended_first_command,
            "source_profile_count": projection.source_profile_count,
            "action_gated_profile_count": projection.action_gated_profile_count,
            "external_write_blocked_by_default": (
                projection.external_write_blocked_by_default
            ),
            "compatibility_facade": projection.compatibility_facade,
            "new_profile_ownership_allowed": (
                projection.new_profile_ownership_allowed
            ),
            "mapped_profile_count": projection.mapped_profile_count,
            "migrated_profile_count": projection.migrated_profile_count,
            "read_first_loop": list(projection.read_first_loop),
        },
        "agent_prompt": result.agent_prompt,
    }


def reward_memory_health_payload(
    result: RewardMemoryHealthResult,
) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "corpus_id": result.corpus_id,
        "class_id": result.class_id,
        "health_state": result.health_state,
        "reason_codes": list(result.reason_codes),
        "scope_check": {
            "project_matches": result.scope_check.project_matches,
            "surface_matches": result.scope_check.surface_matches,
        },
        "freshness_check": {
            "lifecycle_state": result.freshness_check.lifecycle_state,
            "source_revision_matches": (
                result.freshness_check.source_revision_matches
            ),
            "freshness_window_satisfied": (
                result.freshness_check.freshness_window_satisfied
            ),
        },
        "pipeline": {
            "provider_available": result.pipeline.provider_available,
            "corpus_present": result.pipeline.corpus_present,
            "record_count": result.pipeline.record_count,
            "index_required": result.pipeline.index_required,
            "index_present": result.pipeline.index_present,
            "retrieval_query_succeeded": result.pipeline.retrieval_query_succeeded,
            "result_readback_verified": result.pipeline.result_readback_verified,
            "memory_applied_with_receipt": result.pipeline.memory_applied_with_receipt,
        },
        "may_apply_memory": result.may_apply_memory,
        "memory_patch_authority": result.memory_patch_authority,
        "external_write_authorized": result.external_write_authorized,
        "raw_memory_captured": result.raw_memory_captured,
    }


def reward_memory_route_payload(
    result: RewardMemoryRouteResult,
) -> dict[str, object]:
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "case_ref": result.case_ref,
        "decision": result.decision,
        "reason_codes": list(result.reason_codes),
        "required_evidence": list(result.required_evidence),
        "missing_required_evidence": list(result.missing_required_evidence),
        "pilot_authorized": result.pilot_authorized,
        "meta_review_required": result.meta_review_required,
        "route_check_role": result.route_check_role,
        "live_reasoning_required": result.live_reasoning_required,
        "memory_patch_authority": result.memory_patch_authority,
        "external_write_authorized": result.external_write_authorized,
        "raw_issue_or_memory_captured": result.raw_issue_or_memory_captured,
    }


def value_connector_install_check_payload(
    result: ValueConnectorInstallCheckResult,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for item in result.checks:
        check: dict[str, object] = {
            "connector_id": item.connector_id,
            "status": item.status,
            "install": list(item.install),
            "optional_tools": [
                {
                    "tool": tool.tool,
                    "installed": tool.installed,
                    "needed_for": tool.needed_for,
                    "install_hint": tool.install_hint,
                }
                for tool in item.optional_tools
            ],
            "external_write_capability": item.external_write_capability,
        }
        if item.write_gate is not None:
            check["write_gate"] = item.write_gate
        checks.append(check)
    return {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "mode": result.mode,
        "connector": result.connector,
        "checks": checks,
        "truth_contract": {
            "installation_check_only": (
                result.truth_contract.installation_check_only
            ),
            "external_reads_performed": (
                result.truth_contract.external_reads_performed
            ),
            "external_writes_performed": (
                result.truth_contract.external_writes_performed
            ),
            "restricted_material_recorded": (
                result.truth_contract.restricted_material_recorded
            ),
        },
    }


def semantic_preference_application_receipt_payload(
    result: SemanticPreferenceApplicationReceiptResult,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "surface": result.surface,
        "application_id": result.application_id,
        "outcome": result.outcome,
        "preference_ref_digests": list(result.preference_ref_digests),
        "artifact_ref": result.artifact_ref,
    }


def semantic_preference_maintenance_receipt_payload(
    result: SemanticPreferenceMaintenanceReceiptResult,
) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "trigger": result.trigger,
        "outcome": result.outcome,
        "corpus_ids": list(result.corpus_ids),
        "scope_ref_digests": list(result.scope_ref_digests),
        "evidence_ref": result.evidence_ref,
    }


def extension_payload(result: ExtensionResult) -> dict[str, object]:
    if isinstance(result, ExtensionInitResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "operation": result.operation,
            "dry_run": result.dry_run,
            "changed": result.changed,
            "extension_id": result.extension_id,
            "starter_kind": result.starter_kind,
            "capability_id": result.capability_id,
            "managed_entrypoint": result.managed_entrypoint,
            "version": result.version,
            "destination": result.destination,
            "module_name": result.module_name,
            "protocol": result.protocol,
            "permissions": list(result.permissions),
            "files": [asdict(item) for item in result.files],
            "next_commands": asdict(result.next_commands),
        }
    if isinstance(result, ExtensionListResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "extensions": [
                {
                    "id": item.extension_id,
                    "enabled": item.enabled,
                    "active_revision": item.active_revision,
                    "rollback_available": item.rollback_available,
                    "doctor_verified": item.doctor_verified,
                    "revision_count": item.revision_count,
                }
                for item in result.extensions
            ],
        }
    if isinstance(result, ExtensionInstallResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "operation": result.operation,
            "dry_run": result.dry_run,
            "changed": result.changed,
            "extension_id": result.extension_id,
            "version": result.version,
            "revision": result.revision,
            "previous_revision": result.previous_revision,
            "enabled": result.enabled,
            "doctor": _doctor_payload(result.doctor),
            "rollback_available": result.rollback_available,
        }
    if isinstance(result, ExtensionToggleResult):
        payload: dict[str, object] = {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "operation": result.operation,
            "dry_run": result.dry_run,
            "changed": result.changed,
            "would_change": result.would_change,
            "extension_id": result.extension_id,
            "enabled": result.enabled,
            "active_revision": result.active_revision,
        }
        if result.doctor is not None:
            payload["doctor"] = _doctor_payload(result.doctor)
        return payload
    if isinstance(result, ExtensionRollbackResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "operation": result.operation,
            "dry_run": result.dry_run,
            "changed": result.changed,
            "extension_id": result.extension_id,
            "version": result.version,
            "revision": result.revision,
            "previous_revision": result.previous_revision,
            "enabled": result.enabled,
            "doctor": _doctor_payload(result.doctor),
        }
    if isinstance(result, ExtensionDoctorResult):
        return _doctor_payload(result)
    if isinstance(result, ExtensionRunResult):
        payload = {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "operation": result.operation,
            "extension_id": result.extension_id,
            "provider_version": result.provider_version,
            "revision": result.revision,
            "protocol": result.protocol,
            "required_permissions": list(result.required_permissions),
            "dry_run": result.dry_run,
            "executed": result.executed,
            "status": result.status,
            "input_schema_version": result.input_schema_version,
        }
        if result.failure_kind is not None:
            payload["failure_kind"] = result.failure_kind
        if result.exit_code is not None:
            payload["exit_code"] = result.exit_code
        if result.provider_response is not None:
            payload["provider_result"] = {
                "ok": result.provider_response.ok,
                "schema_version": result.provider_response.schema_version,
            }
        return payload
    raise TypeError(f"unsupported extension result: {type(result).__name__}")


def presentation_payload(
    result: PresentationPackageResult
    | PresentationRollbackResult
    | PresentationReadbackResult,
) -> dict[str, object]:
    if isinstance(result, PresentationPackageResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "mode": result.mode,
            "dry_run": result.dry_run,
            "write_required": result.write_required,
            "write_performed": result.write_performed,
            "semantic_noop": result.semantic_noop,
            "requested_revision": result.requested_revision,
            "active_revision": result.active_revision,
            "previous_revision": result.previous_revision,
            "semantic_digest": result.semantic_digest,
            "publisher": _presentation_publisher(result.publisher),
            "output_dir": result.output_dir,
            "manifest_path": result.manifest_path,
            "receipt_path": result.receipt_path,
            "state_receipt_log": result.state_receipt_log,
            "validation": asdict(result.validation),
        }
    if isinstance(result, PresentationRollbackResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "mode": result.mode,
            "dry_run": result.dry_run,
            "write_required": result.write_required,
            "write_performed": result.write_performed,
            "from_revision": result.from_revision,
            "active_revision": result.active_revision,
            "semantic_digest": result.semantic_digest,
            "publisher": _presentation_publisher(result.publisher),
            "output_dir": result.output_dir,
            "manifest_path": result.manifest_path,
            "receipt_path": result.receipt_path,
            "state_receipt_log": result.state_receipt_log,
        }
    if isinstance(result, PresentationReadbackResult):
        return {
            "ok": result.ok,
            "schema_version": result.schema_version,
            "mode": result.mode,
            "dry_run": result.dry_run,
            "verified": result.verified,
            "receipt_url": result.receipt_url,
            "attempts": result.attempts,
            "site_id": result.site_id,
            "revision": result.revision,
            "semantic_digest": result.semantic_digest,
            "state_receipt_log": result.state_receipt_log,
        }
    raise TypeError(f"unsupported presentation result: {type(result).__name__}")


def _provider_state(state: CapabilityProviderState) -> dict[str, object]:
    payload: dict[str, object] = {
        "declared": state.declared,
        "installed": state.installed,
        "enabled": state.enabled,
        "ready": state.ready,
    }
    if state.active_revision is not None:
        payload["active_revision"] = state.active_revision
    return payload


def _content_ops_user_gate(gate: ContentOpsUserGate) -> dict[str, object]:
    return {
        "role": gate.role,
        "action_kind": gate.action_kind,
        "question": gate.question,
        "blocks": list(gate.blocks),
    }


def _content_ops_chain_step(
    step: ContentOpsWalkthroughChainStep,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "step": step.step,
        "result": step.result,
    }
    if step.source_item_id is not None:
        payload["source_item_id"] = step.source_item_id
    if step.external_write_performed is not None:
        payload["external_write_performed"] = step.external_write_performed
    if step.observed_shape is not None:
        payload["observed_shape"] = {
            "channel_count": step.observed_shape.channel_count,
            "recent_record_count": step.observed_shape.recent_record_count,
            "report_count": step.observed_shape.report_count,
            "api_request_count": step.observed_shape.api_request_count,
            "api_path_counts": {
                item.name: item.count
                for item in step.observed_shape.api_path_counts
            },
        }
    if step.owner_gate_required is not None:
        payload["owner_gate_required"] = step.owner_gate_required
    if step.waiting_on is not None:
        payload["waiting_on"] = step.waiting_on
    if step.user_action_required is not None:
        payload["user_action_required"] = step.user_action_required
    if step.approval_required is not None:
        payload["approval_required"] = step.approval_required
    if step.autopublish_allowed is not None:
        payload["autopublish_allowed"] = step.autopublish_allowed
    return payload


def _content_ops_projection(
    projection: ContentOpsSurfaceProjection,
) -> dict[str, object]:
    return {
        "schema_version": projection.schema_version,
        "surface_schema_version": projection.surface_schema_version,
        "surface_id": projection.surface_id,
        "mode": projection.mode,
        "first_screen": {
            "waiting_on": projection.first_screen.waiting_on,
            "user_action_required": projection.first_screen.user_action_required,
            "agent_can_continue": projection.first_screen.agent_can_continue,
            "safe_side_work_available": (
                projection.first_screen.safe_side_work_available
            ),
            "source_review_required_count": (
                projection.first_screen.source_review_required_count
            ),
            "ready_to_draft_count": (
                projection.first_screen.ready_to_draft_count
            ),
            "waiting_for_feedback_count": (
                projection.first_screen.waiting_for_feedback_count
            ),
            "publish_decision_count": (
                projection.first_screen.publish_decision_count
            ),
            "next_safe_action": projection.first_screen.next_safe_action,
        },
        "record_counts": _content_ops_record_counts(projection.record_counts),
        "source_statuses": {
            item.name: item.count for item in projection.source_statuses
        },
        "draft_states": {
            item.name: item.count for item in projection.draft_states
        },
        "feedback_effects": {
            item.name: item.count for item in projection.feedback_effects
        },
        "publish_gate_statuses": {
            item.name: item.count for item in projection.publish_gate_statuses
        },
        "connector_trials": {
            "count": projection.connector_trials.count,
            "states": {
                item.name: item.count for item in projection.connector_trials.states
            },
            "access_modes": {
                item.name: item.count
                for item in projection.connector_trials.access_modes
            },
            "surfaces": {
                item.name: item.count
                for item in projection.connector_trials.surfaces
            },
            "ready_for_metadata_trial_count": (
                projection.connector_trials.ready_for_metadata_trial_count
            ),
            "owner_gate_required_count": (
                projection.connector_trials.owner_gate_required_count
            ),
        },
        "material_memory": {
            "count": projection.material_memory.count,
            "reuse_boundaries": {
                item.name: item.count
                for item in projection.material_memory.reuse_boundaries
            },
        },
        "todo_candidates": [
            _content_ops_todo_candidate(item)
            for item in projection.todo_candidates
        ],
        "validation": _content_ops_validation(projection.validation),
        "truth_contract": {
            "projection_is_writable": (
                projection.truth_contract.projection_is_writable
            ),
            "write_authority": projection.truth_contract.write_authority,
            "source_surface_is_source_of_truth": (
                projection.truth_contract.source_surface_is_source_of_truth
            ),
            "publish_gate_required": (
                projection.truth_contract.publish_gate_required
            ),
            "autopublish_allowed": (
                projection.truth_contract.autopublish_allowed
            ),
            "raw_private_material_copied": (
                projection.truth_contract.raw_private_material_copied
            ),
            "recompute_rule": projection.truth_contract.recompute_rule,
        },
    }


def _content_ops_todo_candidate(
    item: ContentOpsTodoCandidate,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "role": item.role,
        "action_kind": item.action_kind,
        "title": item.title,
    }
    for key, values in (
        ("angle_ids", item.angle_ids),
        ("source_item_ids", item.source_item_ids),
        ("publish_gate_ids", item.publish_gate_ids),
        ("trial_ids", item.trial_ids),
    ):
        if values is not None:
            payload[key] = list(values)
    payload["validation_surface"] = item.validation_surface
    if item.stop_condition is not None:
        payload["stop_condition"] = item.stop_condition
    return payload


def _content_ops_validation(
    validation: ContentOpsSurfaceValidation,
) -> dict[str, object]:
    return {
        "schema_version": validation.schema_version,
        "ok": validation.ok,
        "errors": list(validation.errors),
        "record_counts": _content_ops_record_counts(validation.record_counts),
        "raw_material_key_names": list(validation.raw_material_key_names),
    }


def _content_ops_record_counts(
    counts: ContentOpsRecordCounts,
) -> dict[str, object]:
    return {
        "source_items": counts.source_items,
        "angle_candidates": counts.angle_candidates,
        "draft_items": counts.draft_items,
        "feedback_signals": counts.feedback_signals,
        "publish_gates": counts.publish_gates,
        "material_memory": counts.material_memory,
        "connector_trials": counts.connector_trials,
    }


def _reward_memory_corpus(item: RewardMemoryCorpus) -> dict[str, object]:
    return {
        "corpus_id": item.corpus_id,
        "class_id": item.class_id,
        "provider_id": item.provider_id,
        "owner_ref": item.owner_ref,
        "source_of_truth": item.source_of_truth,
        "read_authority": item.read_authority,
        "write_authority": item.write_authority,
        "scope": {
            "workspace_ref": item.scope.workspace_ref,
            "project_ref": item.scope.project_ref,
            "surface_ids": list(item.scope.surface_ids),
            "user_ref": item.scope.user_ref,
            "peer_ref": item.scope.peer_ref,
            "session_ref": item.scope.session_ref,
        },
        "freshness": {
            "mode": item.freshness.mode,
            "source_revision": item.freshness.source_revision,
            "max_age_seconds": item.freshness.max_age_seconds,
        },
        "lifecycle": {
            "state": item.lifecycle.state,
            "supersedes": list(item.lifecycle.supersedes),
            "superseded_by": item.lifecycle.superseded_by,
            "retirement_reason": item.lifecycle.retirement_reason,
        },
        "retrieval": {
            "index_required": item.retrieval.index_required,
            "readback_required": item.retrieval.readback_required,
            "application_receipt_required": (
                item.retrieval.application_receipt_required
            ),
        },
        "maintenance": {
            "writeback_triggers": list(item.maintenance.writeback_triggers),
            "closure_policy": item.maintenance.closure_policy,
            "retirement_authority": item.maintenance.retirement_authority,
        },
        "privacy": {
            "visibility": item.privacy.visibility,
            "raw_content_in_registry": item.privacy.raw_content_in_registry,
        },
    }


def _reward_memory_candidate_record(
    record: RewardMemoryCandidateRecord,
) -> dict[str, object]:
    return {
        "schema_version": record.schema_version,
        "target_class": record.target_class,
        "content_summary": record.content_summary,
        "source": {
            "source_kind": record.source.source_kind,
            "source_ref": record.source.source_ref,
            "actor_ref": record.source.actor_ref,
            "actor_role": record.source.actor_role,
        },
        "scope": {
            "workspace_ref": record.scope.workspace_ref,
            "project_ref": record.scope.project_ref,
            "surface_ids": list(record.scope.surface_ids),
            "revision_ref": record.scope.revision_ref,
        },
        "reasoning": {
            "summary": record.reasoning.summary,
            "confidence": record.reasoning.confidence,
        },
        "guard_context": {
            "source_freshness": record.guard_context.source_freshness,
            "conflict_state": record.guard_context.conflict_state,
            "current_artifact_verified": (
                record.guard_context.current_artifact_verified
            ),
        },
        "requested_action_scopes": list(record.requested_action_scopes),
        "lifecycle": {
            "state": record.lifecycle.state,
            "supersedes_refs": list(record.lifecycle.supersedes_refs),
        },
        "privacy": {
            "raw_content_captured": record.privacy.raw_content_captured,
        },
        "candidate_ref": record.candidate_ref,
    }


def _reward_memory_candidate_adapter(
    adapter: RewardMemoryCandidateAdapter,
) -> dict[str, object]:
    shared = adapter.shared_candidate
    return {
        "ok": adapter.ok,
        "schema_version": adapter.schema_version,
        "issue_ref": adapter.issue_ref,
        "surface_id": adapter.surface_id,
        "shared_candidate": {
            "ok": shared.ok,
            "schema_version": shared.schema_version,
            "status": shared.status,
            "candidate": _reward_memory_candidate_record(shared.candidate),
            "authority_checkpoint": {
                "verified": shared.authority_checkpoint.verified,
                "source_ref": shared.authority_checkpoint.source_ref,
                "actor_ref": shared.authority_checkpoint.actor_ref,
                "actor_role": shared.authority_checkpoint.actor_role,
                "project_ref": shared.authority_checkpoint.project_ref,
                "action_scopes": list(
                    shared.authority_checkpoint.action_scopes
                ),
            },
            "guard": {
                "passed": shared.guard.passed,
                "reason_codes": list(shared.guard.reason_codes),
                "rule": shared.guard.rule,
                "semantic_reasoning_preserved": (
                    shared.guard.semantic_reasoning_preserved
                ),
            },
            "available_review_decisions": list(
                shared.available_review_decisions
            ),
            "candidate_persisted": shared.candidate_persisted,
            "provider_write_performed": shared.provider_write_performed,
            "external_writes_performed": shared.external_writes_performed,
            "raw_content_captured": shared.raw_content_captured,
        },
        "adapter_role": adapter.adapter_role,
        "fresh_execution_context_source": (
            adapter.fresh_execution_context_source
        ),
        "provider_write_performed": adapter.provider_write_performed,
        "external_writes_performed": adapter.external_writes_performed,
        "raw_content_captured": adapter.raw_content_captured,
    }


def _outcome_capability(
    capability: OutcomeCapabilityContract,
) -> dict[str, object]:
    return {
        "capability_id": capability.capability_id,
        "scope": capability.scope,
        "default_enabled": capability.default_enabled,
        "creates_authority": capability.creates_authority,
        "mutates_core_state": capability.mutates_core_state,
    }


def _doctor_payload(result: ExtensionDoctorResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": result.ok,
        "schema_version": result.schema_version,
        "extension_id": result.extension_id,
    }
    if result.version is not None:
        payload["version"] = result.version
    payload.update(
        {
            "status": result.status,
            "available": result.available,
            "verified": result.verified,
            "entrypoint_identity": result.entrypoint_identity,
            "failure_kind": result.failure_kind,
            "external_writes_performed": result.external_writes_performed,
        }
    )
    return payload


def _presentation_publisher(
    publisher: PresentationPublisher,
) -> Mapping[str, object]:
    payload: dict[str, object] = {
        "kind": publisher.kind,
        "base_url": publisher.base_url,
        "latest_url": publisher.latest_url,
        "revision_url": publisher.revision_url,
        "http_readback_required": publisher.http_readback_required,
    }
    if publisher.deployment_contract is not None:
        payload["deployment_contract"] = asdict(publisher.deployment_contract)
    return payload
