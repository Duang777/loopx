from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from loopx.application.capabilities import (
    ContentOpsItem,
    ContentOpsItemCreateRequest,
    ContentOpsItemCreateResult,
    ContentOpsItemProjection,
    ContentOpsItemProjectionTruthContract,
    DecisionContextInspectProfileRequest,
    DecisionContextInspectProfileResult,
    DecisionContextSourceProviderStatus,
    MaterialLifecycleSkillStatusRequest,
    MaterialLifecycleSkillStatusResult,
    MaterialLifecycleSkillSurfaceStatus,
)
from loopx.application.errors import StateUnavailable
from loopx.capabilities.content_ops.item_lifecycle import (
    build_content_ops_item_packet,
)
from loopx.capabilities.decision_context.profile import (
    resolve_decision_context_activation,
)
from loopx.capabilities.material_lifecycle.project_skill import (
    inspect_project_material_skill,
)


class LocalContentOpsItemProvider:
    """Outer adapter for the deterministic content-item constructor."""

    def __init__(
        self,
        builder: Callable[..., Mapping[str, object]] = build_content_ops_item_packet,
    ) -> None:
        self._builder = builder

    def create_item(
        self,
        request: ContentOpsItemCreateRequest,
    ) -> ContentOpsItemCreateResult:
        payload = self._builder(
            item_id=request.item_id,
            item_kind=request.item_kind,
            channel=request.channel,
            content_digest=request.content_digest,
            content_ref=request.content_ref,
            source_refs=request.source_refs,
            created_at=request.created_at,
        )
        item = _mapping(payload.get("item"), "content_ops_item", "item")
        projection = _mapping(
            payload.get("projection"),
            "content_ops_item",
            "projection",
        )
        truth = _mapping(
            projection.get("truth_contract"),
            "content_ops_item",
            "projection.truth_contract",
        )
        for field in (
            "approval",
            "delivery_intent",
            "delivery_receipt",
            "readback_receipt",
            "last_event",
        ):
            if item.get(field) is not None:
                raise StateUnavailable(
                    details={"resource": "content_ops_item", "field": field}
                )
        return ContentOpsItemCreateResult(
            ok=_boolean(payload, "ok", "content_ops_item"),
            schema_version=_text(payload, "schema_version", "content_ops_item"),
            item=ContentOpsItem(
                schema_version=_text(item, "schema_version", "content_ops_item"),
                item_id=_text(item, "item_id", "content_ops_item"),
                item_kind=_text(item, "item_kind", "content_ops_item"),
                channel=_text(item, "channel", "content_ops_item"),
                state=_text(item, "state", "content_ops_item"),
                revision=_integer(item, "revision", "content_ops_item"),
                content_digest=_text(item, "content_digest", "content_ops_item"),
                content_ref=_text(item, "content_ref", "content_ops_item"),
                source_refs=_text_tuple(
                    item.get("source_refs"),
                    "content_ops_item",
                    "source_refs",
                ),
                approval=None,
                delivery_intent=None,
                delivery_receipt=None,
                readback_receipt=None,
                superseded_by=_optional_text(
                    item,
                    "superseded_by",
                    "content_ops_item",
                ),
                terminal_reason=_optional_text(
                    item,
                    "terminal_reason",
                    "content_ops_item",
                ),
                last_event=None,
                created_at=_text(item, "created_at", "content_ops_item"),
                updated_at=_text(item, "updated_at", "content_ops_item"),
                autopublish_allowed=_boolean(
                    item,
                    "autopublish_allowed",
                    "content_ops_item",
                ),
            ),
            projection=ContentOpsItemProjection(
                schema_version=_text(
                    projection,
                    "schema_version",
                    "content_ops_item",
                ),
                item_id=_text(projection, "item_id", "content_ops_item"),
                item_kind=_text(projection, "item_kind", "content_ops_item"),
                channel=_text(projection, "channel", "content_ops_item"),
                state=_text(projection, "state", "content_ops_item"),
                revision=_integer(projection, "revision", "content_ops_item"),
                approval_present=_boolean(
                    projection,
                    "approval_present",
                    "content_ops_item",
                ),
                delivery_intent_present=_boolean(
                    projection,
                    "delivery_intent_present",
                    "content_ops_item",
                ),
                published_url=_optional_text(
                    projection,
                    "published_url",
                    "content_ops_item",
                ),
                readback_verified=_boolean(
                    projection,
                    "readback_verified",
                    "content_ops_item",
                ),
                terminal=_boolean(projection, "terminal", "content_ops_item"),
                superseded_by=_optional_text(
                    projection,
                    "superseded_by",
                    "content_ops_item",
                ),
                next_actions=_text_tuple(
                    projection.get("next_actions"),
                    "content_ops_item",
                    "projection.next_actions",
                ),
                truth_contract=ContentOpsItemProjectionTruthContract(
                    projection_is_writable=_boolean(
                        truth,
                        "projection_is_writable",
                        "content_ops_item",
                    ),
                    external_effect_authority=_text(
                        truth,
                        "external_effect_authority",
                        "content_ops_item",
                    ),
                    autopublish_allowed=_boolean(
                        truth,
                        "autopublish_allowed",
                        "content_ops_item",
                    ),
                ),
            ),
            external_reads_performed=_boolean(
                payload,
                "external_reads_performed",
                "content_ops_item",
            ),
            external_writes_performed=_boolean(
                payload,
                "external_writes_performed",
                "content_ops_item",
            ),
            autopublish_allowed=_boolean(
                payload,
                "autopublish_allowed",
                "content_ops_item",
            ),
        )


