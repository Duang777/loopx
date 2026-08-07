from __future__ import annotations

from dataclasses import dataclass

from .provider import CanaryProvider, CoreCanaryProvider
from .service import CanaryService


@dataclass(frozen=True, slots=True)
class MaintenanceProviders:
    canary: CanaryProvider = CoreCanaryProvider()


@dataclass(frozen=True, slots=True)
class MaintenanceServices:
    providers: MaintenanceProviders = MaintenanceProviders()

    @property
    def canary(self) -> CanaryService:
        return CanaryService(self.providers.canary)
