from __future__ import annotations

from loopx.cli_contract.core_arguments import register_core_arguments

from ..registrar import CohortRegistrar, CommandBinding, SelectorMatch
from .configuration import handle_configuration
from .history import handle_history
from .leases import (
    handle_lease_acquire,
    handle_lease_inspect,
    handle_lease_release,
    handle_lease_renew,
)
from .quota import (
    handle_quota_overview,
    handle_quota_should_run,
    handle_quota_spend,
    handle_quota_void,
)
from .status import handle_status
from .todos import (
    handle_todo_claim,
    handle_todo_complete,
    handle_todo_list,
    handle_todo_update,
)
from .turns import handle_turn_plan, handle_turn_run_once


def _selector(dest: str, value: str | None) -> tuple[SelectorMatch, ...]:
    return (SelectorMatch(dest=dest, value=value),)


CORE_COHORT = CohortRegistrar(
    cohort_id="core",
    register_arguments=register_core_arguments,
    bindings=(
        CommandBinding(
            command="status",
            application_operation="application.list_goals|goal.overview",
            handler=handle_status,
        ),
        CommandBinding(
            command="configure-goal",
            application_operation=(
                "goal.configuration.preview|goal.configuration.apply"
            ),
            handler=handle_configuration,
        ),
        CommandBinding(
            command="history",
            selectors=_selector("history_action", None),
            application_operation="goal.history.list",
            handler=handle_history,
        ),
        CommandBinding(
            command="todo",
            selectors=_selector("todo_command", "list"),
            application_operation="goal.todos.list",
            handler=handle_todo_list,
        ),
        CommandBinding(
            command="todo",
            selectors=_selector("todo_command", "claim"),
            application_operation="goal.todos.claim",
            handler=handle_todo_claim,
        ),
        CommandBinding(
            command="todo",
            selectors=_selector("todo_command", "update"),
            application_operation="goal.todos.update",
            handler=handle_todo_update,
        ),
        CommandBinding(
            command="todo",
            selectors=_selector("todo_command", "complete"),
            application_operation=(
                "goal.todos.complete.preview|goal.todos.complete.apply"
            ),
            handler=handle_todo_complete,
        ),
        CommandBinding(
            command="task-lease",
            selectors=_selector("task_lease_command", "acquire"),
            application_operation="goal.lease.acquire",
            handler=handle_lease_acquire,
        ),
        CommandBinding(
            command="task-lease",
            selectors=_selector("task_lease_command", "renew"),
            application_operation="goal.lease.renew",
            handler=handle_lease_renew,
        ),
        CommandBinding(
            command="task-lease",
            selectors=_selector("task_lease_command", "release"),
            application_operation="goal.lease.release",
            handler=handle_lease_release,
        ),
        CommandBinding(
            command="task-lease",
            selectors=_selector("task_lease_command", "inspect"),
            application_operation="goal.lease.inspect",
            handler=handle_lease_inspect,
        ),
        CommandBinding(
            command="quota",
            selectors=_selector("quota_command", "status"),
            application_operation="application.list_goals+goal.quota.should_run",
            handler=handle_quota_overview,
        ),
        CommandBinding(
            command="quota",
            selectors=_selector("quota_command", "plan"),
            application_operation="application.list_goals+goal.quota.should_run",
            handler=handle_quota_overview,
        ),
        CommandBinding(
            command="quota",
            selectors=_selector("quota_command", "should-run"),
            application_operation="goal.quota.should_run",
            handler=handle_quota_should_run,
        ),
        CommandBinding(
            command="quota",
            selectors=_selector("quota_command", "spend-slot"),
            application_operation="goal.quota.spend.preview|goal.quota.spend.apply",
            handler=handle_quota_spend,
        ),
        CommandBinding(
            command="quota",
            selectors=_selector("quota_command", "void-slot"),
            application_operation="goal.quota.void.preview|goal.quota.void.apply",
            handler=handle_quota_void,
        ),
        CommandBinding(
            command="turn",
            selectors=_selector("turn_command", "plan"),
            application_operation="goal.turn.plan",
            handler=handle_turn_plan,
        ),
        CommandBinding(
            command="turn",
            selectors=_selector("turn_command", "run-once"),
            application_operation="goal.turn.run_once",
            handler=handle_turn_run_once,
        ),
    ),
)
