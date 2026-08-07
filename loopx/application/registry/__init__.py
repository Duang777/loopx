"""Typed application services for registry outcomes."""

from .inspection import (
    REGISTRY_BOUNDARY_OPERATION,
    REGISTRY_INSPECT_OPERATION,
    CoreRegistryInspectionProvider,
    RegistryBoundaryResult,
    RegistryBoundaryRequest,
    RegistryGoalProjection,
    RegistryInspectionProvider,
    RegistryInspectionResult,
    RegistryInspectionService,
)
from .root import RegistryProviders, RegistryServices

__all__ = [
    "REGISTRY_BOUNDARY_OPERATION",
    "REGISTRY_INSPECT_OPERATION",
    "CoreRegistryInspectionProvider",
    "RegistryBoundaryResult",
    "RegistryBoundaryRequest",
    "RegistryGoalProjection",
    "RegistryInspectionProvider",
    "RegistryInspectionResult",
    "RegistryInspectionService",
    "RegistryProviders",
    "RegistryServices",
]
