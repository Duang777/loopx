from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from loopx.application import (
    ApplicationContext,
    AuthorityDenied,
    Profile,
    StateUnavailable,
    ValidationFailed,
)
from loopx.application.projects import (
    ProjectSkillPreviewResult,
    ProjectProviders,
    ProjectServices,
    ProjectSkillStatusRequest,
    ProjectSkillStatusService,
)
from loopx.application.system import (
    HistoryDiagnosticsService,
    IndexDuplicateInspectionRequest,
    SystemProviders,
    SystemServices,
    TrajectoryHygieneRequest,
)


class _ProjectSkillProvider:
    def __init__(self, *, malformed: bool = False) -> None:
        self.calls = 0
        self.malformed = malformed

    def inspect(self, request: ProjectSkillStatusRequest) -> Mapping[str, object]:
        self.calls += 1
        digest = "a" * 64
        return {
            "skill_id": request.skill_id,
            "project": str(request.project.resolve()),
            "source": str(request.project.resolve().parent / "packaged-skill"),
            "source_digest": digest,
            "project_connected": True,
            "status": "current",
            "managed": True,
            "surfaces": [
                {
                    "surface": "codex",
                    "target": str(request.project / ".agents/skills/loopx-material"),
                    "status": "current",
                    "managed": "yes" if self.malformed else True,
                    "installed_digest": digest,
                    "recorded_source_digest": digest,
                }
            ],
        }


class _ProjectSkillPreviewProvider:
    def __init__(self, *, malformed_mode: bool = False) -> None:
        self.calls: list[str] = []
        self.malformed_mode = malformed_mode

    def preview_install(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]:
        self.calls.append("install")
        return self._payload(request, action="install_or_upgrade", changed=True)

    def preview_uninstall(
        self,
        request: ProjectSkillStatusRequest,
    ) -> Mapping[str, object]:
        self.calls.append("uninstall")
        return self._payload(request, action="uninstall", changed=False)

    def _payload(
        self,
        request: ProjectSkillStatusRequest,
        *,
        action: str,
        changed: bool,
    ) -> Mapping[str, object]:
        project = request.project.resolve()
        digest = "b" * 64
        return {
            "schema_version": "loopx_project_skill_status_v0",
            "skill_id": request.skill_id,
            "delivery": "project_managed_copy",
            "project": str(project),
            "project_connected": True,
            "source": str(project.parent / "packaged-skill"),
            "source_digest": digest,
            "status": "missing",
            "surfaces": [
                {
                    "surface": "codex",
                    "target": str(project / ".agents" / "skills" / request.skill_id),
                    "status": "missing",
                    "managed": False,
                    "installed_digest": None,
                    "recorded_source_digest": None,
                }
            ],
            "managed": False,
            "operation": action,
            "mode": "execute" if self.malformed_mode else "preview",
            "changed": changed,
            "changed_surfaces": ["codex"] if changed else [],
        }


