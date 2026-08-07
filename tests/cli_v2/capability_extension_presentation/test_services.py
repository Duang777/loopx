from __future__ import annotations

from pathlib import Path

import pytest

from loopx.application import Profile
from loopx.application.capabilities import (
    BuiltinCapabilityCatalogProvider,
    BuiltinContentOpsReadProvider,
    BuiltinRewardMemoryFixtureProvider,
    BuiltinRewardMemoryReadProvider,
    BuiltinValueConnectorInstallCheckProvider,
    BuiltinValueConnectorSourceMapProvider,
    CapabilityCatalogListRequest,
    CapabilityCatalogResult,
    CapabilityCatalogService,
    ContentOpsExplorationPlanRequest,
    ContentOpsItemCreateRequest,
    ContentOpsService,
    ContentOpsWalkthroughRequest,
    DecisionContextService,
    DecisionContextInspectProfileRequest,
    MaterialLifecycleService,
    MaterialLifecycleSkillStatusRequest,
    RewardMemoryHealthRequest,
    RewardMemoryCandidateReviewRequest,
    RewardMemoryRouteRequest,
    RewardMemoryService,
    SemanticPreferenceApplicationReceiptRequest,
    SemanticPreferenceMaintenanceReceiptRequest,
    SemanticPreferenceService,
    ValueConnectorInstallCheckRequest,
    ValueConnectorService,
    ValueConnectorSourceMapRequest,
)
from loopx.application.errors import (
    AuthorityDenied,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from loopx.application.extensions import (
    ExtensionInitRequest,
    ExtensionLifecycleService,
    ExtensionListRequest,
    ExtensionListResult,
    ExtensionRunRequest,
)
from loopx.application.presentations import (
    PresentationPackageRequest,
    PresentationPackageResult,
    PresentationPublisher,
    PresentationReadbackRequest,
    PresentationReadbackResult,
    PresentationService,
    PresentationValidation,
)
from loopx.cli_v2.capability_extension_presentation.application import (
    require_application_root,
)
from loopx.cli_v2.capability_extension_presentation.capability_adapters import (
    LocalContentOpsItemProvider,
    LocalDecisionContextProfileProvider,
    LocalMaterialLifecycleSkillProvider,
)


class _ExtensionListProvider:
    def __init__(self) -> None:
        self.list_calls = 0

    def list(self, request: ExtensionListRequest) -> ExtensionListResult:
        self.list_calls += 1
        return ExtensionListResult(
            schema_version="loopx_extension_state_v0",
            extensions=(),
        )


class _ArtifactProvider:
    def __init__(self) -> None:
        self.package_calls = 0

    def package(self, request: PresentationPackageRequest) -> PresentationPackageResult:
        self.package_calls += 1
        return PresentationPackageResult(
            schema_version="loopx_static_site_manifest_v0",
            mode="package",
            dry_run=not request.execute,
            write_required=True,
            write_performed=request.execute,
            semantic_noop=False,
            requested_revision="revision-1",
            active_revision="revision-1",
            previous_revision=None,
            semantic_digest="sha256:fixture",
            publisher=_publisher(),
            output_dir=str(request.output_dir),
            manifest_path=str(request.output_dir / "manifest.json"),
            receipt_path=str(request.output_dir / "receipt.json"),
            state_receipt_log=str(request.output_dir / "events.jsonl"),
            validation=PresentationValidation("passed", "passed", "passed"),
        )


class _ReadbackProvider:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, request: PresentationReadbackRequest) -> PresentationReadbackResult:
        self.calls += 1
        return PresentationReadbackResult(
            schema_version="loopx_static_site_receipt_v0",
            mode="verify-readback",
            dry_run=not request.execute,
            verified=True,
            receipt_url=request.receipt_url or "https://example.test/receipt.json",
            attempts=1,
            site_id="fixture",
            revision="revision-1",
            semantic_digest="sha256:fixture",
            state_receipt_log=str(request.output_dir / "events.jsonl"),
        )