class LocalDecisionContextProfileProvider:
    """Outer adapter for optional local profile inspection."""

    def __init__(self, resolver: Callable[..., object] = resolve_decision_context_activation) -> None:
        self._resolver = resolver

    def inspect_profile(
        self,
        request: DecisionContextInspectProfileRequest,
    ) -> DecisionContextInspectProfileResult:
        resolved = self._resolver(
            goal_id=request.goal_id,
            agent_id=request.agent_id,
            profile_path=request.profile_path,
        )
        if (
            not isinstance(resolved, tuple)
            or len(resolved) != 2
            or not isinstance(resolved[0], Mapping)
        ):
            raise StateUnavailable(
                details={"resource": "decision_context_profile", "field": "result"}
            )
        payload = resolved[0]
        providers_value = payload.get("source_providers")
        providers = (
            tuple(
                DecisionContextSourceProviderStatus(
                    adapter=_text(item, "adapter", "decision_context_profile"),
                    adapter_registered=_boolean(
                        item,
                        "adapter_registered",
                        "decision_context_profile",
                    ),
                    runtime_bound=_boolean(
                        item,
                        "runtime_bound",
                        "decision_context_profile",
                    ),
                    private_config_captured=_boolean(
                        item,
                        "private_config_captured",
                        "decision_context_profile",
                    ),
                )
                for item in _mapping_sequence(
                    providers_value,
                    "decision_context_profile",
                    "source_providers",
                )
            )
            if providers_value is not None
            else None
        )
        return DecisionContextInspectProfileResult(
            ok=_boolean(payload, "ok", "decision_context_profile"),
            schema_version=_text(
                payload,
                "schema_version",
                "decision_context_profile",
            ),
            capability_id=_text(
                payload,
                "capability_id",
                "decision_context_profile",
            ),
            scope=_text(payload, "scope", "decision_context_profile"),
            default_enabled=_boolean(
                payload,
                "default_enabled",
                "decision_context_profile",
            ),
            goal_id=_text(payload, "goal_id", "decision_context_profile"),
            agent_id=_text(payload, "agent_id", "decision_context_profile"),
            profile_configured=_boolean(
                payload,
                "profile_configured",
                "decision_context_profile",
            ),
            enabled=_boolean(payload, "enabled", "decision_context_profile"),
            configured_for_agent=_boolean(
                payload,
                "configured_for_agent",
                "decision_context_profile",
            ),
            available=_boolean(payload, "available", "decision_context_profile"),
            source_count=_integer(
                payload,
                "source_count",
                "decision_context_profile",
            ),
            source_provider_count=_integer(
                payload,
                "source_provider_count",
                "decision_context_profile",
            ),
            runtime_bound_provider_count=_integer(
                payload,
                "runtime_bound_provider_count",
                "decision_context_profile",
            ),
            context_provider_configured=_boolean(
                payload,
                "context_provider_configured",
                "decision_context_profile",
            ),
            automatic_capture=_boolean(
                payload,
                "automatic_capture",
                "decision_context_profile",
            ),
            fail_open=_boolean(payload, "fail_open", "decision_context_profile"),
            external_writes_performed=_boolean(
                payload,
                "external_writes_performed",
                "decision_context_profile",
            ),
            raw_content_captured=_boolean(
                payload,
                "raw_content_captured",
                "decision_context_profile",
            ),
            private_locator_captured=_boolean(
                payload,
                "private_locator_captured",
                "decision_context_profile",
            ),
            credentials_captured=_boolean(
                payload,
                "credentials_captured",
                "decision_context_profile",
            ),
            status=_text(payload, "status", "decision_context_profile"),
            source_providers=providers,
            reason_code=_optional_text(
                payload,
                "reason_code",
                "decision_context_profile",
            ),
            unavailable_adapter_count=_optional_integer(
                payload,
                "unavailable_adapter_count",
                "decision_context_profile",
            ),
        )


