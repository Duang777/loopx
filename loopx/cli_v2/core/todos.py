from __future__ import annotations

import argparse

from loopx.application import TodoCompletion, TodoUpdatePatch

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import pending_migration, require_text, success, write_context


def handle_todo_list(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "todo list requires --goal-id")
    path_gap = _path_override_gap(args, "todo list")
    if path_gap is not None:
        return path_gap
    result = application.get_goal(goal_id).todos.list(
        role=args.role,
        status=args.status,
        todo_id=args.todo_id,
        agent_id=args.agent_id,
    )
    return success(
        operation="goal.todos.list",
        result=result,
        title="LoopX Todo",
        extra={"action": "list", "dry_run": True},
    )


def handle_todo_claim(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "todo claim requires --goal-id")
    todo_id = require_text(args, "todo_id", "todo claim requires --todo-id")
    claimed_by = require_text(
        args,
        "claimed_by",
        "todo claim requires --claimed-by",
    )
    path_gap = _path_override_gap(args, "todo claim")
    if path_gap is not None:
        return path_gap
    actor = str(args.agent_id or claimed_by)
    if args.agent_id and actor != claimed_by:
        return pending_migration(
            command="todo claim",
            reason=(
                "cross-actor claim parity requires a typed delegated-claim "
                "Application operation"
            ),
        )
    if bool(args.dry_run):
        return pending_migration(
            command="todo claim --dry-run",
            reason="claim preview is not exposed by the Application boundary",
        )
    service = application.get_goal(goal_id).todos
    current = service.list(todo_id=todo_id)
    if args.role and (
        not current.items or current.items[0].role != args.role
    ):
        raise ValueError("todo claim --role does not match the selected todo")
    context = write_context(
        actor=actor,
        operation="todo-claim",
        expected_revision=current.revision,
        material={"goal_id": goal_id, "todo_id": todo_id, "claimed_by": claimed_by},
    )
    result = service.claim(todo_id, write_context=context)
    return success(
        operation="goal.todos.claim",
        result=result,
        title="LoopX Todo",
        extra={"action": "claim", "dry_run": False},
    )


def handle_todo_update(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "todo update requires --goal-id")
    todo_id = require_text(args, "todo_id", "todo update requires --todo-id")
    if bool(args.dry_run):
        return pending_migration(
            command="todo update --dry-run",
            reason="todo update preview is not exposed by the Application boundary",
        )
    path_gap = _path_override_gap(args, "todo update")
    if path_gap is not None:
        return path_gap
    unsupported = _unsupported_update_options(args)
    if unsupported:
        return pending_migration(
            command="todo update",
            reason=(
                "typed TodoUpdatePatch does not yet expose: " + ", ".join(unsupported)
            ),
        )
    actor = str(args.agent_id or args.claimed_by or "loopx-cli-v2")
    patch = TodoUpdatePatch(
        text=args.text,
        status=args.status,
        role=args.role,
        note=args.note,
        evidence=args.evidence,
        reason=args.reason,
        task_class=args.task_class,
        action_kind=args.action_kind,
        claimed_by=args.claimed_by,
        clear_claim=bool(args.clear_claim),
    )
    if not any(
        value is not None and value is not False
        for value in (
            patch.text,
            patch.status,
            patch.role,
            patch.note,
            patch.evidence,
            patch.reason,
            patch.task_class,
            patch.action_kind,
            patch.claimed_by,
            patch.clear_claim,
        )
    ):
        raise ValueError("todo update requires at least one mutable todo field")
    service = application.get_goal(goal_id).todos
    current = service.list(todo_id=todo_id)
    context = write_context(
        actor=actor,
        operation="todo-update",
        expected_revision=current.revision,
        material={"goal_id": goal_id, "todo_id": todo_id, "patch": patch},
    )
    result = service.update(todo_id, patch, write_context=context)
    return success(
        operation="goal.todos.update",
        result=result,
        title="LoopX Todo",
        extra={"action": "update", "dry_run": False},
    )


