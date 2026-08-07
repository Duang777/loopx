"""Stable handle for goal-scoped application operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from loopx.application.errors import ValidationFailed

from .status import GoalOverview, GoalStatus, load_goal_overview, load_goal_status

if TYPE_CHECKING:
    from loopx.application.context import ApplicationContext

    from .configuration import GoalConfigurationService
    from .history import GoalHistoryService
    from .leases import GoalLeaseService
    from .quota import GoalQuotaService
    from .todos import GoalTodoService
    from .turns import GoalTurnService


@dataclass(frozen=True, slots=True)
class GoalHandle:
    """Identity-only goal handle; mutable control-plane state is never cached."""

    context: ApplicationContext
    goal_id: str

    def __post_init__(self) -> None:
        normalized = str(self.goal_id or "").strip()
        if not normalized or normalized != self.goal_id:
            raise ValidationFailed(details={"field": "goal_id"})

    def status(self) -> GoalStatus:
        """Read a fresh minimal status projection from the canonical goal route."""

        return load_goal_status(context=self.context, goal_id=self.goal_id)

    def overview(self) -> GoalOverview:
        """Read a fresh overview projection from the canonical goal route."""

        return load_goal_overview(context=self.context, goal_id=self.goal_id)

    @property
    def configuration(self) -> GoalConfigurationService:
        """Return the stateless configuration use-case group for this goal."""

        from .configuration import GoalConfigurationService

        return GoalConfigurationService(context=self.context, goal_id=self.goal_id)

    @property
    def todos(self) -> GoalTodoService:
        """Return the stateless todo lifecycle use-case group."""

        from .todos import GoalTodoService

        return GoalTodoService(context=self.context, goal_id=self.goal_id)

    @property
    def leases(self) -> GoalLeaseService:
        """Return the stateless task-lease use-case group."""

        from .leases import GoalLeaseService

        return GoalLeaseService(context=self.context, goal_id=self.goal_id)

    @property
    def quota(self) -> GoalQuotaService:
        """Return the stateless quota admission and accounting use-case group."""

        from .quota import GoalQuotaService

        return GoalQuotaService(context=self.context, goal_id=self.goal_id)

    @property
    def turns(self) -> GoalTurnService:
        """Return bounded Turn planning backed by explicitly injected providers."""

        from .turns import GoalTurnService

        return GoalTurnService(
            context=self.context,
            goal_id=self.goal_id,
            envelope_source=self.context.turn_envelope_source,
            executor=self.context.turn_executor,
            commit_coordinator=self.context.turn_commit_coordinator,
        )

    @property
    def history(self) -> GoalHistoryService:
        """Return the compact verification-history use-case group."""

        from .history import GoalHistoryService

        return GoalHistoryService(context=self.context, goal_id=self.goal_id)
