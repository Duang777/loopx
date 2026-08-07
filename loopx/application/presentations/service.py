from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from ..contracts import Profile
from ..errors import (
    ApplicationError,
    AuthorityDenied,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from .contracts import (
    PresentationPackageRequest,
    PresentationPackageResult,
    PresentationReadbackRequest,
    PresentationReadbackResult,
    PresentationRollbackRequest,
    PresentationRollbackResult,
)
from .provider import PresentationArtifactProvider, PresentationReadbackProvider


ResultT = TypeVar("ResultT")


class PresentationService:
    """Authority- and provider-aware static presentation orchestration."""

    __slots__ = ("_artifact_provider", "_profile", "_readback_provider")

    def __init__(
        self,
        *,
        profile: Profile,
        artifact_provider: PresentationArtifactProvider | None,
        readback_provider: PresentationReadbackProvider | None,
    ) -> None:
        if not isinstance(profile, Profile):
            raise ValidationFailed(details={"field": "profile"})
        self._profile = profile
        self._artifact_provider = artifact_provider
        self._readback_provider = readback_provider

    def package(
        self,
        request: PresentationPackageRequest,
    ) -> PresentationPackageResult:
        operation = "application.presentations.package"
        self._require_write(request.execute, operation)
        provider = self._require_artifact_provider(operation)
        return self._invoke(lambda: provider.package(request))

    def rollback(
        self,
        request: PresentationRollbackRequest,
    ) -> PresentationRollbackResult:
        operation = "application.presentations.rollback"
        self._require_write(request.execute, operation)
        provider = self._require_artifact_provider(operation)
        return self._invoke(lambda: provider.rollback(request))

    def verify_readback(
        self,
        request: PresentationReadbackRequest,
    ) -> PresentationReadbackResult:
        operation = "application.presentations.verify_readback"
        self._require_execution(operation)
        self._require_write(request.execute, operation)
        provider = self._require_readback_provider(operation)
        return self._invoke(lambda: provider.verify(request))

    def _require_artifact_provider(
        self,
        operation: str,
    ) -> PresentationArtifactProvider:
        if self._artifact_provider is None:
            raise CapabilityUnavailable(
                details={"operation": operation, "provider": "static_site_artifact"}
            )
        return self._artifact_provider

    def _require_readback_provider(
        self,
        operation: str,
    ) -> PresentationReadbackProvider:
        if self._readback_provider is None:
            raise CapabilityUnavailable(
                details={"operation": operation, "provider": "http_readback"}
            )
        return self._readback_provider

    def _require_write(self, execute: bool, operation: str) -> None:
        if execute and not self._profile.allows_writes:
            raise AuthorityDenied(
                details={"operation": operation, "profile": self._profile.value}
            )

    def _require_execution(self, operation: str) -> None:
        if not self._profile.allows_execution:
            raise AuthorityDenied(
                details={"operation": operation, "profile": self._profile.value}
            )

    @staticmethod
    def _invoke(call: Callable[[], ResultT]) -> ResultT:
        try:
            return call()
        except ApplicationError:
            raise
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "presentation", "cause": type(exc).__name__}
            ) from exc
