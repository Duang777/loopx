"""Application-scoped accessor group for system use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .backup import CoreStateBackupProvider, StateBackupProvider, StateBackupService
from .history_diagnostics import (
    CoreHistoryDiagnosticsProvider,
    HistoryDiagnosticsProvider,
    HistoryDiagnosticsService,
)
from .runtime import (
    CoreRuntimeArchiveProvider,
    RuntimeArchiveProvider,
    RuntimeArchiveService,
)
from .state_migration import (
    CoreStateMigrationProvider,
    StateMigrationProvider,
    StateMigrationService,
)
from .upgrades import CoreUpgradePlanProvider, UpgradePlanProvider, UpgradePlanService

if TYPE_CHECKING:
    from ..context import ApplicationContext


@dataclass(frozen=True, slots=True)
class SystemProviders:
    state_backup: StateBackupProvider = CoreStateBackupProvider()
    upgrade_plan: UpgradePlanProvider = CoreUpgradePlanProvider()
    runtime_archive: RuntimeArchiveProvider = CoreRuntimeArchiveProvider()
    state_migration: StateMigrationProvider = CoreStateMigrationProvider()
    history_diagnostics: HistoryDiagnosticsProvider = CoreHistoryDiagnosticsProvider()


@dataclass(frozen=True, slots=True)
class SystemServices:
    """Stateless root accessor; each operation gets current context paths/profile."""

    context: ApplicationContext
    providers: SystemProviders = SystemProviders()

    @property
    def backup(self) -> StateBackupService:
        return StateBackupService(
            profile=self.context.profile,
            provider=self.providers.state_backup,
        )

    @property
    def upgrades(self) -> UpgradePlanService:
        return UpgradePlanService(
            registry_path=self.context.registry_path,
            runtime_root_override=self.context.runtime_root_override,
            profile=self.context.profile,
            provider=self.providers.upgrade_plan,
        )

    @property
    def runtime_archive(self) -> RuntimeArchiveService:
        return RuntimeArchiveService(
            registry_path=self.context.registry_path,
            runtime_root_override=self.context.runtime_root_override,
            profile=self.context.profile,
            provider=self.providers.runtime_archive,
        )

    @property
    def state_migration(self) -> StateMigrationService:
        return StateMigrationService(
            registry_path=self.context.registry_path,
            runtime_root_override=self.context.runtime_root_override,
            profile=self.context.profile,
            provider=self.providers.state_migration,
        )

    @property
    def history_diagnostics(self) -> HistoryDiagnosticsService:
        return HistoryDiagnosticsService(
            registry_path=self.context.registry_path,
            runtime_root_override=self.context.runtime_root_override,
            profile=self.context.profile,
            provider=self.providers.history_diagnostics,
        )
