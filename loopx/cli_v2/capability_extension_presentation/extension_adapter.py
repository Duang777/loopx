from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from loopx.application.errors import StateUnavailable
from loopx.application.extensions.contracts import (
    ExtensionDoctorResult,
    ExtensionFileChange,
    ExtensionInitRequest,
    ExtensionInitResult,
    ExtensionInstallRequest,
    ExtensionInstallResult,
    ExtensionListRequest,
    ExtensionListResult,
    ExtensionMutationRequest,
    ExtensionNextCommands,
    ExtensionProviderResponse,
    ExtensionRollbackResult,
    ExtensionRunRequest,
    ExtensionRunResult,
    ExtensionStatusEntry,
    ExtensionToggleResult,
)
from loopx.extensions.bundled import (
    BUNDLED_EXTENSION_IDS,
    bundled_extension_manifest,
)
from loopx.extensions.runtime import (
    MAX_EXTENSION_REQUEST_BYTES,
    default_extension_state_file,
    disable_extension,
    doctor_installed_extension,
    enable_extension,
    extension_status,
    install_extension,
    rollback_extension,
    run_standalone_extension,
)
from loopx.extensions.scaffold import scaffold_extension


KNOWN_BUNDLED_EXTENSION_IDS = tuple(BUNDLED_EXTENSION_IDS)
EXTENSION_REQUEST_MAX_BYTES = MAX_EXTENSION_REQUEST_BYTES


class LocalExtensionProvider:
    """Explicit adapter over existing local extension lifecycle owners."""

    def initialize(self, request: ExtensionInitRequest) -> ExtensionInitResult:
        return _init_result(
            scaffold_extension(
                request.extension_id,
                destination=request.destination,
                version=request.version,
                execute=request.execute,
            )
        )

    def list(self, request: ExtensionListRequest) -> ExtensionListResult:
        return _list_result(extension_status(state_file=request.state_file))

    def install(
        self,
        request: ExtensionInstallRequest,
        *,
        operation: str,
    ) -> ExtensionInstallResult:
        manifest_path = (
            bundled_extension_manifest(request.bundled_id)
            if request.bundled_id is not None
            else request.manifest_path
        )
        return _install_result(
            install_extension(
                manifest_path,
                state_file=request.state_file,
                operation=operation,
                execute=request.execute,
            )
        )

    def enable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult:
        return _toggle_result(
            enable_extension(
                request.extension_id,
                state_file=request.state_file,
                execute=request.execute,
            )
        )

    def disable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult:
        return _toggle_result(
            disable_extension(
                request.extension_id,
                state_file=request.state_file,
                execute=request.execute,
            )
        )

    def rollback(
        self,
        request: ExtensionMutationRequest,
    ) -> ExtensionRollbackResult:
        return _rollback_result(
            rollback_extension(
                request.extension_id,
                state_file=request.state_file,
                execute=request.execute,
            )
        )

    def doctor(self, request: ExtensionMutationRequest) -> ExtensionDoctorResult:
        return _doctor_result(
            doctor_installed_extension(
                request.extension_id,
                state_file=request.state_file,
                execute=request.execute,
            )
        )

    def run(self, request: ExtensionRunRequest) -> ExtensionRunResult:
        return _run_result(
            run_standalone_extension(
                request.extension_id,
                state_file=request.state_file,
                request=request.request,
                execute=request.execute,
            )
        )


def extension_state_file(
    *,
    runtime_root: str | Path | None,
    override: str | Path | None = None,
) -> Path:
    if override is not None:
        return Path(override).expanduser()
    return default_extension_state_file(runtime_root)


def _init_result(payload: Mapping[str, object]) -> ExtensionInitResult:
    commands = _mapping(payload.get("next_commands"), "next_commands")
    return ExtensionInitResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        operation=_text(payload, "operation"),
        dry_run=_bool(payload, "dry_run"),
        changed=_bool(payload, "changed"),
        extension_id=_text(payload, "extension_id"),
        starter_kind=_text(payload, "starter_kind"),
        capability_id=_optional_text(payload, "capability_id"),
        managed_entrypoint=_text(payload, "managed_entrypoint"),
        version=_text(payload, "version"),
        destination=_text(payload, "destination"),
        module_name=_text(payload, "module_name"),
        protocol=_text(payload, "protocol"),
        permissions=_text_tuple(payload.get("permissions"), "permissions"),
        files=tuple(
            ExtensionFileChange(
                path=_text(item, "path"),
                status=_text(item, "status"),
            )
            for item in _mapping_sequence(payload.get("files"), "files")
        ),
        next_commands=ExtensionNextCommands(
            install_package=_text(commands, "install_package"),
            register_extension=_text(commands, "register_extension"),
            run_extension=_text(commands, "run_extension"),
        ),
    )


def _list_result(payload: Mapping[str, object]) -> ExtensionListResult:
    return ExtensionListResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        extensions=tuple(
            ExtensionStatusEntry(
                extension_id=_text(item, "id"),
                enabled=_bool(item, "enabled"),
                active_revision=_optional_text(item, "active_revision"),
                rollback_available=_bool(item, "rollback_available"),
                doctor_verified=_bool(item, "doctor_verified"),
                revision_count=_int(item, "revision_count"),
            )
            for item in _mapping_sequence(payload.get("extensions"), "extensions")
        ),
    )


