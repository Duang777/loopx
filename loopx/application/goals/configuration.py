"""Typed goal-configuration preview and apply use cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping

from loopx.control_plane.goals.configure_goal_service import (
    configure_goal_with_global_sync,
)
from ..errors import (
    AuthorityDenied,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from ..contracts import WriteCorrectness
from .routing import resolve_canonical_goal_route

if TYPE_CHECKING:
    from ..context import ApplicationContext
    from ..contracts import WriteContext


_OPTIONAL_BOOLEAN_FIELDS = (
    "self_repair_enabled",
    "self_repair_health",
    "self_repair_waiting_projection",
    "change_quality_enabled",
    "change_quality_safe_fix",
    "change_quality_strict_receipt",
    "spawn_allowed",
    "explore_harness_enabled",
    "explore_graph_enabled",
    "lark_kanban_heartbeat_sync",
)
_BOOLEAN_FLAG_FIELDS = (
    "clear_allowed_domains",
    "clear_explore_harness_profile",
    "clear_registered_agents",
    "clear_supervisor",
    "replace_write_scope",
    "clear_write_scope",
    "clear_waiting_on",
    "clear_boundary_authority",
    "clear_issue_fix_reviewer_notification_config",
    "clear_lark_event_inbox_config",
    "clear_reward_memory_config",
)
_OPTIONAL_TEXT_FIELDS = (
    "multi_subagent_feature",
    "orchestration_mode",
    "explore_harness_profile",
    "agent_model",
    "automation_prompt_migration_ack",
    "supervisor_agent",
    "waiting_on",
    "boundary_authority_source",
    "boundary_authority_decision_id",
    "boundary_authority_recorded_at",
    "boundary_authority_expires_at",
    "issue_fix_reviewer_notification_config",
    "lark_event_inbox_config",
    "reward_memory_config",
)
_TEXT_SEQUENCE_FIELDS = (
    "allowed_domains",
    "registered_agents",
    "clear_agent_profiles",
    "clear_agent_work_modes",
    "clear_todo_lifecycle_authority",
    "supervised_agents",
    "write_scope",
    "boundary_authority_scopes",
    "reward_memory_agents",
)
_MAPPING_SEQUENCE_FIELDS = ("agent_profiles", "todo_lifecycle_authority")


@dataclass(frozen=True, slots=True)
class GoalConfigurationPatch:
    """Transport-neutral form of the shipped ``configure-goal`` inputs."""

    quota_compute: float | None = None
    quota_window_hours: float | None = None
    self_repair_enabled: bool | None = None
    self_repair_health: bool | None = None
    self_repair_waiting_projection: bool | None = None
    change_quality_enabled: bool | None = None
    change_quality_safe_fix: bool | None = None
    change_quality_strict_receipt: bool | None = None
    multi_subagent_feature: str | None = None
    orchestration_mode: str | None = None
    spawn_allowed: bool | None = None
    max_children: int | None = None
    allowed_domains: tuple[str, ...] | None = None
    clear_allowed_domains: bool = False
    explore_harness_enabled: bool | None = None
    explore_harness_profile: str | None = None
    clear_explore_harness_profile: bool = False
    explore_graph_enabled: bool | None = None
    registered_agents: tuple[str, ...] | None = None
    clear_registered_agents: bool = False
    agent_profiles: tuple[Mapping[str, Any], ...] | None = None
    clear_agent_profiles: tuple[str, ...] | None = None
    agent_work_modes: Mapping[str, str] | None = None
    clear_agent_work_modes: tuple[str, ...] | None = None
    todo_lifecycle_authority: tuple[Mapping[str, Any], ...] | None = None
    clear_todo_lifecycle_authority: tuple[str, ...] | None = None
    agent_model: str | None = None
    automation_prompt_migration_ack: str | None = None
    supervisor_agent: str | None = None
    supervised_agents: tuple[str, ...] | None = None
    clear_supervisor: bool = False
    write_scope: tuple[str, ...] | None = None
    replace_write_scope: bool = False
    clear_write_scope: bool = False
    waiting_on: str | None = None
    clear_waiting_on: bool = False
    boundary_authority_scopes: tuple[str, ...] | None = None
    boundary_authority_source: str | None = None
    boundary_authority_decision_id: str | None = None
    boundary_authority_recorded_at: str | None = None
    boundary_authority_expires_at: str | None = None
    clear_boundary_authority: bool = False
    issue_fix_reviewer_notification_config: str | None = None
    clear_issue_fix_reviewer_notification_config: bool = False
    lark_event_inbox_config: str | None = None
    clear_lark_event_inbox_config: bool = False
    lark_kanban_heartbeat_sync: bool | None = None
    reward_memory_config: str | None = None
    reward_memory_agents: tuple[str, ...] | None = None
    clear_reward_memory_config: bool = False

    def __post_init__(self) -> None:
        for name in ("quota_compute", "quota_window_hours"):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValidationFailed(details={"field": name})
            object.__setattr__(self, name, float(value))
        if self.max_children is not None and (
            isinstance(self.max_children, bool)
            or not isinstance(self.max_children, int)
        ):
            raise ValidationFailed(details={"field": "max_children"})
        for name in _OPTIONAL_BOOLEAN_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValidationFailed(details={"field": name})
        for name in _BOOLEAN_FLAG_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise ValidationFailed(details={"field": name})
        for name in _OPTIONAL_TEXT_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValidationFailed(details={"field": name})
            object.__setattr__(self, name, value.strip())
        for name in _TEXT_SEQUENCE_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, (str, bytes)):
                raise ValidationFailed(details={"field": name})
            try:
                normalized = tuple(_required_text(item, field=name) for item in value)
            except TypeError as exc:
                raise ValidationFailed(details={"field": name}) from exc
            object.__setattr__(self, name, normalized)
        for name in _MAPPING_SEQUENCE_FIELDS:
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, (str, bytes)):
                raise ValidationFailed(details={"field": name})
            try:
                normalized_mappings = tuple(
                    _frozen_mapping(item, field=name) for item in value
                )
            except TypeError as exc:
                raise ValidationFailed(details={"field": name}) from exc
            object.__setattr__(self, name, normalized_mappings)
        if self.agent_work_modes is not None:
            if not isinstance(self.agent_work_modes, Mapping):
                raise ValidationFailed(details={"field": "agent_work_modes"})
            object.__setattr__(
                self,
                "agent_work_modes",
                MappingProxyType(
                    {
                        _required_text(key, field="agent_work_modes"): _required_text(
                            value,
                            field="agent_work_modes",
                        )
                        for key, value in self.agent_work_modes.items()
                    }
                ),
            )

    def core_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {}
        for descriptor in fields(self):
            name = descriptor.name
            value = getattr(self, name)
            if isinstance(value, bool) and name.startswith(("clear_", "replace_")):
                if value:
                    options[name] = True
                continue
            if value is not None:
                options[name] = _thaw(value)
        return options


@dataclass(frozen=True, slots=True)
class ConfigurationEffect:
    field: str
    before: object
    after: object


WriterCorrectness = WriteCorrectness


PENDING_CONFIGURE_WRITER_CORRECTNESS = WriteCorrectness(
    status="pending_migration",
    atomic_revision_check=False,
    idempotent_retry=False,
)


@dataclass(frozen=True, slots=True)
class ConfigurationPlan:
    goal_id: str
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    changed: bool
    effects: tuple[ConfigurationEffect, ...]
    warnings: tuple[str, ...]
    correctness: WriteCorrectness = PENDING_CONFIGURE_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class ConfigurationApplyResult:
    goal_id: str
    generated_at: str
    previous_revision: str
    revision: str
    plan_hash: str
    changed: bool
    written: bool
    global_sync_verified: bool
    correctness: WriteCorrectness = PENDING_CONFIGURE_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class GoalConfigurationService:
    """A lightweight service that re-resolves canonical state per operation."""

    context: ApplicationContext
    goal_id: str

    def preview(self, patch: GoalConfigurationPatch) -> ConfigurationPlan:
        if not isinstance(patch, GoalConfigurationPatch):
            raise ValidationFailed(details={"field": "patch"})
        if not self.context.writes_available:
            raise AuthorityDenied(
                details={
                    "operation_id": "goal.configuration.preview",
                    "profile": self.context.profile.value,
                }
            )
        source_registry, revision = _configuration_source(
            context=self.context,
            goal_id=self.goal_id,
        )
        payload = _configure(
            registry_path=source_registry,
            goal_id=self.goal_id,
            runtime_root_override=self.context.runtime_root_override,
            execute=False,
            options=patch.core_options(),
        )
        effects = _effects(payload)
        changed = bool(payload.get("changed"))
        can_apply = bool(payload.get("ok", True))
        warnings = [
            "configure writer atomic revision checks and idempotent retry are pending migration"
        ]
        if not changed:
            warnings.append("configuration already matches the requested patch")
        plan_hash = _plan_hash(
            goal_id=self.goal_id,
            revision=revision,
            patch=patch,
            effects=effects,
        )
        return ConfigurationPlan(
            goal_id=self.goal_id,
            generated_at=_generated_at(self.context),
            revision=revision,
            plan_hash=plan_hash,
            can_apply=can_apply,
            changed=changed,
            effects=effects,
            warnings=tuple(warnings),
        )

    def apply(
        self,
        patch: GoalConfigurationPatch,
        *,
        plan_hash: str,
        write_context: WriteContext,
    ) -> ConfigurationApplyResult:
        from ..contracts import WriteContext

        if not isinstance(patch, GoalConfigurationPatch):
            raise ValidationFailed(details={"field": "patch"})
        if not isinstance(write_context, WriteContext):
            raise ValidationFailed(details={"field": "write_context"})
        if not self.context.writes_available:
            raise AuthorityDenied(
                details={
                    "operation_id": "goal.configuration.apply",
                    "profile": self.context.profile.value,
                }
            )
        supplied_plan_hash = str(plan_hash or "").strip()
        if not supplied_plan_hash:
            raise ValidationFailed(details={"field": "plan_hash"})
        if write_context.expected_revision is None:
            raise ValidationFailed(details={"field": "write_context.expected_revision"})

        current_plan = self.preview(patch)
        if write_context.expected_revision != current_plan.revision:
            raise RevisionConflict(
                details={
                    "goal_id": self.goal_id,
                    "expected_revision": write_context.expected_revision,
                    "current_revision": current_plan.revision,
                }
            )
        if supplied_plan_hash != current_plan.plan_hash:
            raise RevisionConflict(
                details={
                    "goal_id": self.goal_id,
                    "reason": "plan_hash_mismatch",
                    "expected_plan_hash": supplied_plan_hash,
                    "current_plan_hash": current_plan.plan_hash,
                }
            )
        if not current_plan.can_apply:
            raise ValidationFailed(details={"field": "plan", "reason": "gated"})

        source_registry, checked_revision = _configuration_source(
            context=self.context,
            goal_id=self.goal_id,
        )
        if checked_revision != current_plan.revision:
            raise RevisionConflict(
                details={
                    "goal_id": self.goal_id,
                    "expected_revision": current_plan.revision,
                    "current_revision": checked_revision,
                }
            )
        payload = _configure(
            registry_path=source_registry,
            goal_id=self.goal_id,
            runtime_root_override=self.context.runtime_root_override,
            execute=True,
            options=patch.core_options(),
        )
        global_sync = payload.get("global_sync")
        global_sync_verified = bool(
            isinstance(global_sync, dict)
            and isinstance(global_sync.get("readback"), dict)
            and global_sync["readback"].get("verified")
        )
        if not payload.get("ok", True) or payload.get("partial_write"):
            _, current_revision = _configuration_source(
                context=self.context,
                goal_id=self.goal_id,
            )
            raise StateUnavailable(
                details={
                    "resource": "goal_configuration",
                    "goal_id": self.goal_id,
                    "partial_write": bool(payload.get("partial_write")),
                    "current_revision": current_revision,
                    "global_sync_status": _global_sync_status(global_sync),
                    "recovery_action": "sync_global",
                }
            )
        _, new_revision = _configuration_source(
            context=self.context,
            goal_id=self.goal_id,
        )
        return ConfigurationApplyResult(
            goal_id=self.goal_id,
            generated_at=_generated_at(self.context),
            previous_revision=current_plan.revision,
            revision=new_revision,
            plan_hash=current_plan.plan_hash,
            changed=bool(payload.get("changed")),
            written=bool(payload.get("written")),
            global_sync_verified=global_sync_verified,
        )


def _configuration_source(
    *,
    context: ApplicationContext,
    goal_id: str,
) -> tuple[Path, str]:
    route = resolve_canonical_goal_route(context=context, goal_id=goal_id)
    return route.registry_path, route.goal_revision


def _configure(
    *,
    registry_path: Path,
    goal_id: str,
    runtime_root_override: str | None,
    execute: bool,
    options: dict[str, Any],
) -> dict[str, Any]:
    try:
        payload = configure_goal_with_global_sync(
            registry_path=registry_path,
            goal_id=goal_id,
            runtime_root_override=runtime_root_override,
            execute=execute,
            **options,
        )
    except FileNotFoundError as exc:
        raise StateUnavailable(
            details={"resource": "goal_configuration", "goal_id": goal_id}
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(details={"operation_id": "goal.configuration"}) from exc
    if not isinstance(payload, dict):
        raise StateUnavailable(
            details={"resource": "goal_configuration", "cause": "invalid_payload"}
        )
    return payload


def _effects(payload: Mapping[str, Any]) -> tuple[ConfigurationEffect, ...]:
    before = payload.get("before") if isinstance(payload.get("before"), dict) else {}
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    return tuple(
        ConfigurationEffect(
            field=str(field),
            before=_freeze(before.get(field)),
            after=_freeze(after.get(field)),
        )
        for field in payload.get("changed_fields") or ()
    )


def _plan_hash(
    *,
    goal_id: str,
    revision: str,
    patch: GoalConfigurationPatch,
    effects: tuple[ConfigurationEffect, ...],
) -> str:
    seed = {
        "goal_id": goal_id,
        "revision": revision,
        "options": patch.core_options(),
        "effects": [
            {
                "field": effect.field,
                "before": _thaw(effect.before),
                "after": _thaw(effect.after),
            }
            for effect in effects
        ],
    }
    digest = hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _generated_at(context: ApplicationContext) -> str:
    value = context.clock()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    generated_at = str(value or "").strip()
    if not generated_at:
        raise StateUnavailable(details={"resource": "clock", "cause": "invalid_value"})
    return generated_at


def _global_sync_status(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unavailable"
    readback = value.get("readback")
    if isinstance(readback, Mapping):
        status = str(readback.get("status") or "").strip()
        if status:
            return status
    return "failed"


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value.strip()


def _frozen_mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValidationFailed(details={"field": field})
    frozen = _freeze(value)
    if not isinstance(frozen, Mapping):
        raise ValidationFailed(details={"field": field})
    return frozen


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
