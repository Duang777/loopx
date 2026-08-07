from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loopx.application.capabilities import (
    CapabilityCatalogListRequest,
    CapabilityDetailRequest,
    ContentOpsApiPathCount,
    ContentOpsExplorationPlanRequest,
    ContentOpsItemCreateRequest,
    ContentOpsWalkthroughRequest,
    DecisionContextInspectProfileRequest,
    MaterialLifecycleSkillStatusRequest,
    RewardMemoryCandidateReviewRequest,
    RewardMemoryHealthRequest,
    RewardMemoryRouteRequest,
    SemanticPreferenceApplicationReceiptRequest,
    SemanticPreferenceMaintenanceReceiptRequest,
    ValueConnectorInstallCheckRequest,
    ValueConnectorSourceMapRequest,
)
from loopx.application.extensions import (
    ExtensionInitRequest,
    ExtensionInstallRequest,
    ExtensionListRequest,
    ExtensionMutationRequest,
    ExtensionResult,
    ExtensionRunRequest,
)
from loopx.application.presentations import (
    PresentationPackageRequest,
    PresentationPackageResult,
    PresentationReadbackRequest,
    PresentationReadbackResult,
    PresentationRollbackRequest,
    PresentationRollbackResult,
)

from ..registrar import CommandOutcome
from .application import require_application_root
from .extension_adapter import EXTENSION_REQUEST_MAX_BYTES, extension_state_file
from .payloads import (
    capability_catalog_payload,
    capability_detail_payload,
    content_ops_exploration_plan_payload,
    content_ops_item_create_payload,
    content_ops_walkthrough_payload,
    decision_context_architecture_payload,
    decision_context_inspect_profile_payload,
    extension_payload,
    material_lifecycle_architecture_payload,
    material_lifecycle_skill_status_payload,
    presentation_payload,
    reward_memory_health_payload,
    reward_memory_candidate_review_payload,
    reward_memory_corpus_registry_payload,
    reward_memory_route_payload,
    semantic_preference_application_receipt_payload,
    semantic_preference_maintenance_receipt_payload,
    value_connector_install_check_payload,
    value_connector_source_map_payload,
)


