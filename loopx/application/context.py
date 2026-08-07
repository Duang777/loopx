from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)
from ..history import load_registry
from .contracts import Profile
from .errors import ValidationFailed
from .goals.turns import TurnCommitCoordinator, TurnEnvelopeSource, TurnExecutor


class Clock(Protocol):
    def __call__(self) -> datetime | str: ...


class RegistryLoader(Protocol):
    def __call__(self, path: Path) -> dict[str, Any]: ...


class GoalRouteResolver(Protocol):
    def __call__(
        self,
        *,
        registry_path: Path,
        goal_id: str,
        runtime_root_override: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    registry_path: Path
    runtime_root_override: str | None = None
    profile: Profile = Profile.CLI
    clock: Clock = utc_now
    scan_roots: tuple[Path, ...] = ()
    turn_envelope_source: TurnEnvelopeSource | None = None
    turn_executor: TurnExecutor | None = None
    turn_commit_coordinator: TurnCommitCoordinator | None = None
    load_registry: RegistryLoader = load_registry
    resolve_goal_route: GoalRouteResolver = resolve_goal_source_runtime_route

    def __post_init__(self) -> None:
        registry_path = Path(self.registry_path).expanduser()
        runtime_root_override = (
            self.runtime_root_override.strip()
            if self.runtime_root_override is not None
            else None
        )
        if self.runtime_root_override is not None and not runtime_root_override:
            raise ValidationFailed(details={"field": "runtime_root_override"})
        if not isinstance(self.profile, Profile):
            raise ValidationFailed(details={"field": "profile"})
        if not callable(self.clock):
            raise ValidationFailed(details={"field": "clock"})
        scan_roots = tuple(Path(path).expanduser() for path in self.scan_roots)
        _validate_provider(
            self.turn_envelope_source,
            field="turn_envelope_source",
            method="load_turn_envelope",
        )
        _validate_provider(
            self.turn_executor,
            field="turn_executor",
            method="execute",
        )
        for method in ("validate_task", "writeback", "spend", "schedule"):
            _validate_provider(
                self.turn_commit_coordinator,
                field="turn_commit_coordinator",
                method=method,
            )
        if not callable(self.load_registry):
            raise ValidationFailed(details={"field": "load_registry"})
        if not callable(self.resolve_goal_route):
            raise ValidationFailed(details={"field": "resolve_goal_route"})
        object.__setattr__(self, "registry_path", registry_path)
        object.__setattr__(self, "runtime_root_override", runtime_root_override)
        object.__setattr__(self, "scan_roots", scan_roots)

    @property
    def writes_available(self) -> bool:
        return self.profile.allows_writes

    @property
    def executor_available(self) -> bool:
        return self.turn_executor is not None

    @property
    def execution_available(self) -> bool:
        return bool(
            self.profile.allows_execution
            and self.turn_envelope_source is not None
            and self.turn_executor is not None
            and self.turn_commit_coordinator is not None
        )


def _validate_provider(value: object, *, field: str, method: str) -> None:
    if value is not None and not callable(getattr(value, method, None)):
        raise ValidationFailed(details={"field": field, "method": method})
