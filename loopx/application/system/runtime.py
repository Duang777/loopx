"""Typed preview/apply use case for archiving obsolete runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from loopx.runtime import archive_runtime_goal

from ..contracts import Profile, WriteContext, WriteCorrectness
from ..errors import StateUnavailable, ValidationFailed
from ._planning import (
    PENDING_SYSTEM_WRITER_CORRECTNESS,
    require_cli_authority,
    require_matching_plan_hash,
    semantic_hash,
    validate_write_context,
)


RUNTIME_ARCHIVE_PREVIEW_OPERATION = "application.system.runtime_archive.preview"
RUNTIME_ARCHIVE_APPLY_OPERATION = "application.system.runtime_archive.apply"


@dataclass(frozen=True, slots=True)
class RuntimeArchiveRequest:
    goal_id: str
    archive_root: Path | None = None
    allow_registered: bool = False

    def __post_init__(self) -> None:
        goal_id = str(self.goal_id or "").strip()
        if not goal_id:
            raise ValidationFailed(details={"field": "goal_id"})
        object.__setattr__(self, "goal_id", goal_id)
        if self.archive_root is not None:
            object.__setattr__(
                self,
                "archive_root",
                Path(self.archive_root).expanduser(),
            )
        if not isinstance(self.allow_registered, bool):
            raise ValidationFailed(details={"field": "allow_registered"})


@dataclass(frozen=True, slots=True)
class RuntimeArchivePlan:
    operation_id: str
    plan_hash: str
    request: RuntimeArchiveRequest
    can_apply: bool
    goal_id: str
    registry_member: bool
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class RuntimeArchiveResult:
    operation_id: str
    plan_hash: str
    goal_id: str
    registry_member: bool
    archived: bool
    archive_name: str | None
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


class RuntimeArchiveProvider(Protocol):
    def archive(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: RuntimeArchiveRequest,
        execute: bool,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreRuntimeArchiveProvider:
    def archive(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: RuntimeArchiveRequest,
        execute: bool,
    ) -> Mapping[str, object]:
        return archive_runtime_goal(
            registry_path=registry_path,
            runtime_root_override=runtime_root_override,
            goal_id=request.goal_id,
            archive_root=request.archive_root,
            allow_registered=request.allow_registered,
            execute=execute,
        )


@dataclass(frozen=True, slots=True)
class RuntimeArchiveService:
    registry_path: Path
    runtime_root_override: str | None
    profile: Profile
    provider: RuntimeArchiveProvider = CoreRuntimeArchiveProvider()

    def preview(self, request: RuntimeArchiveRequest) -> RuntimeArchivePlan:
        require_cli_authority(
            self.profile,
            operation_id=RUNTIME_ARCHIVE_PREVIEW_OPERATION,
        )
        if not isinstance(request, RuntimeArchiveRequest):
            raise ValidationFailed(details={"field": "request"})
        return _project_plan(request, self._call(request=request, execute=False))

    def apply(
        self,
        plan: RuntimeArchivePlan,
        *,
        write_context: WriteContext,
    ) -> RuntimeArchiveResult:
        require_cli_authority(
            self.profile,
            operation_id=RUNTIME_ARCHIVE_APPLY_OPERATION,
        )
        if not isinstance(plan, RuntimeArchivePlan):
            raise ValidationFailed(details={"field": "plan"})
        validate_write_context(
            write_context,
            operation_id=RUNTIME_ARCHIVE_APPLY_OPERATION,
        )
        current_plan = _project_plan(
            plan.request,
            self._call(request=plan.request, execute=False),
        )
        require_matching_plan_hash(
            plan.plan_hash,
            current_plan.plan_hash,
            operation_id=RUNTIME_ARCHIVE_APPLY_OPERATION,
        )
        if not current_plan.can_apply:
            raise ValidationFailed(details={"field": "plan", "reason": "cannot_apply"})
        payload = self._call(request=plan.request, execute=True)
        archive_path = str(payload.get("archive_path") or "").strip()
        archived = _required_bool(payload.get("archived"), field="archived")
        if archived and not archive_path:
            raise _invalid_payload("archive_path")
        return RuntimeArchiveResult(
            operation_id=RUNTIME_ARCHIVE_APPLY_OPERATION,
            plan_hash=plan.plan_hash,
            goal_id=current_plan.goal_id,
            registry_member=current_plan.registry_member,
            archived=archived,
            archive_name=Path(archive_path).name if archive_path else None,
        )

    def _call(
        self,
        *,
        request: RuntimeArchiveRequest,
        execute: bool,
    ) -> Mapping[str, object]:
        try:
            payload = self.provider.archive(
                registry_path=self.registry_path,
                runtime_root_override=self.runtime_root_override,
                request=request,
                execute=execute,
            )
        except ValueError as exc:
            raise ValidationFailed(
                str(exc),
                details={"operation_id": RUNTIME_ARCHIVE_PREVIEW_OPERATION},
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "runtime_archive", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise StateUnavailable(details={"resource": "runtime_archive"})
        return payload


def _project_plan(
    request: RuntimeArchiveRequest,
    payload: Mapping[str, object],
) -> RuntimeArchivePlan:
    projection = {
        "goal_id": _required_text(payload.get("goal_id"), field="goal_id"),
        "registry_member": _required_bool(
            payload.get("registry_member"), field="registry_member"
        ),
        "source_available": bool(
            _required_text(payload.get("source"), field="source")
        ),
    }
    return RuntimeArchivePlan(
        operation_id=RUNTIME_ARCHIVE_PREVIEW_OPERATION,
        plan_hash=semantic_hash(
            operation_id=RUNTIME_ARCHIVE_PREVIEW_OPERATION,
            request=request,
            projection=projection,
        ),
        request=request,
        can_apply=bool(payload.get("ok")),
        goal_id=projection["goal_id"],
        registry_member=projection["registry_member"],
    )


def _required_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_payload(field)
    return value


def _required_text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise _invalid_payload(field)
    return text


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "runtime_archive",
            "cause": "invalid_payload",
            "field": field,
        }
    )
