from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from loopx.application import Profile
from loopx.application.capabilities import (
    BuiltinContentOpsReadProvider,
    BuiltinDecisionContextArchitectureProvider,
    BuiltinMaterialLifecycleArchitectureProvider,
    BuiltinRewardMemoryFixtureProvider,
    BuiltinRewardMemoryReadProvider,
    BuiltinValueConnectorInstallCheckProvider,
    BuiltinValueConnectorSourceMapProvider,
    CapabilityApplicationServices,
    CapabilityCatalogProvider,
    CapabilityCatalogResult,
    CapabilityCatalogService,
    CapabilityCommand,
    CapabilityDetail,
    CapabilityDetailResult,
    CapabilityProtocol,
    CapabilityProviderState,
    CapabilityProviderSummary,
    CapabilitySummary,
    ContentOpsService,
    DecisionContextService,
    MaterialLifecycleService,
    RewardMemoryService,
    ValueConnectorService,
)
from loopx.application.extensions import (
    ExtensionDoctorResult,
    ExtensionFileChange,
    ExtensionInitResult,
    ExtensionInstallResult,
    ExtensionLifecycleService,
    ExtensionListResult,
    ExtensionNextCommands,
    ExtensionRollbackResult,
    ExtensionRunResult,
    ExtensionToggleResult,
)
from loopx.application.presentations import (
    PresentationPackageResult,
    PresentationPublisher,
    PresentationReadbackResult,
    PresentationRollbackResult,
    PresentationService,
    PresentationValidation,
)
from loopx.cli_v2.capability_extension_presentation import (
    CAPABILITY_EXTENSION_PRESENTATION_COHORT,
)
from loopx.cli_v2.capability_extension_presentation.capability_adapters import (
    LocalContentOpsItemProvider,
    LocalDecisionContextProfileProvider,
    LocalMaterialLifecycleSkillProvider,
)
from loopx.cli_v2.capability_extension_presentation.extension_adapter import (
    LocalExtensionProvider,
)
from loopx.cli_v2.capability_extension_presentation.presentation_adapter import (
    LocalStaticSiteArtifactProvider,
)
from loopx.cli_v2.entrypoint import main as v2_main
from loopx.entrypoint import main as legacy_main


@dataclass
class _Root:
    capabilities: object
    extensions: object
    presentations: object


class _CapabilityProvider(CapabilityCatalogProvider):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_capabilities(self, request) -> CapabilityCatalogResult:
        self.calls.append("list")
        return _capability_catalog_result()

    def get_capability(self, request) -> CapabilityDetailResult:
        self.calls.append("get")
        return _capability_detail_result()


class _ContentOpsProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = BuiltinContentOpsReadProvider()
        self.item_delegate = LocalContentOpsItemProvider()

    def exploration_plan(self, request):
        self.calls.append("exploration_plan")
        return self.delegate.exploration_plan(request)

    def walkthrough_artifact(self, request):
        self.calls.append("walkthrough_artifact")
        return self.delegate.walkthrough_artifact(request)

    def create_item(self, request):
        self.calls.append("create_item")
        return self.item_delegate.create_item(request)


class _DecisionContextProfileProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = LocalDecisionContextProfileProvider()

    def inspect_profile(self, request):
        self.calls.append("inspect_profile")
        return self.delegate.inspect_profile(request)


class _MaterialLifecycleSkillProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = LocalMaterialLifecycleSkillProvider()

    def inspect_skill(self, request):
        self.calls.append("inspect_skill")
        return self.delegate.inspect_skill(request)


class _RewardMemoryReadProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = BuiltinRewardMemoryReadProvider()

    def corpus_registry(self):
        self.calls.append("corpus_registry")
        return self.delegate.corpus_registry()

    def candidate_review(self, request):
        self.calls.append("candidate_review")
        return self.delegate.candidate_review(request)


class _ValueConnectorSourceMapProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = BuiltinValueConnectorSourceMapProvider()

    def source_map(self, request):
        self.calls.append("source_map")
        return self.delegate.source_map(request)


