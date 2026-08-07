from __future__ import annotations

from typing import Protocol, cast

from loopx.application.capabilities import CapabilityApplicationServices
from loopx.application.errors import CapabilityUnavailable
from loopx.application.extensions import ExtensionLifecycleService
from loopx.application.presentations import PresentationService


class CapabilityExtensionPresentationApplication(Protocol):
    """Frozen T7B root accessor; production composition belongs to T8."""

    @property
    def capabilities(self) -> CapabilityApplicationServices: ...

    @property
    def extensions(self) -> ExtensionLifecycleService: ...

    @property
    def presentations(self) -> PresentationService: ...


def require_application_root(
    application: object,
) -> CapabilityExtensionPresentationApplication:
    missing = [
        name
        for name in ("capabilities", "extensions", "presentations")
        if getattr(application, name, None) is None
    ]
    if missing:
        raise CapabilityUnavailable(
            details={
                "operation": "application.t7b_root",
                "provider": "capability_extension_presentation_root",
                "missing_accessors": missing,
            }
        )
    return cast(CapabilityExtensionPresentationApplication, application)
