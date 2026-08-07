from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from loopx.canary.planner import build_catalog_canary_profiles
from loopx.canary.runner import build_canary_smoke_suite_profiles

from ..errors import StateUnavailable
from .contracts import (
    CanaryArchetype,
    CanaryArchetypeReference,
    CanaryCandidateCheck,
    CanaryCheckTier,
    CanaryDomainProfile,
    CanaryFamilyProfile,
    CanaryProfilesRequest,
    CanaryProfilesResult,
    CanarySmokeProfile,
    CanarySmokeProfilesRequest,
    CanarySmokeProfilesResult,
    CanarySmokeSuite,
)


class CanaryProvider(Protocol):
    def profiles(self, request: CanaryProfilesRequest) -> CanaryProfilesResult: ...

    def smoke_profiles(
        self,
        request: CanarySmokeProfilesRequest,
    ) -> CanarySmokeProfilesResult: ...


class CoreCanaryProvider:
    """Read-only typed adapter; neither operation invokes a smoke check."""

    def profiles(self, request: CanaryProfilesRequest) -> CanaryProfilesResult:
        return _profiles(
            build_catalog_canary_profiles(catalog_path=request.catalog_path)
        )

    def smoke_profiles(
        self,
        request: CanarySmokeProfilesRequest,
    ) -> CanarySmokeProfilesResult:
        del request
        return _smoke_profiles(build_canary_smoke_suite_profiles())


def _profiles(payload: Mapping[str, object]) -> CanaryProfilesResult:
    _exact_keys(
        payload,
        "profiles",
        {
            "ok",
            "schema_version",
            "source",
            "dry_run",
            "executes_checks",
            "archetype_count",
            "profile_count",
            "domain_profile_count",
            "archetypes",
            "profiles",
            "domain_profiles",
        },
    )
    archetypes = tuple(
        _archetype(_mapping(value, f"archetypes[{index}]"))
        for index, value in enumerate(_sequence(payload, "archetypes"))
    )
    profiles = tuple(
        _family_profile(_mapping(value, f"profiles[{index}]"))
        for index, value in enumerate(_sequence(payload, "profiles"))
    )
    domain_profiles = tuple(
        _domain_profile(_mapping(value, f"domain_profiles[{index}]"))
        for index, value in enumerate(_sequence(payload, "domain_profiles"))
    )
    _require_count(payload, "archetype_count", len(archetypes))
    _require_count(payload, "profile_count", len(profiles))
    _require_count(payload, "domain_profile_count", len(domain_profiles))
    return CanaryProfilesResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        source=_text(payload, "source"),
        dry_run=_bool(payload, "dry_run"),
        executes_checks=_bool(payload, "executes_checks"),
        archetypes=archetypes,
        profiles=profiles,
        domain_profiles=domain_profiles,
    )


def _archetype(payload: Mapping[str, object]) -> CanaryArchetype:
    _exact_keys(
        payload,
        "archetype",
        {
            "id",
            "name",
            "primary_question",
            "trigger_surface",
            "fixture_depth",
            "cost_tier",
            "failure_meaning",
        },
    )
    return CanaryArchetype(
        archetype_id=_text(payload, "id"),
        name=_text(payload, "name"),
        primary_question=_text(payload, "primary_question"),
        trigger_surface=_text(payload, "trigger_surface"),
        fixture_depth=_text(payload, "fixture_depth"),
        cost_tier=_text(payload, "cost_tier"),
        failure_meaning=_text(payload, "failure_meaning"),
    )


def _family_profile(payload: Mapping[str, object]) -> CanaryFamilyProfile:
    _exact_keys(
        payload,
        "family_profile",
        {
            "schema_version",
            "id",
            "family",
            "pattern_ids",
            "default_archetypes",
            "trigger_surfaces",
            "minimum_useful_fixture",
            "failure_meaning",
            "candidate_checks",
        },
    )
    references = tuple(
        _archetype_reference(_mapping(value, "default_archetypes"))
        for value in _sequence(payload, "default_archetypes")
    )
    checks = tuple(
        _candidate_check(_mapping(value, f"candidate_checks[{index}]"))
        for index, value in enumerate(_sequence(payload, "candidate_checks"))
    )
    return CanaryFamilyProfile(
        schema_version=_text(payload, "schema_version"),
        profile_id=_text(payload, "id"),
        family=_text(payload, "family"),
        pattern_ids=_text_tuple(payload, "pattern_ids"),
        default_archetypes=references,
        trigger_surfaces=_text(payload, "trigger_surfaces"),
        minimum_useful_fixture=_text(payload, "minimum_useful_fixture"),
        failure_meaning=_text(payload, "failure_meaning"),
        candidate_checks=checks,
    )


def _archetype_reference(
    payload: Mapping[str, object],
) -> CanaryArchetypeReference:
    _exact_keys(payload, "default_archetype", {"id", "name"})
    return CanaryArchetypeReference(
        archetype_id=_text(payload, "id"),
        name=_text(payload, "name"),
    )


