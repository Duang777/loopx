"""Use the installed CLI transport and real local stores through cutover and recovery."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from tests.control_plane.test_local_authority_shadow_cli_e2e import (
    _workspace,
    _cli,
    _command,
    _env,
    REPO_ROOT,
)


def command_result(registry, root, *args):
    process = subprocess.run(
        _command(registry, root, *args),
        cwd=REPO_ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return process.returncode, json.loads(process.stdout)


def prepare(tmp_path: Path, provider: str):
    registry, state, root = _workspace(tmp_path, goal_id="goal-a")
    if provider == "sqlite":
        subprocess.run(
            [
                os.environ.get("LOOPX_CONTROL_PLANE_NODE", "node"),
                "--no-warnings",
                "--experimental-strip-types",
                "--experimental-sqlite",
                "loopx/control_plane/coordination/local_authority_provider.ts",
                "--runtime-root",
                str(root),
                "--goal-id",
                "goal-a",
                "--execute",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    _cli(
        registry,
        root,
        "configure-goal",
        "--goal-id",
        "goal-a",
        "--coordination-runtime-shadow-file",
        "--execute",
    )
    bootstrap = _cli(
        registry,
        root,
        "coordination-shadow",
        "bootstrap",
        "--goal-id",
        "goal-a",
        "--execute",
    )
    assert bootstrap["bootstrap"]["status"] == "applied"
    for index in range(3):
        _cli(
            registry,
            root,
            "todo",
            "add",
            "--goal-id",
            "goal-a",
            "--role",
            "agent",
            "--text",
            f"Preserve migration record {index}",
        )
    preview = _cli(
        registry, root, "coordination-shadow", "promote", "--goal-id", "goal-a"
    )
    assert preview["promotion"]["status"] == "preview_ready", preview
    saved = tmp_path / "reviewed.json"
    saved.write_text(json.dumps(preview), encoding="utf-8")
    return registry, state, root, saved, preview


@pytest.mark.parametrize("provider", ["file", "sqlite"])
def test_saved_plan_cutover_and_recovery_after_canonical_write_and_missing_legacy(
    tmp_path, provider
):
    registry, state, root, saved, preview = prepare(tmp_path, provider)
    args = (
        "coordination-shadow",
        "promote",
        "--goal-id",
        "goal-a",
        "--reviewed-plan",
        str(saved),
    )
    dry_run = _cli(registry, root, *args)
    assert dry_run["promotion"]["status"] == "preview_ready"
    assert dry_run["executed"] is False
    applied = _cli(registry, root, *args, "--execute")
    assert applied["promotion"]["status"] == "applied", applied
    assert applied["promotion"]["canonical_authority"] == f"{provider}_v0"
    assert (
        applied["promotion"]["promotion_plan_sha256"]
        == preview["promotion"]["plan"]["promotion_plan_sha256"]
    )
    _cli(
        registry,
        root,
        "todo",
        "add",
        "--goal-id",
        "goal-a",
        "--role",
        "agent",
        "--text",
        "Continue after provider cutover",
    )
    state.unlink()
    # Recovery belongs to the durable cutover, not the transient shadow opt-in.
    config = json.loads(registry.read_text())
    config["goals"][0]["coordination"].pop("runtime_shadow", None)
    registry.write_text(json.dumps(config))
    for execution in [(), ("--execute",)]:
        replay = _cli(
            registry,
            root,
            "coordination-shadow",
            "recover-promotion",
            "--goal-id",
            "goal-a",
            "--reviewed-plan",
            str(saved),
            *execution,
        )
        assert replay["promotion"]["status"] == "replayed", replay
        assert replay["promotion"]["cursor"] == "1"
        assert (
            replay["promotion"]["provider_revision"]
            == applied["promotion"]["provider_revision"]
        )
        assert replay["executed"] is False
        assert not state.exists()


def test_saved_plan_source_drift_does_not_freeze_legacy_writes(tmp_path):
    registry, _state, root, saved, _preview = prepare(tmp_path, "file")
    _cli(
        registry,
        root,
        "todo",
        "add",
        "--goal-id",
        "goal-a",
        "--role",
        "agent",
        "--text",
        "New work before cutover",
    )
    code, result = command_result(
        registry,
        root,
        "coordination-shadow",
        "promote",
        "--goal-id",
        "goal-a",
        "--reviewed-plan",
        str(saved),
        "--execute",
    )
    assert code == 1
    assert result["promotion"]["reason_code"] == "local_authority_reviewed_plan_changed"
    assert result["promotion"]["legacy_writer_fenced"] is False
    _cli(
        registry,
        root,
        "todo",
        "add",
        "--goal-id",
        "goal-a",
        "--role",
        "agent",
        "--text",
        "Legacy writer remains usable",
    )


def test_saved_plan_rejects_policy_override_and_recovery_without_fence(tmp_path):
    registry, _state, root, saved, _preview = prepare(tmp_path, "file")
    code, result = command_result(
        registry,
        root,
        "coordination-shadow",
        "promote",
        "--goal-id",
        "goal-a",
        "--reviewed-plan",
        str(saved),
        "--minimum-operations",
        "1",
        "--execute",
    )
    assert code == 1 and "owns qualification policy" in result["error"]
    code, result = command_result(
        registry,
        root,
        "coordination-shadow",
        "recover-promotion",
        "--goal-id",
        "goal-a",
        "--reviewed-plan",
        str(saved),
        "--execute",
    )
    assert code == 1
    assert (
        result["promotion"]["reason_code"]
        == "local_authority_writer_fence_not_verified"
    )
