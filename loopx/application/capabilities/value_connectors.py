from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, TypeVar

from ...capabilities.value_connectors.install_check import (
    build_value_connector_install_check_packet,
)
from ...capabilities.value_connectors.source_map import (
    build_value_connector_source_map_packet,
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
    optional_text,
    sequence,
    text,
    text_tuple,
)


ResultT = TypeVar("ResultT")
_RESOURCE = "value_connector_install_check"
_SOURCE_MAP_RESOURCE = "value_connector_source_map"
_CONNECTOR_IDS = frozenset(
    {
        "all",
        "agent_reach_ops_source_map",
        "finance_market_snapshot",
        "github_public_channel",
        "botmail_identity",
        "community_channel",
        "social_browser_x",
    }
)
_SOURCE_PROFILE_IDS = frozenset(
    {
        "all",
        "github_public_channel",
        "github_public_reply_monitor",
        "content_ops_public_handle",
        "social_browser_x",
        "agent_reach_ops_source_map",
        "finance_market_snapshot",
    }
)


@dataclass(frozen=True, slots=True)
class ValueConnectorInstallCheckRequest:
    connector: str = "all"

    def __post_init__(self) -> None:
        if not isinstance(self.connector, str) or self.connector not in _CONNECTOR_IDS:
            raise ValidationFailed(details={"field": "connector"})


@dataclass(frozen=True, slots=True)
class ValueConnectorOptionalTool:
    tool: str
    installed: bool
    needed_for: str
    install_hint: str


@dataclass(frozen=True, slots=True)
class ValueConnectorInstallCheck:
    connector_id: str
    status: str
    install: tuple[str, ...]
    optional_tools: tuple[ValueConnectorOptionalTool, ...]
    external_write_capability: bool
    write_gate: str | None


@dataclass(frozen=True, slots=True)
class ValueConnectorInstallTruthContract:
    installation_check_only: bool
    external_reads_performed: bool
    external_writes_performed: bool
    restricted_material_recorded: bool


@dataclass(frozen=True, slots=True)
class ValueConnectorInstallCheckResult:
    schema_version: str
    mode: str
    connector: str
    checks: tuple[ValueConnectorInstallCheck, ...]
    truth_contract: ValueConnectorInstallTruthContract
    ok: bool = True


class ValueConnectorInstallCheckProvider(Protocol):
    def check(
        self,
        request: ValueConnectorInstallCheckRequest,
    ) -> ValueConnectorInstallCheckResult: ...


class BuiltinValueConnectorInstallCheckProvider:
    def check(
        self,
        request: ValueConnectorInstallCheckRequest,
    ) -> ValueConnectorInstallCheckResult:
        return _result(
            build_value_connector_install_check_packet(connector=request.connector)
        )


@dataclass(frozen=True, slots=True)
class ValueConnectorSourceMapRequest:
    connector: str = "all"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.connector, str)
            or self.connector not in _SOURCE_PROFILE_IDS
        ):
            raise ValidationFailed(details={"field": "connector"})


@dataclass(frozen=True, slots=True)
class ValueConnectorSourceProfile:
    schema_version: str
    connector_id: str
    status: str
    route_type: str
    boundary: str
    safe_uses: tuple[str, ...]
    commands: tuple[str, ...]
    evidence_schema: str
    maturity_hint: str
    external_reads_allowed: bool
    external_writes_allowed: bool
    write_gate: str | None
    stop_conditions: tuple[str, ...]
    outcome_capability_id: str | None
    provider_binding_state: str
    provider_module: str | None


@dataclass(frozen=True, slots=True)
class ValueConnectorActionGatedProfile:
    connector_id: str
    boundary: str
    purpose: str
    safe_prepare_command: str
    write_gate: str
    outcome_capability_id: str | None
    provider_binding_state: str
    provider_module: str | None


@dataclass(frozen=True, slots=True)
class ValueConnectorEvidenceCardSchema:
    schema_version: str
    connector_id: str
    channel: str
    backend: str
    query_or_target: str
    title: str
    url: str
    summary: str
    boundary: str
    operation: str
    observed_at: str
    confidence: str
    maturity_score: str
    maturity_reason: str
    claims_supported: tuple[str, ...]
    forbidden_next_actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueConnectorMaturityLevel:
    score: int
    meaning: str