def _publisher() -> PresentationPublisher:
    return PresentationPublisher(
        kind="local",
        base_url=None,
        latest_url="./",
        revision_url="./revisions/revision-1/",
        http_readback_required=False,
    )


def _package_request(tmp_path: Path, **overrides: object) -> PresentationPackageRequest:
    values: dict[str, object] = {
        "site_dir": tmp_path / "site",
        "output_dir": tmp_path / "published",
        "site_id": "fixture",
        "desktop_visual_check": "passed",
        "mobile_visual_check": "passed",
        "link_check": "passed",
    }
    values.update(overrides)
    return PresentationPackageRequest(**values)


def test_capability_adapter_projects_owner_mapping_into_explicit_dtos() -> None:
    result = BuiltinCapabilityCatalogProvider().list_capabilities(
        CapabilityCatalogListRequest()
    )
    assert isinstance(result, CapabilityCatalogResult)
    assert result.capabilities
    assert result.providers
    assert result.capabilities[0].capability_id
    assert not hasattr(result, "payload")


def test_capability_provider_missing_fails_closed() -> None:
    with pytest.raises(CapabilityUnavailable) as exc_info:
        CapabilityCatalogService(None).list(CapabilityCatalogListRequest())
    assert exc_info.value.details["provider"] == "capability_catalog"


def test_second_batch_capability_providers_fail_closed() -> None:
    calls = (
        lambda: DecisionContextService(None).describe_architecture(),
        lambda: MaterialLifecycleService(None).describe_architecture(),
        lambda: RewardMemoryService(None).health(RewardMemoryHealthRequest()),
        lambda: RewardMemoryService(None).route(RewardMemoryRouteRequest()),
        lambda: ValueConnectorService(None).install_check(
            ValueConnectorInstallCheckRequest()
        ),
        lambda: SemanticPreferenceService(None).application_receipt(
            SemanticPreferenceApplicationReceiptRequest(
                surface="pr_review.reply",
                application_id="application:fixture",
                outcome="applied",
            )
        ),
        lambda: ContentOpsService(None).exploration_plan(
            ContentOpsExplorationPlanRequest()
        ),
        lambda: ContentOpsService(None).walkthrough_artifact(
            ContentOpsWalkthroughRequest()
        ),
        lambda: ContentOpsService.builtin().create_item(
            ContentOpsItemCreateRequest(
                item_id="item_fixture",
                item_kind="post",
                channel="x_public",
                content_digest="sha256:" + "a" * 64,
                content_ref="artifact:fixture",
                source_refs=("source_fixture",),
                created_at="2026-06-23T00:00:00+00:00",
            )
        ),
        lambda: DecisionContextService.builtin().inspect_profile(
            DecisionContextInspectProfileRequest(
                goal_id="goal_fixture",
                agent_id="agent_fixture",
            )
        ),
        lambda: MaterialLifecycleService.builtin().inspect_skill(
            MaterialLifecycleSkillStatusRequest(Path("."))
        ),
        lambda: RewardMemoryService(None).corpus_registry(),
        lambda: RewardMemoryService(None).candidate_review(
            RewardMemoryCandidateReviewRequest()
        ),
        lambda: ValueConnectorService(
            BuiltinValueConnectorInstallCheckProvider()
        ).source_map(ValueConnectorSourceMapRequest()),
        lambda: SemanticPreferenceService(None).maintenance_receipt(
            SemanticPreferenceMaintenanceReceiptRequest(
                trigger="explicit_feedback",
                outcome="verified",
                corpus_ids=("fixture_corpus",),
            )
        ),
    )
    for call in calls:
        with pytest.raises(CapabilityUnavailable):
            call()


