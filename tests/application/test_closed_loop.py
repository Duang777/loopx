from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from loopx.application import (
    ApplicationContext,
    LoopXApplication,
    Profile,
    QuotaDecision,
    TodoCompletion,
    TurnExecutionMode,
    TurnHost,
    TurnHostRequest,
    TurnHostResult,
    TurnPlan,
    TurnPlanRequest,
    WriteContext,
)

from .fixtures import PRIMARY_AGENT_ID, PRIMARY_GOAL_ID
from .fixtures.closed_loop import (
    FIXED_UTC_TIME,
    ClosedLoopFixture,
    materialize_closed_loop_fixture,
)


PRIVATE_SENTINEL = "application-closed-loop-private-token"
FORBIDDEN_DTO_KEYS = {
    "json_path",
    "markdown_path",
    "registry_path",
    "runtime_root",
    "source_registry",
    "state_file",
}


class AdmittedEnvelopeSource:
    """Build one Core envelope from the typed quota admission projection."""

    def __init__(self, *, private_text: str) -> None:
        self._decision: QuotaDecision | None = None
        self._private_text = private_text
        self.calls: list[tuple[str, str]] = []

    def bind(self, decision: QuotaDecision) -> None:
        self._decision = decision

    def load_turn_envelope(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
        agent_id: str,
    ) -> Mapping[str, Any]:
        del registry_path, runtime_root
        decision = self._decision
        if decision is None:
            raise RuntimeError("quota admission must precede Turn planning")
        if decision.goal_id != goal_id or decision.agent_id != agent_id:
            raise ValueError("Turn identity does not match the admitted decision")
        if decision.selected_todo_id is None:
            raise ValueError("the admitted decision has no selected todo")
        self.calls.append((goal_id, agent_id))
        return {
            "ok": True,
            "schema_version": "loopx_turn_envelope_v0",
            "goal_id": decision.goal_id,
            "agent_id": decision.agent_id,
            "should_run": decision.should_run,
            "effective_action": decision.effective_action or "normal_run",
            "action": {
                "must_attempt": decision.must_attempt,
                "delivery_allowed": decision.delivery_allowed,
                "quiet_noop_allowed": decision.quiet_noop_allowed,
                "selected_todo": {
                    "todo_id": decision.selected_todo_id,
                    "text": self._private_text,
                },
            },
            "user": {
                "action_required": decision.action_required,
                "open_count": decision.open_count,
                "notify": "NOTIFY" if decision.action_required else "DONT_NOTIFY",
            },
            "writeback": {"spend_after_validation": True},
            "scheduler": {"action": "run_now"},
            "action_signature": {
                "matches": decision.envelope_verified,
                "source_hash": decision.revision,
                "envelope_hash": decision.revision,
            },
            "compaction": {"within_budget": decision.envelope_within_budget},
        }


class ClosedLoopExecutor:
    def __init__(self) -> None:
        self.requests: list[TurnHostRequest] = []

    def execute(self, request: TurnHostRequest) -> TurnHostResult:
        self.requests.append(request)
        return TurnHostResult(
            turn_key=request.turn_key,
            result_kind="validated_progress",
            classification="application_closed_loop_progress",
            recommended_action="Commit the validated application successor",
            next_action="Verify successor, quota, history, and status readback",
            delivery_batch_scale="implementation",
            delivery_outcome="outcome_progress",
            vision_unchanged_reason="The closed-loop fixture objective is unchanged.",
            summary="The fake executor completed one bounded fixture step.",
        )