class _HistoryProvider:
    def __init__(
        self,
        *,
        malformed_duplicates: bool = False,
        malformed_trajectory: bool = False,
        unsafe_duplicate_goal: bool = False,
        unknown_trajectory_channel: bool = False,
    ) -> None:
        self.malformed_duplicates = malformed_duplicates
        self.malformed_trajectory = malformed_trajectory
        self.unsafe_duplicate_goal = unsafe_duplicate_goal
        self.unknown_trajectory_channel = unknown_trajectory_channel

    def inspect_index_duplicates(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: IndexDuplicateInspectionRequest,
    ) -> Mapping[str, object]:
        del runtime_root_override
        return {
            "ok": True,
            "registry": str(registry_path),
            "runtime_root": str(registry_path.parent / "runtime"),
            "goal_filter": request.goal_id,
            "checked_goal_count": 1,
            "raw_index_records": "broken" if self.malformed_duplicates else 2,
            "duplicate_group_count": 1,
            "duplicate_row_count": 1,
            "groups": [
                {
                    "goal_id": (
                        "../outside" if self.unsafe_duplicate_goal else "goal-one"
                    ),
                    "index_path": str(registry_path.parent / "index.jsonl"),
                    "generated_at": "2026-01-01T00:00:00Z",
                    "json_path": str(registry_path.parent / "private.json"),
                    "markdown_path": str(registry_path.parent / "private.md"),
                    "json_exists": True,
                    "markdown_exists": False,
                    "line_numbers": [1, 2],
                    "raw_rows": 2,
                    "duplicate_rows": 1,
                    "duplicate_kind": "plain_duplicate",
                    "severity": "warning",
                    "classifications": ["private-fixture-classification"],
                    "health_checks": ["private fixture health"],
                    "reward_overlay_rows": 0,
                    "repair_hint": "private fixture hint",
                }
            ],
            "truncated": False,
            "limit": request.limit,
        }

    def trajectory_hygiene(
        self,
        *,
        registry_path: Path,
        runtime_root_override: str | None,
        request: TrajectoryHygieneRequest,
    ) -> Mapping[str, object]:
        del registry_path, runtime_root_override
        return {
            "ok": True,
            "goal_filter": request.goal_id,
            "sample": {
                "compact_history_row_count": 2,
                "goal_count": 1,
                "source": "public_safe_compact_run_index",
            },
            "channel_counts": (
                {"private-channel": 2}
                if self.unknown_trajectory_channel
                else {"controller": 1, "outcome": 1}
            ),
            "classification_counts": {"private-fixture-classification": 2},
            "metrics": {
                "controller_event_ratio": (2.0 if self.malformed_trajectory else 0.5),
                "compact_controller_char_ratio": 0.5,
                "non_material_event_ratio": 0.5,
                "learning_candidate_count": 1,
                "learning_action_coverage": 1.0,
                "learning_outcome_coverage": 1.0,
                "decision_anchor_coverage": 1.0,
                "duplicate_learning_action_ratio": 0.0,
            },
            "training_boundary": {
                "raw_session_read": False,
                "raw_trajectory_read": False,
                "run_artifact_read": False,
                "compact_index_only": True,
                "seed_model_training_eligible": False,
                "reason": "private fixture reason omitted",
            },
        }


def test_project_skill_status_is_cli_only_and_projects_semantic_labels(
    tmp_path: Path,
) -> None:
    provider = _ProjectSkillProvider()
    service = ProjectSkillStatusService(profile=Profile.CLI, provider=provider)
    result = service.inspect(
        ProjectSkillStatusRequest(
            project=tmp_path / "project",
            skill_id="loopx-material",
        )
    )

    assert result.source_label == "packaged:loopx-material"
    assert result.surfaces[0].target_label == ".agents/skills/loopx-material"
    assert result.surfaces[0].installed_matches_source is True
    assert not hasattr(result, "project")
    assert not hasattr(result.surfaces[0], "target")

    denied = ProjectSkillStatusService(
        profile=Profile.HTTP_LOCAL_OPERATOR,
        provider=provider,
    )
    with pytest.raises(AuthorityDenied):
        denied.inspect(
            ProjectSkillStatusRequest(
                project=tmp_path / "project",
                skill_id="loopx-material",
            )
        )
    assert provider.calls == 1


