from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any

import pytest

from loopx.application import (
    ApplicationContext,
    AuthorityDenied,
    CapabilityUnavailable,
    Profile,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.turns import (
    GoalTurnService,
    TurnCommitCoordinator,
    TurnExecutionMode,
    TurnExecutionResult,
    TurnExecutor,
    TurnHost,
    TurnHostRequest,
    TurnHostResult,
    TurnPlan,
    TurnPlanRequest,
)
from loopx.control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)


GOAL_ID = "application-turn-goal"
AGENT_ID = "codex-turn-fixture"
FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _write_registry(
    path: Path,
    *,
    runtime_root: Path,
    goals: list[dict[str, object]],
    registry_role: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": 1,
        "common_runtime_root": str(runtime_root),
        "goals": goals,
    }
    if registry_role is not None:
        payload["registry_role"] = registry_role
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _state_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / "runtime"
    source_registry = _write_registry(
        tmp_path / "source" / ".loopx" / "registry.json",
        runtime_root=runtime_root,
        goals=[
            {
                "id": GOAL_ID,
                "status": "active",
                "domain": "application-turn-fixture",
                "adapter": {"kind": "generic_project_goal_v0"},
            }
        ],
    )
    global_registry = _write_registry(
        runtime_root / "registry.global.json",
        runtime_root=runtime_root,
        goals=[
            {
                "id": GOAL_ID,
                "status": "active",
                "domain": "application-turn-fixture",
                "adapter": {"kind": "generic_project_goal_v0"},
                "source_registry": str(source_registry.resolve()),
            }
        ],
        registry_role="global-local",
    )
    return source_registry, global_registry, runtime_root


def _envelope(
    *,
    should_run: bool = True,
    todo_id: str = "todo_turn_fixture_001",
    signature: str = "sha256:turn-fixture-v1",
) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": "loopx_turn_envelope_v0",
        "goal_id": GOAL_ID,
        "agent_id": AGENT_ID,
        "should_run": should_run,
        "effective_action": "normal_run" if should_run else "wait",
        "action": {
            "must_attempt": should_run,
            "delivery_allowed": should_run,
            "quiet_noop_allowed": not should_run,
            "selected_todo": {
                "todo_id": todo_id,
                "text": "Advance one bounded public fixture",
            },
        },
        "user": {
            "action_required": False,
            "open_count": 0,
            "notify": "DONT_NOTIFY",
        },
        "writeback": {"spend_after_validation": True},
        "scheduler": {"action": "run_now" if should_run else "wait"},
        "action_signature": {
            "matches": True,
            "source_hash": signature,
            "envelope_hash": signature,
        },
        "compaction": {"within_budget": True},
    }


class RecordingRouteResolver:
    def __init__(self) -> None:
        self.runtime_overrides: list[str | None] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.runtime_overrides.append(kwargs.get("runtime_root_override"))
        return resolve_goal_source_runtime_route(**kwargs)


class MutableEnvelopeSource:
    def __init__(self, envelope: dict[str, object]) -> None:
        self.envelope = envelope
        self.calls: list[dict[str, object]] = []

    def load_turn_envelope(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
        agent_id: str,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "registry_path": registry_path,
                "runtime_root": runtime_root,
                "goal_id": goal_id,
                "agent_id": agent_id,
            }
        )
        return deepcopy(self.envelope)


class CommitRaceEnvelopeSource(MutableEnvelopeSource):
    """Hold one re-plan until another same-key caller has committed."""

    def __init__(self, envelope: dict[str, object]) -> None:
        super().__init__(envelope)
        self.replan_blocked = Event()
        self.release_replan = Event()
        self._call_count = 0
        self._call_lock = Lock()

    def load_turn_envelope(self, **kwargs: Any) -> dict[str, object]:
        with self._call_lock:
            self._call_count += 1
            call_number = self._call_count
        if call_number == 2:
            self.replan_blocked.set()
            if not self.release_replan.wait(timeout=5):
                raise RuntimeError("timed out waiting for the competing Turn commit")
        return super().load_turn_envelope(**kwargs)


