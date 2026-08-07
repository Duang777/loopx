"""Typed local read model for project-managed skill delivery status."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loopx.project_skill_delivery import (
    PROJECT_SKILL_SURFACE_ROOTS,
    PROJECT_SKILL_SURFACES,
    SKILL_ID_RE,
    install_project_skill,
    inspect_project_skill,
    uninstall_project_skill,
)

from ..contracts import Profile
from ..errors import AuthorityDenied, StateUnavailable, ValidationFailed


PROJECT_SKILL_STATUS_OPERATION = "application.projects.skills.inspect"
PROJECT_SKILL_INSTALL_PREVIEW_OPERATION = "application.projects.skills.install.preview"
PROJECT_SKILL_UNINSTALL_PREVIEW_OPERATION = (
    "application.projects.skills.uninstall.preview"
)
PROJECT_SKILL_STATUS_VALUES = {
    "missing",
    "unmanaged",
    "locally_modified",
    "current",
    "stale",
}


@dataclass(frozen=True, slots=True)
class ProjectSkillStatusRequest:
    project: Path
    skill_id: str
    surfaces: tuple[str, ...] = ("codex",)

    def __post_init__(self) -> None:
        project = Path(self.project).expanduser()
        skill_id = _request_text(self.skill_id, field="skill_id")
        if not SKILL_ID_RE.fullmatch(skill_id):
            raise ValidationFailed(details={"field": "skill_id"})
        surfaces = tuple(
            _request_text(surface, field="surfaces") for surface in self.surfaces
        )
        if not surfaces or len(set(surfaces)) != len(surfaces):
            raise ValidationFailed(details={"field": "surfaces"})
        if any(surface not in PROJECT_SKILL_SURFACES for surface in surfaces):
            raise ValidationFailed(details={"field": "surfaces"})
        object.__setattr__(self, "project", project)
        object.__setattr__(self, "skill_id", skill_id)
        object.__setattr__(self, "surfaces", surfaces)


@dataclass(frozen=True, slots=True)
class ProjectSkillSurfaceStatus:
    surface: str
    target_label: str
    status: str
    managed: bool
    target_exists: bool
    installed_digest: str | None
    recorded_source_digest: str | None
    installed_matches_source: bool
    marker_matches_source: bool


@dataclass(frozen=True, slots=True)
class ProjectSkillStatusResult:
    operation_id: str
    skill_id: str
    source_label: str
    source_digest: str
    project_connected: bool
    aggregate_status: str
    managed: bool
    surfaces: tuple[ProjectSkillSurfaceStatus, ...]


@dataclass(frozen=True, slots=True)
class ProjectSkillPreviewSurface:
    surface: str
    target: Path
    status: str
    managed: bool
    installed_digest: str | None
    recorded_source_digest: str | None


@dataclass(frozen=True, slots=True)
class ProjectSkillPreviewResult:
    operation_id: str
    schema_version: str
    skill_id: str
    delivery: str
    project: Path
    project_connected: bool
    source: Path
    source_digest: str
    aggregate_status: str
    surfaces: tuple[ProjectSkillPreviewSurface, ...]
    managed: bool
    action: str
    mode: str
    changed: bool
    changed_surfaces: tuple[str, ...]


class ProjectSkillStatusProvider(Protocol):
    def inspect(self, request: ProjectSkillStatusRequest) -> Mapping[str, object]: ...


class ProjectSkillPreviewProvider(Protocol):
    def preview_install(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]: ...

    def preview_uninstall(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreProjectSkillStatusProvider:
    def inspect(self, request: ProjectSkillStatusRequest) -> Mapping[str, object]:
        return inspect_project_skill(
            request.project,
            request.skill_id,
            surfaces=request.surfaces,
        )


@dataclass(frozen=True, slots=True)
class CoreProjectSkillPreviewProvider:
    def preview_install(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]:
        return install_project_skill(
            request.project,
            request.skill_id,
            surfaces=request.surfaces,
            execute=False,
        )

    def preview_uninstall(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]:
        return uninstall_project_skill(
            request.project,
            request.skill_id,
            surfaces=request.surfaces,
            execute=False,
        )


@dataclass(frozen=True, slots=True)
class ProjectSkillStatusService:
    profile: Profile
    provider: ProjectSkillStatusProvider = CoreProjectSkillStatusProvider()
    preview_provider: ProjectSkillPreviewProvider = CoreProjectSkillPreviewProvider()

    def inspect(
        self,
        request: ProjectSkillStatusRequest,
    ) -> ProjectSkillStatusResult:
        if self.profile is not Profile.CLI:
            raise AuthorityDenied(
                details={
                    "operation_id": PROJECT_SKILL_STATUS_OPERATION,
                    "profile": self.profile.value,
                }
            )
        if not isinstance(request, ProjectSkillStatusRequest):
            raise ValidationFailed(details={"field": "request"})
        try:
            payload = self.provider.inspect(request)
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"operation_id": PROJECT_SKILL_STATUS_OPERATION}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "project_skill", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping):
            raise _invalid_payload("root")
        return _project_result(request, payload)

    def preview_install(
        self,
        request: ProjectSkillStatusRequest,
    ) -> ProjectSkillPreviewResult:
        return self._preview(
            request,
            operation_id=PROJECT_SKILL_INSTALL_PREVIEW_OPERATION,
            action="install_or_upgrade",
            provider_method="preview_install",
        )

    def preview_uninstall(
        self,
        request: ProjectSkillStatusRequest,
    ) -> ProjectSkillPreviewResult:
        return self._preview(
            request,
            operation_id=PROJECT_SKILL_UNINSTALL_PREVIEW_OPERATION,
            action="uninstall",
            provider_method="preview_uninstall",
        )

    def _preview(
        self,
        request: ProjectSkillStatusRequest,
        *,
        operation_id: str,
        action: str,
        provider_method: str,
    ) -> ProjectSkillPreviewResult:
        if self.profile is not Profile.CLI:
            raise AuthorityDenied(
                details={
                    "operation_id": operation_id,
                    "profile": self.profile.value,
                }
            )
        if not isinstance(request, ProjectSkillStatusRequest):
            raise ValidationFailed(details={"field": "request"})
        method = getattr(self.preview_provider, provider_method, None)
        if not callable(method):
            raise StateUnavailable(
                details={
                    "resource": "project_skill_preview",
                    "cause": "provider_unavailable",
                    "operation_id": operation_id,
                }
            )
        try:
            payload = method(request)
        except ValueError as exc:
            raise ValidationFailed(
                str(exc),
                details={"operation_id": operation_id},
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                str(exc),
                details={
                    "resource": "project_skill_preview",
                    "cause": type(exc).__name__,
                    "operation_id": operation_id,
                },
            ) from exc
        if not isinstance(payload, Mapping):
            raise _invalid_preview_payload("root", operation_id=operation_id)
        return _project_preview_result(
            request,
            payload,
            operation_id=operation_id,
            action=action,
        )


def _project_result(
    request: ProjectSkillStatusRequest,
    payload: Mapping[str, object],
) -> ProjectSkillStatusResult:
    skill_id = _required_text(payload.get("skill_id"), field="skill_id")
    if skill_id != request.skill_id:
        raise _invalid_payload("skill_id")
    source_digest = _required_digest(
        payload.get("source_digest"), field="source_digest"
    )
    rows = _mapping_rows(payload.get("surfaces"), field="surfaces")
    surfaces = tuple(
        _project_surface(
            request=request,
            source_digest=source_digest,
            value=value,
        )
        for value in rows
    )
    if tuple(item.surface for item in surfaces) != request.surfaces:
        raise _invalid_payload("surfaces.order")
    aggregate_status = _required_text(payload.get("status"), field="status")
    legal_aggregate = PROJECT_SKILL_STATUS_VALUES | {"mixed"}
    if aggregate_status not in legal_aggregate:
        raise _invalid_payload("status")
    return ProjectSkillStatusResult(
        operation_id=PROJECT_SKILL_STATUS_OPERATION,
        skill_id=skill_id,
        source_label=f"packaged:{request.skill_id}",
        source_digest=source_digest,
        project_connected=_required_bool(
            payload.get("project_connected"), field="project_connected"
        ),
        aggregate_status=aggregate_status,
        managed=_required_bool(payload.get("managed"), field="managed"),
        surfaces=surfaces,
    )


def _project_preview_result(
    request: ProjectSkillStatusRequest,
    payload: Mapping[str, object],
    *,
    operation_id: str,
    action: str,
) -> ProjectSkillPreviewResult:
    schema_version = _preview_text(
        payload.get("schema_version"),
        field="schema_version",
        operation_id=operation_id,
    )
    if schema_version != "loopx_project_skill_status_v0":
        raise _invalid_preview_payload(
            "schema_version",
            operation_id=operation_id,
        )
    skill_id = _preview_text(
        payload.get("skill_id"),
        field="skill_id",
        operation_id=operation_id,
    )
    if skill_id != request.skill_id:
        raise _invalid_preview_payload("skill_id", operation_id=operation_id)
    delivery = _preview_text(
        payload.get("delivery"),
        field="delivery",
        operation_id=operation_id,
    )
    if delivery != "project_managed_copy":
        raise _invalid_preview_payload("delivery", operation_id=operation_id)
    project = _preview_path(
        payload.get("project"),
        field="project",
        operation_id=operation_id,
    )
    expected_project = request.project.resolve()
    if project != expected_project:
        raise _invalid_preview_payload("project", operation_id=operation_id)
    source = _preview_path(
        payload.get("source"),
        field="source",
        operation_id=operation_id,
    )
    source_digest = _preview_digest(
        payload.get("source_digest"),
        field="source_digest",
        operation_id=operation_id,
    )
    raw_surfaces = payload.get("surfaces")
    if not isinstance(raw_surfaces, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in raw_surfaces
    ):
        raise _invalid_preview_payload("surfaces", operation_id=operation_id)
    surfaces = tuple(
        _project_preview_surface(
            request=request,
            project=project,
            value=value,
            operation_id=operation_id,
        )
        for value in raw_surfaces
        if isinstance(value, Mapping)
    )
    if tuple(item.surface for item in surfaces) != request.surfaces:
        raise _invalid_preview_payload("surfaces.order", operation_id=operation_id)
    aggregate_status = _preview_text(
        payload.get("status"),
        field="status",
        operation_id=operation_id,
    )
    if aggregate_status not in PROJECT_SKILL_STATUS_VALUES | {"mixed"}:
        raise _invalid_preview_payload("status", operation_id=operation_id)
    provider_action = _preview_text(
        payload.get("operation"),
        field="operation",
        operation_id=operation_id,
    )
    if provider_action != action:
        raise _invalid_preview_payload("operation", operation_id=operation_id)
    mode = _preview_text(
        payload.get("mode"),
        field="mode",
        operation_id=operation_id,
    )
    if mode != "preview":
        raise _invalid_preview_payload("mode", operation_id=operation_id)
    raw_changed_surfaces = payload.get("changed_surfaces")
    if not isinstance(raw_changed_surfaces, (list, tuple)) or any(
        not isinstance(item, str) or not item.strip() for item in raw_changed_surfaces
    ):
        raise _invalid_preview_payload(
            "changed_surfaces",
            operation_id=operation_id,
        )
    changed_surfaces = tuple(str(item).strip() for item in raw_changed_surfaces)
    expected_changed_surfaces = tuple(
        item.surface
        for item in surfaces
        if (
            item.status != "current"
            if action == "install_or_upgrade"
            else item.status in {"current", "stale"}
        )
    )
    if changed_surfaces != expected_changed_surfaces:
        raise _invalid_preview_payload(
            "changed_surfaces",
            operation_id=operation_id,
        )
    changed = _preview_bool(
        payload.get("changed"),
        field="changed",
        operation_id=operation_id,
    )
    if changed is not bool(changed_surfaces):
        raise _invalid_preview_payload("changed", operation_id=operation_id)
    return ProjectSkillPreviewResult(
        operation_id=operation_id,
        schema_version=schema_version,
        skill_id=skill_id,
        delivery=delivery,
        project=project,
        project_connected=_preview_bool(
            payload.get("project_connected"),
            field="project_connected",
            operation_id=operation_id,
        ),
        source=source,
        source_digest=source_digest,
        aggregate_status=aggregate_status,
        surfaces=surfaces,
        managed=_preview_bool(
            payload.get("managed"),
            field="managed",
            operation_id=operation_id,
        ),
        action=provider_action,
        mode=mode,
        changed=changed,
        changed_surfaces=changed_surfaces,
    )


def _project_preview_surface(
    *,
    request: ProjectSkillStatusRequest,
    project: Path,
    value: Mapping[str, object],
    operation_id: str,
) -> ProjectSkillPreviewSurface:
    surface = _preview_text(
        value.get("surface"),
        field="surfaces.surface",
        operation_id=operation_id,
    )
    if surface not in request.surfaces:
        raise _invalid_preview_payload(
            "surfaces.surface",
            operation_id=operation_id,
        )
    target = _preview_path(
        value.get("target"),
        field="surfaces.target",
        operation_id=operation_id,
    )
    expected_target = project / PROJECT_SKILL_SURFACE_ROOTS[surface] / request.skill_id
    if target != expected_target:
        raise _invalid_preview_payload(
            "surfaces.target",
            operation_id=operation_id,
        )
    status = _preview_text(
        value.get("status"),
        field="surfaces.status",
        operation_id=operation_id,
    )
    if status not in PROJECT_SKILL_STATUS_VALUES:
        raise _invalid_preview_payload(
            "surfaces.status",
            operation_id=operation_id,
        )
    return ProjectSkillPreviewSurface(
        surface=surface,
        target=target,
        status=status,
        managed=_preview_bool(
            value.get("managed"),
            field="surfaces.managed",
            operation_id=operation_id,
        ),
        installed_digest=_preview_optional_digest(
            value.get("installed_digest"),
            field="surfaces.installed_digest",
            operation_id=operation_id,
        ),
        recorded_source_digest=_preview_optional_digest(
            value.get("recorded_source_digest"),
            field="surfaces.recorded_source_digest",
            operation_id=operation_id,
        ),
    )


def _project_surface(
    *,
    request: ProjectSkillStatusRequest,
    source_digest: str,
    value: Mapping[str, object],
) -> ProjectSkillSurfaceStatus:
    surface = _required_text(value.get("surface"), field="surfaces.surface")
    if surface not in request.surfaces:
        raise _invalid_payload("surfaces.surface")
    status = _required_text(value.get("status"), field="surfaces.status")
    if status not in PROJECT_SKILL_STATUS_VALUES:
        raise _invalid_payload("surfaces.status")
    installed_digest = _optional_digest(
        value.get("installed_digest"), field="surfaces.installed_digest"
    )
    recorded_digest = _optional_digest(
        value.get("recorded_source_digest"),
        field="surfaces.recorded_source_digest",
    )
    root = PROJECT_SKILL_SURFACE_ROOTS[surface]
    return ProjectSkillSurfaceStatus(
        surface=surface,
        target_label=(root / request.skill_id).as_posix(),
        status=status,
        managed=_required_bool(value.get("managed"), field="surfaces.managed"),
        target_exists=status != "missing",
        installed_digest=installed_digest,
        recorded_source_digest=recorded_digest,
        installed_matches_source=installed_digest == source_digest,
        marker_matches_source=recorded_digest == source_digest,
    )


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


def _required_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_payload(field)
    return value


def _required_digest(value: object, *, field: str) -> str:
    digest = _required_text(value, field=field)
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise _invalid_payload(field)
    return digest


def _optional_digest(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_digest(value, field=field)


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_payload(field)
    return value.strip()


def _request_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value.strip()


def _preview_text(value: object, *, field: str, operation_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid_preview_payload(field, operation_id=operation_id)
    return value.strip()


def _preview_bool(value: object, *, field: str, operation_id: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_preview_payload(field, operation_id=operation_id)
    return value


def _preview_path(value: object, *, field: str, operation_id: str) -> Path:
    text = _preview_text(value, field=field, operation_id=operation_id)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise _invalid_preview_payload(field, operation_id=operation_id)
    return path


def _preview_digest(value: object, *, field: str, operation_id: str) -> str:
    digest = _preview_text(value, field=field, operation_id=operation_id)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise _invalid_preview_payload(field, operation_id=operation_id)
    return digest


def _preview_optional_digest(
    value: object,
    *,
    field: str,
    operation_id: str,
) -> str | None:
    if value is None:
        return None
    return _preview_digest(value, field=field, operation_id=operation_id)


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "project_skill",
            "cause": "invalid_payload",
            "field": field,
        }
    )


def _invalid_preview_payload(field: str, *, operation_id: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "project_skill_preview",
            "cause": "invalid_payload",
            "field": field,
            "operation_id": operation_id,
        }
    )
