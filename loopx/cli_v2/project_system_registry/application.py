"""Structural Application root required by the T7A CLI cohort."""

from __future__ import annotations

from typing import Protocol, cast

from loopx.application.errors import CapabilityUnavailable
from loopx.application.projects import ProjectServices
from loopx.application.registry import RegistryServices
from loopx.application.system import SystemServices


class ProjectSystemRegistryApplication(Protocol):
    """Frozen cohort accessor contract; central composition belongs to T8."""

    @property
    def system(self) -> SystemServices: ...

    @property
    def registry(self) -> RegistryServices: ...

    @property
    def projects(self) -> ProjectServices: ...


def require_application_root(
    application: object,
) -> ProjectSystemRegistryApplication:
    missing = [
        name
        for name in ("system", "registry")
        if getattr(application, name, None) is None
    ]
    if missing:
        raise CapabilityUnavailable(
            details={
                "operation": "application.t7a_root",
                "provider": "project_system_registry_root",
                "missing_accessors": missing,
            }
        )
    return cast(ProjectSystemRegistryApplication, application)


def require_project_services(application: object) -> ProjectServices:
    projects = getattr(application, "projects", None)
    if projects is None:
        raise CapabilityUnavailable(
            details={
                "operation": "application.projects",
                "provider": "project_services_root",
                "missing_accessors": ["projects"],
            }
        )
    return cast(ProjectServices, projects)