@dataclass(frozen=True, slots=True)
class ValueConnectorSourceMapProjection:
    schema_version: str
    agent_can_start_without_docs: bool
    recommended_first_command: str
    source_profile_count: int
    action_gated_profile_count: int
    external_write_blocked_by_default: bool
    compatibility_facade: bool
    new_profile_ownership_allowed: bool
    mapped_profile_count: int
    migrated_profile_count: int
    read_first_loop: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValueConnectorSourceMapResult:
    schema_version: str
    mode: str
    connector: str
    external_reads_performed: bool
    external_writes_performed: bool
    account_signup_performed: bool
    restricted_material_recorded: bool
    private_source_content_read: bool
    autopublish_allowed: bool
    source_profiles: tuple[ValueConnectorSourceProfile, ...]
    action_gated_profiles: tuple[ValueConnectorActionGatedProfile, ...]
    generic_evidence_card_schema: ValueConnectorEvidenceCardSchema
    maturity_scale: tuple[ValueConnectorMaturityLevel, ...]
    projection: ValueConnectorSourceMapProjection
    agent_prompt: str
    ok: bool = True


class ValueConnectorSourceMapProvider(Protocol):
    def source_map(
        self,
        request: ValueConnectorSourceMapRequest,
    ) -> ValueConnectorSourceMapResult: ...


class BuiltinValueConnectorSourceMapProvider:
    def __init__(
        self,
        *,
        builder: Callable[..., Mapping[str, object]] = (
            build_value_connector_source_map_packet
        ),
    ) -> None:
        self._builder = builder

    def source_map(
        self,
        request: ValueConnectorSourceMapRequest,
    ) -> ValueConnectorSourceMapResult:
        return _source_map_result(self._builder(connector=request.connector))


class ValueConnectorService:
    __slots__ = ("_provider", "_source_map_provider")

    def __init__(
        self,
        provider: ValueConnectorInstallCheckProvider | None,
        source_map_provider: ValueConnectorSourceMapProvider | None = None,
    ) -> None:
        self._provider = provider
        self._source_map_provider = source_map_provider

    @classmethod
    def builtin(cls) -> ValueConnectorService:
        return cls(
            BuiltinValueConnectorInstallCheckProvider(),
            BuiltinValueConnectorSourceMapProvider(),
        )

    def install_check(
        self,
        request: ValueConnectorInstallCheckRequest,
    ) -> ValueConnectorInstallCheckResult:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        "application.capabilities.value_connectors.install_check"
                    ),
                    "provider": "value_connector_install_check",
                }
            )
        return _invoke(lambda: self._provider.check(request), _RESOURCE)

    def source_map(
        self,
        request: ValueConnectorSourceMapRequest,
    ) -> ValueConnectorSourceMapResult:
        if self._source_map_provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        "application.capabilities.value_connectors.source_map"
                    ),
                    "provider": "value_connector_source_map",
                }
            )
        return _invoke(
            lambda: self._source_map_provider.source_map(request),
            _SOURCE_MAP_RESOURCE,
        )


