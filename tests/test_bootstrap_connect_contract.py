from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

from loopx.cli import build_parser, main as cli_main
from loopx.cli_commands import bootstrap_connect


BOOTSTRAP_RESULT_SCHEMA_VERSION = "loopx_bootstrap_result_v0"


def _run_cli(argv: list[str]) -> tuple[int, dict[str, Any]]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli_main(argv)
    payload = json.loads(output.getvalue())
    assert isinstance(payload, dict)
    return exit_code, payload


def _base_argv(project: Path, runtime_root: Path, command: str) -> list[str]:
    return [
        "--format",
        "json",
        "--runtime-root",
        str(runtime_root),
        "--registry",
        str(project / ".loopx" / "registry.json"),
        command,
        "--project",
        str(project),
        "--adapter-kind",
        "read_only_project_map_v0",
        "--adapter-status",
        "connected-read-only",
        "--no-onboarding-scan",
        "--codex-app-heartbeat",
        "ask",
    ]


def test_bootstrap_and_connect_results_are_versioned_for_reuse_and_fork(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    runtime_root = tmp_path / "runtime"
    current_goal = "current-project-goal"
    forked_goal = "independent-goal"

    first_exit, first = _run_cli(
        [
            *_base_argv(project, runtime_root, "bootstrap"),
            "--goal-id",
            current_goal,
            "--objective",
            "Keep the current project goal.",
        ]
    )
    reuse_exit, reuse = _run_cli(
        [
            *_base_argv(project, runtime_root, "connect"),
            "--goal-id",
            current_goal,
            "--objective",
            "This objective must not replace reused state.",
        ]
    )
    fork_exit, fork = _run_cli(
        [
            *_base_argv(project, runtime_root, "connect"),
            "--fork-goal",
            forked_goal,
            "--objective",
            "Start an independent goal.",
        ]
    )

    assert (first_exit, reuse_exit, fork_exit) == (0, 0, 0)
    assert first["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert reuse["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert fork["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert first["registry_goal_action"] == "appended"
    assert first["state_action"] == "created"
    assert reuse["goal_id"] == current_goal
    assert reuse["registry_goal_action"] == "kept-existing"
    assert reuse["state_action"] == "kept-existing"
    assert reuse["global_sync"]["ok"] is True
    assert fork["goal_id"] == forked_goal
    assert fork["registry_goal_action"] == "appended"
    assert fork["state_action"] == "created"
    assert fork["global_sync"]["ok"] is True

    registry = json.loads(
        (project / ".loopx" / "registry.json").read_text(encoding="utf-8")
    )
    assert [goal["id"] for goal in registry["goals"]] == [
        current_goal,
        forked_goal,
    ]
    current_state = project / ".codex" / "goals" / current_goal / "ACTIVE_GOAL_STATE.md"
    assert "Keep the current project goal." in current_state.read_text(encoding="utf-8")
    assert "This objective must not replace reused state." not in current_state.read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("command", ["bootstrap", "connect"])
def test_bootstrap_validation_failure_has_version_and_typed_category(
    tmp_path: Path,
    command: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exit_code, payload = _run_cli(
        [
            *_base_argv(project, tmp_path / "runtime", command),
            "--goal-id",
            "requested-goal",
            "--fork-goal",
            "different-goal",
        ]
    )

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert payload["error_kind"] == "invalid_bootstrap_request"
    assert payload["error"] == (
        "--fork-goal cannot be combined with a different --goal-id"
    )


def test_bootstrap_internal_value_error_is_not_request_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def raise_internal_value_error(**_kwargs: object) -> dict[str, object]:
        raise ValueError("malformed project registry record")

    monkeypatch.setattr(
        bootstrap_connect,
        "bootstrap_project",
        raise_internal_value_error,
    )
    args = build_parser().parse_args(
        [
            "--format",
            "json",
            "connect",
            "--project",
            str(tmp_path),
            "--goal-id",
            "requested-goal",
        ]
    )
    captured: dict[str, object] = {}

    exit_code = bootstrap_connect.handle_bootstrap_connect_command(
        args,
        registry_path=tmp_path / ".loopx" / "registry.json",
        print_payload=lambda payload, *_args: captured.update(payload),
    )

    assert exit_code == 1
    assert captured["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert captured["error_kind"] == "bootstrap_connect_failed"
    assert captured["error"] == "malformed project registry record"


@pytest.mark.parametrize(
    ("failure_payload", "expected_error_kind"),
    [
        (
            {
                "ok": False,
                "error_kind": "project_connection_failed",
                "global_sync": {"error_kind": "must-not-override-top-level"},
            },
            "project_connection_failed",
        ),
        (
            {
                "ok": False,
                "global_sync": {"error_kind": "global_registry_write_denied"},
            },
            "global_registry_write_denied",
        ),
        ({"ok": False}, "bootstrap_connect_failed"),
    ],
)
def test_bootstrap_runtime_failure_has_stable_typed_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_payload: dict[str, object],
    expected_error_kind: str,
) -> None:
    def return_bootstrap_failure(**_kwargs: object) -> dict[str, object]:
        return {
            "goal_id": "requested-goal",
            "error": "global registry is not writable",
            **failure_payload,
        }

    monkeypatch.setattr(
        bootstrap_connect,
        "bootstrap_project",
        return_bootstrap_failure,
    )
    args = build_parser().parse_args(
        [
            "--format",
            "json",
            "bootstrap",
            "--project",
            str(tmp_path),
            "--goal-id",
            "requested-goal",
        ]
    )
    captured: dict[str, object] = {}

    exit_code = bootstrap_connect.handle_bootstrap_connect_command(
        args,
        registry_path=tmp_path / ".loopx" / "registry.json",
        print_payload=lambda payload, *_args: captured.update(payload),
    )

    assert exit_code == 1
    assert captured["schema_version"] == BOOTSTRAP_RESULT_SCHEMA_VERSION
    assert captured["error_kind"] == expected_error_kind
