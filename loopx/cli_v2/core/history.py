from __future__ import annotations

import argparse

from ..registrar import ApplicationFacade, CommandOutcome
from ._shared import require_text, success


def handle_history(
    args: argparse.Namespace,
    application: ApplicationFacade,
) -> CommandOutcome:
    goal_id = require_text(args, "goal_id", "history requires --goal-id in CLI v2")
    result = application.get_goal(goal_id).history.list(page_size=max(0, args.limit))
    return success(
        operation="goal.history.list",
        result=result,
        title="LoopX History",
    )