class ExplodingEnvelopeSource:
    def load_turn_envelope(self, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("provider failed with private internal context")


class FakeExecutor:
    def __init__(self) -> None:
        self.requests: list[TurnHostRequest] = []

    def execute(self, request: TurnHostRequest) -> TurnHostResult:
        self.requests.append(request)
        return TurnHostResult(turn_key=request.turn_key, result_kind="wait")


class FakeCommitCoordinator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate_task(
        self,
        _plan: TurnPlan,
        _result: TurnHostResult,
    ) -> dict[str, object]:
        self.calls.append("validate_task")
        return {
            "status": "passed",
            "validator_kind": "fixture",
            "summary": "public fixture passed",
        }

    def writeback(self, _result: TurnHostResult) -> dict[str, object]:
        self.calls.append("writeback")
        return {"ok": True, "appended": True}

    def spend(self, _plan: TurnPlan) -> dict[str, object]:
        self.calls.append("spend")
        return {"ok": True, "appended": True, "slots": 1}

    def schedule(
        self,
        _plan: TurnPlan,
        _spend: dict[str, object],
    ) -> dict[str, object]:
        self.calls.append("schedule")
        return {"completed": True, "acknowledged": False}


class MaterialExecutor(FakeExecutor):
    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    def execute(self, request: TurnHostRequest) -> TurnHostResult:
        self.requests.append(request)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return TurnHostResult(
            turn_key=request.turn_key,
            result_kind="validated_progress",
            classification="fixture_progress",
            recommended_action="Continue the bounded fixture",
            next_action="Verify the next bounded fixture state",
            delivery_batch_scale="implementation",
            delivery_outcome="outcome_progress",
            vision_unchanged_reason="The fixture objective remains unchanged.",
            summary="One bounded fixture step completed.",
        )


class InterruptingSpendCoordinator(FakeCommitCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.interrupt_next_spend = True

    def spend(self, _plan: TurnPlan) -> dict[str, object]:
        self.calls.append("spend")
        if self.interrupt_next_spend:
            self.interrupt_next_spend = False
            raise SystemExit(17)
        return {"ok": True, "appended": True, "slots": 1}


class EnvelopeMutatingCoordinator(FakeCommitCoordinator):
    def __init__(self, source: CommitRaceEnvelopeSource) -> None:
        super().__init__()
        self.source = source

    def writeback(self, result: TurnHostResult) -> dict[str, object]:
        payload = super().writeback(result)
        self.source.envelope = _envelope(
            todo_id="todo_turn_fixture_after_commit",
            signature="sha256:after-commit",
        )
        self.source.release_replan.set()
        return payload


def _request(*, turn_instance_id: str = "application-turn-001") -> TurnPlanRequest:
    return TurnPlanRequest(
        agent_id=AGENT_ID,
        turn_instance_id=turn_instance_id,
        host=TurnHost.GENERIC_CLI,
        execution_mode=TurnExecutionMode.ISOLATED_HEADLESS,
    )


def _write_context(plan: TurnPlan, request: TurnPlanRequest) -> WriteContext:
    return WriteContext(
        actor=request.agent_id,
        idempotency_key=request.turn_instance_id,
        expected_revision=plan.revision,
    )


def _service(
    tmp_path: Path,
    *,
    envelope: dict[str, object] | None = None,
    profile: Profile = Profile.CLI,
    executor: FakeExecutor | None = None,
    coordinator: FakeCommitCoordinator | None = None,
    envelope_source: MutableEnvelopeSource | None = None,
) -> tuple[
    GoalTurnService,
    MutableEnvelopeSource,
    RecordingRouteResolver,
    Path,
    Path,
]:
    source_registry, global_registry, _runtime_root = _state_tree(tmp_path)
    override_runtime = tmp_path / "operator-runtime-override"
    route_resolver = RecordingRouteResolver()
    envelope_source = envelope_source or MutableEnvelopeSource(envelope or _envelope())
    context = ApplicationContext(
        registry_path=global_registry,
        runtime_root_override=str(override_runtime),
        profile=profile,
        clock=lambda: FIXED_NOW,
        turn_envelope_source=envelope_source,
        turn_executor=executor,
        turn_commit_coordinator=coordinator,
        resolve_goal_route=route_resolver,
    )
    service = GoalTurnService(
        context=context,
        goal_id=GOAL_ID,
        envelope_source=envelope_source,
        executor=executor,
        commit_coordinator=coordinator,
    )
    return service, envelope_source, route_resolver, source_registry, override_runtime


def test_plan_projects_ready_route_from_fresh_canonical_source_without_paths(
    tmp_path: Path,
) -> None:
    executor = FakeExecutor()
    coordinator = FakeCommitCoordinator()
    service, source, resolver, source_registry, override_runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )

    plan = service.plan(_request())

    assert isinstance(plan, TurnPlan)
    assert plan.goal_id == GOAL_ID
    assert plan.agent_id == AGENT_ID
    assert plan.generated_at == "2026-01-02T03:04:05Z"
    assert plan.route == "ready_for_host"
    assert plan.canonical_route_status == "source_registry"
    assert plan.routed_to_source_registry is True
    assert plan.core_contract_valid is True
    assert plan.would_invoke_host is True
    assert plan.can_run is True
    assert plan.execution_authorized is True
    assert plan.executor_available is True
    assert plan.commit_coordinator_available is True
    assert plan.turn_key.startswith("sha256:")
    assert plan.selected_todo_id == "todo_turn_fixture_001"
    assert plan.unavailable_reasons == ()
    assert resolver.runtime_overrides == [None]
    assert source.calls == [
        {
            "registry_path": source_registry.resolve(),
            "runtime_root": override_runtime.resolve(),
            "goal_id": GOAL_ID,
            "agent_id": AGENT_ID,
        }
    ]
    assert executor.requests == []
    serialized = json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "command" not in serialized
    assert "argv" not in serialized


def test_plan_projects_gated_wait_without_calling_executor(tmp_path: Path) -> None:
    executor = FakeExecutor()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        envelope=_envelope(should_run=False),
        executor=executor,
        coordinator=FakeCommitCoordinator(),
    )

    plan = service.plan(_request())

    assert plan.core_contract_valid is True
    assert plan.route == "wait"
    assert plan.would_invoke_host is False
    assert plan.can_run is False
    assert plan.unavailable_reasons == ("route_not_host_executable",)
    assert executor.requests == []


