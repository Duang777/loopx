from __future__ import annotations

import argparse

import pytest

from loopx.cli_commands.quota_context import validate_quota_command_context_request
from loopx.control_plane.quota.error_codes import QuotaCommandValidationError


def _args(**overrides: object) -> argparse.Namespace:
    base = dict(
        quota_command="should-run",
        goal_id="synthetic-goal",
        agent_id="synthetic-agent",
        begin_turn=True,
        turn_instance_id=None,
        todo_id=None,
        replan_obligation_id=None,
        dry_run=False,
        codex_app=False,
        runtime_profile="generic_cli",
        host_surface=None,
        scheduler_owner=None,
        execution_mode=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_begin_turn_rejection_names_the_alternative_for_other_hosts() -> None:
    """An agent-CLI host must learn how to start its turn, not just that it cannot.

    ``--begin-turn`` is reserved for the runtimes that mint Turn identity
    themselves. Every other host — Kiro CLI, ZCode, agy, Gemini CLI, Cursor and
    any custom runner on ``generic_cli`` — starts a turn by passing its own
    ``--turn-instance-id``, so the rejection has to say that.
    """

    with pytest.raises(QuotaCommandValidationError) as excinfo:
        validate_quota_command_context_request(_args())

    message = str(excinfo.value)
    assert "--begin-turn requires runtime-profile" in message
    assert "--turn-instance-id" in message