class _ExtensionProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def initialize(self, request) -> ExtensionInitResult:
        self.calls.append("initialize")
        return ExtensionInitResult(
            schema_version="loopx_extension_scaffold_v0",
            operation="init",
            dry_run=True,
            changed=False,
            extension_id=request.extension_id,
            starter_kind="standalone",
            capability_id=None,
            managed_entrypoint="loopx extension run",
            version=request.version,
            destination=str(request.destination or "packages/fixture-extension"),
            module_name="fixture_extension",
            protocol="fixture_extension_v0",
            permissions=(),
            files=(ExtensionFileChange("pyproject.toml", "would_create"),),
            next_commands=ExtensionNextCommands("install", "register", "run"),
        )

    def list(self, request) -> ExtensionListResult:
        self.calls.append("list")
        return ExtensionListResult(
            schema_version="loopx_extension_state_v0",
            extensions=(),
        )

    def install(self, request, *, operation: str) -> ExtensionInstallResult:
        self.calls.append(operation)
        return ExtensionInstallResult(
            schema_version="loopx_extension_operation_v0",
            operation=operation,
            dry_run=True,
            changed=False,
            extension_id="fixture-extension",
            version="1.0.0",
            revision="revision-1",
            previous_revision=None,
            enabled=None,
            doctor=_doctor(),
            rollback_available=False,
        )

    def enable(self, request) -> ExtensionToggleResult:
        self.calls.append("enable")
        return _toggle("enable", doctor=_doctor())

    def disable(self, request) -> ExtensionToggleResult:
        self.calls.append("disable")
        return _toggle("disable")

    def rollback(self, request) -> ExtensionRollbackResult:
        self.calls.append("rollback")
        return ExtensionRollbackResult(
            schema_version="loopx_extension_operation_v0",
            operation="rollback",
            dry_run=True,
            changed=False,
            extension_id=request.extension_id,
            version="0.9.0",
            revision="revision-0",
            previous_revision="revision-1",
            enabled=True,
            doctor=_doctor(),
        )

    def doctor(self, request) -> ExtensionDoctorResult:
        self.calls.append("doctor")
        return _doctor()

    def run(self, request) -> ExtensionRunResult:
        self.calls.append("run")
        return ExtensionRunResult(
            schema_version="loopx_extension_run_receipt_v0",
            operation="run",
            extension_id=request.extension_id,
            provider_version="1.0.0",
            revision="revision-1",
            protocol="fixture_extension_v0",
            required_permissions=(),
            dry_run=True,
            executed=False,
            status="ready",
            input_schema_version="fixture_request_v0",
        )