def handle_capability_list(args: argparse.Namespace, application: object) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.catalog.list(
        CapabilityCatalogListRequest(
            extension_manifest_paths=tuple(
                Path(value) for value in args.extension_manifest
            ),
            extension_state_file=extension_state_file(
                runtime_root=args.runtime_root,
            ),
        )
    )
    return CommandOutcome(
        payload=capability_catalog_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_capability_show(args: argparse.Namespace, application: object) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.catalog.get(
        CapabilityDetailRequest(
            capability_id=args.capability_id,
            extension_manifest_paths=tuple(
                Path(value) for value in args.extension_manifest
            ),
            extension_state_file=extension_state_file(
                runtime_root=args.runtime_root,
            ),
        )
    )
    return CommandOutcome(
        payload=capability_detail_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_decision_context_architecture(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.decision_context.describe_architecture()
    return CommandOutcome(
        payload=decision_context_architecture_payload(result),
        exit_code=0,
    )


def handle_material_lifecycle_architecture(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.material_lifecycle.describe_architecture()
    return CommandOutcome(
        payload=material_lifecycle_architecture_payload(result),
        exit_code=0,
    )


def handle_content_ops_exploration_plan(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.content_ops.exploration_plan(
        ContentOpsExplorationPlanRequest(
            scenario=args.scenario,
            generated_at=args.generated_at,
        )
    )
    return CommandOutcome(
        payload=content_ops_exploration_plan_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_content_ops_walkthrough(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.content_ops.walkthrough_artifact(
        ContentOpsWalkthroughRequest(
            public_handle_url=args.public_handle_url,
            public_source_item_id=args.public_source_item_id,
            chatview_source_item_id=args.chatview_source_item_id,
            channel_count=args.channel_count,
            recent_record_count=args.recent_record_count,
            report_count=args.report_count,
            api_request_count=args.api_request_count,
            api_path_counts=_content_ops_api_path_counts(args.api_path_count),
            private_preview_item_count=args.private_preview_item_count,
            theme_signals=tuple(args.theme_signal),
            generated_at=args.generated_at,
        )
    )
    return CommandOutcome(
        payload=content_ops_walkthrough_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_content_ops_item_create(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.content_ops.create_item(
        ContentOpsItemCreateRequest(
            item_id=args.item_id,
            item_kind=args.item_kind,
            channel=args.channel,
            content_digest=args.content_digest,
            content_ref=args.content_ref,
            source_refs=tuple(args.source_ref),
            created_at=args.created_at,
        )
    )
    return CommandOutcome(
        payload=content_ops_item_create_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_decision_context_inspect_profile(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.decision_context.inspect_profile(
        DecisionContextInspectProfileRequest(
            goal_id=args.goal_id,
            agent_id=args.agent_id,
            profile_path=Path(args.profile) if args.profile else None,
        )
    )
    return CommandOutcome(
        payload=decision_context_inspect_profile_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_material_lifecycle_skill_status(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.material_lifecycle.inspect_skill(
        MaterialLifecycleSkillStatusRequest(
            project=Path(args.project),
            surfaces=tuple(args.surface or ("codex",)),
        )
    )
    return CommandOutcome(
        payload=material_lifecycle_skill_status_payload(result),
        exit_code=0,
    )


def handle_reward_memory_health(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.reward_memory.health(
        RewardMemoryHealthRequest(case=args.case)
    )
    return CommandOutcome(
        payload=reward_memory_health_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_reward_memory_route(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.reward_memory.route(
        RewardMemoryRouteRequest(
            case=args.case,
            behavior_status=args.behavior_status,
            surface_count=args.surface_count,
            semantic_contract_change=args.semantic_contract_change,
            generic_boundary_for_specific_policy=(
                args.generic_boundary_for_specific_policy
            ),
            user_visible_behavior_change=args.user_visible_behavior_change,
            hot_path_or_storage_change=args.hot_path_or_storage_change,
            retrieval_or_memory_quality_claim=(
                args.retrieval_or_memory_quality_claim
            ),
            edge_case_complexity=args.edge_case_complexity,
            named_reproduction=args.named_reproduction,
            named_validation=args.named_validation,
            effect_evidence=args.effect_evidence,
            ux_evidence=args.ux_evidence,
            benchmark_evidence=args.benchmark_evidence,
            performance_evidence=args.performance_evidence,
        )
    )
    return CommandOutcome(
        payload=reward_memory_route_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_reward_memory_corpus_registry(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.reward_memory.corpus_registry()
    return CommandOutcome(
        payload=reward_memory_corpus_registry_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_reward_memory_candidate_review(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.reward_memory.candidate_review(
        RewardMemoryCandidateReviewRequest(
            case=args.case,
            decision=args.decision,
        )
    )
    return CommandOutcome(
        payload=reward_memory_candidate_review_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_value_connector_install_check(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.value_connectors.install_check(
        ValueConnectorInstallCheckRequest(connector=args.connector)
    )
    return CommandOutcome(
        payload=value_connector_install_check_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_value_connector_source_map(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.value_connectors.source_map(
        ValueConnectorSourceMapRequest(connector=args.connector)
    )
    return CommandOutcome(
        payload=value_connector_source_map_payload(result),
        exit_code=0 if result.ok else 1,
    )


def handle_semantic_preference_application_receipt(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.semantic_preference.application_receipt(
        SemanticPreferenceApplicationReceiptRequest(
            surface=args.surface,
            application_id=args.application_id,
            outcome=args.outcome,
            preference_refs=tuple(args.preference_ref),
            artifact_ref=args.artifact_ref,
        )
    )
    return CommandOutcome(
        payload=semantic_preference_application_receipt_payload(result),
        exit_code=0,
    )


def handle_semantic_preference_maintenance_receipt(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.capabilities.semantic_preference.maintenance_receipt(
        SemanticPreferenceMaintenanceReceiptRequest(
            trigger=args.trigger,
            outcome=args.outcome,
            corpus_ids=tuple(args.corpus_id),
            scope_refs=tuple(args.scope_ref),
            evidence_ref=args.evidence_ref,
        )
    )
    return CommandOutcome(
        payload=semantic_preference_maintenance_receipt_payload(result),
        exit_code=0,
    )


def handle_extension_init(args: argparse.Namespace, application: object) -> CommandOutcome:
    root = require_application_root(application)
    result = root.extensions.initialize(
        ExtensionInitRequest(
            extension_id=args.extension_id,
            destination=Path(args.destination) if args.destination else None,
            version=args.version,
            execute=bool(args.execute),
        )
    )
    return _extension_outcome(result)


def handle_extension_list(args: argparse.Namespace, application: object) -> CommandOutcome:
    root = require_application_root(application)
    result = root.extensions.list(
        ExtensionListRequest(state_file=_state_file(args))
    )
    return _extension_outcome(result)


def handle_extension_install(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    request = ExtensionInstallRequest(
        state_file=_state_file(args),
        manifest_path=Path(args.manifest) if args.manifest else None,
        bundled_id=args.bundled,
        execute=bool(args.execute),
    )
    result = (
        root.extensions.install(request)
        if args.extension_command == "install"
        else root.extensions.upgrade(request)
    )
    return _extension_outcome(result)


def handle_extension_mutation(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    request = ExtensionMutationRequest(
        extension_id=args.extension_id,
        state_file=_state_file(args),
        execute=bool(args.execute),
    )
    if args.extension_command == "enable":
        result = root.extensions.enable(request)
    elif args.extension_command == "disable":
        result = root.extensions.disable(request)
    elif args.extension_command == "rollback":
        result = root.extensions.rollback(request)
    elif args.extension_command == "doctor":
        result = root.extensions.doctor(request)
    else:
        raise ValueError("unsupported typed extension lifecycle operation")
    return _extension_outcome(result)


def handle_extension_run(args: argparse.Namespace, application: object) -> CommandOutcome:
    root = require_application_root(application)
    result = root.extensions.run(
        ExtensionRunRequest(
            extension_id=args.extension_id,
            state_file=_state_file(args),
            request=_load_json_object(args.input_json),
            execute=bool(args.execute),
        )
    )
    return _extension_outcome(result)


def handle_presentation_package(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.presentations.package(
        PresentationPackageRequest(
            site_dir=Path(args.site_dir),
            output_dir=Path(args.output_dir),
            state_dir=Path(args.state_dir) if args.state_dir else None,
            site_id=args.site_id,
            entry_path=args.entry_path,
            revision=args.revision,
            publisher_kind=args.publisher,
            base_url=args.base_url,
            desktop_visual_check=args.desktop_visual_check,
            mobile_visual_check=args.mobile_visual_check,
            link_check=args.link_check,
            execute=bool(args.execute),
        )
    )
    return _presentation_outcome(result)


def handle_presentation_rollback(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.presentations.rollback(
        PresentationRollbackRequest(
            output_dir=Path(args.output_dir),
            state_dir=Path(args.state_dir) if args.state_dir else None,
            revision=args.revision,
            execute=bool(args.execute),
        )
    )
    return _presentation_outcome(result)


def handle_presentation_verify_readback(
    args: argparse.Namespace,
    application: object,
) -> CommandOutcome:
    root = require_application_root(application)
    result = root.presentations.verify_readback(
        PresentationReadbackRequest(
            output_dir=Path(args.output_dir),
            state_dir=Path(args.state_dir) if args.state_dir else None,
            receipt_url=args.receipt_url,
            retries=args.retries,
            retry_delay_seconds=args.retry_delay_seconds,
            execute=bool(args.execute),
        )
    )
    return _presentation_outcome(result)


def _state_file(args: argparse.Namespace) -> Path:
    return extension_state_file(
        runtime_root=args.runtime_root,
        override=args.extension_state_file,
    )


def _content_ops_api_path_counts(
    values: list[str],
) -> tuple[ContentOpsApiPathCount, ...]:
    counts: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--api-path-count must use PATH=COUNT")
        path, raw_count = value.split("=", 1)
        counts[path.strip()] = int(raw_count.strip())
    return tuple(
        ContentOpsApiPathCount(path=path, count=count)
        for path, count in counts.items()
    )


def _extension_outcome(result: ExtensionResult) -> CommandOutcome:
    return CommandOutcome(
        payload=extension_payload(result),
        exit_code=0 if result.ok else 1,
    )


def _presentation_outcome(
    result: PresentationPackageResult
    | PresentationRollbackResult
    | PresentationReadbackResult,
) -> CommandOutcome:
    return CommandOutcome(
        payload=presentation_payload(result),
        exit_code=0 if result.ok else 1,
    )


def _load_json_object(path_text: str) -> dict[str, object]:
    try:
        if path_text == "-":
            binary_stdin = getattr(sys.stdin, "buffer", None)
            raw = (
                binary_stdin.read(EXTENSION_REQUEST_MAX_BYTES + 1)
                if binary_stdin is not None
                else sys.stdin.read(EXTENSION_REQUEST_MAX_BYTES + 1).encode("utf-8")
            )
        else:
            with Path(path_text).open("rb") as input_file:
                raw = input_file.read(EXTENSION_REQUEST_MAX_BYTES + 1)
        if len(raw) > EXTENSION_REQUEST_MAX_BYTES:
            raise ValueError(
                f"extension run input exceeds the {EXTENSION_REQUEST_MAX_BYTES}-byte limit"
            )
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "extension run input must be a readable JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("extension run input must be a JSON object")
    return payload
