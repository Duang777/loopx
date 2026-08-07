"""Behavior-preserving argparse registration for the CLI v2 core cohort.

The imported functions only contribute parser shape here.  Their legacy handler
functions are never registered with or reachable from the v2 dispatcher.
"""

from __future__ import annotations

import argparse

from loopx.cli_commands.history import register_history_command
from loopx.cli_commands.quota import register_quota_command
from loopx.cli_commands.registry_admin_configure import register_configure_goal_command
from loopx.cli_commands.status_registration import register_status_commands
from loopx.cli_commands.task_lease import register_task_lease_command
from loopx.cli_commands.todo import register_todo_command
from loopx.cli_commands.turn import register_turn_commands

from .parser import add_subcommand_format


def register_core_arguments(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the frozen T6 parser slice in legacy command order."""

    register_turn_commands(subparsers, add_subcommand_format)
    register_configure_goal_command(subparsers)
    register_history_command(subparsers)
    register_status_commands(subparsers, add_subcommand_format)
    register_todo_command(subparsers, add_subcommand_format)
    register_task_lease_command(subparsers, add_subcommand_format)
    register_quota_command(subparsers)
