"""Typed read model for managed local upgrade propagation planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from loopx.upgrade import build_upgrade_plan

from ..contracts import Profile, application_public_safe_text
from ..errors import StateUnavailable, ValidationFailed
from ._planning import require_cli_authority


UPGRADE_PLAN_OPERATION = "application.system.upgrades.plan"


@dataclass(frozen=True, slots=True)
class UpgradePlanRequest:
    goal_ids: tuple[str, ...] = ()
    installed_manifest: Path | None = None
    cli_bin: str = "loopx"
    modes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        goal_ids = tuple(_text(item, field="goal_ids") for item in self.goal_ids)
        modes = tuple(_text(item, field="modes") for item in self.modes)
        if any(mode not in {"thin", "brief", "compact"} for mode in modes):
            raise ValidationFailed(details={"field": "modes"})
        object.__setattr__(self, "goal_ids", goal_ids)
        object.__setattr__(self, "modes", modes)
        object.__setattr__(self, "cli_bin", _text(self.cli_bin, field="cli_bin"))
        if self.installed_manifest is not None:
            object.__setattr__(
                self,
                "installed_manifest",
                Path(self.installed_manifest).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class ManagedHeartbeatUpgrade:
    goal_id: str
    requires_update: bool
    registered_agent_count: int
    host_loop_status: str
    peer_runtime_migration_required: bool


@dataclass(frozen=True, slots=True)
class UpgradePlanResult:
    operation_id: str
    managed_goal_count: int
    current_prompt_count: int
    stale_prompt_count: int
    unknown_prompt_count: int
    not_installed_prompt_count: int
    stage_deferred_goal_count: int
    installed_manifest_available: bool
    installed_manifest_entry_count: int
    policy_warning_count: int
    host_loop_missing_goal_count: int
    peer_runtime_migration_count: int
    ready_for_default_promotion: bool
    managed_goals: tuple[ManagedHeartbeatUpgrade, ...]
    recommended_action: str | None


class UpgradePlanProvider(Protocol):
    def build(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: UpgradePlanRequest,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class CoreUpgradePlanProvider:
    def build(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: UpgradePlanRequest,
    ) -> Mapping[str, object]:
        return build_upgrade_plan(
            registry_path=registry_path,
            runtime_root_override=runtime_root_override,
            installed_manifest=request.installed_manifest,
            cli_bin=request.cli_bin,
            modes=request.modes or None,
            goal_ids=request.goal_ids or None,
        )


@dataclass(frozen=True, slots=True)
class UpgradePlanService:
    registry_path: Path
    runtime_root_override: str | None
    profile: Profile
    provider: UpgradePlanProvider = CoreUpgradePlanProvider()

    def plan(self, request: UpgradePlanRequest) -> UpgradePlanResult:
        require_cli_authority(self.profile, operation_id=UPGRADE_PLAN_OPERATION)
        if not isinstance(request, UpgradePlanRequest):
            raise ValidationFailed(details={"field": "request"})
        try:
            payload = self.provider.build(
                registry_path=self.registry_path,
                runtime_root_override=self.runtime_root_override,
                request=request,
            )
        except ValueError as exc:
            raise ValidationFailed(
                str(exc), details={"operation_id": UPGRADE_PLAN_OPERATION}
            ) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "upgrade_plan", "cause": type(exc).__name__}
            ) from exc
        if not isinstance(payload, Mapping) or payload.get("ok") is not True:
            raise StateUnavailable(details={"resource": "upgrade_plan"})
        return _project_result(payload)


def _project_result(payload: Mapping[str, object]) -> UpgradePlanResult:
    raw_summary = payload.get("summary")
    if not isinstance(raw_summary, Mapping):
        raise _invalid_payload("summary")
    summary = raw_summary
    raw_goals = payload.get("managed_heartbeats")
    goal_rows = _mapping_rows(raw_goals, field="managed_heartbeats")
    managed_goals = tuple(_managed_goal(item) for item in goal_rows)
    return UpgradePlanResult(
        operation_id=UPGRADE_PLAN_OPERATION,
        managed_goal_count=_required_int(
            summary.get("managed_goal_count"), field="summary.managed_goal_count"
        ),
        current_prompt_count=_required_int(
            summary.get("current_prompt_count"), field="summary.current_prompt_count"
        ),
        stale_prompt_count=_required_int(
            summary.get("stale_prompt_count"), field="summary.stale_prompt_count"
        ),
        unknown_prompt_count=_required_int(
            summary.get("unknown_prompt_count"), field="summary.unknown_prompt_count"
        ),
        not_installed_prompt_count=_required_int(
            summary.get("not_installed_prompt_count"),
            field="summary.not_installed_prompt_count",
        ),
        stage_deferred_goal_count=_required_int(
            summary.get("stage_deferred_goal_count"),
            field="summary.stage_deferred_goal_count",
        ),
        installed_manifest_available=_required_bool(
            summary.get("installed_manifest_available"),
            field="summary.installed_manifest_available",
        ),
        installed_manifest_entry_count=_required_int(
            summary.get("installed_manifest_entry_count"),
            field="summary.installed_manifest_entry_count",
        ),
        policy_warning_count=_required_int(
            summary.get("installed_prompt_policy_warning_count"),
            field="summary.installed_prompt_policy_warning_count",
        ),
        host_loop_missing_goal_count=_required_int(
            summary.get("host_loop_missing_goal_count"),
            field="summary.host_loop_missing_goal_count",
        ),
        peer_runtime_migration_count=_required_int(
            summary.get("peer_runtime_automation_migration_count"),
            field="summary.peer_runtime_automation_migration_count",
        ),
        ready_for_default_promotion=_required_bool(
            summary.get("ready_for_default_promotion"),
            field="summary.ready_for_default_promotion",
        ),
        managed_goals=managed_goals,
        recommended_action=application_public_safe_text(
            payload.get("recommended_action"), limit=1000
        ),
    )


def _managed_goal(value: Mapping[str, object]) -> ManagedHeartbeatUpgrade:
    agents = value.get("registered_agents")
    activation = value.get("host_loop_activation")
    migration = value.get("peer_runtime_automation_migration")
    if not isinstance(agents, (list, tuple)):
        raise _invalid_payload("managed_heartbeats.registered_agents")
    if not isinstance(activation, Mapping):
        raise _invalid_payload("managed_heartbeats.host_loop_activation")
    if not isinstance(migration, Mapping):
        raise _invalid_payload(
            "managed_heartbeats.peer_runtime_automation_migration"
        )
    return ManagedHeartbeatUpgrade(
        goal_id=_text(value.get("goal_id"), field="goal_id"),
        requires_update=_required_bool(
            value.get("requires_update"), field="managed_heartbeats.requires_update"
        ),
        registered_agent_count=len(agents),
        host_loop_status=_text(
            activation.get("status"), field="host_loop_activation.status"
        ),
        peer_runtime_migration_required=_required_bool(
            migration.get("required"),
            field="peer_runtime_automation_migration.required",
        ),
    )


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


def _invalid_payload(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "upgrade_plan",
            "cause": "invalid_payload",
            "field": field,
        }
    )


def _text(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationFailed(details={"field": field})
    return text
