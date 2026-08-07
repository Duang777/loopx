"""Typed, path-free quota use cases over the shipped quota runtime."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Mapping

from loopx.control_plane.quota.live_decision import (
    build_live_quota_should_run_decision,
)
from loopx.control_plane.quota.spend_sources import (
    DEFAULT_SLOT_SPEND_SOURCE,
    VALID_SLOT_SPEND_SOURCES,
)
from loopx.control_plane.quota.turn_envelope import build_turn_envelope
from loopx.control_plane.todos.contract import normalize_todo_claimed_by
from loopx.quota import spend_quota_slot, void_quota_slot
from loopx.status import collect_status

from ..contracts import (
    WriteContext,
    WriteCorrectness,
    application_public_safe_text,
)
from ..errors import (
    ApplicationError,
    AuthorityDenied,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
)
from .routing import (
    CanonicalGoalRoute,
    effective_runtime_root,
    resolve_canonical_goal_route,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ..context import ApplicationContext


PENDING_QUOTA_WRITER_CORRECTNESS = WriteCorrectness(
    status="pending_migration",
    atomic_revision_check=False,
    idempotent_retry=False,
)


@dataclass(frozen=True, slots=True)
class QuotaBudget:
    compute: float
    window_hours: int
    slot_minutes: int
    allowed_slots: int
    spent_slots: int


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    goal_id: str
    agent_id: str | None
    generated_at: str
    revision: str
    route_status: str
    decision: str
    should_run: bool
    state: str
    effective_action: str | None
    reason: str | None
    action_required: bool
    open_count: int
    recommended_action: str | None
    selected_todo_id: str | None
    must_attempt: bool
    delivery_allowed: bool
    quiet_noop_allowed: bool
    envelope_verified: bool
    envelope_within_budget: bool
    budget: QuotaBudget


@dataclass(frozen=True, slots=True)
class QuotaMutationPlan:
    goal_id: str
    operation: str
    generated_at: str
    revision: str
    plan_hash: str
    can_apply: bool
    slots: int
    source: str
    agent_id: str | None
    before: QuotaBudget
    after: QuotaBudget | None
    would_throttle: bool
    target_generated_at: str | None
    reason_summary: str | None
    reason: str | None
    correctness: WriteCorrectness = PENDING_QUOTA_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class QuotaApplyResult:
    goal_id: str
    operation: str
    generated_at: str
    event_generated_at: str
    previous_revision: str
    revision: str
    plan_hash: str
    written: bool
    slots: int
    source: str
    agent_id: str | None
    target_generated_at: str | None
    correctness: WriteCorrectness = PENDING_QUOTA_WRITER_CORRECTNESS


@dataclass(frozen=True, slots=True)
class _QuotaSnapshot:
    route: CanonicalGoalRoute
    runtime_root: Path
    status_payload: dict[str, Any]
    decision_payload: dict[str, Any]
    envelope_payload: dict[str, Any]
    decision: QuotaDecision


@dataclass(frozen=True, slots=True)
class GoalQuotaService:
    """Goal quota operations that resolve current canonical state per call."""

    context: ApplicationContext
    goal_id: str

    def should_run(self, *, agent_id: str | None = None) -> QuotaDecision:
        return _quota_snapshot(
            context=self.context,
            goal_id=self.goal_id,
            agent_id=_agent_id(agent_id),
            operation_id="goal.quota.should_run",
        ).decision

    def preview_spend(
        self,
        *,
        slots: int = 1,
        source: str = DEFAULT_SLOT_SPEND_SOURCE,
        agent_id: str | None = None,
    ) -> QuotaMutationPlan:
        _require_write_profile(self.context, "goal.quota.spend.preview")
        plan, _ = _spend_plan(
            context=self.context,
            goal_id=self.goal_id,
            slots=_slots(slots),
            source=_source(source),
            agent_id=_agent_id(agent_id),
            operation_id="goal.quota.spend.preview",
        )
        return plan

    def apply_spend(
        self,
        plan: QuotaMutationPlan,
        *,
        write_context: WriteContext,
    ) -> QuotaApplyResult:
        _validate_apply(
            context=self.context,
            plan=plan,
            write_context=write_context,
            operation="spend",
        )
        if plan.goal_id != self.goal_id:
            raise ValidationFailed(details={"field": "plan"})
        current, snapshot = _spend_plan(
            context=self.context,
            goal_id=self.goal_id,
            slots=_slots(plan.slots),
            source=_source(plan.source),
            agent_id=_agent_id(plan.agent_id),
            operation_id="goal.quota.spend.apply",
        )
        _validate_current_plan(
            supplied=plan,
            current=current,
            write_context=write_context,
        )
        payload = _write_spend(snapshot=snapshot, plan=current)
        return _apply_result(
            context=self.context,
            goal_id=self.goal_id,
            plan=current,
            payload=payload,
        )

    def preview_void(
        self,
        *,
        voided_run_generated_at: str,
        reason_summary: str,
        source: str = DEFAULT_SLOT_SPEND_SOURCE,
        agent_id: str | None = None,
    ) -> QuotaMutationPlan:
        _require_write_profile(self.context, "goal.quota.void.preview")
        plan, _ = _void_plan(
            context=self.context,
            goal_id=self.goal_id,
            target_generated_at=_required_text(
                voided_run_generated_at,
                field="voided_run_generated_at",
                limit=160,
            ),
            reason_summary=_required_text(
                reason_summary,
                field="reason_summary",
                limit=240,
            ),
            source=_source(source),
            agent_id=_agent_id(agent_id),
            operation_id="goal.quota.void.preview",
        )
        return plan

    def apply_void(
        self,
        plan: QuotaMutationPlan,
        *,
        write_context: WriteContext,
    ) -> QuotaApplyResult:
        _validate_apply(
            context=self.context,
            plan=plan,
            write_context=write_context,
            operation="void",
        )
        if plan.goal_id != self.goal_id:
            raise ValidationFailed(details={"field": "plan"})
        current, snapshot = _void_plan(
            context=self.context,
            goal_id=self.goal_id,
            target_generated_at=_required_text(
                plan.target_generated_at,
                field="plan.target_generated_at",
                limit=160,
            ),
            reason_summary=_required_text(
                plan.reason_summary,
                field="plan.reason_summary",
                limit=240,
            ),
            source=_source(plan.source),
            agent_id=_agent_id(plan.agent_id),
            operation_id="goal.quota.void.apply",
        )
        _validate_current_plan(
            supplied=plan,
            current=current,
            write_context=write_context,
        )
        payload = _write_void(snapshot=snapshot, plan=current)
        return _apply_result(
            context=self.context,
            goal_id=self.goal_id,
            plan=current,
            payload=payload,
        )


def _quota_snapshot(
    *,
    context: ApplicationContext,
    goal_id: str,
    agent_id: str | None,
    operation_id: str,
) -> _QuotaSnapshot:
    route = resolve_canonical_goal_route(context=context, goal_id=goal_id)
    runtime_root = effective_runtime_root(context, route)
    scan_roots = tuple(context.scan_roots) or (route.registry_path.parent.parent,)
    try:
        status_payload = collect_status(
            registry_path=route.registry_path,
            runtime_root_override=str(runtime_root),
            scan_roots=list(scan_roots),
            limit=20,
            goal_id=goal_id,
        )
    except ApplicationError:
        raise
    except (KeyError, OSError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "goal_quota", "goal_id": goal_id}
        ) from exc
    if not isinstance(status_payload, dict) or status_payload.get("ok") is False:
        raise StateUnavailable(details={"resource": "goal_quota", "goal_id": goal_id})
    try:
        decision_payload = build_live_quota_should_run_decision(
            status_payload,
            goal_id=goal_id,
            agent_id=agent_id,
            available_capabilities=None,
            include_scheduler_detail=False,
            codex_app_current_rrule=None,
            registry_path=route.registry_path,
            runtime_root=runtime_root,
            host_observation_resolver=None,
        )
        envelope_payload = build_turn_envelope(decision_payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    decision = _decision(
        context=context,
        route=route,
        status_payload=status_payload,
        payload=decision_payload,
        envelope=envelope_payload,
        agent_id=agent_id,
    )
    return _QuotaSnapshot(
        route=route,
        runtime_root=runtime_root,
        status_payload=status_payload,
        decision_payload=decision_payload,
        envelope_payload=envelope_payload,
        decision=decision,
    )


def _decision(
    *,
    context: ApplicationContext,
    route: CanonicalGoalRoute,
    status_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
    envelope: Mapping[str, Any],
    agent_id: str | None,
) -> QuotaDecision:
    action = _mapping(envelope.get("action"))
    selected_todo = _mapping(action.get("selected_todo"))
    signature = _mapping(envelope.get("action_signature"))
    compaction = _mapping(envelope.get("compaction"))
    raw_budget = payload.get("quota")
    budget = _budget(
        raw_budget
        if isinstance(raw_budget, Mapping)
        else _status_budget(status_payload, route.goal_id)
    )
    material = {
        "goal_revision": route.goal_revision,
        "agent_id": agent_id,
        "decision": _decision_material(payload, envelope, budget),
        "history": _history_material(status_payload, route.goal_id),
    }
    return QuotaDecision(
        goal_id=route.goal_id,
        agent_id=agent_id,
        generated_at=_generated_at(context),
        revision=_hash(material),
        route_status=route.status,
        decision=str(payload.get("decision") or "unknown"),
        should_run=bool(payload.get("should_run")),
        state=str(payload.get("state") or "unknown"),
        effective_action=_optional_text(payload.get("effective_action"), limit=120),
        reason=_optional_text(payload.get("reason"), limit=360),
        action_required=bool(envelope.get("action_required")),
        open_count=_integer(envelope.get("open_count")),
        recommended_action=_optional_text(
            action.get("recommended_action") or payload.get("recommended_action"),
            limit=360,
        ),
        selected_todo_id=_optional_text(selected_todo.get("todo_id"), limit=160),
        must_attempt=bool(action.get("must_attempt")),
        delivery_allowed=bool(action.get("delivery_allowed")),
        quiet_noop_allowed=bool(action.get("quiet_noop_allowed")),
        envelope_verified=bool(signature.get("matches")),
        envelope_within_budget=bool(compaction.get("within_budget")),
        budget=budget,
    )


def _decision_material(
    payload: Mapping[str, Any],
    envelope: Mapping[str, Any],
    budget: QuotaBudget,
) -> dict[str, Any]:
    action = _mapping(envelope.get("action"))
    selected_todo = _mapping(action.get("selected_todo"))
    return {
        "decision": payload.get("decision"),
        "should_run": bool(payload.get("should_run")),
        "state": payload.get("state"),
        "effective_action": _optional_text(
            payload.get("effective_action"),
            limit=120,
        ),
        "action_required": bool(envelope.get("action_required")),
        "open_count": _integer(envelope.get("open_count")),
        "selected_todo_id": _optional_text(selected_todo.get("todo_id"), limit=160),
        "must_attempt": bool(action.get("must_attempt")),
        "delivery_allowed": bool(action.get("delivery_allowed")),
        "budget": asdict(budget),
    }


def _history_material(payload: Mapping[str, Any], goal_id: str) -> dict[str, Any]:
    run_history = _mapping(payload.get("run_history"))
    goals = run_history.get("goals")
    goal = (
        next(
            (
                item
                for item in goals
                if isinstance(item, Mapping) and str(item.get("id") or "") == goal_id
            ),
            {},
        )
        if isinstance(goals, list)
        else {}
    )
    latest_runs = goal.get("latest_runs") if isinstance(goal, Mapping) else None
    latest = (
        next(
            (item for item in latest_runs if isinstance(item, Mapping)),
            {},
        )
        if isinstance(latest_runs, list)
        else {}
    )
    return {
        "run_count": _integer(payload.get("run_count")),
        "unique_runs": _integer(goal.get("unique_runs"))
        if isinstance(goal, Mapping)
        else 0,
        "latest": {
            "generated_at": latest.get("generated_at"),
            "classification": _optional_text(
                latest.get("classification"),
                limit=160,
            ),
            "agent_id": _optional_text(latest.get("agent_id"), limit=160),
        },
    }


def _status_budget(payload: Mapping[str, Any], goal_id: str) -> Mapping[str, Any]:
    run_history = _mapping(payload.get("run_history"))
    goals = run_history.get("goals")
    if isinstance(goals, list):
        goal = next(
            (
                item
                for item in goals
                if isinstance(item, Mapping) and str(item.get("id") or "") == goal_id
            ),
            None,
        )
        if isinstance(goal, Mapping) and isinstance(goal.get("quota"), Mapping):
            return goal["quota"]
    return {}


def _spend_plan(
    *,
    context: ApplicationContext,
    goal_id: str,
    slots: int,
    source: str,
    agent_id: str | None,
    operation_id: str,
) -> tuple[QuotaMutationPlan, _QuotaSnapshot]:
    snapshot = _quota_snapshot(
        context=context,
        goal_id=goal_id,
        agent_id=agent_id,
        operation_id=operation_id,
    )
    try:
        payload = spend_quota_slot(
            snapshot.status_payload,
            goal_id=goal_id,
            slots=slots,
            execute=False,
            source=source,
            agent_id=agent_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    plan = _plan(
        context=context,
        snapshot=snapshot,
        operation="spend",
        payload=payload,
        slots=slots,
        source=source,
        agent_id=agent_id,
        target_generated_at=None,
        reason_summary=None,
    )
    return plan, snapshot


def _void_plan(
    *,
    context: ApplicationContext,
    goal_id: str,
    target_generated_at: str,
    reason_summary: str,
    source: str,
    agent_id: str | None,
    operation_id: str,
) -> tuple[QuotaMutationPlan, _QuotaSnapshot]:
    snapshot = _quota_snapshot(
        context=context,
        goal_id=goal_id,
        agent_id=agent_id,
        operation_id=operation_id,
    )
    try:
        payload = void_quota_slot(
            snapshot.status_payload,
            goal_id=goal_id,
            voided_run_generated_at=target_generated_at,
            execute=False,
            source=source,
            reason_summary=reason_summary,
            agent_id=agent_id,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationFailed(details={"operation_id": operation_id}) from exc
    plan = _plan(
        context=context,
        snapshot=snapshot,
        operation="void",
        payload=payload,
        slots=max(1, _integer(payload.get("slots"))),
        source=source,
        agent_id=agent_id,
        target_generated_at=target_generated_at,
        reason_summary=reason_summary,
    )
    return plan, snapshot


def _plan(
    *,
    context: ApplicationContext,
    snapshot: _QuotaSnapshot,
    operation: str,
    payload: Mapping[str, Any],
    slots: int,
    source: str,
    agent_id: str | None,
    target_generated_at: str | None,
    reason_summary: str | None,
) -> QuotaMutationPlan:
    before_payload = _mapping(payload.get("before"))
    after_payload = _mapping(payload.get("after"))
    before_budget = before_payload.get("quota")
    before = _budget(
        before_budget
        if isinstance(before_budget, Mapping)
        else asdict(snapshot.decision.budget)
    )
    after = (
        _budget(after_payload.get("quota") or after_payload) if after_payload else None
    )
    seed = {
        "goal_id": snapshot.route.goal_id,
        "operation": operation,
        "revision": snapshot.decision.revision,
        "slots": slots,
        "source": source,
        "agent_id": agent_id,
        "before": asdict(before),
        "after": asdict(after) if after else None,
        "target_generated_at": target_generated_at,
        "reason_summary": reason_summary,
        "can_apply": bool(payload.get("ok")),
    }
    return QuotaMutationPlan(
        goal_id=snapshot.route.goal_id,
        operation=operation,
        generated_at=_generated_at(context),
        revision=snapshot.decision.revision,
        plan_hash=_hash(seed),
        can_apply=bool(payload.get("ok")),
        slots=slots,
        source=source,
        agent_id=agent_id,
        before=before,
        after=after,
        would_throttle=bool(payload.get("would_throttle")),
        target_generated_at=target_generated_at,
        reason_summary=reason_summary,
        reason=_optional_text(payload.get("reason"), limit=360),
    )


def _write_spend(
    *,
    snapshot: _QuotaSnapshot,
    plan: QuotaMutationPlan,
) -> dict[str, Any]:
    try:
        payload = spend_quota_slot(
            snapshot.status_payload,
            goal_id=plan.goal_id,
            slots=plan.slots,
            execute=True,
            source=plan.source,
            agent_id=plan.agent_id,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "quota_writer", "goal_id": plan.goal_id}
        ) from exc
    return _written_payload(payload, goal_id=plan.goal_id)


def _write_void(
    *,
    snapshot: _QuotaSnapshot,
    plan: QuotaMutationPlan,
) -> dict[str, Any]:
    try:
        payload = void_quota_slot(
            snapshot.status_payload,
            goal_id=plan.goal_id,
            voided_run_generated_at=str(plan.target_generated_at),
            execute=True,
            source=plan.source,
            reason_summary=plan.reason_summary,
            agent_id=plan.agent_id,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(
            details={"resource": "quota_writer", "goal_id": plan.goal_id}
        ) from exc
    return _written_payload(payload, goal_id=plan.goal_id)


def _written_payload(payload: object, *, goal_id: str) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or not payload.get("ok")
        or not payload.get("appended")
    ):
        raise StateUnavailable(details={"resource": "quota_writer", "goal_id": goal_id})
    return payload


def _apply_result(
    *,
    context: ApplicationContext,
    goal_id: str,
    plan: QuotaMutationPlan,
    payload: Mapping[str, Any],
) -> QuotaApplyResult:
    current = _quota_snapshot(
        context=context,
        goal_id=goal_id,
        agent_id=plan.agent_id,
        operation_id=f"goal.quota.{plan.operation}.apply",
    ).decision
    event_generated_at = _timestamp(
        payload.get("generated_at"),
        resource="quota_writer",
        goal_id=goal_id,
    )
    return QuotaApplyResult(
        goal_id=goal_id,
        operation=plan.operation,
        generated_at=_generated_at(context),
        event_generated_at=event_generated_at,
        previous_revision=plan.revision,
        revision=current.revision,
        plan_hash=plan.plan_hash,
        written=bool(payload.get("appended")),
        slots=plan.slots,
        source=plan.source,
        agent_id=plan.agent_id,
        target_generated_at=plan.target_generated_at,
    )


def _validate_apply(
    *,
    context: ApplicationContext,
    plan: object,
    write_context: object,
    operation: str,
) -> None:
    if not isinstance(plan, QuotaMutationPlan) or plan.operation != operation:
        raise ValidationFailed(details={"field": "plan"})
    if not isinstance(write_context, WriteContext):
        raise ValidationFailed(details={"field": "write_context"})
    _require_write_profile(context, f"goal.quota.{operation}.apply")
    if write_context.expected_revision is None:
        raise ValidationFailed(details={"field": "write_context.expected_revision"})


def _validate_current_plan(
    *,
    supplied: QuotaMutationPlan,
    current: QuotaMutationPlan,
    write_context: WriteContext,
) -> None:
    if write_context.expected_revision != current.revision:
        raise RevisionConflict(
            details={
                "goal_id": current.goal_id,
                "expected_revision": write_context.expected_revision,
                "current_revision": current.revision,
            }
        )
    if supplied.plan_hash != current.plan_hash:
        raise RevisionConflict(
            details={
                "goal_id": current.goal_id,
                "reason": "plan_hash_mismatch",
                "expected_plan_hash": supplied.plan_hash,
                "current_plan_hash": current.plan_hash,
            }
        )
    if not current.can_apply:
        raise ValidationFailed(
            details={
                "operation_id": f"goal.quota.{current.operation}.apply",
                "reason": "gated",
            }
        )


def _require_write_profile(context: ApplicationContext, operation_id: str) -> None:
    if not context.writes_available:
        raise AuthorityDenied(
            details={
                "operation_id": operation_id,
                "profile": context.profile.value,
            }
        )


def _budget(value: object) -> QuotaBudget:
    payload = _mapping(value)
    return QuotaBudget(
        compute=_quota_number(payload.get("compute"), field="quota.compute"),
        window_hours=_quota_integer(
            payload.get("window_hours"),
            field="quota.window_hours",
            minimum=1,
        ),
        slot_minutes=_quota_integer(
            payload.get("slot_minutes"),
            field="quota.slot_minutes",
            minimum=1,
        ),
        allowed_slots=_quota_integer(
            payload.get("allowed_slots"),
            field="quota.allowed_slots",
            minimum=0,
        ),
        spent_slots=_quota_integer(
            payload.get("spent_slots"),
            field="quota.spent_slots",
            minimum=0,
        ),
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _decimal(value: object, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise _invalid_numeric(field)
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise _invalid_numeric(field) from None
    if not number.is_finite():
        raise _invalid_numeric(field)
    return number


def _quota_number(value: object, *, field: str) -> float:
    number = _decimal(value, field=field)
    if number < 0 or number > 1:
        raise _invalid_numeric(field)
    return float(number)


def _quota_integer(value: object, *, field: str, minimum: int) -> int:
    number = _decimal(value, field=field)
    if number != number.to_integral_value() or number < minimum:
        raise _invalid_numeric(field)
    return int(number)


def _invalid_numeric(field: str) -> StateUnavailable:
    return StateUnavailable(
        details={
            "resource": "goal_quota",
            "field": field,
            "cause": "invalid_numeric",
        }
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return 0
    if not number.is_finite() or number != number.to_integral_value():
        return 0
    return int(number)


def _slots(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationFailed(details={"field": "slots"})
    return value


def _source(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationFailed(details={"field": "source"})
    normalized = value.strip()
    if normalized not in VALID_SLOT_SPEND_SOURCES:
        raise ValidationFailed(
            details={
                "field": "source",
                "allowed": tuple(sorted(VALID_SLOT_SPEND_SOURCES)),
            }
        )
    return normalized


def _agent_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationFailed(details={"field": "agent_id"})
    normalized = normalize_todo_claimed_by(value)
    if not normalized or _public_text(normalized, limit=80) != normalized:
        raise ValidationFailed(details={"field": "agent_id"})
    return normalized


def _required_text(value: object, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValidationFailed(details={"field": field})
    text = " ".join(value.split())
    if not text or len(text) > limit or _public_text(text, limit=limit) != text:
        raise ValidationFailed(details={"field": field})
    return text


def _optional_text(value: object, *, limit: int) -> str | None:
    return _public_text(value, limit=limit)


def _public_text(value: object, *, limit: int) -> str | None:
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
    return _timestamp(value, resource="clock")


def _timestamp(
    value: object,
    *,
    resource: str,
    goal_id: str | None = None,
) -> str:
    text = _public_text(value, limit=160)
    try:
        if not text:
            raise ValueError
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        details: dict[str, object] = {
            "resource": resource,
            "cause": "invalid_timestamp",
        }
        if goal_id:
            details["goal_id"] = goal_id
        raise StateUnavailable(details=details) from exc
    return text


def _hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
