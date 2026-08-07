from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from ..errors import ValidationFailed


def _text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationFailed(details={"field": field})
    return text


def _execute(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValidationFailed(details={"field": "execute"})
    return value


def _freeze_json(value: object, *, field: str) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationFailed(
                    details={"field": field, "cause": "non_string_key"}
                )
            frozen[key] = _freeze_json(item, field=field)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field=field) for item in value)
    raise ValidationFailed(details={"field": field, "cause": "non_json_value"})


@dataclass(frozen=True, slots=True)
class ExtensionInitRequest:
    extension_id: str
    destination: Path | None = None
    version: str = "0.1.0"
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extension_id",
            _text(self.extension_id, field="extension_id"),
        )
        object.__setattr__(self, "version", _text(self.version, field="version"))
        object.__setattr__(self, "execute", _execute(self.execute))
        if self.destination is not None:
            object.__setattr__(
                self,
                "destination",
                Path(self.destination).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class ExtensionListRequest:
    state_file: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_file", Path(self.state_file).expanduser())


@dataclass(frozen=True, slots=True)
class ExtensionInstallRequest:
    state_file: Path
    manifest_path: Path | None = None
    bundled_id: str | None = None
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_file", Path(self.state_file).expanduser())
        object.__setattr__(self, "execute", _execute(self.execute))
        if self.manifest_path is not None:
            object.__setattr__(
                self,
                "manifest_path",
                Path(self.manifest_path).expanduser(),
            )
        bundled_id = (
            _text(self.bundled_id, field="bundled_id")
            if self.bundled_id is not None
            else None
        )
        object.__setattr__(self, "bundled_id", bundled_id)
        if (self.manifest_path is None) == (bundled_id is None):
            raise ValidationFailed(
                "Exactly one extension manifest source is required.",
                details={"fields": ["manifest_path", "bundled_id"]},
            )


@dataclass(frozen=True, slots=True)
class ExtensionMutationRequest:
    extension_id: str
    state_file: Path
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extension_id",
            _text(self.extension_id, field="extension_id"),
        )
        object.__setattr__(self, "state_file", Path(self.state_file).expanduser())
        object.__setattr__(self, "execute", _execute(self.execute))


@dataclass(frozen=True, slots=True)
class ExtensionRunRequest:
    extension_id: str
    state_file: Path
    request: Mapping[str, object]
    execute: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extension_id",
            _text(self.extension_id, field="extension_id"),
        )
        object.__setattr__(self, "state_file", Path(self.state_file).expanduser())
        object.__setattr__(self, "execute", _execute(self.execute))
        if not isinstance(self.request, Mapping):
            raise ValidationFailed(details={"field": "request"})
        object.__setattr__(
            self,
            "request",
            _freeze_json(self.request, field="request"),
        )


@dataclass(frozen=True, slots=True)
class ExtensionFileChange:
    path: str
    status: str


@dataclass(frozen=True, slots=True)
class ExtensionNextCommands:
    install_package: str
    register_extension: str
    run_extension: str


@dataclass(frozen=True, slots=True)
class ExtensionInitResult:
    schema_version: str
    operation: str
    dry_run: bool
    changed: bool
    extension_id: str
    starter_kind: str
    capability_id: str | None
    managed_entrypoint: str
    version: str
    destination: str
    module_name: str
    protocol: str
    permissions: tuple[str, ...]
    files: tuple[ExtensionFileChange, ...]
    next_commands: ExtensionNextCommands
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionStatusEntry:
    extension_id: str
    enabled: bool
    active_revision: str | None
    rollback_available: bool
    doctor_verified: bool
    revision_count: int


@dataclass(frozen=True, slots=True)
class ExtensionListResult:
    schema_version: str
    extensions: tuple[ExtensionStatusEntry, ...]
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionDoctorResult:
    schema_version: str
    extension_id: str
    version: str | None
    status: str
    available: bool
    verified: bool
    entrypoint_identity: str | None
    failure_kind: str | None
    external_writes_performed: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionInstallResult:
    schema_version: str
    operation: str
    dry_run: bool
    changed: bool
    extension_id: str
    version: str
    revision: str
    previous_revision: str | None
    enabled: bool | None
    doctor: ExtensionDoctorResult
    rollback_available: bool
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionToggleResult:
    schema_version: str
    operation: str
    dry_run: bool
    changed: bool
    would_change: bool
    extension_id: str
    enabled: bool
    active_revision: str
    doctor: ExtensionDoctorResult | None = None
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionRollbackResult:
    schema_version: str
    operation: str
    dry_run: bool
    changed: bool
    extension_id: str
    version: str
    revision: str
    previous_revision: str
    enabled: bool
    doctor: ExtensionDoctorResult
    ok: bool = True


@dataclass(frozen=True, slots=True)
class ExtensionProviderResponse:
    ok: bool | None
    schema_version: str | None


@dataclass(frozen=True, slots=True)
class ExtensionRunResult:
    schema_version: str
    operation: str
    extension_id: str
    provider_version: str
    revision: str
    protocol: str
    required_permissions: tuple[str, ...]
    dry_run: bool
    executed: bool
    status: str
    input_schema_version: str | None
    failure_kind: str | None = None
    exit_code: int | None = None
    provider_response: ExtensionProviderResponse | None = None
    ok: bool = True


ExtensionResult = (
    ExtensionInitResult
    | ExtensionListResult
    | ExtensionInstallResult
    | ExtensionToggleResult
    | ExtensionRollbackResult
    | ExtensionDoctorResult
    | ExtensionRunResult
)