class _PresentationProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def package(self, request) -> PresentationPackageResult:
        self.calls.append("package")
        return PresentationPackageResult(
            schema_version="loopx_static_site_manifest_v0",
            mode="package",
            dry_run=True,
            write_required=True,
            write_performed=False,
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

    def rollback(self, request) -> PresentationRollbackResult:
        self.calls.append("rollback")
        return PresentationRollbackResult(
            schema_version="loopx_static_site_manifest_v0",
            mode="rollback",
            dry_run=True,
            write_required=True,
            write_performed=False,
            from_revision="revision-1",
            active_revision="revision-0",
            semantic_digest="sha256:fixture",
            publisher=_publisher(),
            output_dir=str(request.output_dir),
            manifest_path=str(request.output_dir / "manifest.json"),
            receipt_path=str(request.output_dir / "receipt.json"),
            state_receipt_log=str(request.output_dir / "events.jsonl"),
        )

    def verify(self, request) -> PresentationReadbackResult:
        self.calls.append("verify_readback")
        return PresentationReadbackResult(
            schema_version="loopx_static_site_receipt_v0",
            mode="verify-readback",
            dry_run=True,
            verified=True,
            receipt_url=request.receipt_url or "https://example.test/receipt.json",
            attempts=1,
            site_id="fixture-site",
            revision="revision-1",
            semantic_digest="sha256:fixture",
            state_receipt_log=str(request.output_dir / "events.jsonl"),
        )


def _doctor() -> ExtensionDoctorResult:
    return ExtensionDoctorResult(
        schema_version="loopx_extension_doctor_v0",
        extension_id="fixture-extension",
        version="1.0.0",
        status="probe_required",
        available=True,
        verified=False,
        entrypoint_identity=None,
        failure_kind=None,
        external_writes_performed=False,
    )


def _toggle(
    operation: str,
    *,
    doctor: ExtensionDoctorResult | None = None,
) -> ExtensionToggleResult:
    return ExtensionToggleResult(
        schema_version="loopx_extension_operation_v0",
        operation=operation,
        dry_run=True,
        changed=False,
        would_change=True,
        extension_id="fixture-extension",
        enabled=operation != "enable",
        active_revision="revision-1",
        doctor=doctor,
    )


def _publisher() -> PresentationPublisher:
    return PresentationPublisher(
        kind="local",
        base_url=None,
        latest_url="./",
        revision_url="./revisions/revision-1/",
        http_readback_required=False,
    )


def _capability_catalog_result() -> CapabilityCatalogResult:
    state = CapabilityProviderState(True, True, True, True)
    return CapabilityCatalogResult(
        schema_version="loopx_capability_catalog_v0",
        capabilities=(
            CapabilitySummary(
                capability_id="fixture",
                title="Fixture",
                status="active-preview",
                origin="builtin",
                visibility="public",
                provider_id="loopx-core",
                provider_state=state,
                real_world_anchor="fixture",
                entry_command="loopx fixture",
                implemented_protocol_count=1,
                implementation_provider_count=0,
                smoke_count=1,
                next_real_step="validate",
            ),
        ),
        providers=(CapabilityProviderSummary("loopx-core", "builtin", state),),
    )


def _capability_detail_result() -> CapabilityDetailResult:
    return CapabilityDetailResult(
        schema_version="loopx_capability_detail_v0",
        capability=CapabilityDetail(
            capability_id="fixture",
            origin="builtin",
            visibility="public",
            provider_id="loopx-core",
            title="Fixture",
            status="active-preview",
            default_enabled=False,
            real_world_anchor="fixture",
            user_value="fixture",
            entry_command="loopx fixture",
            commands=(CapabilityCommand("loopx fixture", "test", "read-only"),),
            implemented_protocols=(
                CapabilityProtocol("fixture_v0", "loopx.fixture", "docs/fixture.md"),
            ),
            smokes=("python3 fixture.py",),
            docs=("docs/fixture.md",),
            boundaries=("fixture-only",),
            next_real_step="validate",
            provider_state=CapabilityProviderState(True, True, True, True),
        ),
    )


def _fake_root() -> tuple[
    _Root,
    _CapabilityProvider,
    _ContentOpsProvider,
    _DecisionContextProfileProvider,
    _MaterialLifecycleSkillProvider,
    _RewardMemoryReadProvider,
    _ValueConnectorSourceMapProvider,
    _ExtensionProvider,
    _PresentationProvider,
]:
    capability = _CapabilityProvider()
    content_ops = _ContentOpsProvider()
    decision_context = _DecisionContextProfileProvider()
    material_lifecycle = _MaterialLifecycleSkillProvider()
    reward_memory = _RewardMemoryReadProvider()
    value_connectors = _ValueConnectorSourceMapProvider()
    extension = _ExtensionProvider()
    presentation = _PresentationProvider()
    builtins = CapabilityApplicationServices.builtin()
    return (
        _Root(
            capabilities=CapabilityApplicationServices(
                catalog=CapabilityCatalogService(capability),
                content_ops=ContentOpsService(content_ops, content_ops),
                decision_context=DecisionContextService(
                    BuiltinDecisionContextArchitectureProvider(),
                    decision_context,
                ),
                material_lifecycle=MaterialLifecycleService(
                    BuiltinMaterialLifecycleArchitectureProvider(),
                    material_lifecycle,
                ),
                reward_memory=RewardMemoryService(
                    BuiltinRewardMemoryFixtureProvider(),
                    reward_memory,
                ),
                value_connectors=ValueConnectorService(
                    BuiltinValueConnectorInstallCheckProvider(),
                    value_connectors,
                ),
                semantic_preference=builtins.semantic_preference,
            ),
            extensions=ExtensionLifecycleService(
                profile=Profile.CLI,
                provider=extension,
            ),
            presentations=PresentationService(
                profile=Profile.CLI,
                artifact_provider=presentation,
                readback_provider=presentation,
            ),
        ),
        capability,
        content_ops,
        decision_context,
        material_lifecycle,
        reward_memory,
        value_connectors,
        extension,
        presentation,
    )


def test_all_29_bindings_dispatch_through_typed_services_only(tmp_path: Path) -> None:
    (
        root,
        capability,
        content_ops,
        decision_context,
        material_lifecycle,
        reward_memory,
        value_connectors,
        extension,
        presentation,
    ) = _fake_root()
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps({"schema_version": "fixture_request_v0"}),
        encoding="utf-8",
    )
    cases = (
        ["capability", "list"],
        ["capability", "show", "fixture"],
        ["extension", "init", "fixture-extension"],
        ["extension", "list"],
        ["extension", "install", "--manifest", str(tmp_path / "manifest.json")],
        ["extension", "upgrade", "--manifest", str(tmp_path / "manifest.json")],
        ["extension", "enable", "fixture-extension"],
        ["extension", "disable", "fixture-extension"],
        ["extension", "rollback", "fixture-extension"],
        ["extension", "doctor", "fixture-extension"],
        [
            "extension",
            "run",
            "fixture-extension",
            "--input-json",
            str(request_path),
        ],
        [
            "presentation",
            "package",
            "--site-dir",
            str(tmp_path / "site"),
            "--output-dir",
            str(tmp_path / "published"),
            "--site-id",
            "fixture-site",
            "--desktop-visual-check",
            "passed",
            "--mobile-visual-check",
            "passed",
            "--link-check",
            "passed",
        ],
        ["presentation", "rollback", "--output-dir", str(tmp_path / "published")],
        [
            "presentation",
            "verify-readback",
            "--output-dir",
            str(tmp_path / "published"),
            "--receipt-url",
            "https://example.test/receipt.json",
        ],
        ["decision-context", "architecture"],
        [
            "decision-context",
            "inspect-profile",
            "--goal-id",
            "goal_fixture",
            "--agent-id",
            "agent_fixture",
        ],
        ["content-ops", "exploration-plan"],
        [
            "content-ops",
            "walkthrough-artifact",
            "--channel-count",
            "1",
            "--recent-record-count",
            "2",
            "--report-count",
            "3",
            "--api-request-count",
            "4",
        ],
        [
            "content-ops",
            "item-create",
            "--item-id",
            "item_fixture",
            "--item-kind",
            "post",
            "--channel",
            "x_public",
            "--content-digest",
            "sha256:" + "a" * 64,
            "--content-ref",
            "artifact:fixture",
            "--source-ref",
            "source_fixture",
            "--created-at",
            "2026-06-23T00:00:00+00:00",
        ],
        ["material-lifecycle", "architecture"],
        [
            "material-lifecycle",
            "skill-status",
            "--project",
            str(tmp_path),
        ],
        ["reward-memory", "corpus-registry"],
        ["reward-memory", "candidate-review", "--decision", "accept"],
        ["reward-memory", "health-check", "--case", "empty"],
        ["reward-memory", "route-check", "--case", "pr-3237"],
        [
            "semantic-preference",
            "receipt",
            "--surface",
            "pr_review.reply",
            "--application-id",
            "application:fixture",
            "--outcome",
            "applied",
            "--preference-ref",
            "preference:fixture",
        ],
        [
            "semantic-preference",
            "maintenance-receipt",
            "--trigger",
            "explicit_feedback",
            "--outcome",
            "verified",
            "--corpus-id",
            "fixture_corpus",
        ],
        [
            "value-connectors",
            "install-check",
            "--connector",
            "github_public_channel",
        ],
        [
            "value-connectors",
            "source-map",
            "--connector",
            "github_public_channel",
        ],
    )
    for argv in cases:
        output = StringIO()
        assert (
            v2_main(
                ["--format", "json", *argv],
                application_factory=lambda _args, _registry: root,
                cohorts=(CAPABILITY_EXTENSION_PRESENTATION_COHORT,),
                stdout=output,
            )
            == 0
        )
        assert isinstance(json.loads(output.getvalue()), dict)

    assert capability.calls == ["list", "get"]
    assert content_ops.calls == [
        "exploration_plan",
        "walkthrough_artifact",
        "create_item",
    ]
    assert decision_context.calls == ["inspect_profile"]
    assert material_lifecycle.calls == ["inspect_skill"]
    assert reward_memory.calls == ["corpus_registry", "candidate_review"]
    assert value_connectors.calls == ["source_map"]
    assert extension.calls == [
        "initialize",
        "list",
        "install",
        "upgrade",
        "enable",
        "disable",
        "rollback",
        "doctor",
        "run",
    ]
    assert presentation.calls == ["package", "rollback", "verify_readback"]