def test_plan_refreshes_route_and_envelope_on_every_operation(tmp_path: Path) -> None:
    service, source, resolver, _registry, _runtime = _service(
        tmp_path,
        executor=FakeExecutor(),
        coordinator=FakeCommitCoordinator(),
    )
    request = _request()

    first = service.plan(request)
    source.envelope = _envelope(
        todo_id="todo_turn_fixture_002",
        signature="sha256:turn-fixture-v2",
    )
    second = service.plan(request)

    assert resolver.runtime_overrides == [None, None]
    assert len(source.calls) == 2
    assert first.selected_todo_id == "todo_turn_fixture_001"
    assert second.selected_todo_id == "todo_turn_fixture_002"
    assert first.revision != second.revision
    assert first.plan_hash != second.plan_hash
    assert first.turn_key != second.turn_key


def test_plan_reports_executor_and_authority_gates(tmp_path: Path) -> None:
    unavailable, _source, _resolver, _registry, _runtime = _service(
        tmp_path / "unavailable",
        executor=None,
        coordinator=FakeCommitCoordinator(),
    )
    denied, _source, _resolver, _registry, _runtime = _service(
        tmp_path / "denied",
        profile=Profile.HTTP_LOCAL_OPERATOR,
        executor=FakeExecutor(),
        coordinator=FakeCommitCoordinator(),
    )

    unavailable_plan = unavailable.plan(_request(turn_instance_id="unavailable-001"))
    denied_plan = denied.plan(_request(turn_instance_id="denied-001"))

    assert unavailable_plan.can_run is False
    assert unavailable_plan.unavailable_reasons == ("executor_unavailable",)
    assert denied_plan.can_run is False
    assert denied_plan.unavailable_reasons == ("profile_execution_denied",)


