from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol, TypeVar

from ...capabilities.decision_context.architecture import (
    build_decision_context_architecture_packet,
)
from ..errors import (
    ApplicationError,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from ._projection import boolean, mapping, text, text_tuple
from .contracts import OutcomeCapabilityContract


ResultT = TypeVar("ResultT")
_RESOURCE = "decision_context_architecture"
_PROFILE_RESOURCE = "decision_context_profile"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True, slots=True)
class DecisionContextInspectProfileRequest:
    goal_id: str
    agent_id: str
    profile_path: Path | None = None

    def __post_init__(self) -> None:
        for field, value in (("goal_id", self.goal_id), ("agent_id", self.agent_id)):
            if not isinstance(value, str) or not _TOKEN_RE.fullmatch(value):
                raise ValidationFailed(details={"field": field})
        if self.profile_path is not None:
            object.__setattr__(
                self,
                "profile_path",
                Path(self.profile_path).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class DecisionContextSourceProviderStatus:
    adapter: str
    adapter_registered: bool
    runtime_bound: bool
    private_config_captured: bool


@dataclass(frozen=True, slots=True)
class DecisionContextInspectProfileResult:
    schema_version: str
    capability_id: str
    scope: str
    default_enabled: bool
    goal_id: str
    agent_id: str
    profile_configured: bool
    enabled: bool
    configured_for_agent: bool
    available: bool
    source_count: int
    source_provider_count: int
    runtime_bound_provider_count: int
    context_provider_configured: bool
    automatic_capture: bool
    fail_open: bool
    external_writes_performed: bool
    raw_content_captured: bool
    private_locator_captured: bool
    credentials_captured: bool
    status: str
    source_providers: tuple[DecisionContextSourceProviderStatus, ...] | None = None
    reason_code: str | None = None
    unavailable_adapter_count: int | None = None
    ok: bool = True


@dataclass(frozen=True, slots=True)
class DecisionContextProviderBoundaries:
    decision_source_provider: str
    context_provider: str
    provider_failure_policy: str


@dataclass(frozen=True, slots=True)
class DecisionContextArchitectureResult:
    schema_version: str
    status: str
    capability: OutcomeCapabilityContract
    packet_schemas: tuple[str, ...]
    source_schemas: tuple[str, ...]
    assembly_schemas: tuple[str, ...]
    provider_boundaries: DecisionContextProviderBoundaries
    lifecycle: tuple[str, ...]
    invariants: tuple[str, ...]
    next_stage: str


class DecisionContextArchitectureProvider(Protocol):
    def describe_architecture(self) -> DecisionContextArchitectureResult: ...


class DecisionContextProfileProvider(Protocol):
    def inspect_profile(
        self,
        request: DecisionContextInspectProfileRequest,
    ) -> DecisionContextInspectProfileResult: ...


class BuiltinDecisionContextArchitectureProvider:
    def describe_architecture(self) -> DecisionContextArchitectureResult:
        return _result(build_decision_context_architecture_packet())


class DecisionContextService:
    __slots__ = ("_profile_provider", "_provider")

    def __init__(
        self,
        provider: DecisionContextArchitectureProvider | None,
        profile_provider: DecisionContextProfileProvider | None = None,
    ) -> None:
        self._provider = provider
        self._profile_provider = profile_provider

    @classmethod
    def builtin(cls) -> DecisionContextService:
        return cls(BuiltinDecisionContextArchitectureProvider())

    def describe_architecture(self) -> DecisionContextArchitectureResult:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": "application.capabilities.decision_context.describe",
                    "provider": "decision_context_architecture",
                }
            )
        return _invoke(self._provider.describe_architecture, _RESOURCE)

    def inspect_profile(
        self,
        request: DecisionContextInspectProfileRequest,
    ) -> DecisionContextInspectProfileResult:
        if self._profile_provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        "application.capabilities.decision_context.inspect_profile"
                    ),
                    "provider": "decision_context_profile",
                }
            )
        return _invoke(
            lambda: self._profile_provider.inspect_profile(request),
            _PROFILE_RESOURCE,
        )


def _result(payload: Mapping[str, object]) -> DecisionContextArchitectureResult:
    capability = mapping(
        payload.get("capability"),
        resource=_RESOURCE,
        field="capability",
    )
    boundaries = mapping(
        payload.get("provider_boundaries"),
        resource=_RESOURCE,
        field="provider_boundaries",
    )
    return DecisionContextArchitectureResult(
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        status=text(payload, "status", resource=_RESOURCE),
        capability=OutcomeCapabilityContract(
            capability_id=text(capability, "capability_id", resource=_RESOURCE),
            scope=text(capability, "scope", resource=_RESOURCE),
            default_enabled=boolean(
                capability,
                "default_enabled",
                resource=_RESOURCE,
            ),
            creates_authority=boolean(
                capability,
                "creates_authority",
                resource=_RESOURCE,
            ),
            mutates_core_state=boolean(
                capability,
                "mutates_core_state",
                resource=_RESOURCE,
            ),
        ),
        packet_schemas=text_tuple(
            payload.get("packet_schemas"),
            resource=_RESOURCE,
            field="packet_schemas",
        ),
        source_schemas=text_tuple(
            payload.get("source_schemas"),
            resource=_RESOURCE,
            field="source_schemas",
        ),
        assembly_schemas=text_tuple(
            payload.get("assembly_schemas"),
            resource=_RESOURCE,
            field="assembly_schemas",
        ),
        provider_boundaries=DecisionContextProviderBoundaries(
            decision_source_provider=text(
                boundaries,
                "decision_source_provider",
                resource=_RESOURCE,
            ),
            context_provider=text(boundaries, "context_provider", resource=_RESOURCE),
            provider_failure_policy=text(
                boundaries,
                "provider_failure_policy",
                resource=_RESOURCE,
            ),
        ),
        lifecycle=text_tuple(
            payload.get("lifecycle"),
            resource=_RESOURCE,
            field="lifecycle",
        ),
        invariants=text_tuple(
            payload.get("invariants"),
            resource=_RESOURCE,
            field="invariants",
        ),
        next_stage=text(payload, "next_stage", resource=_RESOURCE),
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