def handle_todo_complete(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "todo complete requires --goal-id")
    todo_id = require_text(args, "todo_id", "todo complete requires --todo-id")
    path_gap = _path_override_gap(args, "todo complete")
    if path_gap is not None:
        return path_gap
    unsupported = [
        option
        for option, value in (
            ("--authority-reason", args.authority_reason),
            ("--target-capability", args.target_capabilities),
            ("--capability-gap-status", args.capability_gap_status),
        )
        if value
    ]
    if unsupported:
        return pending_migration(
            command="todo complete",
            reason=(
                "typed TodoCompletion does not yet expose: "
                + ", ".join(unsupported)
            ),
        )
    actor = str(args.agent_id or args.claimed_by or "loopx-cli-v2")
    completion = TodoCompletion(
        evidence=args.evidence,
        note=args.note,
        decision_outcome=args.decision_outcome,
        claimed_by=args.claimed_by,
        clear_claim=bool(args.clear_claim),
        no_followup=bool(args.no_follow_up),
        successor_todo_ids=tuple(args.successor_todo_ids or ()),
        next_agent_todo=args.next_agent_todo,
        next_user_todo=args.next_user_todo,
        next_user_task_class=args.next_user_task_class,
        next_claimed_by=args.next_claimed_by,
        next_task_class=args.next_task_class,
        next_action_kind=args.next_action_kind,
        next_task_repository=args.next_task_repository,
        next_required_capabilities=tuple(args.next_required_capabilities or ()),
        next_continuation_policy=args.next_continuation_policy,
        next_excluded_agents=tuple(args.next_excluded_agents or ()),
        self_merged=bool(args.self_merged),
    )
    service = application.get_goal(goal_id).todos
    if args.role and not service.list(todo_id=todo_id, role=args.role).items:
        raise ValueError("todo complete --role does not match the selected todo")
    plan = service.preview_complete(todo_id, completion, actor=actor)
    if bool(args.dry_run):
        return success(
            operation="goal.todos.complete.preview",
            result=plan,
            title="LoopX Todo",
            extra={"action": "complete", "dry_run": True},
            ok=bool(getattr(plan, "can_apply", True)),
        )
    context = write_context(
        actor=actor,
        operation="todo-complete",
        expected_revision=plan.revision,
        material={
            "goal_id": goal_id,
            "todo_id": todo_id,
            "completion": completion,
            "plan_hash": plan.plan_hash,
        },
    )
    result = service.apply_complete(plan, write_context=context)
    return success(
        operation="goal.todos.complete.apply",
        result=result,
        title="LoopX Todo",
        extra={"action": "complete", "dry_run": False},
    )


def _unsupported_update_options(args: argparse.Namespace) -> list[str]:
    unsupported: list[str] = []
    for option, attribute in (
        ("--task-domain", "task_domain"),
        ("--task-repository", "task_repository"),
        ("--continuation-policy", "continuation_policy"),
        ("--required-write-scope", "required_write_scopes"),
        ("--required-capability", "required_capabilities"),
        ("--target-capability", "target_capabilities"),
        ("--capability-gap-status", "capability_gap_status"),
        ("--explore-result-node-ref", "explore_result_node_refs"),
        ("--decision-scope", "decision_scope"),
        ("--required-decision-scope", "required_decision_scopes"),
        ("--bound-agent", "bound_agent"),
        ("--goal-bound", "goal_bound"),
        ("--blocks-agent", "blocks_agent"),
        ("--excluded-agent", "excluded_agents"),
        ("--global-gate", "global_gate"),
        ("--unblocks-todo-id", "unblocks_todo_id"),
        ("--successor-todo-id", "successor_todo_ids"),
        ("--resume-when", "resume_when"),
        ("--target-key", "monitor_target_key"),
        ("--cadence", "cadence"),
        ("--next-due-at", "next_due_at"),
        ("--expires-at", "expires_at"),
        ("--authority-reason", "authority_reason"),
    ):
        if getattr(args, attribute, None):
            unsupported.append(option)
    for option, attribute in (
        ("--clear-explore-result-node-refs", "clear_explore_result_node_refs"),
        ("--clear-blocks-agent", "clear_blocks_agent"),
        ("--clear-excluded-agents", "clear_excluded_agents"),
        ("--clear-global-gate", "clear_global_gate"),
        ("--clear-resume-when", "clear_resume_when"),
        ("--no-follow-up", "no_follow_up"),
    ):
        if bool(getattr(args, attribute, False)):
            unsupported.append(option)
    return unsupported


def _path_override_gap(
    args: argparse.Namespace,
    command: str,
) -> CommandOutcome | None:
    options = [
        option
        for option, value in (
            ("--project", args.project),
            ("--state-file", args.state_file),
        )
        if value
    ]
    if not options:
        return None
    return pending_migration(
        command=command,
        reason=(
            "canonical Application routing does not expose CLI path overrides: "
            + ", ".join(options)
        ),
    )
