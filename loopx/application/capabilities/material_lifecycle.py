from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeVar

from ...capabilities.material_lifecycle.architecture import (
    build_material_lifecycle_architecture_packet,
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
_RESOURCE = "material_lifecycle_architecture"
_SKILL_RESOURCE = "material_lifecycle_skill_status"
_PROJECT_SKILL_SURFACES = {"codex", "claude-code", "opencode", "pi"}


@dataclass(frozen=True, slots=True)
class MaterialLifecycleSkillStatusRequest:
    project: Path
    surfaces: tuple[str, ...] = ("codex",)

    def __post_init__(self) -> None:
        object.__setattr__(self, "project", Path(self.project).expanduser())
        if (
            not isinstance(self.surfaces, tuple)
            or not self.surfaces
            or not all(isinstance(item, str) for item in self.surfaces)
        ):
            raise ValidationFailed(details={"field": "surfaces"})
        if (
            len(self.surfaces) != len(set(self.surfaces))
            or not set(self.surfaces) <= _PROJECT_SKILL_SURFACES
        ):
            raise ValidationFailed(details={"field": "surfaces"})


@dataclass(frozen=True, slots=True)
class MaterialLifecycleSkillSurfaceStatus:
    surface: str
    target: str
    status: str
    managed: bool
    installed_digest: str | None
    recorded_source_digest: str | None


@dataclass(frozen=True, slots=True)
class MaterialLifecycleSkillStatusResult:
    schema_version: str
    skill_id: str
    delivery: str
    project: str
    project_connected: bool
    source: str
    source_digest: str
    status: str
    surfaces: tuple[MaterialLifecycleSkillSurfaceStatus, ...]
    managed: bool
    surface: str | None = None
    target: str | None = None
    installed_digest: str | None = None
    recorded_source_digest: str | None = None


@dataclass(frozen=True, slots=True)
class MaterialLifecycleSiblingCapabilities:
    decision_context: str
    reward_memory: str
    content_ops: str


@dataclass(frozen=True, slots=True)
class MaterialLifecycleProviderBoundaries:
    raw_material_store: str
    inventory_provider: str
    migration_adapter: str
    decision_policy: str
    exploration_provider: str
    candidate_intake_adapter: str
    ranking_settlement: str


@dataclass(frozen=True, slots=True)
class MaterialLifecycleArchitectureResult:
    schema_version: str
    status: str
    capability: OutcomeCapabilityContract
    contract_schemas: tuple[str, ...]
    sibling_capabilities: MaterialLifecycleSiblingCapabilities
    provider_boundaries: MaterialLifecycleProviderBoundaries
    lifecycle: tuple[str, ...]
    invariants: tuple[str, ...]
    next_stage: str


class MaterialLifecycleArchitectureProvider(Protocol):
    def describe_architecture(self) -> MaterialLifecycleArchitectureResult: ...


class MaterialLifecycleSkillProvider(Protocol):
    def inspect_skill(
        self,
        request: MaterialLifecycleSkillStatusRequest,
    ) -> MaterialLifecycleSkillStatusResult: ...


class BuiltinMaterialLifecycleArchitectureProvider:
    def describe_architecture(self) -> MaterialLifecycleArchitectureResult:
        return _result(build_material_lifecycle_architecture_packet())


class MaterialLifecycleService:
    __slots__ = ("_provider", "_skill_provider")

    def __init__(
        self,
        provider: MaterialLifecycleArchitectureProvider | None,
        skill_provider: MaterialLifecycleSkillProvider | None = None,
    ) -> None:
        self._provider = provider
        self._skill_provider = skill_provider

    @classmethod
    def builtin(cls) -> MaterialLifecycleService:
        return cls(BuiltinMaterialLifecycleArchitectureProvider())

    def describe_architecture(self) -> MaterialLifecycleArchitectureResult:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": "application.capabilities.material_lifecycle.describe",
                    "provider": "material_lifecycle_architecture",
                }
            )
        return _invoke(self._provider.describe_architecture, _RESOURCE)

    def inspect_skill(
        self,
        request: MaterialLifecycleSkillStatusRequest,
    ) -> MaterialLifecycleSkillStatusResult:
        if self._skill_provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        "application.capabilities.material_lifecycle.inspect_skill"
                    ),
                    "provider": "material_lifecycle_skill",
                }
            )
        return _invoke(
            lambda: self._skill_provider.inspect_skill(request),
            _SKILL_RESOURCE,
        )


def _result(payload: Mapping[str, object]) -> MaterialLifecycleArchitectureResult:
    capability = mapping(
        payload.get("capability"),
        resource=_RESOURCE,
        field="capability",
    )
    siblings = mapping(
        payload.get("sibling_capabilities"),
        resource=_RESOURCE,
        field="sibling_capabilities",
    )
    boundaries = mapping(
        payload.get("provider_boundaries"),
        resource=_RESOURCE,
        field="provider_boundaries",
    )
    return MaterialLifecycleArchitectureResult(
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
        contract_schemas=text_tuple(
            payload.get("contract_schemas"),
            resource=_RESOURCE,
            field="contract_schemas",
        ),
        sibling_capabilities=MaterialLifecycleSiblingCapabilities(
            decision_context=text(siblings, "decision_context", resource=_RESOURCE),
            reward_memory=text(siblings, "reward_memory", resource=_RESOURCE),
            content_ops=text(siblings, "content_ops", resource=_RESOURCE),
        ),
        provider_boundaries=MaterialLifecycleProviderBoundaries(
            raw_material_store=text(
                boundaries,
                "raw_material_store",
                resource=_RESOURCE,
            ),
            inventory_provider=text(
                boundaries,
                "inventory_provider",
                resource=_RESOURCE,
            ),
            migration_adapter=text(
                boundaries,
                "migration_adapter",
                resource=_RESOURCE,
            ),
            decision_policy=text(boundaries, "decision_policy", resource=_RESOURCE),
            exploration_provider=text(
                boundaries,
                "exploration_provider",
                resource=_RESOURCE,
            ),
            candidate_intake_adapter=text(
                boundaries,
                "candidate_intake_adapter",
                resource=_RESOURCE,
            ),
            ranking_settlement=text(
                boundaries,
                "ranking_settlement",
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