def test_run_once_preview_is_pure_and_does_not_require_execution_providers(
    tmp_path: Path,
) -> None:
    service, _source, _resolver, _registry, override_runtime = _service(
        tmp_path,
        executor=None,
        coordinator=None,
    )
    request = _request(turn_instance_id="preview-only-001")
    plan = service.plan(request)

    result = service.run_once(
        plan,
        request=request,
        write_context=_write_context(plan, request),
        execute=False,
    )

    assert isinstance(result, TurnExecutionResult)
    assert result.ok is True
    assert result.status == "preview"
    assert result.dry_run is True
    assert result.replayed is False
    assert result.validation is None
    assert result.receipt is None
    assert result.effects.host_invoked is False
    assert result.effects.state_written is False
    assert result.effects.quota_spent is False
    assert result.correctness.atomic_revision_check is False
    assert result.correctness.idempotent_retry is True
    assert not override_runtime.exists()


def test_run_once_commits_and_replays_same_turn_without_duplicate_effects(
    tmp_path: Path,
) -> None:
    executor = MaterialExecutor()
    coordinator = FakeCommitCoordinator()
    service, source, _resolver, _registry, override_runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="commit-replay-001")
    plan = service.plan(request)
    write_context = _write_context(plan, request)

    committed = service.run_once(
        plan,
        request=request,
        write_context=write_context,
        execute=True,
    )
    replayed = service.run_once(
        plan,
        request=request,
        write_context=write_context,
        execute=True,
    )

    assert committed.ok is True
    assert committed.status == "committed"
    assert committed.result_kind == "validated_progress"
    assert committed.validation is not None
    assert committed.validation.status == "passed"
    assert committed.receipt is not None
    assert committed.receipt.status == "committed"
    assert committed.receipt.completed_phases[-1] == "scheduler_ack"
    assert committed.effects.host_invoked is True
    assert committed.effects.state_written is True
    assert committed.effects.quota_spent is True
    assert committed.quota_slot_spend_count == 1
    assert replayed.ok is True
    assert replayed.status == "committed"
    assert replayed.replayed is True
    assert replayed.quota_slot_spend_count == 1
    assert not any(asdict(replayed.effects).values())
    assert len(executor.requests) == 1
    assert coordinator.calls == ["validate_task", "writeback", "spend", "schedule"]
    assert len(source.calls) == 2
    journal_paths = list(
        (override_runtime / "goals" / GOAL_ID / "turns").glob("*.json")
    )
    assert len(journal_paths) == 1
    serialized = json.dumps(asdict(committed), ensure_ascii=False, sort_keys=True)
    assert str(tmp_path) not in serialized


def test_run_once_rejects_forged_plan_semantics_even_with_matching_hashes(
    tmp_path: Path,
) -> None:
    coordinator = FakeCommitCoordinator()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=MaterialExecutor(),
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="forged-plan-001")
    plan = service.plan(request)
    forged = replace(plan, selected_todo_id="todo_turn_fixture_forged")

    with pytest.raises(RevisionConflict) as conflict:
        service.run_once(
            forged,
            request=request,
            write_context=WriteContext(
                actor=request.agent_id,
                idempotency_key=request.turn_instance_id,
                expected_revision=forged.revision,
            ),
            execute=True,
        )

    assert conflict.value.details["reason"] == "plan_mismatch"
    assert coordinator.calls == []


