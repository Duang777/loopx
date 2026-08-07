from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from ..errors import (
    ApplicationError,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from .contracts import (
    CanaryProfilesRequest,
    CanaryProfilesResult,
    CanarySmokeProfilesRequest,
    CanarySmokeProfilesResult,
)
from .provider import CanaryProvider, CoreCanaryProvider


ResultT = TypeVar("ResultT")


class CanaryService:
    __slots__ = ("_provider",)

    def __init__(self, provider: CanaryProvider | None) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> CanaryService:
        return cls(CoreCanaryProvider())

    def profiles(self, request: CanaryProfilesRequest) -> CanaryProfilesResult:
        if not isinstance(request, CanaryProfilesRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider("application.maintenance.canary.profiles")
        result = self._invoke(lambda: provider.profiles(request))
        if not isinstance(result, CanaryProfilesResult):
            raise StateUnavailable(
                details={"resource": "canary", "field": "profiles"}
            )
        if result.executes_checks:
            raise StateUnavailable(
                details={"resource": "canary", "field": "executes_checks"}
            )
        return result

    def smoke_profiles(
        self,
        request: CanarySmokeProfilesRequest,
    ) -> CanarySmokeProfilesResult:
        if not isinstance(request, CanarySmokeProfilesRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.maintenance.canary.smoke_profiles"
        )
        result = self._invoke(lambda: provider.smoke_profiles(request))
        if not isinstance(result, CanarySmokeProfilesResult):
            raise StateUnavailable(
                details={"resource": "canary", "field": "smoke_profiles"}
            )
        if result.executes_checks or result.writes_evidence:
            raise StateUnavailable(
                details={"resource": "canary", "field": "side_effect_boundary"}
            )
        return result

    def _require_provider(self, operation: str) -> CanaryProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={"operation": operation, "provider": "canary_projection"}
            )
        return self._provider

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
                details={"resource": "canary", "cause": type(exc).__name__}
            ) from exc
