from __future__ import annotations

from dataclasses import dataclass

from .catalog import CapabilityCatalogService
from .content_ops import ContentOpsService
from .decision_context import DecisionContextService
from .material_lifecycle import MaterialLifecycleService
from .reward_memory import RewardMemoryService
from .semantic_preference import SemanticPreferenceService
from .value_connectors import ValueConnectorService


@dataclass(frozen=True, slots=True)
class CapabilityApplicationServices:
    """Outcome-owned capability services exposed by the T7B application root."""

    catalog: CapabilityCatalogService
    content_ops: ContentOpsService
    decision_context: DecisionContextService
    material_lifecycle: MaterialLifecycleService
    reward_memory: RewardMemoryService
    value_connectors: ValueConnectorService
    semantic_preference: SemanticPreferenceService

    @classmethod
    def builtin(cls) -> CapabilityApplicationServices:
        return cls(
            catalog=CapabilityCatalogService.builtin(),
            content_ops=ContentOpsService.builtin(),
            decision_context=DecisionContextService.builtin(),
            material_lifecycle=MaterialLifecycleService.builtin(),
            reward_memory=RewardMemoryService.builtin(),
            value_connectors=ValueConnectorService.builtin(),
            semantic_preference=SemanticPreferenceService.builtin(),
        )
