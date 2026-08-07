from __future__ import annotations

import argparse

from loopx.application import WriteContext

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import require_text, success


def handle_lease_inspect(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "task-lease inspect requires --goal-id")
    todo_id = require_text(args, "todo_id", "task-lease inspect requires --todo-id")
    unsupported = [
        option
        for option, value in (
            ("--owner", args.owner),
            ("--idempotency-key", args.idempotency_key),
            ("--new-owner", args.new_owner),
            ("--new-idempotency-key", args.new_idempotency_key),
            ("--ttl-seconds", args.ttl_seconds),
            ("--write-scope", args.write_scopes),
            ("--expected-version", args.expected_version),
        )
        if value is not None and value != []
    ]
    if unsupported:
        raise ValueError(
            "task-lease inspect only accepts --goal-id and --todo-id; unsupported: "
            + ", ".join(unsupported)
        )
    result = application.get_goal(goal_id).leases.inspect(todo_id)
    return success(
        operation="goal.lease.inspect",
        result=result,
        title="LoopX Task Lease",
        extra={"action": "inspect"},
    )


def handle_lease_acquire(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id, todo_id, context = _mutation_context(args, "acquire")
    result = application.get_goal(goal_id).leases.acquire(
        todo_id,
        write_context=context,
        ttl_seconds=args.ttl_seconds,
        write_scopes=tuple(args.write_scopes or ()),
    )
    return success(
        operation="goal.lease.acquire",
        result=result,
        title="LoopX Task Lease",
        extra={"action": "acquire"},
    )


def handle_lease_renew(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    if args.write_scopes:
        raise ValueError("task-lease renew does not accept --write-scope")
    goal_id, todo_id, context = _mutation_context(args, "renew")
    result = application.get_goal(goal_id).leases.renew(
        todo_id,
        write_context=context,
        ttl_seconds=args.ttl_seconds,
    )
    return success(
        operation="goal.lease.renew",
        result=result,
        title="LoopX Task Lease",
        extra={"action": "renew"},
    )


def handle_lease_release(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    if args.write_scopes:
        raise ValueError("task-lease release does not accept --write-scope")
    if args.ttl_seconds is not None:
        raise ValueError("task-lease release does not accept --ttl-seconds")
    goal_id, todo_id, context = _mutation_context(args, "release")
    result = application.get_goal(goal_id).leases.release(
        todo_id,
        write_context=context,
    )
    return success(
        operation="goal.lease.release",
        result=result,
        title="LoopX Task Lease",
        extra={"action": "release"},
    )


def _mutation_context(
    args: argparse.Namespace,
    action: str,
) -> tuple[str, str, WriteContext]:
    goal_id = require_text(args, "goal_id", f"task-lease {action} requires --goal-id")
    todo_id = require_text(args, "todo_id", f"task-lease {action} requires --todo-id")
    owner = require_text(args, "owner", f"task-lease {action} requires --owner")
    idempotency_key = require_text(
        args,
        "idempotency_key",
        f"task-lease {action} requires --idempotency-key",
    )
    expected_revision = (
        f"task_lease_v0:{args.expected_version}"
        if args.expected_version is not None
        else None
    )
    return (
        goal_id,
        todo_id,
        WriteContext(
            actor=owner,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        ),
    )