def _domain_profile(payload: Mapping[str, object]) -> CanaryDomainProfile:
    _allowed_keys(
        payload,
        "domain_profile",
        required={
            "schema_version",
            "id",
            "title",
            "purpose",
            "catalog_families",
            "trigger_hints",
            "checks",
        },
        optional={"quality_risk"},
    )
    checks = tuple(
        _candidate_check(
            _mapping(value, f"checks[{index}]"),
            require_tier=True,
        )
        for index, value in enumerate(_sequence(payload, "checks"))
    )
    return CanaryDomainProfile(
        schema_version=_text(payload, "schema_version"),
        profile_id=_text(payload, "id"),
        title=_text(payload, "title"),
        purpose=_text(payload, "purpose"),
        quality_risk=_optional_text(payload, "quality_risk"),
        catalog_families=_text_tuple(payload, "catalog_families"),
        trigger_hints=_text_tuple(payload, "trigger_hints"),
        checks=checks,
    )


def _candidate_check(
    payload: Mapping[str, object],
    *,
    require_tier: bool = False,
) -> CanaryCandidateCheck:
    _exact_keys(
        payload,
        "candidate_check",
        {"command", "reason", "tier"} if require_tier else {"command", "reason"},
    )
    tier = None
    if require_tier:
        try:
            tier = CanaryCheckTier(_text(payload, "tier"))
        except ValueError as exc:
            raise _invalid("tier") from exc
    elif payload.get("tier") is not None:
        try:
            tier = CanaryCheckTier(_text(payload, "tier"))
        except ValueError as exc:
            raise _invalid("tier") from exc
    return CanaryCandidateCheck(
        command=_text(payload, "command"),
        reason=_text(payload, "reason"),
        tier=tier,
    )


def _smoke_profiles(payload: Mapping[str, object]) -> CanarySmokeProfilesResult:
    _exact_keys(
        payload,
        "smoke_profiles",
        {
            "ok",
            "schema_version",
            "source",
            "profile_count",
            "profiles",
            "executes_checks",
            "writes_evidence",
            "creates_runtime_contract",
            "note",
        },
    )
    profiles: list[CanarySmokeProfile] = []
    for index, value in enumerate(_sequence(payload, "profiles")):
        row = _mapping(value, f"profiles[{index}]")
        _exact_keys(
            row,
            f"profiles[{index}]",
            {"id", "suite", "modules", "exclude_modules", "description"},
        )
        try:
            suite = CanarySmokeSuite(_text(row, "suite"))
        except ValueError as exc:
            raise _invalid(f"profiles[{index}].suite") from exc
        profiles.append(
            CanarySmokeProfile(
                profile_id=_text(row, "id"),
                suite=suite,
                modules=_text_tuple(row, "modules"),
                exclude_modules=_text_tuple(row, "exclude_modules"),
                description=_text(row, "description"),
            )
        )
    _require_count(payload, "profile_count", len(profiles))
    return CanarySmokeProfilesResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        source=_text(payload, "source"),
        profiles=tuple(profiles),
        executes_checks=_bool(payload, "executes_checks"),
        writes_evidence=_bool(payload, "writes_evidence"),
        creates_runtime_contract=_bool(payload, "creates_runtime_contract"),
        note=_text(payload, "note"),
    )


def _invalid(field: str) -> StateUnavailable:
    return StateUnavailable(details={"resource": "canary", "field": field})


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid(field)
    return value


def _sequence(payload: Mapping[str, object], field: str) -> Sequence[object]:
    value = payload.get(field)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _invalid(field)
    return value


def _text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _invalid(field)
    return value


def _optional_text(payload: Mapping[str, object], field: str) -> str | None:
    if payload.get(field) is None:
        return None
    return _text(payload, field)


def _bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise _invalid(field)
    return value


def _int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(field)
    return value


def _text_tuple(payload: Mapping[str, object], field: str) -> tuple[str, ...]:
    values = _sequence(payload, field)
    result: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise _invalid(f"{field}[{index}]")
        result.append(value)
    return tuple(result)


def _require_count(
    payload: Mapping[str, object],
    field: str,
    actual: int,
) -> None:
    if _int(payload, field) != actual:
        raise _invalid(field)


def _exact_keys(
    payload: Mapping[str, object],
    field: str,
    expected: set[str],
) -> None:
    actual = set(payload)
    if actual != expected:
        raise StateUnavailable(
            details={
                "resource": "canary",
                "field": field,
                "missing": sorted(expected - actual),
                "unknown": sorted(actual - expected),
            }
        )


def _allowed_keys(
    payload: Mapping[str, object],
    field: str,
    *,
    required: set[str],
    optional: set[str],
) -> None:
    actual = set(payload)
    if not required <= actual or actual - required - optional:
        raise StateUnavailable(
            details={
                "resource": "canary",
                "field": field,
                "missing": sorted(required - actual),
                "unknown": sorted(actual - required - optional),
            }
        )