def _doctor_result(payload: Mapping[str, object]) -> ExtensionDoctorResult:
    return ExtensionDoctorResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        extension_id=_text(payload, "extension_id"),
        version=_optional_text(payload, "version"),
        status=_text(payload, "status"),
        available=_bool(payload, "available"),
        verified=_bool(payload, "verified"),
        entrypoint_identity=_optional_text(payload, "entrypoint_identity"),
        failure_kind=_optional_text(payload, "failure_kind"),
        external_writes_performed=_bool(payload, "external_writes_performed"),
    )


def _install_result(payload: Mapping[str, object]) -> ExtensionInstallResult:
    return ExtensionInstallResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        operation=_text(payload, "operation"),
        dry_run=_bool(payload, "dry_run"),
        changed=_bool(payload, "changed"),
        extension_id=_text(payload, "extension_id"),
        version=_text(payload, "version"),
        revision=_text(payload, "revision"),
        previous_revision=_optional_text(payload, "previous_revision"),
        enabled=_optional_bool(payload, "enabled"),
        doctor=_doctor_result(_mapping(payload.get("doctor"), "doctor")),
        rollback_available=_bool(payload, "rollback_available"),
    )


def _toggle_result(payload: Mapping[str, object]) -> ExtensionToggleResult:
    doctor = payload.get("doctor")
    return ExtensionToggleResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        operation=_text(payload, "operation"),
        dry_run=_bool(payload, "dry_run"),
        changed=_bool(payload, "changed"),
        would_change=_bool(payload, "would_change"),
        extension_id=_text(payload, "extension_id"),
        enabled=_bool(payload, "enabled"),
        active_revision=_text(payload, "active_revision"),
        doctor=_doctor_result(_mapping(doctor, "doctor"))
        if doctor is not None
        else None,
    )


def _rollback_result(payload: Mapping[str, object]) -> ExtensionRollbackResult:
    return ExtensionRollbackResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        operation=_text(payload, "operation"),
        dry_run=_bool(payload, "dry_run"),
        changed=_bool(payload, "changed"),
        extension_id=_text(payload, "extension_id"),
        version=_text(payload, "version"),
        revision=_text(payload, "revision"),
        previous_revision=_text(payload, "previous_revision"),
        enabled=_bool(payload, "enabled"),
        doctor=_doctor_result(_mapping(payload.get("doctor"), "doctor")),
    )


def _run_result(payload: Mapping[str, object]) -> ExtensionRunResult:
    provider_payload = payload.get("provider_result")
    provider_response = None
    if provider_payload is not None:
        provider_mapping = _mapping(provider_payload, "provider_result")
        provider_response = ExtensionProviderResponse(
            ok=_optional_bool(provider_mapping, "ok"),
            schema_version=_optional_text(provider_mapping, "schema_version"),
        )
    return ExtensionRunResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        operation=_text(payload, "operation"),
        extension_id=_text(payload, "extension_id"),
        provider_version=_text(payload, "provider_version"),
        revision=_text(payload, "revision"),
        protocol=_text(payload, "protocol"),
        required_permissions=_text_tuple(
            payload.get("required_permissions"),
            "required_permissions",
        ),
        dry_run=_bool(payload, "dry_run"),
        executed=_bool(payload, "executed"),
        status=_text(payload, "status"),
        input_schema_version=_optional_text(payload, "input_schema_version"),
        failure_kind=_optional_text(payload, "failure_kind"),
        exit_code=_optional_int(payload, "exit_code"),
        provider_response=provider_response,
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateUnavailable(details={"resource": "extension", "field": field})
    return value


def _sequence(value: object, field: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise StateUnavailable(details={"resource": "extension", "field": field})
    return value


def _mapping_sequence(value: object, field: str) -> tuple[Mapping[str, object], ...]:
    return tuple(_mapping(item, f"{field}[]") for item in _sequence(value, field))


def _text(record: Mapping[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StateUnavailable(details={"resource": "extension", "field": field})
    return value


def _optional_text(record: Mapping[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    return _text(record, field)


def _bool(record: Mapping[str, object], field: str) -> bool:
    value = record.get(field)
    if not isinstance(value, bool):
        raise StateUnavailable(details={"resource": "extension", "field": field})
    return value


def _optional_bool(record: Mapping[str, object], field: str) -> bool | None:
    value = record.get(field)
    if value is None:
        return None
    return _bool(record, field)


def _int(record: Mapping[str, object], field: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StateUnavailable(details={"resource": "extension", "field": field})
    return value


def _optional_int(record: Mapping[str, object], field: str) -> int | None:
    value = record.get(field)
    if value is None:
        return None
    return _int(record, field)


def _text_tuple(value: object, field: str) -> tuple[str, ...]:
    return tuple(_text({field: item}, field) for item in _sequence(value, field))