class ClosedLoopCoordinator:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.goal: Any | None = None
        self.todo_id: str | None = None
        self.lease_revision: str | None = None
        self.completion_plan: Any | None = None
        self.completed: Any | None = None
        self.released: Any | None = None
        self.spend_plan: Any | None = None
        self.spent: Any | None = None

    def bind(self, *, goal: Any, todo_id: str, lease_revision: str) -> None:
        self.goal = goal
        self.todo_id = todo_id
        self.lease_revision = lease_revision

    def validate_task(
        self,
        plan: TurnPlan,
        result: TurnHostResult,
    ) -> Mapping[str, object]:
        assert plan.selected_todo_id == self.todo_id
        assert result.result_kind == "validated_progress"
        self.calls.append("validate_task")
        return {
            "status": "passed",
            "validator_kind": "closed_loop_fixture",
            "summary": "Independent closed-loop fixture postconditions passed",
        }

    def writeback(self, result: TurnHostResult) -> Mapping[str, object]:
        self.calls.append("writeback")
        assert self.goal is not None
        assert self.todo_id is not None
        assert self.lease_revision is not None
        completion = TodoCompletion(
            evidence="typed-application-closed-loop-validated",
            note=result.summary,
            claimed_by=PRIMARY_AGENT_ID,
            next_agent_todo="Verify the committed application successor and history.",
            next_claimed_by=PRIMARY_AGENT_ID,
            next_task_class="advancement_task",
            next_action_kind="verify_application_closed_loop",
        )
        self.completion_plan = self.goal.todos.preview_complete(
            self.todo_id,
            completion,
            actor=PRIMARY_AGENT_ID,
        )
        self.completed = self.goal.todos.apply_complete(
            self.completion_plan,
            write_context=_write_context(
                revision=self.completion_plan.revision,
                key="closed-loop-complete-001",
            ),
        )
        self.released = self.goal.leases.release(
            self.todo_id,
            write_context=_write_context(
                revision=self.lease_revision,
                key="application-fixture-turn-001",
            ),
        )
        return {
            "ok": True,
            "appended": True,
            "classification": result.classification,
        }

    def spend(self, plan: TurnPlan) -> Mapping[str, object]:
        assert self.goal is not None
        assert plan.selected_todo_id == self.todo_id
        self.calls.append("spend")
        self.spend_plan = self.goal.quota.preview_spend(
            slots=1,
            agent_id=PRIMARY_AGENT_ID,
        )
        self.spent = self.goal.quota.apply_spend(
            self.spend_plan,
            write_context=_write_context(
                revision=self.spend_plan.revision,
                key="closed-loop-spend-001",
            ),
        )
        return {
            "ok": True,
            "appended": self.spent.written,
            "generated_at": self.spent.event_generated_at,
            "slots": self.spent.slots,
        }

    def schedule(
        self,
        plan: TurnPlan,
        spend: Mapping[str, object],
    ) -> Mapping[str, object]:
        assert plan.selected_todo_id == self.todo_id
        assert spend.get("slots") == 1
        self.calls.append("schedule")
        return {
            "completed": True,
            "acknowledged": False,
            "apply_needed": False,
            "disposition": "not_required",
        }


def _write_context(*, revision: str, key: str) -> WriteContext:
    return WriteContext(
        actor=PRIMARY_AGENT_ID,
        idempotency_key=key,
        expected_revision=revision,
    )


def _assert_public_dtos(
    values: tuple[object, ...],
    *,
    fixture: ClosedLoopFixture,
) -> None:
    payload = [asdict(value) for value in values]  # type: ignore[arg-type]
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, (list, tuple)):
            return set().union(*(keys(item) for item in value))
        return set()

    assert FORBIDDEN_DTO_KEYS.isdisjoint(keys(payload))
    assert PRIVATE_SENTINEL not in serialized
    for path in (
        fixture.root,
        fixture.project,
        fixture.registry_path,
        fixture.runtime_root,
        *fixture.state_files.values(),
    ):
        assert str(path) not in serialized