def _source_map_result(
    payload: Mapping[str, object],
) -> ValueConnectorSourceMapResult:
    resource = _SOURCE_MAP_RESOURCE
    evidence = mapping(
        payload.get("generic_evidence_card_schema"),
        resource=resource,
        field="generic_evidence_card_schema",
    )
    projection = mapping(
        payload.get("projection"),
        resource=resource,
        field="projection",
    )
    return ValueConnectorSourceMapResult(
        ok=boolean(payload, "ok", resource=resource),
        schema_version=text(payload, "schema_version", resource=resource),
        mode=text(payload, "mode", resource=resource),
        connector=text(payload, "connector", resource=resource),
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
        account_signup_performed=boolean(
            payload,
            "account_signup_performed",
            resource=resource,
        ),
        restricted_material_recorded=boolean(
            payload,
            "restricted_material_recorded",
            resource=resource,
        ),
        private_source_content_read=boolean(
            payload,
            "private_source_content_read",
            resource=resource,
        ),
        autopublish_allowed=boolean(
            payload,
            "autopublish_allowed",
            resource=resource,
        ),
        source_profiles=tuple(
            _source_profile(item, index=index)
            for index, item in enumerate(
                sequence(
                    payload.get("source_profiles"),
                    resource=resource,
                    field="source_profiles",
                )
            )
        ),
        action_gated_profiles=tuple(
            _action_gated_profile(item, index=index)
            for index, item in enumerate(
                sequence(
                    payload.get("action_gated_profiles"),
                    resource=resource,
                    field="action_gated_profiles",
                )
            )
        ),
        generic_evidence_card_schema=ValueConnectorEvidenceCardSchema(
            schema_version=text(evidence, "schema_version", resource=resource),
            connector_id=text(evidence, "connector_id", resource=resource),
            channel=text(evidence, "channel", resource=resource),
            backend=text(evidence, "backend", resource=resource),
            query_or_target=text(
                evidence,
                "query_or_target",
                resource=resource,
            ),
            title=text(evidence, "title", resource=resource),
            url=text(evidence, "url", resource=resource),
            summary=text(evidence, "summary", resource=resource),
            boundary=text(evidence, "boundary", resource=resource),
            operation=text(evidence, "operation", resource=resource),
            observed_at=text(evidence, "observed_at", resource=resource),
            confidence=text(evidence, "confidence", resource=resource),
            maturity_score=text(evidence, "maturity_score", resource=resource),
            maturity_reason=text(
                evidence,
                "maturity_reason",
                resource=resource,
            ),
            claims_supported=text_tuple(
                evidence.get("claims_supported"),
                resource=resource,
                field="generic_evidence_card_schema.claims_supported",
            ),
            forbidden_next_actions=text_tuple(
                evidence.get("forbidden_next_actions"),
                resource=resource,
                field="generic_evidence_card_schema.forbidden_next_actions",
            ),
        ),
        maturity_scale=tuple(
            _maturity_level(item, index=index)
            for index, item in enumerate(
                sequence(
                    payload.get("maturity_scale"),
                    resource=resource,
                    field="maturity_scale",
                )
            )
        ),
        projection=ValueConnectorSourceMapProjection(
            schema_version=text(projection, "schema_version", resource=resource),
            agent_can_start_without_docs=boolean(
                projection,
                "agent_can_start_without_docs",
                resource=resource,
            ),
            recommended_first_command=text(
                projection,
                "recommended_first_command",
                resource=resource,
            ),
            source_profile_count=integer(
                projection,
                "source_profile_count",
                resource=resource,
            ),
            action_gated_profile_count=integer(
                projection,
                "action_gated_profile_count",
                resource=resource,
            ),
            external_write_blocked_by_default=boolean(
                projection,
                "external_write_blocked_by_default",
                resource=resource,
            ),
            compatibility_facade=boolean(
                projection,
                "compatibility_facade",
                resource=resource,
            ),
            new_profile_ownership_allowed=boolean(
                projection,
                "new_profile_ownership_allowed",
                resource=resource,
            ),
            mapped_profile_count=integer(
                projection,
                "mapped_profile_count",
                resource=resource,
            ),
            migrated_profile_count=integer(
                projection,
                "migrated_profile_count",
                resource=resource,
            ),
            read_first_loop=text_tuple(
                projection.get("read_first_loop"),
                resource=resource,
                field="projection.read_first_loop",
            ),
        ),
        agent_prompt=text(payload, "agent_prompt", resource=resource),
    )


def _source_profile(value: object, *, index: int) -> ValueConnectorSourceProfile:
    resource = _SOURCE_MAP_RESOURCE
    item = mapping(value, resource=resource, field=f"source_profiles[{index}]")
    return ValueConnectorSourceProfile(
        schema_version=text(item, "schema_version", resource=resource),
        connector_id=text(item, "connector_id", resource=resource),
        status=text(item, "status", resource=resource),
        route_type=text(item, "route_type", resource=resource),
        boundary=text(item, "boundary", resource=resource),
        safe_uses=text_tuple(
            item.get("safe_uses"),
            resource=resource,
            field=f"source_profiles[{index}].safe_uses",
        ),
        commands=text_tuple(
            item.get("commands"),
            resource=resource,
            field=f"source_profiles[{index}].commands",
        ),
        evidence_schema=text(item, "evidence_schema", resource=resource),
        maturity_hint=text(item, "maturity_hint", resource=resource),
        external_reads_allowed=boolean(
            item,
            "external_reads_allowed",
            resource=resource,
        ),
        external_writes_allowed=boolean(
            item,
            "external_writes_allowed",
            resource=resource,
        ),
        write_gate=optional_text(item, "write_gate", resource=resource),
        stop_conditions=text_tuple(
            item.get("stop_conditions"),
            resource=resource,
            field=f"source_profiles[{index}].stop_conditions",
        ),
        outcome_capability_id=optional_text(
            item,
            "outcome_capability_id",
            resource=resource,
        ),
        provider_binding_state=text(
            item,
            "provider_binding_state",
            resource=resource,
        ),
        provider_module=optional_text(item, "provider_module", resource=resource),
    )