def test_run_once_rejects_invalid_turn_key_before_journal_or_provider_access(
    tmp_path: Path,
) -> None:
    executor = FakeExecutor()
    coordinator = FakeCommitCoordinator()
    service, source, _resolver, _registry, runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="invalid-turn-key-001")
    plan = service.plan(request)
    forged = replace(plan, turn_key="not-a-turn-key")

    with pytest.raises(ValidationFailed) as invalid:
        service.run_once(
            forged,
            request=request,
            write_context=_write_context(forged, request),
            execute=True,
        )

    assert invalid.value.details == {"field": "plan.turn_key"}
    assert len(source.calls) == 1
    assert executor.requests == []
    assert coordinator.calls == []
    assert not (runtime / "goals" / GOAL_ID / "turns").exists()


def test_run_once_recovers_partial_closeout_without_reinvoking_host_or_writeback(
    tmp_path: Path,
) -> None:
    executor = MaterialExecutor()
    coordinator = InterruptingSpendCoordinator()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="partial-recovery-001")
    plan = service.plan(request)
    kwargs = {
        "request": request,
        "write_context": _write_context(plan, request),
        "execute": True,
    }

    with pytest.raises(SystemExit):
        service.run_once(plan, **kwargs)
    recovered = service.run_once(plan, **kwargs)

    assert recovered.status == "committed"
    assert len(executor.requests) == 1
    assert coordinator.calls == [
        "validate_task",
        "writeback",
        "spend",
        "spend",
        "schedule",
    ]


def test_run_once_rejects_stale_plan_before_invoking_executor(tmp_path: Path) -> None:
    executor = MaterialExecutor()
    service, source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=FakeCommitCoordinator(),
    )
    request = _request(turn_instance_id="stale-plan-001")
    plan = service.plan(request)
    source.envelope = _envelope(
        todo_id="todo_turn_fixture_concurrent_writer",
        signature="sha256:concurrent-writer",
    )

    with pytest.raises(RevisionConflict) as conflict:
        service.run_once(
            plan,
            request=request,
            write_context=_write_context(plan, request),
            execute=True,
        )

    assert conflict.value.details["reason"] == "stale_revision"
    assert executor.requests == []


def test_run_once_enforces_execution_authority_and_provider_availability(
    tmp_path: Path,
) -> None:
    request = _request(turn_instance_id="execution-gates-001")
    missing, _source, _resolver, _registry, _runtime = _service(
        tmp_path / "missing",
        executor=None,
        coordinator=FakeCommitCoordinator(),
    )
    missing_plan = missing.plan(request)
    with pytest.raises(CapabilityUnavailable) as unavailable:
        missing.run_once(
            missing_plan,
            request=request,
            write_context=_write_context(missing_plan, request),
            execute=True,
        )
    assert unavailable.value.details["reason"] == "executor_unavailable"

    denied, _source, _resolver, _registry, _runtime = _service(
        tmp_path / "denied",
        profile=Profile.HTTP_LOCAL_OPERATOR,
        executor=MaterialExecutor(),
        coordinator=FakeCommitCoordinator(),
    )
    denied_plan = denied.plan(request)
    with pytest.raises(AuthorityDenied) as authority:
        denied.run_once(
            denied_plan,
            request=request,
            write_context=_write_context(denied_plan, request),
            execute=True,
        )
    assert authority.value.details["reason"] == "profile_execution_denied"


def test_terminal_journal_replay_remains_execution_provider_gated(
    tmp_path: Path,
) -> None:
    executor = MaterialExecutor()
    coordinator = FakeCommitCoordinator()
    service, source, resolver, _registry, _runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="provider-gated-replay-001")
    plan = service.plan(request)
    committed = service.run_once(
        plan,
        request=request,
        write_context=_write_context(plan, request),
        execute=True,
    )
    assert committed.status == "committed"

    unavailable = GoalTurnService(
        context=service.context,
        goal_id=GOAL_ID,
        envelope_source=source,
        executor=None,
        commit_coordinator=coordinator,
    )
    with pytest.raises(CapabilityUnavailable) as blocked:
        unavailable.run_once(
            plan,
            request=request,
            write_context=_write_context(plan, request),
            execute=True,
        )

    assert blocked.value.details["reason"] == "executor_unavailable"
    assert len(executor.requests) == 1
    assert len(resolver.runtime_overrides) >= 1


