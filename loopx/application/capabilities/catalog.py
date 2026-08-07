from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ...capabilities.catalog import (
    build_capability_catalog_packet,
    build_capability_detail_packet,
)
from ..errors import CapabilityUnavailable, StateUnavailable, ValidationFailed


@dataclass(frozen=True, slots=True)
class CapabilityCatalogListRequest:
    extension_manifest_paths: tuple[Path, ...] = ()
    extension_state_file: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extension_manifest_paths",
            tuple(Path(path).expanduser() for path in self.extension_manifest_paths),
        )
        if self.extension_state_file is not None:
            object.__setattr__(
                self,
                "extension_state_file",
                Path(self.extension_state_file).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class CapabilityDetailRequest:
    capability_id: str
    extension_manifest_paths: tuple[Path, ...] = ()
    extension_state_file: Path | None = None

    def __post_init__(self) -> None:
        capability_id = str(self.capability_id or "").strip()
        if not capability_id:
            raise ValidationFailed(details={"field": "capability_id"})
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(
            self,
            "extension_manifest_paths",
            tuple(Path(path).expanduser() for path in self.extension_manifest_paths),
        )
        if self.extension_state_file is not None:
            object.__setattr__(
                self,
                "extension_state_file",
                Path(self.extension_state_file).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class CapabilityProviderState:
    declared: bool
    installed: bool
    enabled: bool
    ready: bool
    active_revision: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityProviderSummary:
    provider_id: str
    origin: str
    state: CapabilityProviderState


@dataclass(frozen=True, slots=True)
class CapabilitySummary:
    capability_id: str
    title: str
    status: str
    origin: str
    visibility: str
    provider_id: str
    provider_state: CapabilityProviderState
    real_world_anchor: str
    entry_command: str
    implemented_protocol_count: int
    implementation_provider_count: int
    smoke_count: int
    next_real_step: str


@dataclass(frozen=True, slots=True)
class CapabilityCommand:
    command: str
    purpose: str
    write_boundary: str


@dataclass(frozen=True, slots=True)
class CapabilityProtocol:
    schema_version: str
    module: str
    doc: str


@dataclass(frozen=True, slots=True)
class CapabilityDetail:
    capability_id: str
    origin: str
    visibility: str
    provider_id: str
    title: str
    status: str
    default_enabled: bool
    real_world_anchor: str
    user_value: str
    entry_command: str
    commands: tuple[CapabilityCommand, ...]
    implemented_protocols: tuple[CapabilityProtocol, ...]
    smokes: tuple[str, ...]
    docs: tuple[str, ...]
    boundaries: tuple[str, ...]
    next_real_step: str
    provider_state: CapabilityProviderState


@dataclass(frozen=True, slots=True)
class CapabilityCatalogResult:
    schema_version: str
    capabilities: tuple[CapabilitySummary, ...]
    providers: tuple[CapabilityProviderSummary, ...]
    ok: bool = True


@dataclass(frozen=True, slots=True)
class CapabilityDetailResult:
    schema_version: str
    capability: CapabilityDetail
    ok: bool = True


class CapabilityCatalogProvider(Protocol):
    def list_capabilities(
        self,
        request: CapabilityCatalogListRequest,
    ) -> CapabilityCatalogResult: ...

    def get_capability(
        self,
        request: CapabilityDetailRequest,
    ) -> CapabilityDetailResult: ...


class BuiltinCapabilityCatalogProvider:
    """Adapter that projects the existing catalog owner's mappings into DTOs."""

    def list_capabilities(
        self,
        request: CapabilityCatalogListRequest,
    ) -> CapabilityCatalogResult:
        payload = build_capability_catalog_packet(
            request.extension_manifest_paths,
            extension_state_file=request.extension_state_file,
        )
        return _catalog_result(payload)

    def get_capability(
        self,
        request: CapabilityDetailRequest,
    ) -> CapabilityDetailResult:
        payload = build_capability_detail_packet(
            request.capability_id,
            request.extension_manifest_paths,
            extension_state_file=request.extension_state_file,
        )
        return _detail_result(payload)


class CapabilityCatalogService:
    """Caller-outcome facade that does not duplicate catalog lifecycle rules."""

    __slots__ = ("_provider",)

    def __init__(self, provider: CapabilityCatalogProvider | None) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> CapabilityCatalogService:
        return cls(BuiltinCapabilityCatalogProvider())

    def list(self, request: CapabilityCatalogListRequest) -> CapabilityCatalogResult:
        provider = self._require_provider("application.capabilities.list")
        return self._invoke(lambda: provider.list_capabilities(request))

    def get(self, request: CapabilityDetailRequest) -> CapabilityDetailResult:
        provider = self._require_provider("application.capabilities.get")
        return self._invoke(lambda: provider.get_capability(request))

    def _require_provider(self, operation: str) -> CapabilityCatalogProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": operation,
                    "provider": "capability_catalog",
                }
            )
        return self._provider

    @staticmethod
    def _invoke(call):
        try:
            return call()
        except (CapabilityUnavailable, StateUnavailable, ValidationFailed):
            raise
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={
                    "resource": "capability_catalog",
                    "cause": type(exc).__name__,
                }
            ) from exc