def _action_gated_profile(
    value: object,
    *,
    index: int,
) -> ValueConnectorActionGatedProfile:
    resource = _SOURCE_MAP_RESOURCE
    item = mapping(
        value,
        resource=resource,
        field=f"action_gated_profiles[{index}]",
    )
    return ValueConnectorActionGatedProfile(
        connector_id=text(item, "connector_id", resource=resource),
        boundary=text(item, "boundary", resource=resource),
        purpose=text(item, "purpose", resource=resource),
        safe_prepare_command=text(item, "safe_prepare_command", resource=resource),
        write_gate=text(item, "write_gate", resource=resource),
        outcome_capability_id=optional_text(
            item,
            "outcome_capability_id",
            resource=resource,
        ),
        provider_binding_state=text(
            item,
            "provider_binding_state",
            resource=resource,
        ),
        provider_module=optional_text(item, "provider_module", resource=resource),
    )


def _maturity_level(value: object, *, index: int) -> ValueConnectorMaturityLevel:
    resource = _SOURCE_MAP_RESOURCE
    item = mapping(value, resource=resource, field=f"maturity_scale[{index}]")
    return ValueConnectorMaturityLevel(
        score=integer(item, "score", resource=resource),
        meaning=text(item, "meaning", resource=resource),
    )


def _result(payload: Mapping[str, object]) -> ValueConnectorInstallCheckResult:
    raw_checks = sequence(payload.get("checks"), resource=_RESOURCE, field="checks")
    truth = mapping(
        payload.get("truth_contract"),
        resource=_RESOURCE,
        field="truth_contract",
    )
    return ValueConnectorInstallCheckResult(
        ok=boolean(payload, "ok", resource=_RESOURCE),
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        mode=text(payload, "mode", resource=_RESOURCE),
        connector=text(payload, "connector", resource=_RESOURCE),
        checks=tuple(_check(item, index=index) for index, item in enumerate(raw_checks)),
        truth_contract=ValueConnectorInstallTruthContract(
            installation_check_only=boolean(
                truth,
                "installation_check_only",
                resource=_RESOURCE,
            ),
            external_reads_performed=boolean(
                truth,
                "external_reads_performed",
                resource=_RESOURCE,
            ),
            external_writes_performed=boolean(
                truth,
                "external_writes_performed",
                resource=_RESOURCE,
            ),
            restricted_material_recorded=boolean(
                truth,
                "restricted_material_recorded",
                resource=_RESOURCE,
            ),
        ),
    )


def _check(value: object, *, index: int) -> ValueConnectorInstallCheck:
    item = mapping(value, resource=_RESOURCE, field=f"checks[{index}]")
    raw_tools = sequence(
        item.get("optional_tools"),
        resource=_RESOURCE,
        field=f"checks[{index}].optional_tools",
    )
    return ValueConnectorInstallCheck(
        connector_id=text(item, "connector_id", resource=_RESOURCE),
        status=text(item, "status", resource=_RESOURCE),
        install=text_tuple(
            item.get("install"),
            resource=_RESOURCE,
            field=f"checks[{index}].install",
        ),
        optional_tools=tuple(
            _optional_tool(tool, check_index=index, tool_index=tool_index)
            for tool_index, tool in enumerate(raw_tools)
        ),
        external_write_capability=boolean(
            item,
            "external_write_capability",
            resource=_RESOURCE,
        ),
        write_gate=optional_text(item, "write_gate", resource=_RESOURCE),
    )


def _optional_tool(
    value: object,
    *,
    check_index: int,
    tool_index: int,
) -> ValueConnectorOptionalTool:
    item = mapping(
        value,
        resource=_RESOURCE,
        field=f"checks[{check_index}].optional_tools[{tool_index}]",
    )
    return ValueConnectorOptionalTool(
        tool=text(item, "tool", resource=_RESOURCE),
        installed=boolean(item, "installed", resource=_RESOURCE),
        needed_for=text(item, "needed_for", resource=_RESOURCE),
        install_hint=text(item, "install_hint", resource=_RESOURCE),
    )


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
