from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutcomeCapabilityContract:
    capability_id: str
    scope: str
    default_enabled: bool
    creates_authority: bool
    mutates_core_state: bool