class LocalMaterialLifecycleSkillProvider:
    """Outer adapter for read-only managed project-skill inspection."""

    def __init__(
        self,
        inspector: Callable[..., Mapping[str, object]] = inspect_project_material_skill,
    ) -> None:
        self._inspector = inspector

    def inspect_skill(
        self,
        request: MaterialLifecycleSkillStatusRequest,
    ) -> MaterialLifecycleSkillStatusResult:
        payload = self._inspector(request.project, surfaces=request.surfaces)
        return MaterialLifecycleSkillStatusResult(
            schema_version=_text(
                payload,
                "schema_version",
                "material_lifecycle_skill",
            ),
            skill_id=_text(payload, "skill_id", "material_lifecycle_skill"),
            delivery=_text(payload, "delivery", "material_lifecycle_skill"),
            project=_text(payload, "project", "material_lifecycle_skill"),
            project_connected=_boolean(
                payload,
                "project_connected",
                "material_lifecycle_skill",
            ),
            source=_text(payload, "source", "material_lifecycle_skill"),
            source_digest=_text(
                payload,
                "source_digest",
                "material_lifecycle_skill",
            ),
            status=_text(payload, "status", "material_lifecycle_skill"),
            surfaces=tuple(
                MaterialLifecycleSkillSurfaceStatus(
                    surface=_text(item, "surface", "material_lifecycle_skill"),
                    target=_text(item, "target", "material_lifecycle_skill"),
                    status=_text(item, "status", "material_lifecycle_skill"),
                    managed=_boolean(
                        item,
                        "managed",
                        "material_lifecycle_skill",
                    ),
                    installed_digest=_optional_text(
                        item,
                        "installed_digest",
                        "material_lifecycle_skill",
                    ),
                    recorded_source_digest=_optional_text(
                        item,
                        "recorded_source_digest",
                        "material_lifecycle_skill",
                    ),
                )
                for item in _mapping_sequence(
                    payload.get("surfaces"),
                    "material_lifecycle_skill",
                    "surfaces",
                )
            ),
            managed=_boolean(payload, "managed", "material_lifecycle_skill"),
            surface=_optional_text(payload, "surface", "material_lifecycle_skill"),
            target=_optional_text(payload, "target", "material_lifecycle_skill"),
            installed_digest=_optional_text(
                payload,
                "installed_digest",
                "material_lifecycle_skill",
            ),
            recorded_source_digest=_optional_text(
                payload,
                "recorded_source_digest",
                "material_lifecycle_skill",
            ),
        )


def _mapping(
    value: object,
    resource: str,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def _sequence(value: object, resource: str, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def _mapping_sequence(
    value: object,
    resource: str,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        _mapping(item, resource, f"{field}[]")
        for item in _sequence(value, resource, field)
    )


def _text(record: Mapping[str, object], field: str, resource: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def _optional_text(
    record: Mapping[str, object],
    field: str,
    resource: str,
) -> str | None:
    if record.get(field) is None:
        return None
    return _text(record, field, resource)


def _boolean(record: Mapping[str, object], field: str, resource: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def _integer(record: Mapping[str, object], field: str, resource: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StateUnavailable(details={"resource": resource, "field": field})
    return value


def _optional_integer(
    record: Mapping[str, object],
    field: str,
    resource: str,
) -> int | None:
    if record.get(field) is None:
        return None
    return _integer(record, field, resource)


def _text_tuple(value: object, resource: str, field: str) -> tuple[str, ...]:
    return tuple(
        _text({field: item}, field, resource)
        for item in _sequence(value, resource, field)
    )
