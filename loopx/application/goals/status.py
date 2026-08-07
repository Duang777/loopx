"""Path-free goal status projections over the shipped status collector."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loopx.application.errors import (
    GoalNotFound,
    RevisionConflict,
    StateUnavailable,
)
from loopx.paths import registry_project_root
from loopx.registry import registry_goals, resolve_state_file
from loopx.status import collect_status

from .routing import effective_runtime_root, resolve_canonical_goal_route

if TYPE_CHECKING:
    from loopx.application.context import ApplicationContext


@dataclass(frozen=True, slots=True)
class GoalStatus:
    goal_id: str
    status: str | None
    attention_status: str | None
    generated_at: str
    revision: str
    route_status: str
    routed_to_source_registry: bool


@dataclass(frozen=True, slots=True)
class GoalOverview:
    goal_id: str
    status: str | None
    attention_status: str | None
    domain: str | None
    adapter_kind: str | None
    adapter_status: str | None
    generated_at: str
    revision: str
    route_status: str
    routed_to_source_registry: bool


@dataclass(frozen=True, slots=True)
class _GoalObservation:
    goal_id: str
    status: str | None
    attention_status: str | None
    domain: str | None
    adapter_kind: str | None
    adapter_status: str | None
    generated_at: str
    revision: str
    route_status: str
    routed_to_source_registry: bool


def _generated_at(context: ApplicationContext) -> str:
    try:
        value = context.clock()
    except (OSError, TypeError, ValueError) as exc:
        raise StateUnavailable(
            message="application clock is unavailable",
            details={"error_type": type(exc).__name__},
        ) from exc
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    text = str(value or "").strip()
    if not text:
        raise StateUnavailable(message="application clock returned no value")
    return text


def _read_registry_bytes(path: Path, *, goal_id: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StateUnavailable(
            message="canonical goal registry is unreadable",
            details={"goal_id": goal_id, "error_type": type(exc).__name__},
        ) from exc


def _active_state_digest(
    goal: dict[str, Any],
    *,
    source_registry: Path,
    goal_id: str,
) -> str | None:
    raw_state_file = str(goal.get("state_file") or "").strip()
    if not raw_state_file:
        return None
    raw_repo = str(goal.get("repo") or "").strip()
    if not raw_repo:
        raise StateUnavailable(
            message="canonical goal repository is unavailable",
            details={"goal_id": goal_id},
        )
    repo = Path(raw_repo).expanduser()
    if not repo.is_absolute():
        repo = registry_project_root(source_registry) / repo
    state_file = resolve_state_file(repo, raw_state_file)
    if state_file is None:
        return None
    try:
        content = state_file.read_bytes()
    except OSError as exc:
        raise StateUnavailable(
            message="canonical active goal state is unreadable",
            details={"goal_id": goal_id, "error_type": type(exc).__name__},
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _goal_row(payload: dict[str, Any], goal_id: str) -> dict[str, Any] | None:
    return next(
        (row for row in registry_goals(payload) if str(row.get("id") or "") == goal_id),
        None,
    )


def _status_goal(payload: dict[str, Any], goal_id: str) -> dict[str, Any] | None:
    history = payload.get("run_history")
    goals = history.get("goals") if isinstance(history, dict) else None
    if not isinstance(goals, list):
        return None
    return next(
        (
            row
            for row in goals
            if isinstance(row, dict) and str(row.get("id") or "") == goal_id
        ),
        None,
    )


def _attention_status(payload: dict[str, Any], goal_id: str) -> str | None:
    queue = payload.get("attention_queue")
    items = queue.get("items") if isinstance(queue, dict) else None
    if not isinstance(items, list):
        return None
    row = next(
        (
            item
            for item in items
            if isinstance(item, dict) and str(item.get("goal_id") or "") == goal_id
        ),
        None,
    )
    return str(row.get("status") or "").strip() or None if row else None


def _history_semantics(status_goal: dict[str, Any]) -> dict[str, Any]:
    latest_runs = status_goal.get("latest_runs")
    latest_run = (
        next((row for row in latest_runs if isinstance(row, dict)), None)
        if isinstance(latest_runs, list)
        else None
    )
    return {
        "unique_runs": int(status_goal.get("unique_runs") or 0),
        "latest": (
            {
                "generated_at": str(latest_run.get("generated_at") or ""),
                "classification": str(latest_run.get("classification") or ""),
                "agent_id": str(latest_run.get("agent_id") or ""),
                "delivery_outcome": str(latest_run.get("delivery_outcome") or ""),
                "progress_scope": str(latest_run.get("progress_scope") or ""),
            }
            if latest_run
            else None
        ),
    }


def _semantic_revision(
    *,
    goal_id: str,
    status: str | None,
    attention_status: str | None,
    domain: str | None,
    adapter_kind: str | None,
    adapter_status: str | None,
    route_status: str,
    routed_to_source_registry: bool,
    active_state_digest: str | None,
    history_semantics: dict[str, Any],
) -> str:
    material = {
        "goal_id": goal_id,
        "status": status,
        "attention_status": attention_status,
        "domain": domain,
        "adapter_kind": adapter_kind,
        "adapter_status": adapter_status,
        "route_status": route_status,
        "routed_to_source_registry": routed_to_source_registry,
        "active_state_sha256": active_state_digest,
        "history": history_semantics,
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _observe_goal(*, context: ApplicationContext, goal_id: str) -> _GoalObservation:
    route = resolve_canonical_goal_route(context=context, goal_id=goal_id)
    source_registry = route.registry_path
    before_registry_bytes = _read_registry_bytes(source_registry, goal_id=goal_id)
    try:
        source_payload = context.load_registry(source_registry)
    except (OSError, ValueError) as exc:
        raise StateUnavailable(
            message="canonical goal registry could not be loaded",
            details={"goal_id": goal_id, "error_type": type(exc).__name__},
        ) from exc
    if not isinstance(source_payload, dict):
        raise StateUnavailable(
            message="canonical goal registry is invalid",
            details={"goal_id": goal_id, "error_type": "invalid_payload"},
        )
    goal = _goal_row(source_payload, goal_id)
    if goal is None:
        raise GoalNotFound(details={"goal_id": goal_id})
    before_active_state_digest = _active_state_digest(
        goal,
        source_registry=source_registry,
        goal_id=goal_id,
    )

    configured_scan_roots = tuple(getattr(context, "scan_roots", ()) or ())
    scan_roots = [Path(root) for root in configured_scan_roots]
    if not scan_roots:
        scan_roots = [source_registry.parent.parent]
    try:
        payload = collect_status(
            registry_path=source_registry,
            runtime_root_override=str(effective_runtime_root(context, route)),
            scan_roots=scan_roots,
            limit=1,
            goal_id=goal_id,
        )
    except (KeyError, OSError, ValueError) as exc:
        raise StateUnavailable(
            message="canonical goal status is unavailable",
            details={"goal_id": goal_id, "error_type": type(exc).__name__},
        ) from exc

    after_registry_bytes = _read_registry_bytes(source_registry, goal_id=goal_id)
    after_active_state_digest = _active_state_digest(
        goal,
        source_registry=source_registry,
        goal_id=goal_id,
    )
    if (
        before_registry_bytes != after_registry_bytes
        or before_active_state_digest != after_active_state_digest
    ):
        raise RevisionConflict(
            message="canonical goal state changed during status collection",
            details={"goal_id": goal_id},
        )
    status_goal = _status_goal(payload, goal_id)
    if status_goal is None:
        raise GoalNotFound(details={"goal_id": goal_id})

    status = str(status_goal.get("status") or "").strip() or None
    attention_status = _attention_status(payload, goal_id)
    domain = str(status_goal.get("domain") or "").strip() or None
    adapter_kind = str(status_goal.get("adapter_kind") or "").strip() or None
    adapter_status = str(status_goal.get("adapter_status") or "").strip() or None
    route_status = route.status
    routed_to_source_registry = route.routed_to_source_registry
    revision = _semantic_revision(
        goal_id=goal_id,
        status=status,
        attention_status=attention_status,
        domain=domain,
        adapter_kind=adapter_kind,
        adapter_status=adapter_status,
        route_status=route_status,
        routed_to_source_registry=routed_to_source_registry,
        active_state_digest=after_active_state_digest,
        history_semantics=_history_semantics(status_goal),
    )

    return _GoalObservation(
        goal_id=goal_id,
        status=status,
        attention_status=attention_status,
        domain=domain,
        adapter_kind=adapter_kind,
        adapter_status=adapter_status,
        generated_at=_generated_at(context),
        revision=revision,
        route_status=route_status,
        routed_to_source_registry=routed_to_source_registry,
    )


def load_goal_status(*, context: ApplicationContext, goal_id: str) -> GoalStatus:
    observation = _observe_goal(context=context, goal_id=goal_id)
    return GoalStatus(
        goal_id=observation.goal_id,
        status=observation.status,
        attention_status=observation.attention_status,
        generated_at=observation.generated_at,
        revision=observation.revision,
        route_status=observation.route_status,
        routed_to_source_registry=observation.routed_to_source_registry,
    )


def load_goal_overview(*, context: ApplicationContext, goal_id: str) -> GoalOverview:
    observation = _observe_goal(context=context, goal_id=goal_id)
    return GoalOverview(
        goal_id=observation.goal_id,
        status=observation.status,
        attention_status=observation.attention_status,
        domain=observation.domain,
        adapter_kind=observation.adapter_kind,
        adapter_status=observation.adapter_status,
        generated_at=observation.generated_at,
        revision=observation.revision,
        route_status=observation.route_status,
        routed_to_source_registry=observation.routed_to_source_registry,
    )
