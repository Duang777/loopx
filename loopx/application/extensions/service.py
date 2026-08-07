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
from .provider import ExtensionProvider


ResultT = TypeVar("ResultT")


class ExtensionLifecycleService:
    """Authority-aware orchestration over an injected extension owner adapter."""

    __slots__ = ("_profile", "_provider")

    def __init__(
        self,
        *,
        profile: Profile,
        provider: ExtensionProvider | None,
    ) -> None:
        if not isinstance(profile, Profile):
            raise ValidationFailed(details={"field": "profile"})
        self._profile = profile
        self._provider = provider

    def initialize(self, request: ExtensionInitRequest) -> ExtensionInitResult:
        self._require_write(request.execute, "application.extensions.initialize")
        provider = self._require_provider("application.extensions.initialize")
        return self._invoke(lambda: provider.initialize(request))

    def list(self, request: ExtensionListRequest) -> ExtensionListResult:
        provider = self._require_provider("application.extensions.list")
        return self._invoke(lambda: provider.list(request))

    def install(self, request: ExtensionInstallRequest) -> ExtensionInstallResult:
        self._require_write(request.execute, "application.extensions.install")
        self._require_execution(request.execute, "application.extensions.install")
        provider = self._require_provider("application.extensions.install")
        return self._invoke(lambda: provider.install(request, operation="install"))

    def upgrade(self, request: ExtensionInstallRequest) -> ExtensionInstallResult:
        self._require_write(request.execute, "application.extensions.upgrade")
        self._require_execution(request.execute, "application.extensions.upgrade")
        provider = self._require_provider("application.extensions.upgrade")
        return self._invoke(lambda: provider.install(request, operation="upgrade"))

    def enable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult:
        self._require_write(request.execute, "application.extensions.enable")
        self._require_execution(request.execute, "application.extensions.enable")
        provider = self._require_provider("application.extensions.enable")
        return self._invoke(lambda: provider.enable(request))

    def disable(self, request: ExtensionMutationRequest) -> ExtensionToggleResult:
        self._require_write(request.execute, "application.extensions.disable")
        provider = self._require_provider("application.extensions.disable")
        return self._invoke(lambda: provider.disable(request))

    def rollback(self, request: ExtensionMutationRequest) -> ExtensionRollbackResult:
        self._require_write(request.execute, "application.extensions.rollback")
        self._require_execution(request.execute, "application.extensions.rollback")
        provider = self._require_provider("application.extensions.rollback")
        return self._invoke(lambda: provider.rollback(request))

    def doctor(self, request: ExtensionMutationRequest) -> ExtensionDoctorResult:
        self._require_write(request.execute, "application.extensions.doctor")
        self._require_execution(request.execute, "application.extensions.doctor")
        provider = self._require_provider("application.extensions.doctor")
        return self._invoke(lambda: provider.doctor(request))

    def run(self, request: ExtensionRunRequest) -> ExtensionRunResult:
        self._require_execution(request.execute, "application.extensions.run")
        provider = self._require_provider("application.extensions.run")
        return self._invoke(lambda: provider.run(request))

    def _require_provider(self, operation: str) -> ExtensionProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={"operation": operation, "provider": "extension_lifecycle"}
            )
        return self._provider

    def _require_write(self, execute: bool, operation: str) -> None:
        if execute and not self._profile.allows_writes:
            raise AuthorityDenied(
                details={"operation": operation, "profile": self._profile.value}
            )

    def _require_execution(self, execute: bool, operation: str) -> None:
        if execute and not self._profile.allows_execution:
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
                details={"resource": "extension", "cause": type(exc).__name__}
            ) from exc
