"""Typed preview/apply facade for private local LoopX state backups."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from loopx.state_backup import build_state_backup_plan, execute_state_backup_plan

from ..contracts import Profile, WriteContext, WriteCorrectness
from ..errors import StateUnavailable, ValidationFailed
from ._planning import (
    PENDING_SYSTEM_WRITER_CORRECTNESS,
    require_cli_authority,
    require_matching_plan_hash,
    semantic_hash,
    validate_write_context,
)


BACKUP_PREVIEW_OPERATION = "application.system.backup.preview"
BACKUP_APPLY_OPERATION = "application.system.backup.apply"


@dataclass(frozen=True, slots=True)
class StateBackupRequest:
    project: Path = Path(".")
    runtime_root: Path | None = None
    output_dir: Path | None = None
    backup_id: str | None = None
    include_automations: bool = True
    include_skills: bool = True
    include_registry_projects: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "project", Path(self.project).expanduser())
        for name in ("runtime_root", "output_dir"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, Path(value).expanduser())
        if self.backup_id is not None:
            backup_id = self.backup_id.strip()
            if not backup_id:
                raise ValidationFailed(details={"field": "backup_id"})
            object.__setattr__(self, "backup_id", backup_id)
        for name in (
            "include_automations",
            "include_skills",
            "include_registry_projects",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValidationFailed(details={"field": name})


@dataclass(frozen=True, slots=True)
class StateBackupTargetEffect:
    key: str
    archive_path: str
    path_count: int
    file_count: int
    directory_count: int
    symlink_count: int
    byte_count: int


@dataclass(frozen=True, slots=True)
class StateBackupPlan:
    operation_id: str
    plan_hash: str
    request: StateBackupRequest
    can_apply: bool
    backup_id: str
    targets: tuple[StateBackupTargetEffect, ...]
    missing_target_count: int
    warning_count: int
    logical_source_bytes: int
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class StateBackupApplyResult:
    operation_id: str
    plan_hash: str
    backup_id: str
    written: bool
    target_count: int
    archive_sha256: str | None
    archive_size_bytes: int | None
    warning_count: int
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


class StateBackupProvider(Protocol):
    def preview(self, request: StateBackupRequest) -> Mapping[str, object]: ...

    def apply(self, provider_plan: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreStateBackupProvider:
    def preview(self, request: StateBackupRequest) -> Mapping[str, object]:
        return build_state_backup_plan(
            project=request.project,
            runtime_root=request.runtime_root,
            output_dir=request.output_dir,
            backup_id=request.backup_id,
            include_automations=request.include_automations,
            include_skills=request.include_skills,
            include_registry_projects=request.include_registry_projects,
        )

    def apply(self, provider_plan: Mapping[str, object]) -> Mapping[str, object]:
        return execute_state_backup_plan(dict(provider_plan))


@dataclass(frozen=True, slots=True)
class StateBackupService:
    profile: Profile
    provider: StateBackupProvider = CoreStateBackupProvider()

    def preview(self, request: StateBackupRequest) -> StateBackupPlan:
        require_cli_authority(self.profile, operation_id=BACKUP_PREVIEW_OPERATION)
        if not isinstance(request, StateBackupRequest):
            raise ValidationFailed(details={"field": "request"})
        payload = self._provider_call(lambda: self.provider.preview(request))
        backup_id = _required_text(payload.get("backup_id"), field="backup_id")
        effective_request = replace(request, backup_id=backup_id)
        return _project_plan(effective_request, payload)

    def apply(
        self,
        plan: StateBackupPlan,
        *,
        write_context: WriteContext,
    ) -> StateBackupApplyResult:
        require_cli_authority(self.profile, operation_id=BACKUP_APPLY_OPERATION)
        if not isinstance(plan, StateBackupPlan):
            raise ValidationFailed(details={"field": "plan"})
        validate_write_context(write_context, operation_id=BACKUP_APPLY_OPERATION)
        current_payload = self._provider_call(
            lambda: self.provider.preview(plan.request)
        )
        current_plan = _project_plan(plan.request, current_payload)
        require_matching_plan_hash(
            plan.plan_hash,
            current_plan.plan_hash,
            operation_id=BACKUP_APPLY_OPERATION,
        )
        if not current_plan.can_apply:
            raise ValidationFailed(details={"field": "plan", "reason": "cannot_apply"})
        applied = self._provider_call(lambda: self.provider.apply(current_payload))
        execution = applied.get("execution")
        if applied.get("ok") is True and not isinstance(execution, Mapping):
            raise _invalid_payload("execution")
        execution = execution if isinstance(execution, Mapping) else {}
        written = bool(applied.get("ok")) and not bool(applied.get("dry_run", True))
        return StateBackupApplyResult(
            operation_id=BACKUP_APPLY_OPERATION,
            plan_hash=plan.plan_hash,
            backup_id=current_plan.backup_id,
            written=written,
            target_count=len(current_plan.targets),
            archive_sha256=(
                _required_text(
                    execution.get("archive_sha256"),
                    field="execution.archive_sha256",
                )
                if written
                else _optional_text(execution.get("archive_sha256"))
            ),
            archive_size_bytes=_optional_int(
                (
                    _required_int(
                        execution.get("archive_size_bytes"),
                        field="execution.archive_size_bytes",
                    )
                    if written
                    else execution.get("archive_size_bytes")
                ),
                field="execution.archive_size_bytes",
            ),
            warning_count=current_plan.warning_count,
        )

    def _provider_call(
        self,
        call: Callable[[], Mapping[str, object]],
    ) -> Mapping[str, object]:
        try:
            payload = call()
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"operation_id": BACKUP_PREVIEW_OPERATION}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "state_backup", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping):
            raise StateUnavailable(
                details={"resource": "state_backup", "cause": "invalid_payload"}
            )
        return payload


def _project_plan(
    request: StateBackupRequest,
    payload: Mapping[str, object],
) -> StateBackupPlan:
    target_rows = _mapping_rows(payload.get("included"), field="included")
    targets = tuple(_target_effect(item) for item in target_rows)
    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        raise _invalid_payload("summary")
    missing_target_count = _required_int(
        summary.get("missing_target_count"), field="summary.missing_target_count"
    )
    warning_count = _required_int(
        summary.get("warning_count"), field="summary.warning_count"
    )
    logical_source_bytes = _required_int(
        summary.get("logical_source_bytes"), field="summary.logical_source_bytes"
    )
    projection = {
        "backup_id": payload.get("backup_id"),
        "targets": targets,
        "missing_target_count": missing_target_count,
        "warning_count": warning_count,
        "logical_source_bytes": logical_source_bytes,
    }
    return StateBackupPlan(
        operation_id=BACKUP_PREVIEW_OPERATION,
        plan_hash=semantic_hash(
            operation_id=BACKUP_PREVIEW_OPERATION,
            request=request,
            projection=projection,
        ),
        request=request,
        can_apply=bool(payload.get("ok")) and bool(targets),
        backup_id=_required_text(payload.get("backup_id"), field="backup_id"),
        targets=targets,
        missing_target_count=missing_target_count,
        warning_count=warning_count,
        logical_source_bytes=logical_source_bytes,
    )


def _target_effect(value: Mapping[str, object]) -> StateBackupTargetEffect:
    stats = value.get("stats")
    stats = stats if isinstance(stats, Mapping) else {}
    return StateBackupTargetEffect(
        key=_required_text(value.get("key"), field="target.key"),
        archive_path=_required_text(
            value.get("archive_path"), field="target.archive_path"
        ),
        path_count=_required_int(stats.get("paths"), field="target.stats.paths"),
        file_count=_required_int(stats.get("files"), field="target.stats.files"),
        directory_count=_required_int(
            stats.get("directories"), field="target.stats.directories"
        ),
        symlink_count=_required_int(
            stats.get("symlinks"), field="target.stats.symlinks"
        ),
        byte_count=_required_int(stats.get("bytes"), field="target.stats.bytes"),
    )


def _required_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise _invalid_payload(field)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise _invalid_payload(field) from None
    if parsed < 0:
        raise _invalid_payload(field)
    return parsed


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise _invalid_payload(field)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise _invalid_payload(field) from None
    if parsed < 0:
        raise _invalid_payload(field)
    return parsed


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StateUnavailable(details={"resource": "state_backup", "field": field})
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _mapping_rows(
    value: object,
    *,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise _invalid_payload(field)
    return tuple(value)  # type: ignore[return-value]


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "state_backup",
            "cause": "invalid_payload",
            "field": field,
        }
    )