def _catalog_result(payload: Mapping[str, object]) -> CapabilityCatalogResult:
    return CapabilityCatalogResult(
        ok=_required_bool(payload, "ok"),
        schema_version=_required_text(payload, "schema_version"),
        capabilities=tuple(
            _summary(_mapping(item, "capabilities[]"))
            for item in _sequence(payload.get("capabilities"), "capabilities")
        ),
        providers=tuple(
            _provider_summary(_mapping(item, "providers[]"))
            for item in _sequence(payload.get("providers"), "providers")
        ),
    )


def _detail_result(payload: Mapping[str, object]) -> CapabilityDetailResult:
    record = _mapping(payload.get("capability"), "capability")
    return CapabilityDetailResult(
        ok=_required_bool(payload, "ok"),
        schema_version=_required_text(payload, "schema_version"),
        capability=CapabilityDetail(
            capability_id=_required_text(record, "id"),
            origin=_required_text(record, "origin"),
            visibility=_required_text(record, "visibility"),
            provider_id=_required_text(record, "provider_id"),
            title=_required_text(record, "title"),
            status=_required_text(record, "status"),
            default_enabled=_required_bool(record, "default_enabled"),
            real_world_anchor=_required_text(record, "real_world_anchor"),
            user_value=_required_text(record, "user_value"),
            entry_command=_required_text(record, "entry_command"),
            commands=tuple(
                _command(_mapping(item, "commands[]"))
                for item in _sequence(record.get("commands"), "commands")
            ),
            implemented_protocols=tuple(
                _protocol(_mapping(item, "implemented_protocols[]"))
                for item in _sequence(
                    record.get("implemented_protocols"),
                    "implemented_protocols",
                )
            ),
            smokes=_text_tuple(record.get("smokes"), "smokes"),
            docs=_text_tuple(record.get("docs"), "docs"),
            boundaries=_text_tuple(record.get("boundaries"), "boundaries"),
            next_real_step=_required_text(record, "next_real_step"),
            provider_state=_provider_state(
                _mapping(record.get("provider_state"), "provider_state")
            ),
        ),
    )


def _summary(record: Mapping[str, object]) -> CapabilitySummary:
    return CapabilitySummary(
        capability_id=_required_text(record, "id"),
        title=_required_text(record, "title"),
        status=_required_text(record, "status"),
        origin=_required_text(record, "origin"),
        visibility=_required_text(record, "visibility"),
        provider_id=_required_text(record, "provider_id"),
        provider_state=_provider_state(
            _mapping(record.get("provider_state"), "provider_state")
        ),
        real_world_anchor=_required_text(record, "real_world_anchor"),
        entry_command=_required_text(record, "entry_command"),
        implemented_protocol_count=_required_int(
            record,
            "implemented_protocol_count",
        ),
        implementation_provider_count=_required_int(
            record,
            "implementation_provider_count",
        ),
        smoke_count=_required_int(record, "smoke_count"),
        next_real_step=_required_text(record, "next_real_step"),
    )


def _provider_summary(record: Mapping[str, object]) -> CapabilityProviderSummary:
    return CapabilityProviderSummary(
        provider_id=_required_text(record, "id"),
        origin=_required_text(record, "origin"),
        state=_provider_state(record),
    )


def _provider_state(record: Mapping[str, object]) -> CapabilityProviderState:
    active_revision = record.get("active_revision")
    if active_revision is not None and not isinstance(active_revision, str):
        raise StateUnavailable(details={"resource": "capability_catalog"})
    return CapabilityProviderState(
        declared=_required_bool(record, "declared"),
        installed=_required_bool(record, "installed"),
        enabled=_required_bool(record, "enabled"),
        ready=_required_bool(record, "ready"),
        active_revision=active_revision,
    )


def _command(record: Mapping[str, object]) -> CapabilityCommand:
    return CapabilityCommand(
        command=_required_text(record, "command"),
        purpose=_required_text(record, "purpose"),
        write_boundary=_required_text(record, "write_boundary"),
    )


def _protocol(record: Mapping[str, object]) -> CapabilityProtocol:
    return CapabilityProtocol(
        schema_version=_required_text(record, "schema_version"),
        module=_required_text(record, "module"),
        doc=_required_text(record, "doc"),
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateUnavailable(
            details={"resource": "capability_catalog", "field": field}
        )
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StateUnavailable(
            details={"resource": "capability_catalog", "field": field}
        )
    return value


def _required_text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StateUnavailable(
            details={"resource": "capability_catalog", "field": field}
        )
    return value


def _required_bool(record: Mapping[str, object], field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise StateUnavailable(
            details={"resource": "capability_catalog", "field": field}
        )
    return value


def _required_int(record: Mapping[str, object], field: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StateUnavailable(
            details={"resource": "capability_catalog", "field": field}
        )
    return value


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    return tuple(
        _required_text({field: item}, field) for item in _sequence(value, field)
    )
