from __future__ import annotations

import hashlib
import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

import pytest

from loopx.application import ApplicationContext, Profile
from loopx.application.projects import ProjectServices
from loopx.application.registry import RegistryServices
from loopx.application.system import SystemServices
from loopx.cli import main as legacy_main
from loopx.cli_v2.entrypoint import main as v2_main
from loopx.cli_v2.project_system_registry import PROJECT_SYSTEM_REGISTRY_COHORT


@dataclass(frozen=True)
class _ApplicationRoot:
    projects: ProjectServices
    system: SystemServices
    registry: RegistryServices


@dataclass(frozen=True)
class _ReadFixture:
    root: Path
    project: Path
    registry: Path
    runtime: Path
    goal_id: str


def _application_factory(args: object, registry_path: Path) -> _ApplicationRoot:
    context = ApplicationContext(
        registry_path=registry_path,
        runtime_root_override=getattr(args, "runtime_root", None),
        profile=Profile.CLI,
    )
    return _ApplicationRoot(
        projects=ProjectServices(context=context),
        system=SystemServices(context=context),
        registry=RegistryServices(context=context),
    )


def _seed_read_fixture(tmp_path: Path) -> _ReadFixture:
    project = tmp_path / "project"
    runtime = tmp_path / "runtime"
    goal_id = "read-diagnostics-fixture"
    state_file = project / ".codex" / "goals" / goal_id / "ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True)
    state_file.write_text(
        "---\nupdated_at: 2026-01-01T00:00:00+00:00\n---\n",
        encoding="utf-8",
    )

    registry = project / ".loopx" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "common_runtime_root": str(runtime),
                "goals": [
                    {
                        "id": goal_id,
                        "domain": "fixture",
                        "status": "active-read-only",
                        "repo": str(project),
                        "state_file": str(state_file.relative_to(project)),
                        "adapter": {
                            "kind": "fixture",
                            "status": "connected-read-only",
                        },
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    artifacts = project / "artifacts"
    artifacts.mkdir()
    (artifacts / "run.json").write_text('{"ok": true}\n', encoding="utf-8")
    (artifacts / "run.md").write_text("# Run\n", encoding="utf-8")

    runs = runtime / "goals" / goal_id / "runs"
    runs.mkdir(parents=True)
    duplicate = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "goal_id": goal_id,
        "classification": "state_refreshed",
        "recommended_action": "fixture-action-one",
        "health_check": "fixture-health-one",
        "json_path": "artifacts/run.json",
        "markdown_path": "artifacts/run.md",
    }
    outcome = {
        "generated_at": "2026-01-01T00:00:01+00:00",
        "goal_id": goal_id,
        "classification": "patch_validated",
        "recommended_action": "fixture-action-two",
        "health_check": "fixture-health-two",
        "delivery_outcome": "outcome_progress",
        "json_path": "artifacts/outcome.json",
        "markdown_path": "artifacts/outcome.md",
    }
    (runs / "index.jsonl").write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in (duplicate, dict(duplicate), outcome)
        ),
        encoding="utf-8",
    )
    (runs / "trajectory.json").write_text(
        "not-json-and-must-not-be-read",
        encoding="utf-8",
    )
    return _ReadFixture(
        root=tmp_path,
        project=project,
        registry=registry,
        runtime=runtime,
        goal_id=goal_id,
    )


def _snapshot(root: Path) -> dict[str, tuple[str, str | None]]:
    snapshot: dict[str, tuple[str, str | None]] = {}
    for path in sorted(root.rglob("*")):
        label = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[label] = ("symlink", str(path.readlink()))
        elif path.is_file():
            snapshot[label] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        elif path.is_dir():
            snapshot[label] = ("directory", None)
        else:
            snapshot[label] = ("other", None)
    return snapshot


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("read-only diagnostics must not launch subprocesses")

    for name in ("run", "Popen", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, fail)


def _run_legacy(argv: list[str]) -> dict[str, object]:
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = legacy_main(argv)
    assert exit_code == 0, output.getvalue()
    payload = json.loads(output.getvalue())
    assert isinstance(payload, dict)
    return payload


def _run_v2(argv: list[str], *, format_name: str = "json") -> str:
    output = io.StringIO()
    exit_code = v2_main(
        ["--format", format_name, *argv],
        application_factory=_application_factory,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=output,
    )
    assert exit_code == 0, output.getvalue()
    return output.getvalue()