def test_run_once_binds_write_identity_to_agent_turn_and_revision(
    tmp_path: Path,
) -> None:
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=MaterialExecutor(),
        coordinator=FakeCommitCoordinator(),
    )
    request = _request(turn_instance_id="write-identity-001")
    plan = service.plan(request)

    with pytest.raises(AuthorityDenied):
        service.run_once(
            plan,
            request=request,
            write_context=WriteContext(
                actor="codex-other-agent",
                idempotency_key=request.turn_instance_id,
                expected_revision=plan.revision,
            ),
            execute=True,
        )
    with pytest.raises(ValidationFailed) as invalid_key:
        service.run_once(
            plan,
            request=request,
            write_context=WriteContext(
                actor=request.agent_id,
                idempotency_key="different-logical-turn",
                expected_revision=plan.revision,
            ),
            execute=True,
        )
    assert invalid_key.value.details["reason"] == "must_match_turn_instance_id"
    with pytest.raises(RevisionConflict):
        service.run_once(
            plan,
            request=request,
            write_context=WriteContext(
                actor=request.agent_id,
                idempotency_key=request.turn_instance_id,
                expected_revision=f"sha256:{'0' * 64}",
            ),
            execute=True,
        )


def test_concurrent_same_turn_is_single_flight_and_second_call_replays(
    tmp_path: Path,
) -> None:
    executor = MaterialExecutor(delay_seconds=0.1)
    coordinator = FakeCommitCoordinator()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
    )
    request = _request(turn_instance_id="concurrent-single-flight-001")
    plan = service.plan(request)
    write_context = _write_context(plan, request)

    def invoke() -> TurnExecutionResult:
        return service.run_once(
            plan,
            request=request,
            write_context=write_context,
            execute=True,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: invoke(), range(2)))

    assert [result.status for result in results] == ["committed", "committed"]
    assert sorted(result.replayed for result in results) == [False, True]
    assert len(executor.requests) == 1
    assert coordinator.calls.count("writeback") == 1
    assert coordinator.calls.count("spend") == 1


def test_same_turn_replays_when_replan_finishes_after_competing_commit(
    tmp_path: Path,
) -> None:
    source = CommitRaceEnvelopeSource(_envelope())
    coordinator = EnvelopeMutatingCoordinator(source)
    executor = MaterialExecutor()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=executor,
        coordinator=coordinator,
        envelope_source=source,
    )
    request = _request(turn_instance_id="replan-after-commit-001")
    plan = service.plan(request)
    write_context = _write_context(plan, request)

    def invoke() -> TurnExecutionResult:
        return service.run_once(
            plan,
            request=request,
            write_context=write_context,
            execute=True,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        delayed = pool.submit(invoke)
        assert source.replan_blocked.wait(timeout=5)
        committed = invoke()
        replayed = delayed.result(timeout=5)

    assert committed.status == "committed"
    assert committed.replayed is False
    assert replayed.status == "committed"
    assert replayed.replayed is True
    assert len(executor.requests) == 1
    assert coordinator.calls.count("writeback") == 1
    assert coordinator.calls.count("spend") == 1


def test_plan_omits_unsafe_selected_todo_identity_and_blocks_execution(
    tmp_path: Path,
) -> None:
    unsafe_id = "/private/tmp/private.txt " + "to" + "ken=abcdefghijklmnop"
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        envelope=_envelope(todo_id=unsafe_id),
        executor=FakeExecutor(),
        coordinator=FakeCommitCoordinator(),
    )

    plan = service.plan(_request())

    assert plan.selected_todo_id is None
    assert plan.can_run is False
    assert "selected_todo_invalid" in plan.unavailable_reasons
    serialized = json.dumps(asdict(plan), ensure_ascii=False, sort_keys=True)
    assert "/private/tmp/private.txt" not in serialized
    assert "abcdefghijklmnop" not in serialized


