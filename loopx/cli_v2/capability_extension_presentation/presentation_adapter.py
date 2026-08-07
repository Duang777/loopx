from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from loopx.application.errors import StateUnavailable
from loopx.application.presentations.contracts import (
    PresentationDeploymentContract,
    PresentationPackageRequest,
    PresentationPackageResult,
    PresentationPublisher,
    PresentationReadbackRequest,
    PresentationReadbackResult,
    PresentationRollbackRequest,
    PresentationRollbackResult,
    PresentationValidation,
)
from loopx.presentation.static_site import (
    package_static_site,
    rollback_static_site,
    verify_static_site_readback,
)


class LocalStaticSiteArtifactProvider:
    """Adapter over the existing provider-neutral static-site owner."""

    def package(
        self,
        request: PresentationPackageRequest,
    ) -> PresentationPackageResult:
        payload = package_static_site(
            site_dir=request.site_dir,
            output_dir=request.output_dir,
            site_id=request.site_id,
            entry_path=request.entry_path,
            revision=request.revision,
            publisher_kind=request.publisher_kind,
            base_url=request.base_url,
            state_dir=request.state_dir,
            desktop_visual_check=request.desktop_visual_check,
            mobile_visual_check=request.mobile_visual_check,
            link_check=request.link_check,
            execute=request.execute,
        )
        return _package_result(payload)

    def rollback(
        self,
        request: PresentationRollbackRequest,
    ) -> PresentationRollbackResult:
        payload = rollback_static_site(
            output_dir=request.output_dir,
            state_dir=request.state_dir,
            revision=request.revision,
            execute=request.execute,
        )
        return _rollback_result(payload)


class HttpPresentationReadbackProvider:
    """Explicitly injected HTTP reader; no implicit network authority exists."""

    __slots__ = ("_opener",)

    def __init__(self, opener: Callable[..., Any]) -> None:
        if not callable(opener):
            raise TypeError("presentation readback opener must be callable")
        self._opener = opener

    def verify(
        self,
        request: PresentationReadbackRequest,
    ) -> PresentationReadbackResult:
        payload = verify_static_site_readback(
            output_dir=request.output_dir,
            state_dir=request.state_dir,
            receipt_url=request.receipt_url,
            retries=request.retries,
            retry_delay_seconds=request.retry_delay_seconds,
            execute=request.execute,
            opener=self._opener,
        )
        return _readback_result(payload)


def _package_result(payload: Mapping[str, object]) -> PresentationPackageResult:
    return PresentationPackageResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        mode=_text(payload, "mode"),
        dry_run=_bool(payload, "dry_run"),
        write_required=_bool(payload, "write_required"),
        write_performed=_bool(payload, "write_performed"),
        semantic_noop=_bool(payload, "semantic_noop"),
        requested_revision=_text(payload, "requested_revision"),
        active_revision=_text(payload, "active_revision"),
        previous_revision=_optional_text(payload, "previous_revision"),
        semantic_digest=_text(payload, "semantic_digest"),
        publisher=_publisher(_mapping(payload.get("publisher"), "publisher")),
        output_dir=_text(payload, "output_dir"),
        manifest_path=_text(payload, "manifest_path"),
        receipt_path=_text(payload, "receipt_path"),
        state_receipt_log=_text(payload, "state_receipt_log"),
        validation=_validation(
            _mapping(payload.get("validation"), "validation")
        ),
    )


def _rollback_result(payload: Mapping[str, object]) -> PresentationRollbackResult:
    return PresentationRollbackResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        mode=_text(payload, "mode"),
        dry_run=_bool(payload, "dry_run"),
        write_required=_bool(payload, "write_required"),
        write_performed=_bool(payload, "write_performed"),
        from_revision=_text(payload, "from_revision"),
        active_revision=_text(payload, "active_revision"),
        semantic_digest=_text(payload, "semantic_digest"),
        publisher=_publisher(_mapping(payload.get("publisher"), "publisher")),
        output_dir=_text(payload, "output_dir"),
        manifest_path=_text(payload, "manifest_path"),
        receipt_path=_text(payload, "receipt_path"),
        state_receipt_log=_text(payload, "state_receipt_log"),
    )


def _readback_result(payload: Mapping[str, object]) -> PresentationReadbackResult:
    return PresentationReadbackResult(
        ok=_bool(payload, "ok"),
        schema_version=_text(payload, "schema_version"),
        mode=_text(payload, "mode"),
        dry_run=_bool(payload, "dry_run"),
        verified=_bool(payload, "verified"),
        receipt_url=_text(payload, "receipt_url"),
        attempts=_int(payload, "attempts"),
        site_id=_text(payload, "site_id"),
        revision=_text(payload, "revision"),
        semantic_digest=_text(payload, "semantic_digest"),
        state_receipt_log=_text(payload, "state_receipt_log"),
    )


def _publisher(payload: Mapping[str, object]) -> PresentationPublisher:
    deployment = payload.get("deployment_contract")
    contract = None
    if deployment is not None:
        mapping = _mapping(deployment, "deployment_contract")
        contract = PresentationDeploymentContract(
            artifact_root=_text(mapping, "artifact_root"),
            provider_owns_deploy_receipt=_bool(
                mapping,
                "provider_owns_deploy_receipt",
            ),
            loopx_receipt_readback=_text(mapping, "loopx_receipt_readback"),
        )
    return PresentationPublisher(
        kind=_text(payload, "kind"),
        base_url=_optional_text(payload, "base_url"),
        latest_url=_text(payload, "latest_url"),
        revision_url=_text(payload, "revision_url"),
        http_readback_required=_bool(payload, "http_readback_required"),
        deployment_contract=contract,
    )


def _validation(payload: Mapping[str, object]) -> PresentationValidation:
    return PresentationValidation(
        desktop_visual_check=_text(payload, "desktop_visual_check"),
        mobile_visual_check=_text(payload, "mobile_visual_check"),
        link_check=_text(payload, "link_check"),
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise StateUnavailable(details={"resource": "presentation", "field": field})
    return value


def _text(payload: Mapping[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StateUnavailable(details={"resource": "presentation", "field": field})
    return value


def _optional_text(payload: Mapping[str, object], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    return _text(payload, field)


def _bool(payload: Mapping[str, object], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise StateUnavailable(details={"resource": "presentation", "field": field})
    return value


def _int(payload: Mapping[str, object], field: str) -> int:
    value = payload.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise StateUnavailable(details={"resource": "presentation", "field": field})
    return value
