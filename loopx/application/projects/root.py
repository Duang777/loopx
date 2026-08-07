"""Application-scoped accessor group for project-local use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .skills import (
    CoreProjectSkillPreviewProvider,
    CoreProjectSkillStatusProvider,
    ProjectSkillPreviewProvider,
    ProjectSkillStatusProvider,
    ProjectSkillStatusService,
)

if TYPE_CHECKING:
    from ..context import ApplicationContext


@dataclass(frozen=True, slots=True)
class ProjectProviders:
    skill_status: ProjectSkillStatusProvider = CoreProjectSkillStatusProvider()
    skill_preview: ProjectSkillPreviewProvider = CoreProjectSkillPreviewProvider()


@dataclass(frozen=True, slots=True)
class ProjectServices:
    context: ApplicationContext
    providers: ProjectProviders = ProjectProviders()

    @property
    def skills(self) -> ProjectSkillStatusService:
        return ProjectSkillStatusService(
            profile=self.context.profile,
            provider=self.providers.skill_status,
            preview_provider=self.providers.skill_preview,
        )