def test_turn_service_validates_direct_providers_and_wraps_provider_failure(
    tmp_path: Path,
) -> None:
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        executor=FakeExecutor(),
        coordinator=FakeCommitCoordinator(),
    )

    with pytest.raises(ValidationFailed) as invalid:
        GoalTurnService(
            context=service.context,
            goal_id=GOAL_ID,
            envelope_source=ExplodingEnvelopeSource(),
            executor=object(),  # type: ignore[arg-type]
            commit_coordinator=FakeCommitCoordinator(),
        )
    assert invalid.value.details == {"field": "executor", "method": "execute"}

    failed = GoalTurnService(
        context=service.context,
        goal_id=GOAL_ID,
        envelope_source=ExplodingEnvelopeSource(),
        executor=FakeExecutor(),
        commit_coordinator=FakeCommitCoordinator(),
    )
    with pytest.raises(StateUnavailable) as unavailable:
        failed.plan(_request())
    assert unavailable.value.details == {
        "resource": "turn_envelope",
        "goal_id": GOAL_ID,
        "error_type": "RuntimeError",
    }


def test_turn_plan_request_rejects_non_json_session_binding() -> None:
    with pytest.raises(ValidationFailed) as invalid:
        TurnPlanRequest(
            agent_id=AGENT_ID,
            turn_instance_id="non-json-session-binding-001",
            host=TurnHost.GENERIC_CLI,
            execution_mode=TurnExecutionMode.ISOLATED_HEADLESS,
            session_binding={"native_handle": object()},
        )

    assert invalid.value.details == {
        "field": "session_binding",
        "reason": "not_json_compatible",
    }


def test_turn_plan_rejects_non_json_envelope_provider_packet(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope["provider_private_handle"] = object()
    executor = FakeExecutor()
    service, _source, _resolver, _registry, _runtime = _service(
        tmp_path,
        envelope=envelope,
        executor=executor,
        coordinator=FakeCommitCoordinator(),
    )

    with pytest.raises(StateUnavailable) as invalid:
        service.plan(_request(turn_instance_id="non-json-envelope-001"))

    assert invalid.value.details == {
        "resource": "turn_envelope",
        "goal_id": GOAL_ID,
        "cause": "not_json_compatible",
    }
    assert executor.requests == []


def test_provider_protocols_are_typed_and_command_free() -> None:
    executor = FakeExecutor()
    coordinator = FakeCommitCoordinator()
    envelope = _envelope()
    request = TurnHostRequest(
        turn_key=f"sha256:{'a' * 64}",
        route="ready_for_host",
        session={"action": "start_new"},
        turn_envelope=envelope,
        result_contract={"schema_version": "loopx_turn_result_v0"},
    )

    assert isinstance(executor, TurnExecutor)
    assert isinstance(coordinator, TurnCommitCoordinator)
    assert [field.name for field in fields(TurnPlanRequest)] == [
        "agent_id",
        "turn_instance_id",
        "host",
        "execution_mode",
        "scheduler_owner",
        "session_binding",
    ]
    assert not {"command", "argv", "project", "runtime_root"} & {
        field.name for field in fields(TurnHostRequest)
    }
    assert request.turn_envelope["goal_id"] == GOAL_ID
    envelope["goal_id"] = "mutated-after-construction"
    assert request.turn_envelope["goal_id"] == GOAL_ID
    result = executor.execute(request)
    assert isinstance(result, TurnHostResult)
    assert result.turn_key == request.turn_key


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary", "to" + "ken=abcdefghijklmnop"),
        ("recommended_action", "/Users/example/private.txt"),
        ("next_action", "/etc/shadow"),
        ("result_kind", "unsupported-result"),
        ("turn_key", "not-a-turn-key"),
    ],
)
def test_turn_host_result_rejects_unsafe_or_invalid_provider_output(
    field: str,
    value: str,
) -> None:
    values = {
        "turn_key": f"sha256:{'a' * 64}",
        "result_kind": "wait",
        field: value,
    }

    with pytest.raises(ValidationFailed) as raised:
        TurnHostResult(**values)

    assert raised.value.details["field"] == field
