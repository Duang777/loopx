from __future__ import annotations

import argparse

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import pending_migration, require_text, success, write_context


def handle_quota_overview(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    if args.available_capabilities:
        return pending_migration(
            command=f"quota {args.quota_command}",
            reason=(
                "Application quota admission does not yet accept the CLI "
                "--available-capability envelope"
            ),
        )
    decisions = []
    for summary in application.list_goals():
        goal_id = str(getattr(summary, "goal_id"))
        decisions.append(
            application.get_goal(goal_id).quota.should_run(agent_id=args.agent_id)
        )
    return success(
        operation="application.list_goals+goal.quota.should_run",
        result=tuple(decisions),
        title="LoopX Quota",
        extra={"mode": args.quota_command},
    )


def handle_quota_should_run(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "quota should-run requires --goal-id")
    unsupported = _unsupported_should_run_options(args)
    if unsupported:
        return pending_migration(
            command="quota should-run",
            reason=(
                "the typed quota decision does not yet expose compatibility options: "
                + ", ".join(unsupported)
            ),
        )
    result = application.get_goal(goal_id).quota.should_run(agent_id=args.agent_id)
    return success(
        operation="goal.quota.should_run",
        result=result,
        title="LoopX Quota Should Run",
        extra={"mode": "should-run"},
    )


def handle_quota_spend(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    _validate_preview_flags(args, "quota spend-slot")
    capability_gap = _available_capability_gap(args, "quota spend-slot")
    if capability_gap is not None:
        return capability_gap
    goal_id = require_text(args, "goal_id", "quota spend-slot requires --goal-id")
    service = application.get_goal(goal_id).quota
    plan = service.preview_spend(
        slots=args.slots,
        source=args.source,
        agent_id=args.agent_id,
    )
    if not bool(args.execute):
        return success(
            operation="goal.quota.spend.preview",
            result=plan,
            title="LoopX Quota Slot",
            extra={"mode": "spend-slot", "dry_run": True, "source": args.source},
            ok=bool(getattr(plan, "can_apply", True)),
        )
    actor = str(args.agent_id or "loopx-cli-v2")
    context = write_context(
        actor=actor,
        operation="quota-spend",
        expected_revision=plan.revision,
        material={"goal_id": goal_id, "plan_hash": plan.plan_hash},
    )
    result = service.apply_spend(plan, write_context=context)
    return success(
        operation="goal.quota.spend.apply",
        result=result,
        title="LoopX Quota Slot",
        extra={"mode": "spend-slot", "dry_run": False, "source": args.source},
    )


def handle_quota_void(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    _validate_preview_flags(args, "quota void-slot")
    capability_gap = _available_capability_gap(args, "quota void-slot")
    if capability_gap is not None:
        return capability_gap
    goal_id = require_text(args, "goal_id", "quota void-slot requires --goal-id")
    target = require_text(
        args,
        "void_generated_at",
        "quota void-slot requires --void-generated-at",
    )
    reason = require_text(
        args,
        "reason_summary",
        "quota void-slot requires --reason-summary",
    )
    service = application.get_goal(goal_id).quota
    plan = service.preview_void(
        voided_run_generated_at=target,
        reason_summary=reason,
        source=args.source,
        agent_id=args.agent_id,
    )
    if not bool(args.execute):
        return success(
            operation="goal.quota.void.preview",
            result=plan,
            title="LoopX Quota Slot",
            extra={"mode": "void-slot", "dry_run": True, "source": args.source},
            ok=bool(getattr(plan, "can_apply", True)),
        )
    actor = str(args.agent_id or "loopx-cli-v2")
    context = write_context(
        actor=actor,
        operation="quota-void",
        expected_revision=plan.revision,
        material={"goal_id": goal_id, "plan_hash": plan.plan_hash},
    )
    result = service.apply_void(plan, write_context=context)
    return success(
        operation="goal.quota.void.apply",
        result=result,
        title="LoopX Quota Slot",
        extra={"mode": "void-slot", "dry_run": False, "source": args.source},
    )


def _unsupported_should_run_options(args: argparse.Namespace) -> list[str]:
    values = (
        ("--available-capability", args.available_capabilities),
        ("--include-detail", args.include_details),
        ("--include-scheduler-detail", args.include_scheduler_detail),
        ("--codex-app-current-rrule", args.codex_app_current_rrule),
        ("--runtime-profile", args.runtime_profile),
        ("--codex-app", args.codex_app),
        ("--host-surface", args.host_surface),
        ("--scheduler-owner", args.scheduler_owner),
        ("--execution-mode", args.execution_mode),
        ("--turn-envelope", args.turn_envelope),
        ("--turn-instance-id", args.turn_instance_id),
    )
    return [option for option, value in values if value]


def _validate_preview_flags(args: argparse.Namespace, command: str) -> None:
    if bool(args.dry_run) and bool(args.execute):
        raise ValueError(f"{command} accepts either --dry-run or --execute, not both")


def _available_capability_gap(
    args: argparse.Namespace,
    command: str,
) -> CommandOutcome | None:
    if not args.available_capabilities:
        return None
    return pending_migration(
        command=command,
        reason=(
            "Application quota accounting does not yet accept the CLI "
            "--available-capability envelope"
        ),
    )
