"""Typed preview/apply facade for explicit legacy-state migration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol

from loopx.global_registry import sync_project_registry_to_global
from loopx.paths import DEFAULT_RUNTIME_ROOT
from loopx.state_migration import (
    LEGACY_GLOBAL_REGISTRY,
    LEGACY_RUNTIME_ROOT,
    legacy_registry_goal_ids,
    migrate_legacy_state,
)

from ..contracts import Profile, WriteContext, WriteCorrectness
from ..errors import StateUnavailable, ValidationFailed
from ._planning import (
    PENDING_SYSTEM_WRITER_CORRECTNESS,
    require_cli_authority,
    require_matching_plan_hash,
    semantic_hash,
    validate_write_context,
)


STATE_MIGRATION_PREVIEW_OPERATION = "application.system.state_migration.preview"
STATE_MIGRATION_APPLY_OPERATION = "application.system.state_migration.apply"


@dataclass(frozen=True, slots=True)
class StateMigrationRequest:
    legacy_registry: Path = LEGACY_GLOBAL_REGISTRY
    legacy_runtime_root: Path = LEGACY_RUNTIME_ROOT
    target_runtime_root: Path | None = None
    goal_ids: tuple[str, ...] = ()
    all_goals: bool = False
    goal_id_map: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    path_map: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    copy_active_state: bool = False
    copy_runtime: bool = False
    sync_global: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "legacy_registry",
            Path(self.legacy_registry).expanduser(),
        )
        object.__setattr__(
            self,
            "legacy_runtime_root",
            Path(self.legacy_runtime_root).expanduser(),
        )
        if self.target_runtime_root is not None:
            object.__setattr__(
                self,
                "target_runtime_root",
                Path(self.target_runtime_root).expanduser(),
            )
        goal_ids = tuple(_text(item, field="goal_ids") for item in self.goal_ids)
        if bool(goal_ids) == bool(self.all_goals):
            raise ValidationFailed(
                details={"field": "goal_selector", "reason": "choose_exactly_one"}
            )
        object.__setattr__(self, "goal_ids", goal_ids)
        object.__setattr__(
            self,
            "goal_id_map",
            _mapping(self.goal_id_map, field="goal_id_map"),
        )
        object.__setattr__(
            self,
            "path_map",
            _mapping(self.path_map, field="path_map"),
        )
        for name in (
            "all_goals",
            "copy_active_state",
            "copy_runtime",
            "sync_global",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ValidationFailed(details={"field": name})


@dataclass(frozen=True, slots=True)
class MigrationCopyProjection:
    selected_count: int
    copy_requested: bool
    copied_count: int
    skipped_count: int


@dataclass(frozen=True, slots=True)
class StateMigrationPlan:
    operation_id: str
    plan_hash: str
    request: StateMigrationRequest
    can_apply: bool
    selected_goal_ids: tuple[str, ...]
    migrated_goal_ids: tuple[str, ...]
    target_registry_goal_count: int
    active_state: MigrationCopyProjection
    runtime_goals: MigrationCopyProjection
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class StateMigrationResult:
    operation_id: str
    plan_hash: str
    migrated_goal_ids: tuple[str, ...]
    wrote_project_registry: bool
    active_state: MigrationCopyProjection
    runtime_goals: MigrationCopyProjection
    global_sync_attempted_count: int
    global_sync_verified: bool
    partial_global_sync: bool
    correctness: WriteCorrectness = PENDING_SYSTEM_WRITER_CORRECTNESS


class StateMigrationProvider(Protocol):
    def goal_ids(self, registry_path: Path) -> tuple[str, ...]: ...

    def migrate(
        self,
        *,
        target_registry_path: Path,
        target_runtime_root: Path,
        request: StateMigrationRequest,
        goal_ids: tuple[str, ...],
        execute: bool,
    ) -> Mapping[str, object]: ...

    def sync_goal(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreStateMigrationProvider:
    def goal_ids(self, registry_path: Path) -> tuple[str, ...]:
        return tuple(legacy_registry_goal_ids(registry_path))

    def migrate(
        self,
        *,
        target_registry_path: Path,
        target_runtime_root: Path,
        request: StateMigrationRequest,
        goal_ids: tuple[str, ...],
        execute: bool,
    ) -> Mapping[str, object]:
        return migrate_legacy_state(
            legacy_registry_path=request.legacy_registry,
            target_registry_path=target_registry_path,
            legacy_runtime_root=request.legacy_runtime_root,
            target_runtime_root=target_runtime_root,
            goal_ids=list(goal_ids),
            goal_id_map=dict(request.goal_id_map),
            path_map=dict(request.path_map),
            copy_active_state=request.copy_active_state,
            copy_runtime=request.copy_runtime,
            execute=execute,
        )

    def sync_goal(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
    ) -> Mapping[str, object]:
        return sync_project_registry_to_global(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            goal_id=goal_id,
            dry_run=False,
        )


@dataclass(frozen=True, slots=True)
class StateMigrationService:
    registry_path: Path
    runtime_root_override: str | None
    profile: Profile
    provider: StateMigrationProvider = CoreStateMigrationProvider()

    def preview(self, request: StateMigrationRequest) -> StateMigrationPlan:
        require_cli_authority(
            self.profile,
            operation_id=STATE_MIGRATION_PREVIEW_OPERATION,
        )
        if not isinstance(request, StateMigrationRequest):
            raise ValidationFailed(details={"field": "request"})
        goal_ids = self._selected_goal_ids(request)
        payload = self._migrate(request=request, goal_ids=goal_ids, execute=False)
        return _project_plan(request, payload)

    def apply(
        self,
        plan: StateMigrationPlan,
        *,
        write_context: WriteContext,
    ) -> StateMigrationResult:
        require_cli_authority(
            self.profile,
            operation_id=STATE_MIGRATION_APPLY_OPERATION,
        )
        if not isinstance(plan, StateMigrationPlan):
            raise ValidationFailed(details={"field": "plan"})
        validate_write_context(
            write_context,
            operation_id=STATE_MIGRATION_APPLY_OPERATION,
        )
        goal_ids = self._selected_goal_ids(plan.request)
        current_plan = _project_plan(
            plan.request,
            self._migrate(request=plan.request, goal_ids=goal_ids, execute=False),
        )
        require_matching_plan_hash(
            plan.plan_hash,
            current_plan.plan_hash,
            operation_id=STATE_MIGRATION_APPLY_OPERATION,
        )
        if not current_plan.can_apply:
            raise ValidationFailed(details={"field": "plan", "reason": "cannot_apply"})
        payload = self._migrate(request=plan.request, goal_ids=goal_ids, execute=True)
        applied_projection = _copy_projections(plan.request, payload)
        sync_results: list[Mapping[str, object]] = []
        if bool(payload.get("ok")) and plan.request.sync_global:
            for goal_id in _texts(payload.get("migrated_goal_ids")):
                sync_results.append(
                    self._sync_goal(request=plan.request, goal_id=goal_id)
                )
        sync_verified = (
            all(
                _required_bool(result.get("ok"), field="global_sync.ok")
                for result in sync_results
            )
            if plan.request.sync_global
            else True
        )
        wrote = _required_bool(
            payload.get("wrote_project_registry"), field="wrote_project_registry"
        )
        return StateMigrationResult(
            operation_id=STATE_MIGRATION_APPLY_OPERATION,
            plan_hash=plan.plan_hash,
            migrated_goal_ids=_texts(payload.get("migrated_goal_ids")),
            wrote_project_registry=wrote,
            active_state=applied_projection[0],
            runtime_goals=applied_projection[1],
            global_sync_attempted_count=len(sync_results),
            global_sync_verified=sync_verified,
            partial_global_sync=bool(wrote and plan.request.sync_global and not sync_verified),
        )

    def _selected_goal_ids(self, request: StateMigrationRequest) -> tuple[str, ...]:
        if not request.all_goals:
            return request.goal_ids
        try:
            return tuple(self.provider.goal_ids(request.legacy_registry))
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"operation_id": STATE_MIGRATION_PREVIEW_OPERATION}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "legacy_registry", "cause": type(exc).__name__}
            ) from exc

    def _target_runtime_root(self, request: StateMigrationRequest) -> Path:
        if request.target_runtime_root is not None:
            return request.target_runtime_root
        if self.runtime_root_override:
            return Path(self.runtime_root_override).expanduser()
        return DEFAULT_RUNTIME_ROOT

    def _migrate(
        self,
        *,
        request: StateMigrationRequest,
        goal_ids: tuple[str, ...],
        execute: bool,
    ) -> Mapping[str, object]:
        try:
            payload = self.provider.migrate(
                target_registry_path=self.registry_path,
                target_runtime_root=self._target_runtime_root(request),
                request=request,
                goal_ids=goal_ids,
                execute=execute,
            )
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"operation_id": STATE_MIGRATION_PREVIEW_OPERATION}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "state_migration", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise StateUnavailable(details={"resource": "state_migration"})
        return payload

    def _sync_goal(
        self,
        *,
        request: StateMigrationRequest,
        goal_id: str,
    ) -> Mapping[str, object]:
        try:
            payload = self.provider.sync_goal(
                registry_path=self.registry_path,
                runtime_root=self._target_runtime_root(request),
                goal_id=goal_id,
            )
        except (OSError, ValueError) as exc:
            return {"ok": False, "goal_id": goal_id, "error": str(exc)}
        if not isinstance(payload, Mapping):
            raise _invalid_payload("global_sync")
        return payload


def _project_plan(
    request: StateMigrationRequest,
    payload: Mapping[str, object],
) -> StateMigrationPlan:
    active_state, runtime_goals = _copy_projections(request, payload)
    projection = {
        "selected_goal_ids": _texts(payload.get("selected_goal_ids")),
        "migrated_goal_ids": _texts(payload.get("migrated_goal_ids")),
        "target_registry_goal_count": _required_int(
            payload.get("project_registry_goal_count"),
            field="project_registry_goal_count",
        ),
        "active_state": active_state,
        "runtime_goals": runtime_goals,
    }
    return StateMigrationPlan(
        operation_id=STATE_MIGRATION_PREVIEW_OPERATION,
        plan_hash=semantic_hash(
            operation_id=STATE_MIGRATION_PREVIEW_OPERATION,
            request=request,
            projection=projection,
        ),
        request=request,
        can_apply=_required_bool(payload.get("ok"), field="ok"),
        selected_goal_ids=projection["selected_goal_ids"],
        migrated_goal_ids=projection["migrated_goal_ids"],
        target_registry_goal_count=projection["target_registry_goal_count"],
        active_state=active_state,
        runtime_goals=runtime_goals,
    )


def _copy_projections(
    request: StateMigrationRequest,
    payload: Mapping[str, object],
) -> tuple[MigrationCopyProjection, MigrationCopyProjection]:
    active_rows = _rows(payload.get("active_state"))
    runtime_rows = _rows(payload.get("runtime_goals"))
    return (
        MigrationCopyProjection(
            selected_count=len(active_rows),
            copy_requested=request.copy_active_state,
            copied_count=sum(
                _required_bool(row.get("copied"), field="active_state.copied")
                for row in active_rows
            ),
            skipped_count=sum(bool(row.get("skipped_reason")) for row in active_rows),
        ),
        MigrationCopyProjection(
            selected_count=len(runtime_rows),
            copy_requested=request.copy_runtime,
            copied_count=sum(
                _required_bool(row.get("copied"), field="runtime_goals.copied")
                for row in runtime_rows
            ),
            skipped_count=sum(bool(row.get("skipped_reason")) for row in runtime_rows),
        ),
    )


def parse_mapping_entries(values: tuple[str, ...], *, field: str) -> Mapping[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        key, separator, replacement = str(value).partition("=")
        key = key.strip()
        replacement = replacement.strip()
        if not separator or not key or not replacement:
            raise ValidationFailed(details={"field": field, "value": str(value)})
        if key in parsed:
            raise ValidationFailed(
                details={"field": field, "value": key, "reason": "duplicate"}
            )
        parsed[key] = replacement
    return MappingProxyType(parsed)


def _mapping(value: Mapping[str, str], *, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValidationFailed(details={"field": field})
    return MappingProxyType(
        {
            _text(key, field=field): _text(item, field=field)
            for key, item in value.items()
        }
    )


def _rows(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise _invalid_payload("copy_rows")
    return tuple(value)  # type: ignore[return-value]


def _texts(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise _invalid_payload("goal_ids")
    texts = tuple(str(item or "").strip() for item in value)
    if any(not item for item in texts):
        raise _invalid_payload("goal_ids")
    return texts


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


def _required_bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid_payload(field)
    return value


def _text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationFailed(details={"field": field})
    return text


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "state_migration",
            "cause": "invalid_payload",
            "field": field,
        }
    )
