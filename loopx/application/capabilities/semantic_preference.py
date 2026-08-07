from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

from ...capabilities.semantic_preference.contract import (
    application_receipt,
    maintenance_receipt,
)
from ..errors import (
    ApplicationError,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from ._projection import optional_text, text, text_tuple


ResultT = TypeVar("ResultT")
_RESOURCE = "semantic_preference_receipt"
_SURFACE_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/#-]{0,199}$")
_CORPUS_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_RECEIPT_REFS = 20
_MAX_CORPORA = 20


@dataclass(frozen=True, slots=True)
class SemanticPreferenceApplicationReceiptRequest:
    surface: str
    application_id: str
    outcome: str
    preference_refs: tuple[str, ...] = ()
    artifact_ref: str | None = None

    def __post_init__(self) -> None:
        surface = _validated_text(self.surface, "surface")
        if not _SURFACE_RE.fullmatch(surface):
            raise ValidationFailed(details={"field": "surface"})
        application_id = _token(self.application_id, "application_id")
        if self.outcome not in {"applied", "ignored", "failed"}:
            raise ValidationFailed(details={"field": "outcome"})
        refs = _text_sequence(self.preference_refs, "preference_refs")
        refs = tuple(ref for ref in refs if ref.strip())
        if len(refs) > _MAX_RECEIPT_REFS:
            raise ValidationFailed(details={"field": "preference_refs"})
        artifact_ref = self.artifact_ref
        if artifact_ref is not None and artifact_ref != "":
            artifact_ref = _token(artifact_ref, "artifact_ref")
        else:
            artifact_ref = None
        object.__setattr__(self, "surface", surface)
        object.__setattr__(self, "application_id", application_id)
        object.__setattr__(self, "preference_refs", refs)
        object.__setattr__(self, "artifact_ref", artifact_ref)


@dataclass(frozen=True, slots=True)
class SemanticPreferenceMaintenanceReceiptRequest:
    trigger: str
    outcome: str
    corpus_ids: tuple[str, ...]
    scope_refs: tuple[str, ...] = ()
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.trigger not in {"explicit_feedback", "source_truth_changed"}:
            raise ValidationFailed(details={"field": "trigger"})
        if self.outcome not in {"verified", "no_write_rationale", "failed"}:
            raise ValidationFailed(details={"field": "outcome"})
        corpus_ids = tuple(
            sorted(set(_text_sequence(self.corpus_ids, "corpus_ids")))
        )
        if (
            not corpus_ids
            or len(corpus_ids) > _MAX_CORPORA
            or any(not _CORPUS_ID_RE.fullmatch(value) for value in corpus_ids)
        ):
            raise ValidationFailed(details={"field": "corpus_ids"})
        scope_refs = tuple(
            ref.strip()
            for ref in _text_sequence(self.scope_refs, "scope_refs")
            if ref.strip()
        )
        if len(scope_refs) > _MAX_CORPORA or any(
            not _TOKEN_RE.fullmatch(ref) for ref in scope_refs
        ):
            raise ValidationFailed(details={"field": "scope_refs"})
        evidence_ref = self.evidence_ref
        if evidence_ref is not None and evidence_ref != "":
            evidence_ref = _token(evidence_ref, "evidence_ref")
        else:
            evidence_ref = None
        object.__setattr__(self, "corpus_ids", corpus_ids)
        object.__setattr__(self, "scope_refs", scope_refs)
        object.__setattr__(self, "evidence_ref", evidence_ref)


@dataclass(frozen=True, slots=True)
class SemanticPreferenceApplicationReceiptResult:
    schema_version: str
    surface: str
    application_id: str
    outcome: str
    preference_ref_digests: tuple[str, ...]
    artifact_ref: str | None


@dataclass(frozen=True, slots=True)
class SemanticPreferenceMaintenanceReceiptResult:
    schema_version: str
    trigger: str
    outcome: str
    corpus_ids: tuple[str, ...]
    scope_ref_digests: tuple[str, ...]
    evidence_ref: str | None


class SemanticPreferenceReceiptProvider(Protocol):
    def application_receipt(
        self,
        request: SemanticPreferenceApplicationReceiptRequest,
    ) -> SemanticPreferenceApplicationReceiptResult: ...

    def maintenance_receipt(
        self,
        request: SemanticPreferenceMaintenanceReceiptRequest,
    ) -> SemanticPreferenceMaintenanceReceiptResult: ...


class BuiltinSemanticPreferenceReceiptProvider:
    def application_receipt(
        self,
        request: SemanticPreferenceApplicationReceiptRequest,
    ) -> SemanticPreferenceApplicationReceiptResult:
        return _application_result(
            application_receipt(
                surface=request.surface,
                application_id=request.application_id,
                outcome=request.outcome,
                preference_refs=request.preference_refs,
                artifact_ref=request.artifact_ref,
            )
        )

    def maintenance_receipt(
        self,
        request: SemanticPreferenceMaintenanceReceiptRequest,
    ) -> SemanticPreferenceMaintenanceReceiptResult:
        return _maintenance_result(
            maintenance_receipt(
                trigger=request.trigger,
                outcome=request.outcome,
                corpus_ids=request.corpus_ids,
                scope_refs=request.scope_refs,
                evidence_ref=request.evidence_ref,
            )
        )


class SemanticPreferenceService:
    __slots__ = ("_provider",)

    def __init__(self, provider: SemanticPreferenceReceiptProvider | None) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> SemanticPreferenceService:
        return cls(BuiltinSemanticPreferenceReceiptProvider())

    def application_receipt(
        self,
        request: SemanticPreferenceApplicationReceiptRequest,
    ) -> SemanticPreferenceApplicationReceiptResult:
        provider = self._require_provider("receipt")
        return _invoke(lambda: provider.application_receipt(request))

    def maintenance_receipt(
        self,
        request: SemanticPreferenceMaintenanceReceiptRequest,
    ) -> SemanticPreferenceMaintenanceReceiptResult:
        provider = self._require_provider("maintenance_receipt")
        return _invoke(lambda: provider.maintenance_receipt(request))

    def _require_provider(self, operation: str) -> SemanticPreferenceReceiptProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": (
                        "application.capabilities.semantic_preference."
                        f"{operation}"
                    ),
                    "provider": "semantic_preference_receipt",
                }
            )
        return self._provider


