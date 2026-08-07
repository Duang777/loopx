from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from loopx.application import (
    ApplicationContext,
    AuthorityDenied,
    Profile,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.quota import (
    GoalQuotaService,
    QuotaApplyResult,
    QuotaDecision,
    QuotaMutationPlan,
)
from loopx.control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)

from .fixtures import (
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    SECONDARY_AGENT_ID,
    SECONDARY_GOAL_ID,
    materialize_closed_loop_fixture,
)
from .fixtures.closed_loop import FIXED_UTC_TIME, ClosedLoopFixture


FORBIDDEN_PROJECTION_FIELDS = {
    "index_path",
    "json_path",
    "logs",
    "markdown_path",
    "payload",
    "raw",
    "registry",
    "runtime_root",
    "source_registry",
    "state_file",
}
SECRET_LIKE_TEXT = "sk-" + "1" * 16


def _service(
    fixture: ClosedLoopFixture,
    goal_id: str = PRIMARY_GOAL_ID,
    *,
    profile: Profile = Profile.CLI,
    resolver: Any = resolve_goal_source_runtime_route,
) -> GoalQuotaService:
    return GoalQuotaService(
        context=ApplicationContext(
            registry_path=fixture.registry_path,
            runtime_root_override=str(fixture.runtime_root),
            scan_roots=(fixture.project,),
            profile=profile,
            clock=lambda: FIXED_UTC_TIME,
            resolve_goal_route=resolver,
        ),
        goal_id=goal_id,
    )


def _assert_public_projection(value: object, fixture: ClosedLoopFixture) -> None:
    payload = asdict(value)  # type: ignore[arg-type]
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert FORBIDDEN_PROJECTION_FIELDS.isdisjoint(payload)
    assert all(
        not isinstance(getattr(value, field.name), dict) for field in fields(value)
    )
    for path in (
        fixture.root,
        fixture.project,
        fixture.registry_path,
        fixture.runtime_root,
        *fixture.state_files.values(),
    ):
        assert str(path) not in serialized


def _index_record_count(fixture: ClosedLoopFixture, goal_id: str) -> int:
    index_path = fixture.runtime_root / "goals" / goal_id / "runs" / "index.jsonl"
    if not index_path.exists():
        return 0
    return len(index_path.read_text(encoding="utf-8").splitlines())


def _write_context(
    revision: str,
    *,
    idempotency_key: str,
) -> WriteContext:
    return WriteContext(
        actor="application-quota-test",
        idempotency_key=idempotency_key,
        expected_revision=revision,
    )


