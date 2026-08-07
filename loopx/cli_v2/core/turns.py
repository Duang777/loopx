from __future__ import annotations

import argparse

from loopx.application import TurnExecutionMode, TurnHost, TurnPlanRequest, WriteContext

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import pending_migration, require_text, success


def handle_turn_plan(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "turn plan requires --goal-id")
    request = _request(args)
    result = application.get_goal(goal_id).turns.plan(request)
    return success(
        operation="goal.turn.plan",
        result=result,
        title="LoopX Turn Plan",
        extra={"mode": "plan"},
        ok=bool(getattr(result, "core_contract_valid", True)),
    )


def handle_turn_run_once(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "turn run-once requires --goal-id")
    if args.resume_turn_key:
        return pending_migration(
            command="turn run-once --resume-turn-key",
            reason="journal-key resume is not exposed by the typed Turn operation",
        )
    request = _request(args)
    service = application.get_goal(goal_id).turns
    plan = service.plan(request)
    context = WriteContext(
        actor=request.agent_id,
        idempotency_key=request.turn_instance_id,
        expected_revision=plan.revision,
    )
    result = service.run_once(
        plan,
        request=request,
        write_context=context,
        execute=bool(args.execute),
        retry_failed=bool(args.retry_failed_turn),
    )
    return success(
        operation="goal.turn.run_once",
        result=result,
        title="LoopX Turn Run Once",
        extra={"mode": "run_once", "dry_run": not bool(args.execute)},
        ok=bool(result.get("ok", False) if isinstance(result, dict) else result.ok),
    )


def _request(args: argparse.Namespace) -> TurnPlanRequest:
    agent_id = require_text(args, "agent_id", "turn requires --agent-id")
    turn_instance_id = require_text(
        args,
        "turn_instance_id",
        "CLI v2 Turn requires --turn-instance-id",
    )
    resume_identity = {
        "goal_id": args.resume_goal_id,
        "agent_id": args.resume_agent_id,
        "todo_id": args.resume_todo_id,
    }
    supplied = [key for key, value in resume_identity.items() if value is not None]
    if supplied and len(supplied) != len(resume_identity):
        raise ValueError(
            "resume planning requires --resume-goal-id, --resume-agent-id, "
            "and --resume-todo-id together"
        )
    session_binding = None
    if supplied:
        session_binding = {
            "schema_version": "loopx_turn_session_binding_v0",
            **resume_identity,
        }
    return TurnPlanRequest(
        agent_id=agent_id,
        turn_instance_id=turn_instance_id,
        host=TurnHost(args.host),
        execution_mode=TurnExecutionMode(args.execution_mode),
        scheduler_owner=args.scheduler_owner,
        session_binding=session_binding,
    )
