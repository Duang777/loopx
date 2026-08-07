from __future__ import annotations

import json
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Mapping

from application.fixtures import (
    PRIMARY_AGENT_ID,
    PRIMARY_GOAL_ID,
    materialize_closed_loop_fixture,
)
from loopx.application import (
    ApplicationContext,
    LoopXApplication,
    Profile,
    TurnHostRequest,
    TurnHostResult,
    TurnPlan,
)
from loopx.cli_v2 import main


FIXED_NOW = datetime(2026, 8, 7, 4, 5, 6, tzinfo=timezone.utc)


class _FixtureEnvelopeSource:
    def __init__(self, todo_id: str) -> None:
        self.todo_id = todo_id
        self.calls = 0

    def load_turn_envelope(
        self,
        *,
        registry_path: Path,
        runtime_root: Path,
        goal_id: str,
        agent_id: str,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root
        self.calls += 1
        assert goal_id == PRIMARY_GOAL_ID
        assert agent_id == PRIMARY_AGENT_ID
        return {
            "ok": True,
            "schema_version": "loopx_turn_envelope_v0",
            "goal_id": goal_id,
            "agent_id": agent_id,
            "should_run": True,
            "effective_action": "normal_run",
            "action": {
                "must_attempt": True,
                "delivery_allowed": True,
                "quiet_noop_allowed": False,
                "selected_todo": {
                    "todo_id": self.todo_id,
                    "text": "Run one controlled CLI v2 fixture turn",
                },
            },
            "user": {
                "action_required": False,
                "open_count": 0,
                "notify": "DONT_NOTIFY",
            },
            "writeback": {"spend_after_validation": True},
            "scheduler": {"action": "run_now"},
            "action_signature": {
                "matches": True,
                "source_hash": "sha256:cli-v2-turn-fixture",
                "envelope_hash": "sha256:cli-v2-turn-fixture",
            },
            "compaction": {"within_budget": True},
        }


class _FixtureExecutor:
    def __init__(self) -> None:
        self.requests: list[TurnHostRequest] = []

    def execute(self, request: TurnHostRequest) -> TurnHostResult:
        self.requests.append(request)
        return TurnHostResult(
            turn_key=request.turn_key,
            result_kind="validated_progress",
            classification="cli_v2_fixture_progress",
            recommended_action="Read back the controlled fixture receipt",
            next_action="Continue only from the verified fixture state",
            delivery_batch_scale="implementation",
            delivery_outcome="outcome_progress",
            vision_unchanged_reason="The controlled fixture objective is unchanged.",
            summary="The injected fixture executor completed one bounded turn.",
        )


class _FixtureCoordinator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate_task(
        self,
        plan: TurnPlan,
        result: TurnHostResult,
    ) -> Mapping[str, object]:
        assert plan.turn_key == result.turn_key
        self.calls.append("validate_task")
        return {
            "status": "passed",
            "validator_kind": "cli_v2_controlled_fixture",
            "summary": "Controlled fixture validation passed",
        }

    def writeback(self, result: TurnHostResult) -> Mapping[str, object]:
        assert result.result_kind == "validated_progress"
        self.calls.append("writeback")
        return {"ok": True, "appended": True}

    def spend(self, plan: TurnPlan) -> Mapping[str, object]:
        assert plan.goal_id == PRIMARY_GOAL_ID
        self.calls.append("spend")
        return {
            "ok": True,
            "appended": True,
            "generated_at": "2026-08-07T04:05:06Z",
            "slots": 1,
        }

    def schedule(
        self,
        plan: TurnPlan,
        spend: Mapping[str, object],
    ) -> Mapping[str, object]:
        assert plan.goal_id == PRIMARY_GOAL_ID
        assert spend["slots"] == 1
        self.calls.append("schedule")
        return {
            "disposition": "not_required",
            "completed": True,
            "acknowledged": False,
            "apply_needed": False,
        }


def test_turn_execute_uses_injected_fixture_executor_and_replays_locally(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    envelope = _FixtureEnvelopeSource(fixture.todo_ids["primary_next"])
    executor = _FixtureExecutor()
    coordinator = _FixtureCoordinator()
    application = LoopXApplication(
        ApplicationContext(
            registry_path=fixture.registry_path,
            profile=Profile.CLI,
            clock=lambda: FIXED_NOW,
            turn_envelope_source=envelope,
            turn_executor=executor,
            turn_commit_coordinator=coordinator,
        )
    )
    argv = [
        "--format",
        "json",
        "--registry",
        str(fixture.registry_path),
        "turn",
        "run-once",
        "--goal-id",
        PRIMARY_GOAL_ID,
        "--agent-id",
        PRIMARY_AGENT_ID,
        "--turn-instance-id",
        "cli-v2-controlled-turn-001",
        "--project",
        str(fixture.project),
        "--execute",
    ]

    first_output = StringIO()
    first_code = main(
        argv,
        application_factory=lambda _args, _path: application,
        stdout=first_output,
    )
    first = json.loads(first_output.getvalue())

    assert first_code == 0
    assert first["result"]["ok"] is True
    assert first["result"]["dry_run"] is False
    assert first["result"]["replayed"] is False
    assert first["result"]["effects"] == {
        "host_invoked": True,
        "state_written": True,
        "scheduler_acknowledged": False,
        "quota_spent": True,
    }
    assert len(executor.requests) == 1
    assert coordinator.calls == ["validate_task", "writeback", "spend", "schedule"]

    replay_output = StringIO()
    replay_code = main(
        argv,
        application_factory=lambda _args, _path: application,
        stdout=replay_output,
    )
    replay = json.loads(replay_output.getvalue())

    assert replay_code == 0
    assert replay["result"]["ok"] is True
    assert replay["result"]["replayed"] is True
    assert len(executor.requests) == 1
    assert coordinator.calls == ["validate_task", "writeback", "spend", "schedule"]