def test_project_skill_malformed_provider_boolean_fails_closed(
    tmp_path: Path,
) -> None:
    service = ProjectSkillStatusService(
        profile=Profile.CLI,
        provider=_ProjectSkillProvider(malformed=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.inspect(
            ProjectSkillStatusRequest(
                project=tmp_path / "project",
                skill_id="loopx-material",
            )
        )
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "surfaces.managed"


def test_project_skill_request_rejects_noncanonical_skill_id(tmp_path: Path) -> None:
    with pytest.raises(ValidationFailed):
        ProjectSkillStatusRequest(
            project=tmp_path / "project",
            skill_id="../outside",
        )


def test_project_skill_preview_is_typed_cli_only_and_never_requests_execute(
    tmp_path: Path,
) -> None:
    provider = _ProjectSkillPreviewProvider()
    service = ProjectSkillStatusService(
        profile=Profile.CLI,
        preview_provider=provider,
    )
    request = ProjectSkillStatusRequest(
        project=tmp_path / "project",
        skill_id="loopx-material",
    )

    install = service.preview_install(request)
    uninstall = service.preview_uninstall(request)

    assert isinstance(install, ProjectSkillPreviewResult)
    assert install.action == "install_or_upgrade"
    assert install.mode == "preview"
    assert install.changed_surfaces == ("codex",)
    assert uninstall.action == "uninstall"
    assert uninstall.mode == "preview"
    assert uninstall.changed_surfaces == ()
    assert provider.calls == ["install", "uninstall"]

    for profile in (Profile.HTTP_READ_ONLY, Profile.HTTP_LOCAL_OPERATOR):
        denied = ProjectSkillStatusService(
            profile=profile,
            preview_provider=provider,
        )
        with pytest.raises(AuthorityDenied):
            denied.preview_install(request)
        with pytest.raises(AuthorityDenied):
            denied.preview_uninstall(request)
    assert provider.calls == ["install", "uninstall"]


def test_project_skill_preview_provider_execute_mode_fails_closed(
    tmp_path: Path,
) -> None:
    service = ProjectSkillStatusService(
        profile=Profile.CLI,
        preview_provider=_ProjectSkillPreviewProvider(malformed_mode=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.preview_install(
            ProjectSkillStatusRequest(
                project=tmp_path / "project",
                skill_id="loopx-material",
            )
        )
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "mode"


def test_history_duplicate_projection_omits_paths_and_raw_text(tmp_path: Path) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=str(tmp_path / "runtime"),
        profile=Profile.HTTP_READ_ONLY,
        provider=_HistoryProvider(),
    )
    result = service.inspect_index_duplicates(
        IndexDuplicateInspectionRequest(goal_id="goal-one", limit=10)
    )

    assert result.duplicate_group_count == 1
    assert result.groups[0].classification_count == 1
    assert result.groups[0].json_artifact_available is True
    assert not hasattr(result.groups[0], "index_path")
    assert not hasattr(result.groups[0], "classifications")
    assert not hasattr(result.groups[0], "health_checks")


def test_history_duplicate_malformed_provider_count_fails_closed(
    tmp_path: Path,
) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_HistoryProvider(malformed_duplicates=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.inspect_index_duplicates(IndexDuplicateInspectionRequest())
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "raw_index_records"


def test_history_duplicate_provider_goal_id_is_bounded(tmp_path: Path) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_HistoryProvider(unsafe_duplicate_goal=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.inspect_index_duplicates(IndexDuplicateInspectionRequest())
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "groups.goal_id"


@pytest.mark.parametrize(
    "request_factory",
    (
        IndexDuplicateInspectionRequest,
        TrajectoryHygieneRequest,
    ),
)
def test_history_request_goal_id_type_fails_with_application_error(
    request_factory,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        request_factory(
            goal_id=(
                None
                if request_factory is TrajectoryHygieneRequest
                else object()
            )
        )

    assert error.value.details == {"field": "goal_id"}


def test_trajectory_projection_is_aggregate_only(tmp_path: Path) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_HistoryProvider(),
    )
    result = service.trajectory_hygiene(
        TrajectoryHygieneRequest(goal_id="goal-one", limit=10)
    )

    assert result.compact_history_row_count == 2
    assert result.training_boundary.raw_trajectory_read is False
    assert result.metrics.controller_event_ratio == 0.5
    assert not hasattr(result, "classification_counts")
    assert not hasattr(result, "recommended_action")
    assert not hasattr(result.training_boundary, "reason")


def test_trajectory_malformed_provider_ratio_fails_closed(tmp_path: Path) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_HistoryProvider(malformed_trajectory=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.trajectory_hygiene(TrajectoryHygieneRequest(goal_id="goal-one"))
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "metrics.controller_event_ratio"


def test_trajectory_provider_channel_is_a_fixed_public_enum(tmp_path: Path) -> None:
    service = HistoryDiagnosticsService(
        registry_path=tmp_path / "registry.json",
        runtime_root_override=None,
        profile=Profile.CLI,
        provider=_HistoryProvider(unknown_trajectory_channel=True),
    )
    with pytest.raises(StateUnavailable) as error:
        service.trajectory_hygiene(TrajectoryHygieneRequest(goal_id="goal-one"))
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "channel_counts.channel"


def test_project_and_system_accessors_preserve_injected_providers(
    tmp_path: Path,
) -> None:
    context = ApplicationContext(
        registry_path=tmp_path / "registry.json",
        profile=Profile.CLI,
    )
    skill_provider = _ProjectSkillProvider()
    history_provider = _HistoryProvider()
    projects = ProjectServices(
        context=context,
        providers=ProjectProviders(skill_status=skill_provider),
    )
    system = SystemServices(
        context=context,
        providers=SystemProviders(history_diagnostics=history_provider),
    )
    assert projects.skills.provider is skill_provider
    assert system.history_diagnostics.provider is history_provider
