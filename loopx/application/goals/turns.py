"""Transport-neutral planning and execution for one bounded LoopX Turn."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from loopx.control_plane.todos.contract import (
    normalize_todo_claimed_by,
    normalize_todo_id,
)
from loopx.control_plane.turn_driver import (
    LOOPX_TURN_RESULT_SCHEMA_VERSION,
    LoopXTurnResultKind,
    build_loopx_turn_plan,
    load_loopx_turn_plan_from_journal,
    run_loopx_turn_once,
)
from loopx.control_plane.turn_driver.executor import turn_journal_path
from loopx.control_plane.turn_driver.transaction import TRANSACTION_PHASES
from loopx.turn_identity import normalize_turn_instance_id

from ..contracts import WriteContext, WriteCorrectness, application_public_safe_text
from ..errors import (
    ApplicationError,
    AuthorityDenied,
    CapabilityUnavailable,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from .routing import effective_runtime_root, resolve_canonical_goal_route

if TYPE_CHECKING:
    from ..context import ApplicationContext


class TurnHost(str, Enum):
    CODEX_CLI = "codex-cli"
    CLAUDE_CODE = "claude-code"
    GENERIC_CLI = "generic-cli"


class TurnExecutionMode(str, Enum):
    INTERACTIVE_VISIBLE = "interactive-visible"
    ISOLATED_HEADLESS = "isolated-headless"


_TURN_KEY_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_RESULT_TEXT_LIMITS = {
    "classification": 120,
    "recommended_action": 1_200,
    "next_action": 1_200,
    "delivery_batch_scale": 120,
    "delivery_outcome": 120,
    "vision_unchanged_reason": 240,
    "path_delta_mode": 80,
    "agent_vision_json": 3_200,
    "summary": 400,
}

TURN_WRITE_CORRECTNESS = WriteCorrectness(
    status="core_turn_journal_v0",
    atomic_revision_check=False,
    idempotent_retry=True,
)


@dataclass(frozen=True, slots=True)
class TurnPlanRequest:
    """Caller-selected Turn identity, never a command or argv payload."""

    agent_id: str
    turn_instance_id: str
    host: TurnHost
    execution_mode: TurnExecutionMode
    scheduler_owner: str | None = None
    session_binding: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        agent_id = normalize_todo_claimed_by(self.agent_id)
        if not agent_id:
            raise ValidationFailed(details={"field": "agent_id"})
        try:
            turn_instance_id = normalize_turn_instance_id(self.turn_instance_id)
        except ValueError as exc:
            raise ValidationFailed(details={"field": "turn_instance_id"}) from exc
        if turn_instance_id is None:
            raise ValidationFailed(details={"field": "turn_instance_id"})
        if not isinstance(self.host, TurnHost):
            raise ValidationFailed(details={"field": "host"})
        if not isinstance(self.execution_mode, TurnExecutionMode):
            raise ValidationFailed(details={"field": "execution_mode"})
        scheduler_owner = (
            self.scheduler_owner.strip() if self.scheduler_owner is not None else None
        )
        if self.scheduler_owner is not None and not scheduler_owner:
            raise ValidationFailed(details={"field": "scheduler_owner"})
        if self.session_binding is not None and not isinstance(
            self.session_binding, Mapping
        ):
            raise ValidationFailed(details={"field": "session_binding"})
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "turn_instance_id", turn_instance_id)
        object.__setattr__(self, "scheduler_owner", scheduler_owner)
        if self.session_binding is not None:
            try:
                session_binding = _freeze_json(self.session_binding)
            except (TypeError, ValueError) as exc:
                raise ValidationFailed(
                    details={
                        "field": "session_binding",
                        "reason": "not_json_compatible",
                    }
                ) from exc
            object.__setattr__(self, "session_binding", session_binding)

    def identity(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "turn_instance_id": self.turn_instance_id,
            "host": self.host.value,
            "execution_mode": self.execution_mode.value,
            "scheduler_owner": self.scheduler_owner,
            "session_binding": _thaw(self.session_binding),
        }


@dataclass(frozen=True, slots=True)
class TurnHostRequest:
    """One bounded, path-free request for a future executor provider."""

    turn_key: str
    route: str
    session: Mapping[str, object]
    turn_envelope: Mapping[str, object]
    result_contract: Mapping[str, object]
    child_operations: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        for field in ("turn_key", "route"):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field=field),
            )
        for field in ("session", "turn_envelope", "result_contract"):
            value = getattr(self, field)
            if not isinstance(value, Mapping):
                raise ValidationFailed(details={"field": field})
            try:
                frozen = _freeze_json(value)
            except (TypeError, ValueError) as exc:
                raise ValidationFailed(
                    details={"field": field, "reason": "not_json_compatible"}
                ) from exc
            object.__setattr__(self, field, frozen)
        if isinstance(self.child_operations, (str, bytes, Mapping)):
            raise ValidationFailed(details={"field": "child_operations"})
        children: list[Mapping[str, object]] = []
        for child in self.child_operations:
            if not isinstance(child, Mapping):
                raise ValidationFailed(details={"field": "child_operations"})
            try:
                frozen_child = _freeze_json(child)
            except (TypeError, ValueError) as exc:
                raise ValidationFailed(
                    details={
                        "field": "child_operations",
                        "reason": "not_json_compatible",
                    }
                ) from exc
            children.append(frozen_child)
        object.__setattr__(self, "child_operations", tuple(children))


@dataclass(frozen=True, slots=True)
class TurnHostResult:
    """Constrained public result returned by a future executor provider."""

    turn_key: str
    result_kind: str
    classification: str | None = None
    recommended_action: str | None = None
    next_action: str | None = None
    delivery_batch_scale: str | None = None
    delivery_outcome: str | None = None
    vision_unchanged_reason: str | None = None
    path_delta_mode: str | None = None
    agent_vision_json: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        turn_key = _required_text(self.turn_key, field="turn_key")
        if _TURN_KEY_PATTERN.fullmatch(turn_key) is None:
            raise ValidationFailed(details={"field": "turn_key"})
        try:
            result_kind = LoopXTurnResultKind(
                _required_text(self.result_kind, field="result_kind")
            ).value
        except ValueError as exc:
            raise ValidationFailed(details={"field": "result_kind"}) from exc
        object.__setattr__(self, "turn_key", turn_key)
        object.__setattr__(self, "result_kind", result_kind)
        for field in (
            "classification",
            "recommended_action",
            "next_action",
            "delivery_batch_scale",
            "delivery_outcome",
            "vision_unchanged_reason",
            "path_delta_mode",
            "agent_vision_json",
            "summary",
        ):
            value = getattr(self, field)
            if value is None:
                continue
            object.__setattr__(
                self,
                field,
                _public_optional_text(
                    value,
                    field=field,
                    limit=_RESULT_TEXT_LIMITS[field],
                ),
            )


@runtime_checkable
class TurnExecutor(Protocol):
    """Provider port: execute exactly one bounded host request."""

    def execute(self, request: TurnHostRequest) -> TurnHostResult: ...


@runtime_checkable
class TurnCommitCoordinator(Protocol):
    """Application-owned transaction callbacks; never executor authority."""

    def validate_task(
        self,
        plan: TurnPlan,
        result: TurnHostResult,
    ) -> Mapping[str, object]: ...

    def writeback(self, result: TurnHostResult) -> Mapping[str, object]: ...

    def spend(self, plan: TurnPlan) -> Mapping[str, object]: ...

    def schedule(
        self,
        plan: TurnPlan,
        spend: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class TurnEnvelopeSource(Protocol):
    """Application-owned source for a fresh Core TurnEnvelope."""

    def load_turn_envelope(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
        agent_id: str,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TurnPlan:
    goal_id: str
    agent_id: str
    generated_at: str
    revision: str
    plan_hash: str
    route: str
    canonical_route_status: str
    routed_to_source_registry: bool
    core_contract_valid: bool
    would_invoke_host: bool
    can_run: bool
    execution_authorized: bool
    executor_available: bool
    commit_coordinator_available: bool
    turn_key: str
    selected_todo_id: str | None
    unavailable_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TurnExecutionEffects:
    host_invoked: bool
    state_written: bool
    quota_spent: bool
    scheduler_acknowledged: bool


@dataclass(frozen=True, slots=True)
class TurnTaskValidation:
    status: str
    validator_kind: str
    summary: str
    recovery_kind: str | None
    exit_code: int | None


@dataclass(frozen=True, slots=True)
class TurnReceipt:
    status: str
    result_kind: str | None
    completed_phases: tuple[str, ...]
    failed_phase: str | None
    next_phase: str | None


@dataclass(frozen=True, slots=True)
class TurnSchedulerResult:
    disposition: str
    completed: bool
    acknowledged: bool
    apply_needed: bool


@dataclass(frozen=True, slots=True)
class TurnExecutionResult:
    goal_id: str
    agent_id: str
    generated_at: str
    revision: str
    plan_hash: str
    turn_key: str
    ok: bool
    status: str
    result_kind: str | None
    dry_run: bool
    replayed: bool
    journal_ref: str
    execution_mode: str
    effects: TurnExecutionEffects
    validation: TurnTaskValidation | None
    receipt: TurnReceipt | None
    scheduler: TurnSchedulerResult | None
    quota_slot_spend_count: int
    reason: str | None
    correctness: WriteCorrectness = TURN_WRITE_CORRECTNESS


@dataclass(frozen=True, slots=True)
class _PreparedTurn:
    plan: TurnPlan
    core_plan: dict[str, Any]
    runtime_root: Path
    project: Path


@dataclass(frozen=True, slots=True)
class GoalTurnService:
    """Plan and execute a Turn through the shipped Core transaction seam."""

    context: ApplicationContext
    goal_id: str
    envelope_source: TurnEnvelopeSource | None = None
    executor: TurnExecutor | None = None
    commit_coordinator: TurnCommitCoordinator | None = None

    def __post_init__(self) -> None:
        _provider_method(
            self.envelope_source,
            field="envelope_source",
            method="load_turn_envelope",
        )
        _provider_method(self.executor, field="executor", method="execute")
        for method in ("validate_task", "writeback", "spend", "schedule"):
            _provider_method(
                self.commit_coordinator,
                field="commit_coordinator",
                method=method,
            )

    def plan(self, request: TurnPlanRequest) -> TurnPlan:
        return self._prepare(request).plan

    def run_once(
        self,
        plan: TurnPlan,
        *,
        request: TurnPlanRequest,
        write_context: WriteContext,
        execute: bool,
        retry_failed: bool = False,
    ) -> TurnExecutionResult:
        """Preview or execute one journaled Turn without exposing host commands."""

        _validate_run_request(
            service=self,
            plan=plan,
            request=request,
            write_context=write_context,
            execute=execute,
            retry_failed=retry_failed,
        )
        if execute:
            _require_execution_providers(self)
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        runtime_root = effective_runtime_root(self.context, route)
        prepared: _PreparedTurn | None = None
        core_plan: dict[str, Any]
        canonical_plan = plan

        if execute:
            journal_path = turn_journal_path(
                runtime_root,
                goal_id=self.goal_id,
                turn_key=plan.turn_key,
            )
            if journal_path.exists():
                core_plan = _load_journal_core_plan(
                    runtime_root=runtime_root,
                    goal_id=self.goal_id,
                    turn_key=plan.turn_key,
                )
                _validate_journal_plan(
                    supplied=plan,
                    request=request,
                    core_plan=core_plan,
                    route_status=route.status,
                    routed_to_source_registry=route.routed_to_source_registry,
                )
            else:
                prepared = self._prepare(request)
                try:
                    _validate_current_plan(supplied=plan, current=prepared.plan)
                except RevisionConflict:
                    # A same-key caller may have created and committed the journal
                    # while this caller was rebuilding its fresh plan.  Prefer the
                    # durable idempotency record, but only after binding it back to
                    # the caller-supplied plan and request.
                    if not journal_path.exists():
                        raise
                    core_plan = _load_journal_core_plan(
                        runtime_root=runtime_root,
                        goal_id=self.goal_id,
                        turn_key=plan.turn_key,
                    )
                    _validate_journal_plan(
                        supplied=plan,
                        request=request,
                        core_plan=core_plan,
                        route_status=route.status,
                        routed_to_source_registry=route.routed_to_source_registry,
                    )
                    prepared = None
                else:
                    core_plan = prepared.core_plan
                    canonical_plan = prepared.plan
        else:
            prepared = self._prepare(request)
            _validate_current_plan(supplied=plan, current=prepared.plan)
            core_plan = prepared.core_plan
            canonical_plan = prepared.plan

        if not plan.would_invoke_host:
            raise CapabilityUnavailable(
                details={
                    "operation_id": "goal.turn.run_once",
                    "reason": "route_not_host_executable",
                }
            )

        project = (
            prepared.project
            if prepared is not None
            else route.registry_path.parent.parent
        )
        executor = self.executor
        coordinator = self.commit_coordinator

        def host_runner(raw_request: Mapping[str, Any]) -> dict[str, Any]:
            if executor is None:  # guarded for execute=True; never reached in preview
                raise RuntimeError("executor unavailable")
            typed_request = _host_request(raw_request)
            result = executor.execute(typed_request)
            if not isinstance(result, TurnHostResult):
                raise TypeError("executor returned an invalid result")
            return _core_host_result(result)

        def task_validator(
            _core_plan: Mapping[str, Any],
            raw_result: Mapping[str, Any],
        ) -> Mapping[str, object]:
            if coordinator is None:  # guarded for execute=True
                raise RuntimeError("commit coordinator unavailable")
            return coordinator.validate_task(
                canonical_plan,
                _typed_host_result(raw_result),
            )

        def writeback(raw_result: dict[str, Any]) -> dict[str, Any]:
            if coordinator is None:  # guarded for execute=True
                raise RuntimeError("commit coordinator unavailable")
            return _callback_payload(
                coordinator.writeback(_typed_host_result(raw_result)),
                phase="writeback",
            )

        def spend() -> dict[str, Any]:
            if coordinator is None:  # guarded for execute=True
                raise RuntimeError("commit coordinator unavailable")
            return _callback_payload(
                coordinator.spend(canonical_plan),
                phase="quota_spend",
            )

        def schedule(spend_payload: dict[str, Any]) -> dict[str, Any]:
            if coordinator is None:  # guarded for execute=True
                raise RuntimeError("commit coordinator unavailable")
            return _scheduler_payload(
                coordinator.schedule(canonical_plan, spend_payload)
            )

        try:
            payload = run_loopx_turn_once(
                core_plan,
                host_runner=host_runner,
                project=project,
                runtime_root=runtime_root,
                goal_id=self.goal_id,
                timeout_seconds=1.0,
                execute=execute,
                retry_failed=retry_failed,
                task_validator=task_validator if execute else None,
                writeback=writeback if execute else None,
                spend=spend if execute else None,
                scheduler=schedule if execute else None,
            )
        except ApplicationError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise StateUnavailable(
                details={
                    "resource": "turn_execution",
                    "goal_id": self.goal_id,
                    "error_type": type(exc).__name__,
                }
            ) from exc
        return _execution_result(
            context=self.context,
            plan=canonical_plan,
            payload=payload,
        )

    def _prepare(self, request: TurnPlanRequest) -> _PreparedTurn:
        if not isinstance(request, TurnPlanRequest):
            raise ValidationFailed(details={"field": "request"})
        if self.envelope_source is None:
            raise CapabilityUnavailable(
                details={
                    "operation_id": "goal.turn.plan",
                    "reason": "turn_envelope_source_unavailable",
                }
            )
        route = resolve_canonical_goal_route(context=self.context, goal_id=self.goal_id)
        runtime_root = effective_runtime_root(self.context, route)
        try:
            loaded = self.envelope_source.load_turn_envelope(
                registry_path=route.registry_path,
                runtime_root=runtime_root,
                goal_id=route.goal_id,
                agent_id=request.agent_id,
            )
        except ApplicationError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise StateUnavailable(
                details={
                    "resource": "turn_envelope",
                    "goal_id": route.goal_id,
                    "error_type": type(exc).__name__,
                }
            ) from exc
        if not isinstance(loaded, Mapping):
            raise StateUnavailable(
                details={
                    "resource": "turn_envelope",
                    "goal_id": route.goal_id,
                    "cause": "invalid_payload",
                }
            )
        try:
            frozen_envelope = _freeze_json(loaded)
        except (TypeError, ValueError) as exc:
            raise StateUnavailable(
                details={
                    "resource": "turn_envelope",
                    "goal_id": route.goal_id,
                    "cause": "not_json_compatible",
                }
            ) from exc
        thawed_envelope = _thaw(frozen_envelope)
        if not isinstance(thawed_envelope, Mapping):  # root was validated above
            raise StateUnavailable(
                details={
                    "resource": "turn_envelope",
                    "goal_id": route.goal_id,
                    "cause": "invalid_payload",
                }
            )
        envelope = dict(thawed_envelope)
        if str(envelope.get("goal_id") or "") != route.goal_id:
            raise ValidationFailed(
                details={
                    "field": "turn_envelope.goal_id",
                    "reason": "identity_mismatch",
                }
            )
        if str(envelope.get("agent_id") or "") != request.agent_id:
            raise ValidationFailed(
                details={
                    "field": "turn_envelope.agent_id",
                    "reason": "identity_mismatch",
                }
            )
        try:
            core_plan = build_loopx_turn_plan(
                envelope,
                host=request.host.value,
                execution_mode=request.execution_mode.value,
                scheduler_owner=request.scheduler_owner,
                session_binding=(
                    _thaw(request.session_binding)
                    if request.session_binding is not None
                    else None
                ),
                turn_instance_id=request.turn_instance_id,
            )
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(
                details={"field": "turn_plan", "reason": "core_contract"}
            ) from exc

        core_route = core_plan.get("route")
        core_route = core_route if isinstance(core_route, dict) else {}
        transaction = core_plan.get("transaction")
        transaction = transaction if isinstance(transaction, dict) else {}
        selected_todo = core_route.get("selected_todo")
        selected_todo = selected_todo if isinstance(selected_todo, dict) else {}
        raw_selected_todo_id = str(selected_todo.get("todo_id") or "").strip()
        selected_todo_id = (
            normalize_todo_id(raw_selected_todo_id) if raw_selected_todo_id else None
        )
        revision = _canonical_hash(
            {
                "goal_revision": route.goal_revision,
                "turn_envelope": envelope,
            }
        )
        plan_hash = _canonical_hash(
            {
                "goal_id": route.goal_id,
                "revision": revision,
                "request": request.identity(),
                "core_plan": core_plan,
            }
        )
        execution_authorized = self.context.profile.allows_execution
        executor_available = isinstance(self.executor, TurnExecutor)
        coordinator_available = isinstance(
            self.commit_coordinator,
            TurnCommitCoordinator,
        )
        core_contract_valid = core_plan.get("ok") is True
        would_invoke_host = core_route.get("would_invoke_host") is True
        unavailable_reasons: list[str] = []
        if not core_contract_valid:
            unavailable_reasons.append("core_contract_invalid")
        if not would_invoke_host:
            unavailable_reasons.append("route_not_host_executable")
        if not execution_authorized:
            unavailable_reasons.append("profile_execution_denied")
        if not executor_available:
            unavailable_reasons.append("executor_unavailable")
        if not coordinator_available:
            unavailable_reasons.append("commit_coordinator_unavailable")
        if raw_selected_todo_id and selected_todo_id is None:
            unavailable_reasons.append("selected_todo_invalid")
        plan = TurnPlan(
            goal_id=route.goal_id,
            agent_id=request.agent_id,
            generated_at=_generated_at(self.context),
            revision=revision,
            plan_hash=plan_hash,
            route=str(core_route.get("kind") or "contract_error"),
            canonical_route_status=route.status,
            routed_to_source_registry=route.routed_to_source_registry,
            core_contract_valid=core_contract_valid,
            would_invoke_host=would_invoke_host,
            can_run=not unavailable_reasons,
            execution_authorized=execution_authorized,
            executor_available=executor_available,
            commit_coordinator_available=coordinator_available,
            turn_key=str(transaction.get("turn_key") or ""),
            selected_todo_id=selected_todo_id,
            unavailable_reasons=tuple(unavailable_reasons),
        )
        return _PreparedTurn(
            plan=plan,
            core_plan=core_plan,
            runtime_root=runtime_root,
            project=route.registry_path.parent.parent,
        )


def _validate_run_request(
    *,
    service: GoalTurnService,
    plan: TurnPlan,
    request: TurnPlanRequest,
    write_context: WriteContext,
    execute: bool,
    retry_failed: bool,
) -> None:
    if not isinstance(plan, TurnPlan):
        raise ValidationFailed(details={"field": "plan"})
    if not isinstance(request, TurnPlanRequest):
        raise ValidationFailed(details={"field": "request"})
    if not isinstance(write_context, WriteContext):
        raise ValidationFailed(details={"field": "write_context"})
    if not isinstance(execute, bool):
        raise ValidationFailed(details={"field": "execute"})
    if not isinstance(retry_failed, bool):
        raise ValidationFailed(details={"field": "retry_failed"})
    if plan.goal_id != service.goal_id:
        raise ValidationFailed(details={"field": "plan.goal_id"})
    if plan.agent_id != request.agent_id:
        raise ValidationFailed(details={"field": "request.agent_id"})
    if _TURN_KEY_PATTERN.fullmatch(plan.turn_key) is None:
        raise ValidationFailed(details={"field": "plan.turn_key"})
    if write_context.actor != request.agent_id:
        raise AuthorityDenied(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "actor_agent_mismatch",
            }
        )
    if write_context.idempotency_key != request.turn_instance_id:
        raise ValidationFailed(
            details={
                "field": "write_context.idempotency_key",
                "reason": "must_match_turn_instance_id",
            }
        )
    if write_context.expected_revision is None:
        raise ValidationFailed(
            details={
                "field": "write_context.expected_revision",
                "reason": "required",
            }
        )
    if write_context.expected_revision != plan.revision:
        raise RevisionConflict(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "expected_revision_mismatch",
                "expected_revision": write_context.expected_revision,
                "plan_revision": plan.revision,
            }
        )


def _load_journal_core_plan(
    *,
    runtime_root: Path,
    goal_id: str,
    turn_key: str,
) -> dict[str, Any]:
    try:
        return load_loopx_turn_plan_from_journal(
            runtime_root,
            goal_id=goal_id,
            turn_key=turn_key,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(
            details={
                "resource": "turn_journal",
                "goal_id": goal_id,
            }
        ) from exc


def _require_execution_providers(service: GoalTurnService) -> None:
    if not service.context.profile.allows_execution:
        raise AuthorityDenied(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "profile_execution_denied",
                "profile": service.context.profile.value,
            }
        )
    if not isinstance(service.executor, TurnExecutor):
        raise CapabilityUnavailable(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "executor_unavailable",
            }
        )
    if not isinstance(service.commit_coordinator, TurnCommitCoordinator):
        raise CapabilityUnavailable(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "commit_coordinator_unavailable",
            }
        )


def _validate_current_plan(*, supplied: TurnPlan, current: TurnPlan) -> None:
    if supplied.revision != current.revision:
        raise RevisionConflict(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "stale_revision",
                "expected_revision": supplied.revision,
                "current_revision": current.revision,
            }
        )
    supplied_semantics = asdict(supplied)
    current_semantics = asdict(current)
    supplied_semantics.pop("generated_at", None)
    current_semantics.pop("generated_at", None)
    if supplied_semantics != current_semantics:
        raise RevisionConflict(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "plan_mismatch",
                "expected_plan_hash": supplied.plan_hash,
                "current_plan_hash": current.plan_hash,
            }
        )


def _validate_journal_plan(
    *,
    supplied: TurnPlan,
    request: TurnPlanRequest,
    core_plan: Mapping[str, Any],
    route_status: str,
    routed_to_source_registry: bool,
) -> None:
    envelope = core_plan.get("turn_envelope")
    envelope = envelope if isinstance(envelope, Mapping) else {}
    transaction = core_plan.get("transaction")
    transaction = transaction if isinstance(transaction, Mapping) else {}
    core_route = core_plan.get("route")
    core_route = core_route if isinstance(core_route, Mapping) else {}
    selected_todo = core_route.get("selected_todo")
    selected_todo = selected_todo if isinstance(selected_todo, Mapping) else {}
    raw_selected_todo_id = str(selected_todo.get("todo_id") or "").strip()
    selected_todo_id = (
        normalize_todo_id(raw_selected_todo_id) if raw_selected_todo_id else None
    )
    expected_hash = _canonical_hash(
        {
            "goal_id": supplied.goal_id,
            "revision": supplied.revision,
            "request": request.identity(),
            "core_plan": core_plan,
        }
    )
    semantic_projection = {
        "goal_id": str(envelope.get("goal_id") or ""),
        "agent_id": str(envelope.get("agent_id") or ""),
        "route": str(core_route.get("kind") or "contract_error"),
        "canonical_route_status": route_status,
        "routed_to_source_registry": routed_to_source_registry,
        "core_contract_valid": core_plan.get("ok") is True,
        "would_invoke_host": core_route.get("would_invoke_host") is True,
        "can_run": True,
        "execution_authorized": True,
        "executor_available": True,
        "commit_coordinator_available": True,
        "turn_key": str(transaction.get("turn_key") or ""),
        "selected_todo_id": selected_todo_id,
        "unavailable_reasons": (),
    }
    supplied_projection = {key: getattr(supplied, key) for key in semantic_projection}
    if (
        expected_hash != supplied.plan_hash
        or semantic_projection != supplied_projection
    ):
        raise RevisionConflict(
            details={
                "operation_id": "goal.turn.run_once",
                "reason": "journal_plan_mismatch",
            }
        )


def _host_request(value: Mapping[str, Any]) -> TurnHostRequest:
    children = value.get("child_operations")
    if not isinstance(children, (list, tuple)):
        children = ()
    return TurnHostRequest(
        turn_key=str(value.get("turn_key") or ""),
        route=str(value.get("route") or ""),
        session=_mapping(value.get("session")),
        turn_envelope=_mapping(value.get("turn_envelope")),
        result_contract=_mapping(value.get("result_contract")),
        child_operations=tuple(item for item in children if isinstance(item, Mapping)),
    )


def _core_host_result(result: TurnHostResult) -> dict[str, Any]:
    payload = {
        "schema_version": LOOPX_TURN_RESULT_SCHEMA_VERSION,
        "turn_key": result.turn_key,
        "result_kind": result.result_kind,
        "completed_phases": list(TRANSACTION_PHASES[:2]),
    }
    for field, value in asdict(result).items():
        if field not in {"turn_key", "result_kind"} and value is not None:
            payload[field] = value
    return payload


def _typed_host_result(value: Mapping[str, Any]) -> TurnHostResult:
    agent_vision = value.get("agent_vision")
    return TurnHostResult(
        turn_key=str(value.get("turn_key") or ""),
        result_kind=str(value.get("result_kind") or ""),
        classification=_raw_optional_text(value.get("classification")),
        recommended_action=_raw_optional_text(value.get("recommended_action")),
        next_action=_raw_optional_text(value.get("next_action")),
        delivery_batch_scale=_raw_optional_text(value.get("delivery_batch_scale")),
        delivery_outcome=_raw_optional_text(value.get("delivery_outcome")),
        vision_unchanged_reason=_raw_optional_text(
            value.get("vision_unchanged_reason")
        ),
        path_delta_mode=_raw_optional_text(value.get("path_delta_mode")),
        agent_vision_json=(
            json.dumps(agent_vision, ensure_ascii=False, sort_keys=True)
            if isinstance(agent_vision, Mapping)
            else _raw_optional_text(value.get("agent_vision_json"))
        ),
        summary=_raw_optional_text(value.get("summary")),
    )


def _callback_payload(value: Mapping[str, object], *, phase: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"ok": False, "reason": f"{phase}_provider_invalid"}
    return dict(value)


def _scheduler_payload(value: Mapping[str, object]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "completed": False,
            "acknowledged": False,
            "apply_needed": False,
            "disposition": "scheduler_provider_invalid",
        }
    return dict(value)


def _execution_result(
    *,
    context: ApplicationContext,
    plan: TurnPlan,
    payload: Mapping[str, Any],
) -> TurnExecutionResult:
    effects = _mapping(payload.get("effects"))
    raw_validation = _mapping(payload.get("validation"))
    raw_receipt = _mapping(payload.get("receipt"))
    raw_scheduler = _mapping(payload.get("scheduler"))
    return TurnExecutionResult(
        goal_id=plan.goal_id,
        agent_id=plan.agent_id,
        generated_at=_generated_at(context),
        revision=plan.revision,
        plan_hash=plan.plan_hash,
        turn_key=plan.turn_key,
        ok=payload.get("ok") is True,
        status=_safe_text(payload.get("status"), fallback="unknown", limit=80),
        result_kind=_safe_optional_text(payload.get("result_kind"), limit=80),
        dry_run=payload.get("dry_run") is True,
        replayed=payload.get("replayed") is True,
        journal_ref=_safe_text(
            payload.get("journal_ref"), fallback="turn:unknown", limit=80
        ),
        execution_mode=_safe_text(
            payload.get("execution_mode"), fallback="unknown", limit=80
        ),
        effects=TurnExecutionEffects(
            host_invoked=effects.get("host_invoked") is True,
            state_written=effects.get("state_written") is True,
            quota_spent=effects.get("quota_spent") is True,
            scheduler_acknowledged=effects.get("scheduler_acknowledged") is True,
        ),
        validation=(
            TurnTaskValidation(
                status=_safe_text(
                    raw_validation.get("status"), fallback="unknown", limit=80
                ),
                validator_kind=_safe_text(
                    raw_validation.get("validator_kind"),
                    fallback="unknown",
                    limit=80,
                ),
                summary=_safe_text(
                    raw_validation.get("summary"),
                    fallback="Validation details are unavailable.",
                    limit=240,
                ),
                recovery_kind=_safe_optional_text(
                    raw_validation.get("recovery_kind"), limit=80
                ),
                exit_code=(
                    raw_validation["exit_code"]
                    if isinstance(raw_validation.get("exit_code"), int)
                    and not isinstance(raw_validation.get("exit_code"), bool)
                    else None
                ),
            )
            if raw_validation
            else None
        ),
        receipt=(
            TurnReceipt(
                status=_safe_text(
                    raw_receipt.get("status"), fallback="unknown", limit=80
                ),
                result_kind=_safe_optional_text(
                    raw_receipt.get("result_kind"), limit=80
                ),
                completed_phases=tuple(
                    phase
                    for phase in TRANSACTION_PHASES
                    if phase in tuple(raw_receipt.get("completed_phases") or ())
                ),
                failed_phase=_safe_optional_text(
                    raw_receipt.get("failed_phase"), limit=80
                ),
                next_phase=_safe_optional_text(raw_receipt.get("next_phase"), limit=80),
            )
            if raw_receipt
            else None
        ),
        scheduler=(
            TurnSchedulerResult(
                disposition=_safe_text(
                    raw_scheduler.get("disposition"), fallback="unknown", limit=120
                ),
                completed=raw_scheduler.get("completed") is True,
                acknowledged=raw_scheduler.get("acknowledged") is True,
                apply_needed=raw_scheduler.get("apply_needed") is True,
            )
            if raw_scheduler
            else None
        ),
        quota_slot_spend_count=(
            int(payload.get("quota_slot_spend_count") or 0)
            if isinstance(payload.get("quota_slot_spend_count"), int)
            else 0
        ),
        reason=_safe_optional_text(payload.get("reason"), limit=400),
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _raw_optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _safe_text(value: object, *, fallback: str, limit: int) -> str:
    return _safe_optional_text(value, limit=limit) or fallback


def _safe_optional_text(value: object, *, limit: int) -> str | None:
    return application_public_safe_text(value, limit=limit)


def _generated_at(context: ApplicationContext) -> str:
    try:
        value = context.clock()
    except (OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(details={"resource": "clock"}) from exc
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    text = str(value or "").strip()
    if not text:
        raise StateUnavailable(details={"resource": "clock"})
    return text


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        _thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value.strip()


def _public_optional_text(value: object, *, field: str, limit: int) -> str | None:
    if not isinstance(value, str):
        raise ValidationFailed(details={"field": field})
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit or application_public_safe_text(text, limit=limit) != text:
        raise ValidationFailed(details={"field": field, "reason": "not_public_safe"})
    return text


def _provider_method(value: object, *, field: str, method: str) -> None:
    if value is not None and not callable(getattr(value, method, None)):
        raise ValidationFailed(details={"field": field, "method": method})


def _freeze_json(value: object) -> object:
    """Freeze one JSON-compatible packet without coercing invalid provider data."""

    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    raise TypeError("value is not JSON-compatible")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
