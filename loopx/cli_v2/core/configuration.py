from __future__ import annotations

import argparse
import json
from dataclasses import fields
from typing import Any

from loopx.application import GoalConfigurationPatch

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import require_text, success, write_context


_ARGUMENT_NAMES = {
    "allowed_domains": "allowed_domain",
    "agent_profiles": "agent_profile_jsons",
    "automation_prompt_migration_ack": "ack_automation_prompt_migration",
    "todo_lifecycle_authority": "todo_lifecycle_authority_jsons",
    "boundary_authority_scopes": "boundary_authority_scope",
}


def handle_configuration(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "configure-goal requires --goal-id")
    patch = _patch(args)
    service = application.get_goal(goal_id).configuration
    plan = service.preview(patch)
    if not bool(args.execute):
        return success(
            operation="goal.configuration.preview",
            result=plan,
            title="LoopX Goal Configuration",
            extra={"dry_run": True, "execute": False},
            ok=bool(getattr(plan, "can_apply", True)),
        )
    context = write_context(
        actor="loopx-cli-v2",
        operation="configure-goal",
        expected_revision=plan.revision,
        material={"goal_id": goal_id, "patch": patch, "plan_hash": plan.plan_hash},
    )
    result = service.apply(patch, plan_hash=plan.plan_hash, write_context=context)
    return success(
        operation="goal.configuration.apply",
        result=result,
        title="LoopX Goal Configuration",
        extra={"dry_run": False, "execute": True},
    )


def _patch(args: argparse.Namespace) -> GoalConfigurationPatch:
    values: dict[str, Any] = {}
    for descriptor in fields(GoalConfigurationPatch):
        field_name = descriptor.name
        argument_name = _ARGUMENT_NAMES.get(field_name, field_name)
        value = getattr(args, argument_name, None)
        if field_name in {"agent_profiles", "todo_lifecycle_authority"}:
            value = _json_objects(value, option=argument_name)
        elif field_name == "agent_work_modes":
            value = _work_modes(value)
        elif _is_sequence_field(field_name) and value is not None:
            value = tuple(value)
        if value is not None:
            values[field_name] = value
    return GoalConfigurationPatch(**values)


def _json_objects(value: object, *, option: str) -> tuple[dict[str, object], ...] | None:
    if value is None:
        return None
    rows: list[dict[str, object]] = []
    for raw in value:
        parsed = json.loads(str(raw))
        if not isinstance(parsed, dict):
            raise ValueError(f"{option} must contain JSON objects")
        rows.append(parsed)
    return tuple(rows)


def _work_modes(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    modes: dict[str, str] = {}
    for raw in value:
        agent_id, separator, mode = str(raw).partition("=")
        agent_id = agent_id.strip()
        mode = mode.strip()
        if not separator or not agent_id or mode not in {"active", "monitor_only"}:
            raise ValueError("--agent-work-mode must use AGENT_ID=active|monitor_only")
        if agent_id in modes:
            raise ValueError(f"duplicate --agent-work-mode for {agent_id}")
        modes[agent_id] = mode
    return modes


def _is_sequence_field(name: str) -> bool:
    return name in {
        "allowed_domains",
        "registered_agents",
        "clear_agent_profiles",
        "clear_agent_work_modes",
        "clear_todo_lifecycle_authority",
        "supervised_agents",
        "write_scope",
        "boundary_authority_scopes",
        "reward_memory_agents",
    }