def test_typed_application_closed_loop_plans_then_commits_and_verifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    source = AdmittedEnvelopeSource(
        private_text=f"Inspect {fixture.project}/private.txt; {PRIVATE_SENTINEL}",
    )
    executor = ClosedLoopExecutor()
    coordinator = ClosedLoopCoordinator()
    application = LoopXApplication(
        ApplicationContext(
            registry_path=fixture.registry_path,
            runtime_root_override=str(fixture.runtime_root),
            scan_roots=(fixture.project,),
            profile=Profile.CLI,
            clock=lambda: FIXED_UTC_TIME,
            turn_envelope_source=source,
            turn_executor=executor,
            turn_commit_coordinator=coordinator,
        )
    )
    goal = application.get_goal(PRIMARY_GOAL_ID)

    # Observe: read fresh status, todos, and verification history.
    before_status = goal.status()
    before_todos = goal.todos.list(
        status="open",
        todo_id=fixture.todo_ids["primary_next"],
        agent_id=PRIMARY_AGENT_ID,
    )
    before_history = goal.history.list(page_size=10)
    assert before_status.status == "active"
    assert len(before_todos.items) == 1
    selected = before_todos.items[0]
    assert selected.todo_id == fixture.todo_ids["primary_next"]
    assert selected.claimed_by == PRIMARY_AGENT_ID
    assert before_history.total_count == 1

    # Admit: obtain the live quota decision through the goal handle.
    admission = goal.quota.should_run(agent_id=PRIMARY_AGENT_ID)
    assert admission.should_run is True
    assert admission.selected_todo_id == selected.todo_id
    assert admission.budget.spent_slots == 0
    source.bind(admission)

    # Coordinate: replay the existing owner claim and lease without changing state.
    claim = goal.todos.claim(
        selected.todo_id,
        write_context=_write_context(
            revision=before_todos.revision,
            key="closed-loop-claim-001",
        ),
    )
    assert claim.changed is False
    assert claim.item is not None
    assert claim.item.claimed_by == PRIMARY_AGENT_ID

    lease_before = goal.leases.inspect(selected.todo_id)
    assert lease_before.active is True
    assert lease_before.lease is not None
    lease = goal.leases.acquire(
        selected.todo_id,
        write_context=_write_context(
            revision=lease_before.lease.revision,
            key="application-fixture-turn-001",
        ),
        ttl_seconds=3600,
        write_scopes=("tests/application/**",),
    )
    assert lease.changed is False
    assert lease.idempotent is True
    assert lease.lease == lease_before.lease

    coordinator.bind(
        goal=goal,
        todo_id=selected.todo_id,
        lease_revision=lease_before.lease.revision,
    )

    # Execute/Commit: the fake provider runs one bounded Turn. Application/Core
    # independently validates, writes state, spends quota, and closes scheduling.
    turn_request = TurnPlanRequest(
        agent_id=PRIMARY_AGENT_ID,
        turn_instance_id="application-closed-loop-turn-001",
        host=TurnHost.GENERIC_CLI,
        execution_mode=TurnExecutionMode.ISOLATED_HEADLESS,
    )
    turn = goal.turns.plan(turn_request)
    assert turn.route == "ready_for_host"
    assert turn.core_contract_valid is True
    assert turn.can_run is True
    assert turn.selected_todo_id == selected.todo_id
    assert source.calls == [(PRIMARY_GOAL_ID, PRIMARY_AGENT_ID)]
    assert executor.requests == []
    assert coordinator.calls == []

    spend_event_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    monkeypatch.setattr(
        "loopx.control_plane.quota.slot_accounting._now_local",
        lambda: spend_event_time,
    )
    turn_write_context = _write_context(
        revision=turn.revision,
        key=turn_request.turn_instance_id,
    )
    execution = goal.turns.run_once(
        turn,
        request=turn_request,
        write_context=turn_write_context,
        execute=True,
    )
    replay = goal.turns.run_once(
        turn,
        request=turn_request,
        write_context=turn_write_context,
        execute=True,
    )
    assert execution.ok is True
    assert execution.status == "committed"
    assert execution.validation is not None
    assert execution.validation.status == "passed"
    assert execution.effects.host_invoked is True
    assert execution.effects.state_written is True
    assert execution.effects.quota_spent is True
    assert replay.replayed is True
    assert replay.effects.host_invoked is False
    assert replay.effects.state_written is False
    assert replay.effects.quota_spent is False
    assert len(executor.requests) == 1
    assert coordinator.calls == ["validate_task", "writeback", "spend", "schedule"]
    assert source.calls == [
        (PRIMARY_GOAL_ID, PRIMARY_AGENT_ID),
        (PRIMARY_GOAL_ID, PRIMARY_AGENT_ID),
    ]

    completion_plan = coordinator.completion_plan
    completed = coordinator.completed
    released = coordinator.released
    spend_plan = coordinator.spend_plan
    spent = coordinator.spent
    assert completion_plan is not None
    assert completed is not None
    assert released is not None
    assert spend_plan is not None
    assert spent is not None
    assert completion_plan.can_apply is True
    assert len(completion_plan.successor_todo_ids) == 1
    assert completed.item is not None
    assert completed.item.status == "done"
    assert completed.successor_todo_ids == completion_plan.successor_todo_ids
    assert released.changed is True
    assert released.lease is not None
    assert released.lease.active is False
    assert spend_plan.can_apply is True
    assert spend_plan.before.spent_slots == 0
    assert spend_plan.after is not None
    assert spend_plan.after.spent_slots == 1
    assert spent.written is True
    assert spent.event_generated_at == spend_event_time

    # Verify: observe the successor, status revision, accounting, and history receipt.
    after_status = goal.status()
    after_todos = goal.todos.list()
    after_admission = goal.quota.should_run(agent_id=PRIMARY_AGENT_ID)
    after_history = goal.history.list(page_size=10)
    lease_after = goal.leases.inspect(selected.todo_id)
    successor_id = completed.successor_todo_ids[0]
    todos_by_id = {item.todo_id: item for item in after_todos.items}

    assert after_status.revision != before_status.revision
    assert todos_by_id[selected.todo_id].status == "done"
    assert todos_by_id[successor_id].status == "open"
    assert todos_by_id[successor_id].claimed_by == PRIMARY_AGENT_ID
    assert after_admission.budget.spent_slots == 1
    assert after_history.total_count == before_history.total_count + 1
    assert after_history.items[0].classification == "quota_slot_spent"
    assert after_history.items[0].agent_id == PRIMARY_AGENT_ID
    assert after_history.items[0].artifacts_verified is True
    assert lease_after.active is False
    assert len(executor.requests) == 1
    assert coordinator.calls == ["validate_task", "writeback", "spend", "schedule"]

    _assert_public_dtos(
        (
            before_status,
            before_todos,
            before_history,
            admission,
            claim,
            lease_before,
            lease,
            turn,
            execution,
            replay,
            completion_plan,
            completed,
            released,
            spend_plan,
            spent,
            after_status,
            after_todos,
            after_admission,
            after_history,
            lease_after,
        ),
        fixture=fixture,
    )
