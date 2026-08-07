from __future__ import annotations

import argparse

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import success


def handle_status(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = str(getattr(args, "goal_id", None) or "").strip()
    if goal_id:
        result = application.get_goal(goal_id).overview()
        operation = "goal.overview"
    else:
        result = application.list_goals()
        operation = "application.list_goals"
    return success(
        operation=operation,
        result=result,
        title="LoopX Status",
        extra={"goal_filter": goal_id or None},
    )
