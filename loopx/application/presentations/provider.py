from __future__ import annotations

from typing import Protocol

from .contracts import (
    PresentationPackageRequest,
    PresentationPackageResult,
    PresentationReadbackRequest,
    PresentationReadbackResult,
    PresentationRollbackRequest,
    PresentationRollbackResult,
)


class PresentationArtifactProvider(Protocol):
    def package(
        self,
        request: PresentationPackageRequest,
    ) -> PresentationPackageResult: ...

    def rollback(
        self,
        request: PresentationRollbackRequest,
    ) -> PresentationRollbackResult: ...


class PresentationReadbackProvider(Protocol):
    def verify(
        self,
        request: PresentationReadbackRequest,
    ) -> PresentationReadbackResult: ...