def test_value_connector_adapter_discards_compatibility_only_fields() -> None:
    result = BuiltinValueConnectorInstallCheckProvider().check(
        ValueConnectorInstallCheckRequest(connector="finance_market_snapshot")
    )
    assert result.checks[0].connector_id == "finance_market_snapshot"
    assert not hasattr(result.checks[0], "migration")
    assert not hasattr(result, "payload")

    source_map = BuiltinValueConnectorSourceMapProvider().source_map(
        ValueConnectorSourceMapRequest(connector="finance_market_snapshot")
    )
    assert source_map.source_profiles[0].connector_id == "finance_market_snapshot"
    assert not hasattr(source_map.source_profiles[0], "migration")


def test_third_batch_malformed_owner_packets_fail_closed() -> None:
    calls = (
        lambda: BuiltinContentOpsReadProvider(
            exploration_builder=lambda **_kwargs: {"ok": True}
        ).exploration_plan(ContentOpsExplorationPlanRequest()),
        lambda: BuiltinContentOpsReadProvider(
            walkthrough_builder=lambda **_kwargs: {"ok": True}
        ).walkthrough_artifact(ContentOpsWalkthroughRequest()),
        lambda: BuiltinRewardMemoryReadProvider(
            registry_builder=lambda: {"ok": True}
        ).corpus_registry(),
        lambda: BuiltinRewardMemoryReadProvider(
            candidate_fixture_builder=lambda: {"ok": True}
        ).candidate_review(RewardMemoryCandidateReviewRequest()),
        lambda: BuiltinValueConnectorSourceMapProvider(
            builder=lambda **_kwargs: {"ok": True}
        ).source_map(ValueConnectorSourceMapRequest()),
        lambda: LocalContentOpsItemProvider(
            builder=lambda **_kwargs: {"ok": True}
        ).create_item(
            ContentOpsItemCreateRequest(
                item_id="item_fixture",
                item_kind="post",
                channel="x_public",
                content_digest="sha256:" + "a" * 64,
                content_ref="artifact:fixture",
                source_refs=(),
                created_at="2026-06-23T00:00:00+00:00",
            )
        ),
        lambda: LocalDecisionContextProfileProvider(
            resolver=lambda **_kwargs: ({"ok": True}, None)
        ).inspect_profile(
            DecisionContextInspectProfileRequest(
                goal_id="goal_fixture",
                agent_id="agent_fixture",
            )
        ),
        lambda: LocalMaterialLifecycleSkillProvider(
            inspector=lambda *_args, **_kwargs: {"schema_version": "fixture"}
        ).inspect_skill(MaterialLifecycleSkillStatusRequest(Path("."))),
    )
    for call in calls:
        with pytest.raises(StateUnavailable):
            call()


def test_walkthrough_provider_forces_no_fetch_and_never_opens_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loopx.capabilities.content_ops import surface

    original = surface.build_content_ops_public_handle_observation_packet
    fetch_values: list[bool] = []

    def observe(**kwargs):
        fetch_values.append(kwargs["fetch"])
        return original(**kwargs)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("walkthrough provider must not open a network route")

    monkeypatch.setattr(
        surface,
        "build_content_ops_public_handle_observation_packet",
        observe,
    )
    monkeypatch.setattr(surface, "build_opener", fail_network)
    result = ContentOpsService.builtin().walkthrough_artifact(
        ContentOpsWalkthroughRequest(
            channel_count=1,
            recent_record_count=2,
            report_count=3,
            api_request_count=4,
        )
    )
    assert result.external_reads_performed is False
    assert fetch_values == [False]


def test_candidate_review_reducer_is_deterministic_and_has_no_persistence_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import random
    import time
    import uuid

    def forbidden(*_args, **_kwargs):
        raise AssertionError("candidate reducer must not use writes, time, or random")

    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(uuid, "uuid4", forbidden)
    service = RewardMemoryService(
        BuiltinRewardMemoryFixtureProvider(),
        BuiltinRewardMemoryReadProvider(),
    )
    request = RewardMemoryCandidateReviewRequest(decision="accept")
    first = service.candidate_review(request)
    second = service.candidate_review(request)
    assert first == second
    assert first.provider_write_performed is False
    assert first.external_writes_performed is False
    assert first.adapter.shared_candidate.candidate_persisted is False