def _legacy_output(argv: list[str]) -> tuple[int, str]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = legacy_main(argv)
    return exit_code, output.getvalue()


def _v2_output(argv: list[str], root: _Root) -> tuple[int, str]:
    output = StringIO()
    exit_code = v2_main(
        argv,
        application_factory=lambda _args, _registry: root,
        cohorts=(CAPABILITY_EXTENSION_PRESENTATION_COHORT,),
        stdout=output,
    )
    return exit_code, output.getvalue()


def _legacy_external_output(argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            exit_code = legacy_main(argv)
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _v2_external_output(argv: list[str], root: _Root) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            exit_code = v2_main(
                argv,
                application_factory=lambda _args, _registry: root,
                cohorts=(CAPABILITY_EXTENSION_PRESENTATION_COHORT,),
                stdout=stdout,
                stderr=stderr,
            )
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _item_create_argv(content_digest: str) -> list[str]:
    return [
        "content-ops",
        "item-create",
        "--item-id",
        "item_fixture",
        "--item-kind",
        "post",
        "--channel",
        "x_public",
        "--content-digest",
        content_digest,
        "--content-ref",
        "artifact:fixture",
        "--source-ref",
        "source_fixture",
        "--created-at",
        "2026-06-23T00:00:00+00:00",
    ]


def _local_root() -> _Root:
    builtins = CapabilityApplicationServices.builtin()
    return _Root(
        capabilities=CapabilityApplicationServices(
            catalog=builtins.catalog,
            content_ops=ContentOpsService(
                BuiltinContentOpsReadProvider(),
                LocalContentOpsItemProvider(),
            ),
            decision_context=DecisionContextService(
                BuiltinDecisionContextArchitectureProvider(),
                LocalDecisionContextProfileProvider(),
            ),
            material_lifecycle=MaterialLifecycleService(
                BuiltinMaterialLifecycleArchitectureProvider(),
                LocalMaterialLifecycleSkillProvider(),
            ),
            reward_memory=builtins.reward_memory,
            value_connectors=builtins.value_connectors,
            semantic_preference=builtins.semantic_preference,
        ),
        extensions=ExtensionLifecycleService(
            profile=Profile.CLI,
            provider=LocalExtensionProvider(),
        ),
        presentations=PresentationService(
            profile=Profile.CLI,
            artifact_provider=LocalStaticSiteArtifactProvider(),
            readback_provider=None,
        ),
    )


def _forbid_external_effects(
    monkeypatch,
    operation: str,
    *,
    allow_file_reads: bool = True,
) -> None:
    import builtins
    import socket
    import sqlite3
    import subprocess

    def forbidden(*_args, **_kwargs):
        raise AssertionError(f"{operation} crossed an external effect boundary")

    real_open = builtins.open
    real_path_open = Path.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            return forbidden(file, mode, *args, **kwargs)
        return real_open(file, mode, *args, **kwargs)

    def read_only_path_open(path, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            return forbidden(path, mode, *args, **kwargs)
        return real_path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(
        builtins,
        "open",
        read_only_open if allow_file_reads else forbidden,
    )
    monkeypatch.setattr(
        Path,
        "open",
        read_only_path_open if allow_file_reads else forbidden,
    )
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "touch", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)


def test_item_create_depth_closure_matches_exact_external_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _forbid_external_effects(monkeypatch, "item-create")

    registry = ["--registry", str(tmp_path / "registry.json")]
    success = _item_create_argv("sha256:" + "a" * 64)
    invalid = _item_create_argv("not-a-digest")
    cases = (
        ("help", [*registry, "content-ops", "item-create", "--help"], 0),
        ("success-json", [*registry, "--format", "json", *success], 0),
        ("success-markdown", [*registry, "--format", "markdown", *success], 0),
        ("validation-json", [*registry, "--format", "json", *invalid], 1),
        ("validation-markdown", [*registry, "--format", "markdown", *invalid], 1),
    )
    root = _local_root()
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv, expected_exit_code in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == expected_exit_code, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    success_payload = json.loads(observed["success-json"][1])
    assert success_payload["external_reads_performed"] is False
    assert success_payload["external_writes_performed"] is False
    assert success_payload["autopublish_allowed"] is False
    assert observed["success-markdown"][1].endswith("\n\n")
    assert "content_digest must use sha256" in observed["validation-json"][1]
    assert observed["validation-markdown"][1].endswith("\n\n")
    assert list(tmp_path.iterdir()) == []


def test_exploration_plan_depth_closure_matches_exact_external_contract(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _forbid_external_effects(monkeypatch, "exploration-plan")

    registry = ["--registry", str(tmp_path / "registry.json")]
    success = [
        "content-ops",
        "exploration-plan",
        "--scenario",
        "public_fixture",
        "--generated-at",
        "2026-06-23T00:00:00Z",
    ]
    invalid = [
        "content-ops",
        "exploration-plan",
        "--scenario",
        "secret",
    ]
    cases = (
        ("help", [*registry, "content-ops", "exploration-plan", "--help"], 0),
        ("success-json", [*registry, "--format", "json", *success], 0),
        ("success-markdown", [*registry, "--format", "markdown", *success], 0),
        ("validation-json", [*registry, "--format", "json", *invalid], 1),
        ("validation-markdown", [*registry, "--format", "markdown", *invalid], 1),
    )
    root = _local_root()
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv, expected_exit_code in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == expected_exit_code, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    success_payload = json.loads(observed["success-json"][1])
    assert success_payload["external_reads_performed"] is False
    assert success_payload["external_writes_performed"] is False
    assert success_payload["private_source_bodies_read"] is False
    assert success_payload["local_paths_captured"] is False
    assert success_payload["autopublish_allowed"] is False
    assert observed["success-markdown"][1].endswith("\n\n")
    assert "scenario must be a compact public-safe label" in observed[
        "validation-json"
    ][1]
    assert observed["validation-markdown"][1].endswith("\n\n")
    assert list(tmp_path.iterdir()) == []


def test_walkthrough_artifact_depth_closure_is_exact_public_safe_and_io_free(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _local_root()
    _forbid_external_effects(
        monkeypatch,
        "content-ops walkthrough-artifact",
        allow_file_reads=False,
    )

    registry = ["--registry", str(tmp_path / "registry.json")]
    success = [
        "content-ops",
        "walkthrough-artifact",
        "--public-handle-url",
        "https://example.com/public-handle",
        "--public-source-item-id",
        "source_public_fixture",
        "--chatview-source-item-id",
        "source_private_metadata_fixture",
        "--channel-count",
        "2",
        "--recent-record-count",
        "50",
        "--report-count",
        "2",
        "--api-request-count",
        "54",
        "--api-path-count",
        "/api/channels=1",
        "--api-path-count",
        "/api/messages/:id=50",
        "--private-preview-item-count",
        "12",
        "--theme-signal",
        "agent workflows",
        "--generated-at",
        "2026-06-23T00:00:00Z",
    ]
    invalid = [
        *success,
    ]
    invalid[invalid.index("https://example.com/public-handle")] = (
        "https://127.0.0.1/private"
    )
    cases = (
        (
            "help",
            [*registry, "content-ops", "walkthrough-artifact", "--help"],
            0,
        ),
        ("success-json", [*registry, "--format", "json", *success], 0),
        (
            "success-markdown",
            [*registry, "--format", "markdown", *success],
            0,
        ),
        ("private-url-json", [*registry, "--format", "json", *invalid], 1),
        (
            "private-url-markdown",
            [*registry, "--format", "markdown", *invalid],
            1,
        ),
    )
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv, expected_exit_code in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == expected_exit_code, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    success_payload = json.loads(observed["success-json"][1])
    assert list(success_payload) == [
        "ok",
        "schema_version",
        "mode",
        "generated_at",
        "operator_artifact",
        "chain_steps",
        "aggregation_projection",
        "validation",
        "packet_summary",
        "external_reads_performed",
        "external_writes_performed",
        "private_source_bodies_read",
        "private_source_content_read",
        "autopublish_allowed",
        "public_repo_safe",
        "next_safe_action",
    ]
    assert success_payload["external_reads_performed"] is False
    assert success_payload["external_writes_performed"] is False
    assert success_payload["private_source_bodies_read"] is False
    assert success_payload["private_source_content_read"] is False
    assert success_payload["autopublish_allowed"] is False
    assert success_payload["public_repo_safe"] is True
    private_preview = success_payload["operator_artifact"][
        "private_operator_preview"
    ]
    assert private_preview["stored_in_repo"] is False
    assert private_preview["source_content_recorded"] is False
    assert private_preview["response_payload_recorded"] is False

    success_serialized = observed["success-json"][1]
    assert "raw_connector_body" not in success_serialized
    assert "response_body" not in success_serialized
    assert "credential" not in success_serialized.lower()
    assert "secret" not in success_serialized.lower()
    assert observed["success-json"][1].endswith("\n")
    assert observed["success-markdown"][1].startswith(
        "# LoopX Content-Ops Walkthrough Artifact\n"
    )
    assert observed["success-markdown"][1].endswith("\n\n")

    expected_error = "public handle URL must not target private or local addresses"
    for label in ("private-url-json", "private-url-markdown"):
        assert expected_error in observed[label][1]
        assert "127.0.0.1" not in observed[label][1]
        assert "/private" not in observed[label][1]
        assert observed[label][1].endswith("\n\n" if label.endswith("markdown") else "\n")
    assert list(tmp_path.iterdir()) == []


def test_decision_context_inspect_profile_depth_closure_is_exact_and_read_only(
    monkeypatch,
    tmp_path: Path,
) -> None:
    invalid_profile = tmp_path / "invalid-profile.json"
    invalid_profile.write_text("{not-json\n", encoding="utf-8")
    profile_before = invalid_profile.read_bytes()
    _forbid_external_effects(monkeypatch, "decision-context inspect-profile")

    registry = ["--registry", str(tmp_path / "registry.json")]
    success = [
        "decision-context",
        "inspect-profile",
        "--goal-id",
        "goal_fixture",
        "--agent-id",
        "agent_fixture",
    ]
    invalid = [*success, "--profile", str(invalid_profile)]
    cases = (
        (
            "help",
            [*registry, "decision-context", "inspect-profile", "--help"],
            0,
        ),
        ("success-json", [*registry, "--format", "json", *success], 0),
        ("success-markdown", [*registry, "--format", "markdown", *success], 0),
        ("invalid-profile-json", [*registry, "--format", "json", *invalid], 0),
        (
            "invalid-profile-markdown",
            [*registry, "--format", "markdown", *invalid],
            0,
        ),
    )
    root = _local_root()
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv, expected_exit_code in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == expected_exit_code, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    success_payload = json.loads(observed["success-json"][1])
    assert success_payload["status"] == "disabled"
    assert success_payload["profile_configured"] is False
    invalid_payload = json.loads(observed["invalid-profile-json"][1])
    assert invalid_payload["status"] == "profile_invalid"
    assert invalid_payload["reason_code"] == "profile_unavailable_or_invalid"
    assert invalid_payload["profile_configured"] is True
    for field in (
        "external_writes_performed",
        "raw_content_captured",
        "private_locator_captured",
        "credentials_captured",
    ):
        assert success_payload[field] is False
        assert invalid_payload[field] is False
    assert str(invalid_profile) not in observed["invalid-profile-json"][1]
    assert observed["success-markdown"][1] == (
        "# Decision Context\n\n"
        "- status: `disabled`\n"
        "- capability_id: `decision_context`\n"
        "- packet_schemas: `0`\n"
        "- source_schemas: `0`\n"
        "- source_count: `0`\n\n"
    )
    assert observed["invalid-profile-markdown"][1] == (
        "# Decision Context\n\n"
        "- status: `profile_invalid`\n"
        "- capability_id: `decision_context`\n"
        "- packet_schemas: `0`\n"
        "- source_schemas: `0`\n"
        "- source_count: `0`\n\n"
    )
    assert invalid_profile.read_bytes() == profile_before
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "invalid-profile.json"
    ]


def test_decision_context_architecture_depth_closure_is_exact_and_io_free(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _local_root()
    _forbid_external_effects(
        monkeypatch,
        "decision-context architecture",
        allow_file_reads=False,
    )

    registry = ["--registry", str(tmp_path / "registry.json")]
    command = ["decision-context", "architecture"]
    cases = (
        ("help", [*registry, *command, "--help"]),
        ("success-json", [*registry, "--format", "json", *command]),
        ("success-markdown", [*registry, "--format", "markdown", *command]),
    )
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == 0, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    payload = json.loads(observed["success-json"][1])
    assert list(payload) == [
        "schema_version",
        "status",
        "capability",
        "packet_schemas",
        "source_schemas",
        "assembly_schemas",
        "provider_boundaries",
        "lifecycle",
        "invariants",
        "next_stage",
    ]
    assert payload["status"] == "experimental"
    assert payload["capability"]["default_enabled"] is False
    assert payload["capability"]["creates_authority"] is False
    assert payload["capability"]["mutates_core_state"] is False
    assert observed["success-markdown"][1] == (
        "# Decision Context\n\n"
        "- status: `experimental`\n"
        "- capability_id: `decision_context`\n"
        "- packet_schemas: `3`\n"
        "- source_schemas: `2`\n"
        "- source_count: `0`\n\n"
    )
    serialized = observed["success-json"][1]
    assert str(tmp_path) not in serialized
    assert not {"project", "source", "target", "credentials"} & payload.keys()
    with monkeypatch.context() as strict_metadata_guard:
        def forbidden_metadata(*_args, **_kwargs):
            raise AssertionError("static architecture contract attempted local I/O")

        strict_metadata_guard.setattr(Path, "exists", forbidden_metadata)
        strict_metadata_guard.setattr(Path, "is_file", forbidden_metadata)
        assert root.capabilities.decision_context.describe_architecture().status == (
            "experimental"
        )
    assert list(tmp_path.iterdir()) == []


def test_material_lifecycle_architecture_depth_closure_is_exact_and_io_free(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _local_root()
    _forbid_external_effects(
        monkeypatch,
        "material-lifecycle architecture",
        allow_file_reads=False,
    )

    registry = ["--registry", str(tmp_path / "registry.json")]
    command = ["material-lifecycle", "architecture"]
    cases = (
        ("help", [*registry, *command, "--help"]),
        ("success-json", [*registry, "--format", "json", *command]),
        ("success-markdown", [*registry, "--format", "markdown", *command]),
    )
    observed: dict[str, tuple[int, str, str]] = {}
    for label, argv in cases:
        legacy = _legacy_external_output(argv)
        current = _v2_external_output(argv, root)
        assert legacy[0] == 0, label
        assert current == legacy, label
        assert current[2] == "", label
        observed[label] = current

    payload = json.loads(observed["success-json"][1])
    assert list(payload) == [
        "schema_version",
        "status",
        "capability",
        "contract_schemas",
        "sibling_capabilities",
        "provider_boundaries",
        "lifecycle",
        "invariants",
        "next_stage",
    ]
    assert list(payload["capability"]) == [
        "capability_id",
        "scope",
        "default_enabled",
        "creates_authority",
        "mutates_core_state",
    ]
    assert list(payload["sibling_capabilities"]) == [
        "decision_context",
        "reward_memory",
        "content_ops",
    ]
    assert list(payload["provider_boundaries"]) == [
        "raw_material_store",
        "inventory_provider",
        "migration_adapter",
        "decision_policy",
        "exploration_provider",
        "candidate_intake_adapter",
        "ranking_settlement",
    ]
    assert payload["status"] == "experimental"
    assert payload["capability"]["default_enabled"] is False
    assert payload["capability"]["creates_authority"] is False
    assert payload["capability"]["mutates_core_state"] is False
    assert len(payload["contract_schemas"]) == 13
    assert observed["success-json"][1].endswith("\n")
    assert observed["success-markdown"][1] == (
        "# Material Lifecycle\n\n"
        "- status: `experimental`\n"
        "- capability_id: `material_lifecycle`\n"
        "- contract_schemas: `13`\n\n"
    )

    def nested_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(
                *(nested_keys(item) for item in value.values())
            )
        if isinstance(value, list):
            return set().union(*(nested_keys(item) for item in value))
        return set()

    serialized = observed["success-json"][1]
    assert str(tmp_path) not in serialized
    assert "/Users/" not in serialized
    assert not {
        "project",
        "source",
        "target",
        "path",
        "paths",
        "credentials",
    } & nested_keys(payload)
    with monkeypatch.context() as strict_metadata_guard:
        def forbidden_metadata(*_args, **_kwargs):
            raise AssertionError("static architecture contract attempted path metadata I/O")

        for attribute in ("exists", "is_file", "is_dir", "stat", "lstat"):
            strict_metadata_guard.setattr(Path, attribute, forbidden_metadata)
        assert root.capabilities.material_lifecycle.describe_architecture().status == (
            "experimental"
        )
    assert list(tmp_path.iterdir()) == []




def test_json_differential_for_safe_read_preview_and_fixture_calls(
    tmp_path: Path,
) -> None:
    root = _local_root()
    runtime_root = tmp_path / "runtime"
    state_file = tmp_path / "extensions.json"
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text("<h1>Fixture</h1>\n", encoding="utf-8")
    cases = (
        [
            "--runtime-root",
            str(runtime_root),
            "--format",
            "json",
            "capability",
            "list",
        ],
        [
            "--format",
            "json",
            "extension",
            "list",
            "--state-file",
            str(state_file),
        ],
        [
            "--format",
            "json",
            "extension",
            "init",
            "fixture-extension",
            "--destination",
            str(tmp_path / "fixture-extension"),
        ],
        [
            "--format",
            "json",
            "presentation",
            "package",
            "--site-dir",
            str(site_dir),
            "--output-dir",
            str(tmp_path / "published"),
            "--site-id",
            "fixture-site",
            "--desktop-visual-check",
            "passed",
            "--mobile-visual-check",
            "passed",
            "--link-check",
            "passed",
        ],
        ["--format", "json", "decision-context", "architecture"],
        [
            "--format",
            "json",
            "decision-context",
            "inspect-profile",
            "--goal-id",
            "goal_fixture",
            "--agent-id",
            "agent_fixture",
        ],
        [
            "--format",
            "json",
            "content-ops",
            "exploration-plan",
            "--scenario",
            "public_fixture",
        ],
        [
            "--format",
            "json",
            "content-ops",
            "walkthrough-artifact",
            "--channel-count",
            "2",
            "--recent-record-count",
            "50",
            "--report-count",
            "2",
            "--api-request-count",
            "54",
            "--api-path-count",
            "/api/channels=1",
            "--api-path-count",
            "/api/messages/:id=50",
            "--private-preview-item-count",
            "12",
            "--theme-signal",
            "agent workflows",
        ],
        [
            "--format",
            "json",
            "content-ops",
            "item-create",
            "--item-id",
            "item_fixture",
            "--item-kind",
            "post",
            "--channel",
            "x_public",
            "--content-digest",
            "sha256:" + "a" * 64,
            "--content-ref",
            "artifact:fixture",
            "--source-ref",
            "source_fixture",
            "--created-at",
            "2026-06-23T00:00:00+00:00",
        ],
        ["--format", "json", "material-lifecycle", "architecture"],
        [
            "--format",
            "json",
            "material-lifecycle",
            "skill-status",
            "--project",
            str(tmp_path),
        ],
        ["--format", "json", "reward-memory", "corpus-registry"],
        [
            "--format",
            "json",
            "reward-memory",
            "candidate-review",
            "--decision",
            "accept",
        ],
        [
            "--format",
            "json",
            "reward-memory",
            "health-check",
            "--case",
            "empty",
        ],
        [
            "--format",
            "json",
            "reward-memory",
            "route-check",
            "--case",
            "pr-3237",
        ],
        [
            "--format",
            "json",
            "semantic-preference",
            "receipt",
            "--surface",
            "pr_review.reply",
            "--application-id",
            "application:fixture",
            "--outcome",
            "applied",
            "--preference-ref",
            "preference:fixture",
            "--artifact-ref",
            "artifact:fixture",
        ],
        [
            "--format",
            "json",
            "semantic-preference",
            "maintenance-receipt",
            "--trigger",
            "explicit_feedback",
            "--outcome",
            "verified",
            "--corpus-id",
            "fixture_corpus",
            "--scope-ref",
            "project:fixture",
            "--evidence-ref",
            "evidence:fixture",
        ],
        [
            "--format",
            "json",
            "value-connectors",
            "install-check",
            "--connector",
            "github_public_channel",
        ],
    )
    for argv in cases:
        legacy = _legacy_output(argv)
        v2 = _v2_output(argv, root)
        assert v2 == legacy, argv


def test_json_differential_for_github_public_source_map_only() -> None:
    argv = [
        "--format",
        "json",
        "value-connectors",
        "source-map",
        "--connector",
        "github_public_channel",
    ]
    assert _v2_output(argv, _local_root()) == _legacy_output(argv)


def test_markdown_compatibility_view_is_still_missing(tmp_path: Path) -> None:
    argv = [
        "--runtime-root",
        str(tmp_path / "runtime"),
        "capability",
        "list",
    ]
    legacy = _legacy_output(argv)
    v2 = _v2_output(argv, _local_root())
    assert legacy[0] == v2[0] == 0
    assert legacy[1].startswith("# LoopX Capabilities")
    assert v2[1].startswith("# LoopX CLI v2")
    assert v2[1] != legacy[1]
