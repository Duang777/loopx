"""Typed registry and registry-boundary inspection services."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loopx.registry import inspect_registry, inspect_registry_boundary

from ..contracts import Profile, application_public_safe_text
from ..errors import StateUnavailable, ValidationFailed


REGISTRY_INSPECT_OPERATION = "application.registry.inspect"
REGISTRY_BOUNDARY_OPERATION = "application.registry.inspect_boundary"


@dataclass(frozen=True, slots=True)
class RegistryGoalProjection:
    goal_id: str
    domain: str | None
    status: str
    repo_exists: bool
    state_file_exists: bool
    adapter_kind: str | None
    adapter_status: str | None
    authority_source_count: int


@dataclass(frozen=True, slots=True)
class RegistryInspectionResult:
    operation_id: str
    schema_version: str | None
    goal_count: int
    status_counts: tuple[tuple[str, int], ...]
    problem_codes: tuple[str, ...]
    goals: tuple[RegistryGoalProjection, ...]
    ok: bool


@dataclass(frozen=True, slots=True)
class RegistryBoundaryRequest:
    path: Path | None = None
    require_not_tracked: bool = False
    require_gitignored: bool = False

    def __post_init__(self) -> None:
        if self.path is not None:
            object.__setattr__(self, "path", Path(self.path).expanduser())
        for name in ("require_not_tracked", "require_gitignored"):
            if not isinstance(getattr(self, name), bool):
                raise ValidationFailed(details={"field": name})


@dataclass(frozen=True, slots=True)
class RegistryBoundaryResult:
    operation_id: str
    ok: bool
    exists: bool
    path_label: str
    classification: str | None
    boundary_kind: str | None
    goal_count: int
    authority_source_count: int
    private_marker_count: int
    git_available: bool
    inside_worktree: bool
    tracked: bool
    ignored: bool
    should_be_gitignored: bool
    github_push_allowed: bool
    risks: tuple[str, ...]


class RegistryInspectionProvider(Protocol):
    def inspect(self, path: Path) -> Mapping[str, object]: ...

    def inspect_boundary(self, path: Path) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreRegistryInspectionProvider:
    def inspect(self, path: Path) -> Mapping[str, object]:
        return inspect_registry(path)

    def inspect_boundary(self, path: Path) -> Mapping[str, object]:
        return inspect_registry_boundary(path)


@dataclass(frozen=True, slots=True)
class RegistryInspectionService:
    registry_path: Path
    profile: Profile
    provider: RegistryInspectionProvider = CoreRegistryInspectionProvider()

    def inspect(self) -> RegistryInspectionResult:
        payload = self._call(self.provider.inspect, self.registry_path)
        if payload.get("ok") is not True and payload.get("error"):
            raise StateUnavailable(
                str(payload.get("error")),
                details={"resource": "registry", "path_label": self.registry_path.name},
            )
        return _project_registry(payload)

    def inspect_boundary(
        self,
        request: RegistryBoundaryRequest,
    ) -> RegistryBoundaryResult:
        if not isinstance(request, RegistryBoundaryRequest):
            raise ValidationFailed(details={"field": "request"})
        path = request.path or self.registry_path
        payload = dict(self._call(self.provider.inspect_boundary, path))
        if payload.get("ok") is not True and payload.get("error"):
            raise StateUnavailable(
                str(payload.get("error")),
                details={"resource": "registry_boundary", "path_label": path.name},
            )
        git = _required_mapping(payload.get("git"), field="git")
        risks = list(_required_texts(payload.get("risks"), field="risks"))
        if (
            request.require_not_tracked
            and _required_bool(payload.get("ok"), field="ok")
            and _required_bool(git.get("tracked"), field="git.tracked")
            and not _required_bool(
                payload.get("github_push_allowed"), field="github_push_allowed"
            )
        ):
            payload["ok"] = False
            if "registry_tracked_but_not_push_allowed" not in risks:
                risks.append("registry_tracked_but_not_push_allowed")
        if (
            request.require_gitignored
            and _required_bool(payload.get("ok"), field="ok")
            and _required_bool(
                payload.get("should_be_gitignored"), field="should_be_gitignored"
            )
            and _required_bool(
                git.get("inside_worktree"), field="git.inside_worktree"
            )
            and not _required_bool(git.get("ignored"), field="git.ignored")
            and not _required_bool(git.get("tracked"), field="git.tracked")
        ):
            payload["ok"] = False
            if "registry_should_be_gitignored" not in risks:
                risks.append("registry_should_be_gitignored")
        payload["risks"] = risks
        return _project_boundary(payload)

    def _call(
        self,
        provider_call: Callable[[Path], Mapping[str, object]],
        path: Path,
    ) -> Mapping[str, object]:
        try:
            payload = provider_call(path)
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"resource": "registry", "path_label": path.name}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={
                    "resource": "registry",
                    "path_label": path.name,
                    "cause": type(exc).__name__,
                }
            ) from exc
        if not isinstance(payload, Mapping):
            raise _invalid_payload("root")
        return payload


def _project_registry(payload: Mapping[str, object]) -> RegistryInspectionResult:
    goals = tuple(
        _project_goal(item)
        for item in _required_mapping_rows(payload.get("goals"), field="goals")
    )
    status_counts = _required_mapping(payload.get("status_counts"), field="status_counts")
    projected_counts = tuple(
        sorted(
            (
                _required_text(key, field="status_counts.key"),
                _required_int(value, field="status_counts.value"),
            )
            for key, value in status_counts.items()
        )
    )
    diagnostics = _required_mapping_rows(
        payload.get("problem_diagnostics"), field="problem_diagnostics"
    )
    return RegistryInspectionResult(
        operation_id=REGISTRY_INSPECT_OPERATION,
        schema_version=_optional_safe_text(payload.get("schema_version")),
        goal_count=_required_int(payload.get("goal_count"), field="goal_count"),
        status_counts=projected_counts,
        problem_codes=tuple(
            _required_text(item.get("code"), field="problem_diagnostics.code")
            for item in diagnostics
        ),
        goals=goals,
        ok=_required_bool(payload.get("ok"), field="ok"),
    )


def _project_goal(value: Mapping[str, object]) -> RegistryGoalProjection:
    return RegistryGoalProjection(
        goal_id=_required_text(value.get("id"), field="goals.id"),
        domain=_optional_safe_text(value.get("domain")),
        status=_required_text(value.get("status"), field="goals.status"),
        repo_exists=_required_bool(value.get("repo_exists"), field="goals.repo_exists"),
        state_file_exists=_required_bool(
            value.get("state_file_exists"), field="goals.state_file_exists"
        ),
        adapter_kind=_optional_safe_text(value.get("adapter_kind")),
        adapter_status=_optional_safe_text(value.get("adapter_status")),
        authority_source_count=_required_int(
            value.get("authority_source_count"), field="goals.authority_source_count"
        ),
    )


def _project_boundary(payload: Mapping[str, object]) -> RegistryBoundaryResult:
    git = _required_mapping(payload.get("git"), field="git")
    return RegistryBoundaryResult(
        operation_id=REGISTRY_BOUNDARY_OPERATION,
        ok=_required_bool(payload.get("ok"), field="ok"),
        exists=_required_bool(payload.get("exists"), field="exists"),
        path_label=_required_text(payload.get("path_label"), field="path_label"),
        classification=_optional_safe_text(payload.get("classification")),
        boundary_kind=_optional_safe_text(payload.get("boundary_kind")),
        goal_count=_required_int(payload.get("goal_count"), field="goal_count"),
        authority_source_count=_required_int(
            payload.get("authority_source_count"), field="authority_source_count"
        ),
        private_marker_count=_required_int(
            payload.get("private_marker_count"), field="private_marker_count"
        ),
        git_available=_required_bool(git.get("available"), field="git.available"),
        inside_worktree=_required_bool(
            git.get("inside_worktree"), field="git.inside_worktree"
        ),
        tracked=_required_bool(git.get("tracked"), field="git.tracked"),
        ignored=_required_bool(git.get("ignored"), field="git.ignored"),
        should_be_gitignored=_required_bool(
            payload.get("should_be_gitignored"), field="should_be_gitignored"
        ),
        github_push_allowed=_required_bool(
            payload.get("github_push_allowed"), field="github_push_allowed"
        ),
        risks=_required_texts(payload.get("risks"), field="risks"),
    )


def _required_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid_payload(field)
    return value


def _required_mapping_rows(
    value: object,
    *,
    field: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise _invalid_payload(field)
    return tuple(value)  # type: ignore[return-value]


def _required_texts(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _invalid_payload(field)
    return tuple(_required_text(item, field=field) for item in value)


def _required_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_payload(field)
    return value


def _required_int(value: object, *, field: str) -> int:
    if value is None or isinstance(value, bool):
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
        raise _invalid_payload(field)
    return text


def _optional_safe_text(value: object) -> str | None:
    return application_public_safe_text(value, limit=500)


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "registry_inspection",
            "cause": "invalid_payload",
            "field": field,
        }
    )
