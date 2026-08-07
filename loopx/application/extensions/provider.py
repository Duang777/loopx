from __future__ import annotations

from typing import Protocol

from .contracts import (
    ExtensionDoctorResult,
    ExtensionInitRequest,
    ExtensionInitResult,
    ExtensionInstallRequest,
    ExtensionInstallResult,
    ExtensionListRequest,
    ExtensionListResult,
    ExtensionMutationRequest,
    ExtensionRollbackResult,
    ExtensionRunRequest,
    ExtensionRunResult,
    ExtensionToggleResult,
)


class ExtensionProvider(Protocol):
    def initialize(self, request: ExtensionInitRequest) -> ExtensionInitResult: ...

    def list(self, request: ExtensionListRequest) -> ExtensionListResult: ...

    def install(
        self,
        request: ExtensionInstallRequest,
        *,
        operation: str,
    ) -> ExtensionInstallResult: ...

    def enable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult: ...

    def disable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult: ...

    def rollback(
        self,
        request: ExtensionMutationRequest,
    ) -> ExtensionRollbackResult: ...

    def doctor(self, request: ExtensionMutationRequest) -> ExtensionDoctorResult: ...

    def run(self, request: ExtensionRunRequest) -> ExtensionRunResult: ...
