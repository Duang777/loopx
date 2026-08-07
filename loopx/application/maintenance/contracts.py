from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..errors import ValidationFailed


class CanaryCheckTier(str, Enum):
    DEFAULT = "default"
    DEEP = "deep"


class CanarySmokeSuite(str, Enum):
    FULL_PUBLIC = "full-public"


@dataclass(frozen=True, slots=True)
class CanaryProfilesRequest:
    catalog_path: Path | None = None

    def __post_init__(self) -> None:
        if self.catalog_path is not None:
            if not isinstance(self.catalog_path, (str, Path)):
                raise ValidationFailed(details={"field": "catalog_path"})
            object.__setattr__(
                self,
                "catalog_path",
                Path(self.catalog_path).expanduser(),
            )


@dataclass(frozen=True, slots=True)
class CanarySmokeProfilesRequest:
    """Explicit no-input request for the non-executing profile projection."""


@dataclass(frozen=True, slots=True)
class CanaryArchetype:
    archetype_id: str
    name: str
    primary_question: str
    trigger_surface: str
    fixture_depth: str
    cost_tier: str
    failure_meaning: str


@dataclass(frozen=True, slots=True)
class CanaryArchetypeReference:
    archetype_id: str
    name: str


@dataclass(frozen=True, slots=True)
class CanaryCandidateCheck:
    command: str
    reason: str
    tier: CanaryCheckTier | None = None


@dataclass(frozen=True, slots=True)
class CanaryFamilyProfile:
    schema_version: str
    profile_id: str
    family: str
    pattern_ids: tuple[str, ...]
    default_archetypes: tuple[CanaryArchetypeReference, ...]
    trigger_surfaces: str
    minimum_useful_fixture: str
    failure_meaning: str
    candidate_checks: tuple[CanaryCandidateCheck, ...]


@dataclass(frozen=True, slots=True)
class CanaryDomainProfile:
    schema_version: str
    profile_id: str
    title: str
    purpose: str
    catalog_families: tuple[str, ...]
    trigger_hints: tuple[str, ...]
    checks: tuple[CanaryCandidateCheck, ...]
    quality_risk: str | None = None


@dataclass(frozen=True, slots=True)
class CanaryProfilesResult:
    ok: bool
    schema_version: str
    source: str
    dry_run: bool
    executes_checks: bool
    archetypes: tuple[CanaryArchetype, ...]
    profiles: tuple[CanaryFamilyProfile, ...]
    domain_profiles: tuple[CanaryDomainProfile, ...]

    @property
    def archetype_count(self) -> int:
        return len(self.archetypes)

    @property
    def profile_count(self) -> int:
        return len(self.profiles)

    @property
    def domain_profile_count(self) -> int:
        return len(self.domain_profiles)


@dataclass(frozen=True, slots=True)
class CanarySmokeProfile:
    profile_id: str
    suite: CanarySmokeSuite
    modules: tuple[str, ...]
    exclude_modules: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class CanarySmokeProfilesResult:
    ok: bool
    schema_version: str
    source: str
    profiles: tuple[CanarySmokeProfile, ...]
    executes_checks: bool
    writes_evidence: bool
    creates_runtime_contract: bool
    note: str

    @property
    def profile_count(self) -> int:
        return len(self.profiles)