def _invoke_legacy(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = legacy_main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _invoke_v2(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = v2_main(
        argv,
        application_factory=_application_factory,
        cohorts=(PROJECT_SYSTEM_REGISTRY_COHORT,),
        stdout=stdout,
        stderr=stderr,
    )
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _all_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _all_keys(item)}
    return set()


def test_project_skill_status_matches_legacy_semantics_without_paths_or_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)
    command = [
        "project-skill",
        "status",
        "--project",
        str(fixture.project),
        "--skill",
        "loopx-material",
        "--surface",
        "codex",
        "--surface",
        "claude-code",
    ]

    legacy = _run_legacy([*command, "--format", "json"])
    assert _snapshot(fixture.root) == before
    rendered = _run_v2(command)
    current = json.loads(rendered)
    assert _snapshot(fixture.root) == before

    assert {
        "skill_id": current["skill_id"],
        "source_digest": current["source_digest"],
        "project_connected": current["project_connected"],
        "status": current["status"],
        "managed": current["managed"],
        "surfaces": [
            {
                "surface": row["surface"],
                "status": row["status"],
                "managed": row["managed"],
                "installed_digest": row["installed_digest"],
                "recorded_source_digest": row["recorded_source_digest"],
            }
            for row in current["surfaces"]
        ],
    } == {
        "skill_id": legacy["skill_id"],
        "source_digest": legacy["source_digest"],
        "project_connected": legacy["project_connected"],
        "status": legacy["status"],
        "managed": legacy["managed"],
        "surfaces": [
            {
                "surface": row["surface"],
                "status": row["status"],
                "managed": row["managed"],
                "installed_digest": row["installed_digest"],
                "recorded_source_digest": row["recorded_source_digest"],
            }
            for row in legacy["surfaces"]
        ],
    }
    assert current["source_label"] == "packaged:loopx-material"
    assert [row["target_label"] for row in current["surfaces"]] == [
        ".agents/skills/loopx-material",
        ".claude/skills/loopx-material",
    ]
    assert str(tmp_path) not in rendered
    assert {"project", "source", "target"}.isdisjoint(_all_keys(current))


@pytest.mark.parametrize("action", ("install", "uninstall"))
def test_project_skill_preview_matches_legacy_exact_cli_without_writes(
    action: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)
    command = [
        "--format",
        "json",
        "project-skill",
        action,
        "--project",
        str(fixture.project),
        "--skill",
        "loopx-material",
        "--surface",
        "codex",
        "--surface",
        "claude-code",
    ]

    legacy = _invoke_legacy(command)
    assert _snapshot(fixture.root) == before
    current = _invoke_v2(command)
    assert _snapshot(fixture.root) == before

    assert current == legacy
    assert current[0] == 0
    assert current[2] == ""
    payload = json.loads(current[1])
    assert payload["mode"] == "preview"
    assert payload["operation"] == (
        "install_or_upgrade" if action == "install" else "uninstall"
    )


def test_project_skill_install_preview_error_matches_legacy_exact_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disconnected = tmp_path / "disconnected-project"
    disconnected.mkdir()
    before = _snapshot(tmp_path)
    _forbid_subprocess(monkeypatch)
    command = [
        "--format",
        "json",
        "project-skill",
        "install",
        "--project",
        str(disconnected),
        "--skill",
        "loopx-material",
    ]

    legacy = _invoke_legacy(command)
    assert _snapshot(tmp_path) == before
    current = _invoke_v2(command)
    assert _snapshot(tmp_path) == before

    assert current == legacy
    assert current[0] == 2
    assert current[2] == ""
    assert json.loads(current[1])["status"] == "blocked"


@pytest.mark.parametrize("action", ("install", "uninstall"))
def test_project_skill_execute_remains_fail_closed_without_provider_writes(
    action: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)

    exit_code, stdout, stderr = _invoke_v2(
        [
            "--format",
            "json",
            "project-skill",
            action,
            "--project",
            str(fixture.project),
            "--skill",
            "loopx-material",
            "--execute",
        ]
    )

    assert exit_code == 2
    assert stderr == ""
    assert json.loads(stdout)["error"]["code"] == "cli_v2_pending_migration"
    assert _snapshot(fixture.root) == before


