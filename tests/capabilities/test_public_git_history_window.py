from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from loopx.capabilities.catalog import BUILTIN_CAPABILITIES
from loopx.capabilities.public_git_history_window.effect_program import (
    PublicRepositoryAction,
    build_public_git_history_effect_request,
    evaluate_public_git_history_effect,
)
from loopx.capabilities.public_git_history_window.policy import (
    PUBLIC_GIT_HISTORY_WINDOW_POLICY_SCHEMA_VERSION,
    normalize_public_git_history_window_config,
    public_git_history_window_goal_policy,
)
from loopx.cli import main
from loopx.configure_goal import configure_goal
from loopx.control_plane.quota.goal_boundary import goal_boundary

GOAL_ID = "public-history-window-fixture"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        text=True,
        capture_output=True,
    )


def _policy(*, start: str = "09:00", end: str = "17:00") -> dict[str, object]:
    return normalize_public_git_history_window_config(
        {
            "schema_version": "public_git_history_window_config_v0",
            "timezone": "UTC",
            "blocked_windows": [
                {"window_id": "fixture-window", "start": start, "end": end}
            ],
            "public_repositories_only": True,
            "collaboration_writes_allowed": True,
        }
    )


def _request(
    *,
    action: PublicRepositoryAction | str = PublicRepositoryAction.PUSH,
    observed_at: str = "2026-01-05T12:00:00+00:00",
    visibility: str = "public",
    outgoing_commits: list[dict[str, str]] | None = None,
):
    return build_public_git_history_effect_request(
        effect_id="effect-fixture-001",
        goal_id=GOAL_ID,
        action=action,
        repository_visibility=visibility,
        repository_identity="example/project",
        observed_at=observed_at,
        outgoing_commits=outgoing_commits or [],
        outgoing_commits_verified=True,
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / ".gitignore").write_text(".loopx/config/\n", encoding="utf-8")
    config_dir = repo / ".loopx" / "config"
    config_dir.mkdir(parents=True)
    config = config_dir / "public-history-window.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": "public_git_history_window_config_v0",
                "timezone": "UTC",
                "blocked_windows": [
                    {
                        "window_id": "fixture-window",
                        "start": "09:00",
                        "end": "17:00",
                    }
                ],
                "public_repositories_only": True,
                "collaboration_writes_allowed": True,
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "goals": [
                    {
                        "id": GOAL_ID,
                        "repo": str(repo),
                        "control_plane": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return repo, registry, config


@pytest.mark.parametrize(
    ("observed_at", "disposition", "defer_until"),
    [
        ("2026-01-05T08:59:59+00:00", "allow", None),
        ("2026-01-05T09:00:00+00:00", "defer", "2026-01-05T17:00:00+00:00"),
        ("2026-01-05T16:59:59+00:00", "defer", "2026-01-05T17:00:00+00:00"),
        ("2026-01-05T17:00:00+00:00", "allow", None),
    ],
)
def test_window_start_is_inclusive_and_end_is_exclusive(
    observed_at: str,
    disposition: str,
    defer_until: str | None,
) -> None:
    decision = evaluate_public_git_history_effect(
        _request(observed_at=observed_at),
        policy=_policy(),
    )

    assert decision["disposition"] == disposition
    assert decision.get("defer_until") == defer_until


@pytest.mark.parametrize(
    ("observed_at", "disposition", "defer_until"),
    [
        ("2026-01-05T21:59:59+00:00", "allow", None),
        ("2026-01-05T22:00:00+00:00", "defer", "2026-01-06T06:00:00+00:00"),
        ("2026-01-06T05:59:59+00:00", "defer", "2026-01-06T06:00:00+00:00"),
        ("2026-01-06T06:00:00+00:00", "allow", None),
    ],
)
def test_cross_midnight_windows_have_the_correct_resume_day(
    observed_at: str,
    disposition: str,
    defer_until: str | None,
) -> None:
    decision = evaluate_public_git_history_effect(
        _request(observed_at=observed_at),
        policy=_policy(start="22:00", end="06:00"),
    )

    assert decision["disposition"] == disposition
    assert decision.get("defer_until") == defer_until


@pytest.mark.parametrize(
    "action",
    [
        PublicRepositoryAction.PR_COMMENT,
        PublicRepositoryAction.PR_REVIEW,
        PublicRepositoryAction.PR_METADATA,
        PublicRepositoryAction.REQUEST_REVIEWER,
        PublicRepositoryAction.LABEL,
    ],
)
def test_pr_collaboration_writes_remain_available_during_a_window(
    action: PublicRepositoryAction,
) -> None:
    decision = evaluate_public_git_history_effect(
        _request(action=action),
        policy=_policy(),
    )

    assert decision["disposition"] == "allow"
    assert decision["reason_code"] == "collaboration_write_outside_capability"
    assert decision["history_write"] is False


def test_pr_create_requires_a_remote_head_and_no_implicit_push() -> None:
    decision = evaluate_public_git_history_effect(
        _request(action=PublicRepositoryAction.PR_CREATE),
        policy=_policy(),
    )

    assert decision["disposition"] == "allow"
    assert decision["required_guards"] == [
        "head_already_remote",
        "no_implicit_push",
    ]


def test_private_repository_is_outside_public_only_policy_and_unknown_fails_closed() -> None:
    private = evaluate_public_git_history_effect(
        _request(visibility="private"),
        policy=_policy(),
    )
    unknown = evaluate_public_git_history_effect(
        _request(visibility="unknown"),
        policy=_policy(),
    )

    assert private["disposition"] == "allow"
    assert private["reason_code"] == "private_repository_outside_policy"
    assert unknown["disposition"] == "reject"
    assert unknown["reason_code"] == "repository_visibility_unknown"


def test_auto_merge_fails_closed_until_execution_time_can_be_rechecked() -> None:
    decision = evaluate_public_git_history_effect(
        _request(
            action=PublicRepositoryAction.AUTO_MERGE_ENABLE,
            observed_at="2026-01-05T18:00:00+00:00",
        ),
        policy=_policy(),
    )

    assert decision["disposition"] == "reject"
    assert decision["reason_code"] == "execution_time_not_rechecked"
    assert "evaluate pr_merge" in decision["required_action"]


@pytest.mark.parametrize("field", ["author_at", "committer_at"])
def test_later_push_rejects_an_outgoing_commit_created_in_the_window(field: str) -> None:
    commit = {
        "sha": "abc123",
        "author_at": "2026-01-05T08:00:00+00:00",
        "committer_at": "2026-01-05T08:00:00+00:00",
    }
    commit[field] = "2026-01-05T12:00:00+00:00"
    decision = evaluate_public_git_history_effect(
        _request(
            observed_at="2026-01-05T18:00:00+00:00",
            outgoing_commits=[commit],
        ),
        policy=_policy(),
    )

    assert decision["disposition"] == "reject"
    assert decision["reason_code"] == "outgoing_commit_timestamp_in_blocked_window"
    assert {item["field"] for item in decision["violating_commits"]} == {field}
    assert "recreate" in decision["required_action"]


def test_same_effect_and_inputs_produce_the_same_receipt_identity() -> None:
    request = _request(observed_at="2026-01-05T18:00:00+00:00")

    first = evaluate_public_git_history_effect(request, policy=_policy())
    second = evaluate_public_git_history_effect(request, policy=_policy())

    assert first["receipt"] == second["receipt"]


def test_publication_rejects_an_unverified_empty_outgoing_commit_inventory() -> None:
    request = build_public_git_history_effect_request(
        effect_id="effect-unverified-inventory",
        goal_id=GOAL_ID,
        action=PublicRepositoryAction.PUSH,
        repository_visibility="public",
        repository_identity="example/project",
        observed_at="2026-01-05T18:00:00+00:00",
    )

    decision = evaluate_public_git_history_effect(request, policy=_policy())

    assert decision["disposition"] == "reject"
    assert decision["reason_code"] == "outgoing_commit_inventory_unverified"
    assert "target remote ref" in decision["required_action"]


def test_policy_rejects_a_configuration_that_claims_to_block_collaboration() -> None:
    with pytest.raises(ValueError, match="must be true"):
        normalize_public_git_history_window_config(
            {
                "schema_version": "public_git_history_window_config_v0",
                "timezone": "UTC",
                "blocked_windows": [
                    {"window_id": "fixture", "start": "09:00", "end": "17:00"}
                ],
                "public_repositories_only": True,
                "collaboration_writes_allowed": False,
            }
        )


def test_goal_configuration_defaults_off_then_registers_only_the_private_pointer(
    tmp_path: Path,
) -> None:
    _repo, registry, _config = _fixture(tmp_path)
    stored = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    assert public_git_history_window_goal_policy(stored) == {
        "schema_version": PUBLIC_GIT_HISTORY_WINDOW_POLICY_SCHEMA_VERSION,
        "enabled": False,
        "config_path": None,
    }

    preview = configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        public_git_history_window_config=(
            ".loopx/config/public-history-window.json"
        ),
        execute=False,
    )
    assert preview["after"]["public_git_history_window"] == {
        "enabled": True,
        "config_pointer_registered": True,
    }
    assert "timezone" not in json.dumps(preview)
    assert "09:00" not in json.dumps(preview)


def test_goal_boundary_projects_guard_contract_without_private_window_values(
    tmp_path: Path,
) -> None:
    repo, registry, _config = _fixture(tmp_path)
    goal = json.loads(registry.read_text(encoding="utf-8"))["goals"][0]
    goal["control_plane"] = {
        "public_git_history_window": {
            "enabled": True,
            "config_path": ".loopx/config/public-history-window.json",
        }
    }

    boundary = goal_boundary(goal, registry_path=registry)

    assert boundary is not None
    capability = boundary["capabilities"]["public_git_history_window"]
    assert capability["enabled"] is True
    assert capability["config_pointer_registered"] is True
    assert "pr_comment" in capability["collaboration_writes_excluded"]
    assert str(repo) not in json.dumps(capability)
    assert "09:00" not in json.dumps(capability)


def test_cli_loads_the_ignored_config_and_returns_a_defer_receipt(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _repo, registry, _config = _fixture(tmp_path)
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        public_git_history_window_config=(
            ".loopx/config/public-history-window.json"
        ),
        execute=True,
    )

    code = main(
        [
            "--registry",
            str(registry),
            "--format",
            "json",
            "public-git-history-window",
            "evaluate",
            "--goal-id",
            GOAL_ID,
            "--effect-id",
            "effect-cli-001",
            "--action",
            "push",
            "--repository-visibility",
            "public",
            "--repository-identity",
            "example/project",
            "--observed-at",
            "2026-01-05T12:00:00+00:00",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 3
    assert output["disposition"] == "defer"
    assert output["receipt"]["effect_id"] == "effect-cli-001"


def test_config_loader_rejects_a_tracked_policy_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo, registry, config = _fixture(tmp_path)
    (repo / ".gitignore").write_text("", encoding="utf-8")
    _git(repo, "add", str(config.relative_to(repo)))
    configure_goal(
        registry_path=registry,
        goal_id=GOAL_ID,
        public_git_history_window_config=(
            ".loopx/config/public-history-window.json"
        ),
        execute=True,
    )

    code = main(
        [
            "--registry",
            str(registry),
            "--format",
            "json",
            "public-git-history-window",
            "evaluate",
            "--goal-id",
            GOAL_ID,
            "--effect-id",
            "effect-cli-002",
            "--action",
            "push",
            "--repository-visibility",
            "public",
            "--repository-identity",
            "example/project",
            "--observed-at",
            "2026-01-05T18:00:00+00:00",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert "ignored and untracked" in output["error"]


def test_capability_catalog_declares_effect_and_enforcement_boundaries() -> None:
    capability = next(
        item
        for item in BUILTIN_CAPABILITIES
        if item["id"] == "public_git_history_window"
    )

    assert capability["provider_id"] == "loopx-core"
    assert capability["default_enabled"] is False
    assert {item["schema_version"] for item in capability["implemented_protocols"]} == {
        "public_git_history_window_config_v0",
        "public_git_history_window_decision_v0",
        "public_git_history_window_receipt_v0",
    }
    assert any("Raw git callers" in value for value in capability["boundaries"])


def test_loopx_project_skill_requires_the_goal_boundary_guard() -> None:
    skill = Path("skills/loopx-project/SKILL.md").read_text(encoding="utf-8")

    assert "goal_boundary.capabilities.public_git_history_window.enabled=true" in skill
    assert "Never satisfy the policy by" in skill
    assert "rewriting author or committer timestamps" in skill