def test_new_safe_batch_never_opens_network_process_or_write_seams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import socket
    import subprocess

    def forbidden(*_args, **_kwargs):
        raise AssertionError("safe read/constructor batch crossed an effect boundary")

    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    item = ContentOpsService(
        BuiltinContentOpsReadProvider(),
        LocalContentOpsItemProvider(),
    ).create_item(
        ContentOpsItemCreateRequest(
            item_id="item_fixture",
            item_kind="post",
            channel="x_public",
            content_digest="sha256:" + "a" * 64,
            content_ref="artifact:fixture",
            source_refs=("source_fixture",),
            created_at="2026-06-23T00:00:00+00:00",
        )
    )
    profile = DecisionContextService(
        None,
        LocalDecisionContextProfileProvider(),
    ).inspect_profile(
        DecisionContextInspectProfileRequest(
            goal_id="goal_fixture",
            agent_id="agent_fixture",
        )
    )
    skill = MaterialLifecycleService(
        None,
        LocalMaterialLifecycleSkillProvider(),
    ).inspect_skill(MaterialLifecycleSkillStatusRequest(tmp_path))

    assert item.external_reads_performed is False
    assert item.external_writes_performed is False
    assert profile.external_writes_performed is False
    assert profile.status == "disabled"
    assert skill.status == "missing"
    assert list(tmp_path.iterdir()) == []


def test_item_create_digest_validation_is_actionable() -> None:
    with pytest.raises(ValidationFailed) as caught:
        ContentOpsItemCreateRequest(
            item_id="item_fixture",
            item_kind="post",
            channel="x_public",
            content_digest="not-a-digest",
            content_ref="artifact:fixture",
            source_refs=("source_fixture",),
            created_at="2026-06-23T00:00:00+00:00",
        )

    assert str(caught.value) == (
        "content_digest must use sha256:<64 lowercase hex chars>"
    )
    assert dict(caught.value.details) == {"field": "content_digest"}


@pytest.mark.parametrize(
    "request_factory",
    (
        lambda: RewardMemoryHealthRequest(case="unknown"),
        lambda: RewardMemoryRouteRequest(surface_count=True),
        lambda: ValueConnectorInstallCheckRequest(connector="unknown"),
        lambda: SemanticPreferenceApplicationReceiptRequest(
            surface="not-qualified",
            application_id="application:fixture",
            outcome="applied",
        ),
        lambda: SemanticPreferenceMaintenanceReceiptRequest(
            trigger="explicit_feedback",
            outcome="verified",
            corpus_ids=(),
        ),
        lambda: ContentOpsExplorationPlanRequest(scenario=""),
        lambda: ContentOpsWalkthroughRequest(channel_count=-1),
        lambda: RewardMemoryCandidateReviewRequest(decision="unknown"),
        lambda: ValueConnectorSourceMapRequest(connector="unknown"),
        lambda: ContentOpsItemCreateRequest(
            item_id="item_fixture",
            item_kind="post",
            channel="x_public",
            content_digest="not-a-digest",
            content_ref="artifact:fixture",
            source_refs=(),
            created_at="2026-06-23T00:00:00+00:00",
        ),
        lambda: DecisionContextInspectProfileRequest(
            goal_id="not valid",
            agent_id="agent_fixture",
        ),
        lambda: MaterialLifecycleSkillStatusRequest(
            Path("."),
            surfaces=("unknown",),
        ),
    ),
)
def test_second_batch_requests_validate_at_application_boundary(
    request_factory,
) -> None:
    with pytest.raises(ValidationFailed):
        request_factory()