def test_should_run_projects_live_eligible_and_gated_decisions(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    route_calls: list[tuple[str, str | None]] = []

    def counting_resolver(
        *,
        registry_path: Path,
        goal_id: str,
        runtime_root_override: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route_calls.append((goal_id, runtime_root_override))
        return resolve_goal_source_runtime_route(
            registry_path=registry_path,
            goal_id=goal_id,
            runtime_root_override=runtime_root_override,
            registry=registry,
        )

    eligible = _service(fixture, resolver=counting_resolver).should_run(
        agent_id=PRIMARY_AGENT_ID
    )
    gated = _service(
        fixture,
        SECONDARY_GOAL_ID,
        resolver=counting_resolver,
    ).should_run(agent_id=SECONDARY_AGENT_ID)

    assert route_calls == [
        (PRIMARY_GOAL_ID, None),
        (SECONDARY_GOAL_ID, None),
    ]
    assert isinstance(eligible, QuotaDecision)
    assert eligible.generated_at == FIXED_UTC_TIME
    assert eligible.should_run is True
    assert eligible.state == "eligible"
    assert eligible.decision == "run"
    assert eligible.must_attempt is True
    assert eligible.delivery_allowed is True
    assert eligible.action_required is False
    assert eligible.selected_todo_id == fixture.todo_ids["primary_next"]
    assert eligible.envelope_verified is True
    assert eligible.envelope_within_budget is True
    assert eligible.budget.spent_slots == 0
    assert eligible.budget.allowed_slots == 360

    assert isinstance(gated, QuotaDecision)
    assert gated.generated_at == FIXED_UTC_TIME
    assert gated.state == "operator_gate"
    assert gated.action_required is True
    assert gated.open_count == 1
    assert gated.effective_action == "operator_gate_notify"
    assert gated.selected_todo_id == fixture.todo_ids["secondary_agent"]
    assert gated.envelope_verified is True

    _assert_public_projection(eligible, fixture)
    _assert_public_projection(gated, fixture)


def test_quota_projection_filters_unsafe_text_and_preserves_numeric_precision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    compute = {"value": "0.123456789123456"}

    def decision_packet(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "goal_id": PRIMARY_GOAL_ID,
            "decision": "run",
            "should_run": True,
            "state": "eligible",
            "effective_action": SECRET_LIKE_TEXT,
            "reason": f"Bearer {'a' * 24}",
            "recommended_action": f"Inspect {fixture.registry_path}",
            "quota": {
                "compute": compute["value"],
                "window_hours": "12",
                "slot_minutes": "1",
                "allowed_slots": "9007199254740993",
                "spent_slots": "7",
            },
        }

    def turn_envelope(_payload: object) -> dict[str, object]:
        return {
            "action_required": False,
            "open_count": 0,
            "action": {
                "recommended_action": f"Inspect {fixture.registry_path}",
                "selected_todo": {"todo_id": f"{'to' + 'ken='}{'b' * 16}"},
                "must_attempt": True,
                "delivery_allowed": True,
                "quiet_noop_allowed": False,
            },
            "action_signature": {"matches": True},
            "compaction": {"within_budget": True},
        }

    monkeypatch.setattr(
        "loopx.application.goals.quota.build_live_quota_should_run_decision",
        decision_packet,
    )
    monkeypatch.setattr(
        "loopx.application.goals.quota.build_turn_envelope",
        turn_envelope,
    )
    service = _service(fixture)

    first = service.should_run(agent_id=PRIMARY_AGENT_ID)
    second = service.should_run(agent_id=PRIMARY_AGENT_ID)

    assert first == second
    assert first.effective_action is None
    assert first.reason is None
    assert first.recommended_action is None
    assert first.selected_todo_id is None
    assert first.budget.compute == float(compute["value"])
    assert first.budget.allowed_slots == 9_007_199_254_740_993
    assert first.budget.spent_slots == 7
    serialized = json.dumps(asdict(first), ensure_ascii=False, sort_keys=True)
    assert SECRET_LIKE_TEXT not in serialized
    assert "Bearer" not in serialized
    assert "to" + "ken=" not in serialized
    assert str(fixture.registry_path) not in serialized

    compute["value"] = "0.123456789123457"
    changed = service.should_run(agent_id=PRIMARY_AGENT_ID)
    assert changed.budget.compute == float(compute["value"])
    assert changed.revision != first.revision


@pytest.mark.parametrize("invalid_compute", ["NaN", "not-a-number", "1.25"])
def test_quota_malformed_numeric_projection_raises_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_compute: str,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)

    monkeypatch.setattr(
        "loopx.application.goals.quota.build_live_quota_should_run_decision",
        lambda *_args, **_kwargs: {
            "ok": True,
            "decision": "run",
            "should_run": True,
            "state": "eligible",
            "quota": {
                "compute": invalid_compute,
                "window_hours": 12,
                "slot_minutes": 1,
                "allowed_slots": 360,
                "spent_slots": 0,
            },
        },
    )
    monkeypatch.setattr(
        "loopx.application.goals.quota.build_turn_envelope",
        lambda _payload: {
            "action": {},
            "action_signature": {"matches": True},
            "compaction": {"within_budget": True},
        },
    )

    with pytest.raises(StateUnavailable) as raised:
        _service(fixture).should_run(agent_id=PRIMARY_AGENT_ID)

    assert raised.value.details == {
        "resource": "goal_quota",
        "field": "quota.compute",
        "cause": "invalid_numeric",
    }


def test_real_quota_config_uses_core_precision_and_changes_public_revision(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    before = service.should_run(agent_id=PRIMARY_AGENT_ID)
    registry = json.loads(fixture.registry_path.read_text(encoding="utf-8"))
    goal = next(item for item in registry["goals"] if item["id"] == PRIMARY_GOAL_ID)
    goal["quota"]["compute"] = 0.123456789123456
    fixture.registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    after = service.should_run(agent_id=PRIMARY_AGENT_ID)

    assert after.budget.compute == 0.12
    assert after.revision != before.revision


def test_spend_and_void_apply_revalidate_revision_and_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    event_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    monkeypatch.setattr(
        "loopx.control_plane.quota.slot_accounting._now_local",
        lambda: event_time,
    )

    spend_plan = service.preview_spend(
        slots=1,
        source="adapter",
        agent_id=PRIMARY_AGENT_ID,
    )

    assert isinstance(spend_plan, QuotaMutationPlan)
    assert spend_plan.can_apply is True
    assert spend_plan.source == "adapter"
    assert spend_plan.before.spent_slots == 0
    assert spend_plan.after is not None
    assert spend_plan.after.spent_slots == 1
    assert spend_plan.plan_hash.startswith("sha256:")
    assert spend_plan.correctness.status == "pending_migration"
    assert spend_plan.correctness.atomic_revision_check is False
    assert spend_plan.correctness.idempotent_retry is False
    _assert_public_projection(spend_plan, fixture)

    initial_count = _index_record_count(fixture, PRIMARY_GOAL_ID)
    with pytest.raises(RevisionConflict):
        service.apply_spend(
            spend_plan,
            write_context=_write_context(
                f"sha256:{'0' * 64}",
                idempotency_key="quota-stale-001",
            ),
        )
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count

    wrong_hash = replace(spend_plan, plan_hash=f"sha256:{'f' * 64}")
    with pytest.raises(RevisionConflict):
        service.apply_spend(
            wrong_hash,
            write_context=_write_context(
                spend_plan.revision,
                idempotency_key="quota-hash-001",
            ),
        )
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count

    spend_result = service.apply_spend(
        spend_plan,
        write_context=_write_context(
            spend_plan.revision,
            idempotency_key="quota-spend-001",
        ),
    )

    assert isinstance(spend_result, QuotaApplyResult)
    assert spend_result.written is True
    assert spend_result.source == "adapter"
    assert spend_result.event_generated_at == event_time
    assert spend_result.previous_revision == spend_plan.revision
    assert spend_result.revision != spend_plan.revision
    assert service.should_run(agent_id=PRIMARY_AGENT_ID).budget.spent_slots == 1
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count + 1
    _assert_public_projection(spend_result, fixture)

    with pytest.raises(RevisionConflict):
        service.apply_spend(
            spend_plan,
            write_context=_write_context(
                spend_plan.revision,
                idempotency_key="quota-spend-001",
            ),
        )
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count + 1

    void_plan = service.preview_void(
        voided_run_generated_at=spend_result.event_generated_at,
        reason_summary="Correct one duplicate fixture spend.",
        source="visible-goal",
        agent_id=PRIMARY_AGENT_ID,
    )
    assert void_plan.can_apply is True
    assert void_plan.source == "visible-goal"
    assert void_plan.target_generated_at == spend_result.event_generated_at
    assert void_plan.before.spent_slots == 1
    assert void_plan.after is not None
    assert void_plan.after.spent_slots == 0

    void_result = service.apply_void(
        void_plan,
        write_context=_write_context(
            void_plan.revision,
            idempotency_key="quota-void-001",
        ),
    )
    assert void_result.written is True
    assert void_result.source == "visible-goal"
    assert void_result.target_generated_at == spend_result.event_generated_at
    assert service.should_run(agent_id=PRIMARY_AGENT_ID).budget.spent_slots == 0
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count + 2
    _assert_public_projection(void_plan, fixture)
    _assert_public_projection(void_result, fixture)

    with pytest.raises(RevisionConflict):
        service.apply_void(
            void_plan,
            write_context=_write_context(
                void_plan.revision,
                idempotency_key="quota-void-001",
            ),
        )
    assert _index_record_count(fixture, PRIMARY_GOAL_ID) == initial_count + 2


@pytest.mark.parametrize(
    "failing_dependency",
    [
        "build_live_quota_should_run_decision",
        "spend_quota_slot",
    ],
)
def test_spend_apply_recalculation_reports_apply_operation_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failing_dependency: str,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    service = _service(fixture)
    plan = service.preview_spend(agent_id=PRIMARY_AGENT_ID)

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("simulated Core recalculation failure")

    monkeypatch.setattr(
        f"loopx.application.goals.quota.{failing_dependency}",
        fail,
    )

    with pytest.raises(ValidationFailed) as raised:
        service.apply_spend(
            plan,
            write_context=_write_context(
                plan.revision,
                idempotency_key=f"quota-apply-error-{failing_dependency}",
            ),
        )

    assert raised.value.details == {"operation_id": "goal.quota.spend.apply"}


def test_gated_spend_is_not_written_and_read_only_profile_denies_mutations(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    gated_service = _service(fixture, SECONDARY_GOAL_ID)
    gated_plan = gated_service.preview_spend(agent_id=SECONDARY_AGENT_ID)
    initial_count = _index_record_count(fixture, SECONDARY_GOAL_ID)

    assert gated_plan.can_apply is False
    assert gated_plan.after is None
    with pytest.raises(ValidationFailed) as gated_error:
        gated_service.apply_spend(
            gated_plan,
            write_context=_write_context(
                gated_plan.revision,
                idempotency_key="quota-gated-001",
            ),
        )
    assert gated_error.value.details == {
        "operation_id": "goal.quota.spend.apply",
        "reason": "gated",
    }
    assert _index_record_count(fixture, SECONDARY_GOAL_ID) == initial_count

    writable_plan = _service(fixture).preview_spend(agent_id=PRIMARY_AGENT_ID)
    read_only = _service(fixture, profile=Profile.HTTP_READ_ONLY)
    with pytest.raises(AuthorityDenied) as preview_error:
        read_only.preview_spend(agent_id=PRIMARY_AGENT_ID)
    with pytest.raises(AuthorityDenied) as apply_error:
        read_only.apply_spend(
            writable_plan,
            write_context=_write_context(
                writable_plan.revision,
                idempotency_key="quota-read-only-001",
            ),
        )
    assert preview_error.value.details == {
        "operation_id": "goal.quota.spend.preview",
        "profile": "http_read_only",
    }
    assert apply_error.value.details == {
        "operation_id": "goal.quota.spend.apply",
        "profile": "http_read_only",
    }

    with pytest.raises(ValidationFailed) as unsafe_reason:
        _service(fixture).preview_void(
            voided_run_generated_at=FIXED_UTC_TIME,
            reason_summary=f"Inspect {fixture.registry_path}",
            agent_id=PRIMARY_AGENT_ID,
        )
    assert unsafe_reason.value.details == {"field": "reason_summary"}

    with pytest.raises(ValidationFailed) as secret_reason:
        _service(fixture).preview_void(
            voided_run_generated_at=FIXED_UTC_TIME,
            reason_summary=f"{'to' + 'ken='}{'c' * 16}",
            agent_id=PRIMARY_AGENT_ID,
        )
    assert secret_reason.value.details == {"field": "reason_summary"}

    with pytest.raises(ValidationFailed) as secret_agent:
        _service(fixture).should_run(agent_id=SECRET_LIKE_TEXT)
    assert secret_agent.value.details == {"field": "agent_id"}

    default_source_plan = _service(fixture).preview_spend(agent_id=PRIMARY_AGENT_ID)
    assert default_source_plan.source == "heartbeat"

    with pytest.raises(ValidationFailed) as invalid_source:
        _service(fixture).preview_spend(
            source="unknown-source",
            agent_id=PRIMARY_AGENT_ID,
        )
    assert invalid_source.value.details == {
        "field": "source",
        "allowed": ("adapter", "controller", "heartbeat", "visible-goal"),
    }
