from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from loopx.application import ApplicationContext, Profile, StateUnavailable
from loopx.application.registry import (
    RegistryBoundaryRequest,
    RegistryInspectionService,
)
from loopx.application.registry.root import RegistryProviders, RegistryServices


class _RegistryProvider:
    def __init__(self) -> None:
        self.malformed_goal_count = False
        self.tracked = False
        self.ignored = True

    def inspect(self, path: Path) -> Mapping[str, object]:
        return {
            "ok": True,
            "schema_version": "0.1",
            "goal_count": "bad" if self.malformed_goal_count else 1,
            "status_counts": {"active": 1},
            "problem_diagnostics": [],
            "goals": [
                {
                    "id": "goal-one",
                    "domain": "fixture",
                    "status": "active",
                    "repo_exists": True,
                    "state_file_exists": True,
                    "adapter_kind": "read_only",
                    "adapter_status": "ready",
                    "authority_source_count": 0,
                }
            ],
        }

    def inspect_boundary(self, path: Path) -> Mapping[str, object]:
        return {
            "ok": True,
            "exists": True,
            "path_label": path.name,
            "classification": "project_local_private_registry",
            "boundary_kind": "project_local_private_registry",
            "goal_count": 1,
            "authority_source_count": 0,
            "private_marker_count": 0,
            "git": {
                "available": True,
                "inside_worktree": True,
                "tracked": self.tracked,
                "ignored": self.ignored,
            },
            "should_be_gitignored": True,
            "github_push_allowed": False,
            "risks": [],
        }


def test_registry_inspection_projects_only_typed_public_safe_fields(
    tmp_path: Path,
) -> None:
    service = RegistryInspectionService(
        registry_path=tmp_path / "registry.json",
        profile=Profile.HTTP_READ_ONLY,
        provider=_RegistryProvider(),
    )
    result = service.inspect()

    assert result.goal_count == 1
    assert result.goals[0].goal_id == "goal-one"
    assert not hasattr(result, "details")
    assert all(not hasattr(goal, "repo") for goal in result.goals)


def test_registry_inspection_malformed_count_fails_closed(tmp_path: Path) -> None:
    provider = _RegistryProvider()
    provider.malformed_goal_count = True
    service = RegistryInspectionService(
        registry_path=tmp_path / "registry.json",
        profile=Profile.CLI,
        provider=provider,
    )

    with pytest.raises(StateUnavailable) as error:
        service.inspect()
    assert error.value.details["cause"] == "invalid_payload"
    assert error.value.details["field"] == "goal_count"


def test_registry_boundary_policy_is_applied_to_typed_projection(
    tmp_path: Path,
) -> None:
    provider = _RegistryProvider()
    provider.tracked = True
    provider.ignored = False
    service = RegistryInspectionService(
        registry_path=tmp_path / "registry.json",
        profile=Profile.CLI,
        provider=provider,
    )

    result = service.inspect_boundary(
        RegistryBoundaryRequest(require_not_tracked=True)
    )
    assert result.ok is False
    assert "registry_tracked_but_not_push_allowed" in result.risks
    assert not hasattr(result, "details")


def test_registry_root_accessor_preserves_injected_provider(tmp_path: Path) -> None:
    provider = _RegistryProvider()
    services = RegistryServices(
        context=ApplicationContext(
            registry_path=tmp_path / "registry.json",
            profile=Profile.CLI,
        ),
        providers=RegistryProviders(inspection=provider),
    )
    assert services.inspection.provider is provider
