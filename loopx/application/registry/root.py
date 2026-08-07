"""Application-scoped accessor group for registry use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .inspection import (
    CoreRegistryInspectionProvider,
    RegistryInspectionProvider,
    RegistryInspectionService,
)

if TYPE_CHECKING:
    from ..context import ApplicationContext


@dataclass(frozen=True, slots=True)
class RegistryProviders:
    inspection: RegistryInspectionProvider = CoreRegistryInspectionProvider()


@dataclass(frozen=True, slots=True)
class RegistryServices:
    context: ApplicationContext
    providers: RegistryProviders = RegistryProviders()

    @property
    def inspection(self) -> RegistryInspectionService:
        return RegistryInspectionService(
            registry_path=self.context.registry_path,
            profile=self.context.profile,
            provider=self.providers.inspection,
        )