def test_index_duplicate_inspection_matches_legacy_counts_without_raw_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)
    command = [
        "--registry",
        str(fixture.registry),
        "--runtime-root",
        str(fixture.runtime),
        "history",
        "inspect-index-duplicates",
        "--goal-id",
        fixture.goal_id,
        "--limit",
        "10",
    ]

    legacy = _run_legacy(["--format", "json", *command])
    assert _snapshot(fixture.root) == before
    rendered = _run_v2(command)
    current = json.loads(rendered)
    assert _snapshot(fixture.root) == before

    legacy_groups = [
        {
            "goal_id": row["goal_id"],
            "duplicate_kind": row["duplicate_kind"],
            "severity": row["severity"],
            "raw_row_count": row["raw_rows"],
            "duplicate_row_count": row["duplicate_rows"],
            "line_count": len(row["line_numbers"]),
            "reward_overlay_row_count": row["reward_overlay_rows"],
            "classification_count": len(row["classifications"]),
            "json_artifact_available": row["json_exists"],
            "markdown_artifact_available": row["markdown_exists"],
        }
        for row in legacy["groups"]
    ]
    assert current["checked_goal_count"] == legacy["checked_goal_count"]
    assert current["raw_index_record_count"] == legacy["raw_index_records"]
    assert current["duplicate_group_count"] == legacy["duplicate_group_count"]
    assert current["duplicate_row_count"] == legacy["duplicate_row_count"]
    assert current["groups"] == legacy_groups
    assert current["truncated"] == legacy["truncated"]
    assert str(tmp_path) not in rendered
    assert "fixture-action-one" not in rendered
    assert "fixture-health-one" not in rendered
    forbidden = {
        "registry",
        "runtime_root",
        "index_path",
        "json_path",
        "markdown_path",
        "generated_at",
        "classifications",
        "health_checks",
        "repair_hint",
        "recommended_action",
    }
    assert forbidden.isdisjoint(_all_keys(current))


def test_trajectory_hygiene_matches_legacy_aggregates_and_ignores_raw_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)
    command = [
        "--registry",
        str(fixture.registry),
        "--runtime-root",
        str(fixture.runtime),
        "history",
        "trajectory-hygiene",
        "--goal-id",
        fixture.goal_id,
        "--limit",
        "10",
    ]

    legacy = _run_legacy(["--format", "json", *command])
    assert _snapshot(fixture.root) == before
    rendered = _run_v2(command)
    current = json.loads(rendered)
    assert _snapshot(fixture.root) == before

    assert current["goal_filter"] == legacy["goal_filter"]
    assert current["sample"] == legacy["sample"]
    assert current["channel_counts"] == legacy["channel_counts"]
    assert current["metrics"] == legacy["metrics"]
    assert current["training_boundary"] == {
        key: legacy["training_boundary"][key]
        for key in (
            "raw_session_read",
            "raw_trajectory_read",
            "run_artifact_read",
            "compact_index_only",
            "seed_model_training_eligible",
        )
    }
    assert current["training_boundary"]["raw_trajectory_read"] is False
    assert str(tmp_path) not in rendered
    assert "fixture-action-one" not in rendered
    assert "fixture-action-two" not in rendered
    forbidden = {
        "registry",
        "runtime_root",
        "classification_counts",
        "recommended_action",
        "reason",
        "json_path",
        "markdown_path",
        "index_path",
    }
    assert forbidden.isdisjoint(_all_keys(current))


@pytest.mark.parametrize(
    ("command", "heading"),
    (
        (
            [
                "project-skill",
                "status",
                "--project",
                "{project}",
                "--skill",
                "loopx-material",
            ],
            "# LoopX Project Skill",
        ),
        (
            [
                "--registry",
                "{registry}",
                "--runtime-root",
                "{runtime}",
                "history",
                "inspect-index-duplicates",
                "--goal-id",
                "{goal_id}",
            ],
            "# LoopX History Index Duplicate Inspection",
        ),
        (
            [
                "--registry",
                "{registry}",
                "--runtime-root",
                "{runtime}",
                "history",
                "trajectory-hygiene",
                "--goal-id",
                "{goal_id}",
            ],
            "# LoopX Trajectory Hygiene",
        ),
    ),
)
def test_read_diagnostic_markdown_uses_only_typed_projection(
    command: list[str],
    heading: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _seed_read_fixture(tmp_path)
    before = _snapshot(fixture.root)
    _forbid_subprocess(monkeypatch)
    values = {
        "project": str(fixture.project),
        "registry": str(fixture.registry),
        "runtime": str(fixture.runtime),
        "goal_id": fixture.goal_id,
    }

    rendered = _run_v2(
        [part.format_map(values) for part in command],
        format_name="markdown",
    )

    assert rendered.startswith(heading)
    assert str(tmp_path) not in rendered
    assert _snapshot(fixture.root) == before