def test_extension_provider_missing_and_write_authority_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(CapabilityUnavailable):
        ExtensionLifecycleService(profile=Profile.CLI, provider=None).list(
            ExtensionListRequest(tmp_path / "state.json")
        )

    provider = _ExtensionListProvider()
    read_only = ExtensionLifecycleService(
        profile=Profile.HTTP_READ_ONLY,
        provider=provider,
    )
    with pytest.raises(AuthorityDenied):
        read_only.initialize(
            ExtensionInitRequest("fixture-extension", execute=True)
        )
    assert provider.list_calls == 0


def test_extension_run_request_recursively_freezes_json(tmp_path: Path) -> None:
    original = {"items": [{"value": 1}]}
    request = ExtensionRunRequest(
        extension_id="fixture-extension",
        state_file=tmp_path / "state.json",
        request=original,
    )
    original["items"][0]["value"] = 2
    frozen_items = request.request["items"]
    assert isinstance(frozen_items, tuple)
    assert frozen_items[0]["value"] == 1
    with pytest.raises(ValidationFailed):
        ExtensionRunRequest(
            extension_id="fixture-extension",
            state_file=tmp_path / "state.json",
            request={"invalid": object()},
        )


@pytest.mark.parametrize(
    ("overrides", "field"),
    (
        ({"site_id": ""}, "site_id"),
        ({"entry_path": ""}, "entry_path"),
        ({"desktop_visual_check": ""}, "desktop_visual_check"),
        ({"publisher_kind": "unknown"}, "publisher_kind"),
        ({"execute": 1}, "execute"),
    ),
)
def test_presentation_package_request_rejects_invalid_boundary_values(
    tmp_path: Path,
    overrides: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        _package_request(tmp_path, **overrides)
    assert exc_info.value.details["field"] == field


@pytest.mark.parametrize(
    ("kwargs", "field"),
    (
        ({"receipt_url": "file:///private/receipt.json"}, "receipt_url"),
        ({"retries": 0}, "retries"),
        ({"retries": 11}, "retries"),
        ({"retry_delay_seconds": -0.1}, "retry_delay_seconds"),
        ({"retry_delay_seconds": 31}, "retry_delay_seconds"),
        ({"execute": "yes"}, "execute"),
    ),
)
def test_presentation_readback_request_rejects_invalid_boundary_values(
    tmp_path: Path,
    kwargs: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(ValidationFailed) as exc_info:
        PresentationReadbackRequest(output_dir=tmp_path, **kwargs)
    assert exc_info.value.details["field"] == field


def test_presentation_provider_and_execution_authority_fail_closed(
    tmp_path: Path,
) -> None:
    artifact = _ArtifactProvider()
    no_readback = PresentationService(
        profile=Profile.CLI,
        artifact_provider=artifact,
        readback_provider=None,
    )
    assert no_readback.package(_package_request(tmp_path)).dry_run is True
    assert artifact.package_calls == 1
    with pytest.raises(CapabilityUnavailable):
        no_readback.verify_readback(
            PresentationReadbackRequest(
                output_dir=tmp_path,
                receipt_url="https://example.test/receipt.json",
            )
        )

    readback = _ReadbackProvider()
    read_only = PresentationService(
        profile=Profile.HTTP_READ_ONLY,
        artifact_provider=artifact,
        readback_provider=readback,
    )
    with pytest.raises(AuthorityDenied):
        read_only.verify_readback(
            PresentationReadbackRequest(
                output_dir=tmp_path,
                receipt_url="https://example.test/receipt.json",
            )
        )
    assert readback.calls == 0


def test_cli_cohort_root_accessor_never_reads_application_context() -> None:
    class ContextOnly:
        context = object()

    with pytest.raises(CapabilityUnavailable) as exc_info:
        require_application_root(ContextOnly())
    assert exc_info.value.details["missing_accessors"] == [
        "capabilities",
        "extensions",
        "presentations",
    ]