def _application_result(
    payload: Mapping[str, object],
) -> SemanticPreferenceApplicationReceiptResult:
    return SemanticPreferenceApplicationReceiptResult(
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        surface=text(payload, "surface", resource=_RESOURCE),
        application_id=text(payload, "application_id", resource=_RESOURCE),
        outcome=text(payload, "outcome", resource=_RESOURCE),
        preference_ref_digests=text_tuple(
            payload.get("preference_ref_digests"),
            resource=_RESOURCE,
            field="preference_ref_digests",
        ),
        artifact_ref=optional_text(payload, "artifact_ref", resource=_RESOURCE),
    )


def _maintenance_result(
    payload: Mapping[str, object],
) -> SemanticPreferenceMaintenanceReceiptResult:
    return SemanticPreferenceMaintenanceReceiptResult(
        schema_version=text(payload, "schema_version", resource=_RESOURCE),
        trigger=text(payload, "trigger", resource=_RESOURCE),
        outcome=text(payload, "outcome", resource=_RESOURCE),
        corpus_ids=text_tuple(
            payload.get("corpus_ids"),
            resource=_RESOURCE,
            field="corpus_ids",
        ),
        scope_ref_digests=text_tuple(
            payload.get("scope_ref_digests"),
            resource=_RESOURCE,
            field="scope_ref_digests",
        ),
        evidence_ref=optional_text(payload, "evidence_ref", resource=_RESOURCE),
    )


def _validated_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationFailed(details={"field": field})
    return value.strip()


def _token(value: object, field: str) -> str:
    result = _validated_text(value, field)
    if not _TOKEN_RE.fullmatch(result):
        raise ValidationFailed(details={"field": field})
    return result


def _text_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValidationFailed(details={"field": field})
    if not all(isinstance(item, str) for item in value):
        raise ValidationFailed(details={"field": field})
    return tuple(value)


def _invoke(call: Callable[[], ResultT]) -> ResultT:
    try:
        return call()
    except ApplicationError:
        raise
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    except OSError as exc:
        raise StateUnavailable(
            details={"resource": _RESOURCE, "cause": type(exc).__name__}
        ) from exc
