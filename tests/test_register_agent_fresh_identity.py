from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from loopx.cli_commands import registry_admin
from loopx.cli import main

GOAL_ID = "fresh-agent-race-fixture"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _goal(project: Path, source_registry: Path, agents: list[str]) -> dict[str, object]:
    return {
        "id": GOAL_ID,
        "domain": "fresh-agent-race",
        "status": "active",
        "repo": str(project),
        "state_file": f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md",
        "adapter": {"kind": "fixture", "status": "connected-read-only"},
        "coordination": {
            "write_scope": [],
            "claim_ttl_minutes": 30,
            "requires_parent_approval": ["write", "publish", "production-action"],
            "registered_agents": agents,
            "agent_model": "peer_v1",
        },
        "source_registry": str(source_registry),
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    runtime_root = tmp_path / "runtime"
    project = tmp_path / "project"
    source_registry = project / ".loopx" / "registry.json"
    state_file = project / f".codex/goals/{GOAL_ID}/ACTIVE_GOAL_STATE.md"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("# Active Goal State\n\n## Agent Todo\n\n", encoding="utf-8")
    project_payload = {
        "schema_version": "0.1",
        "common_runtime_root": str(runtime_root),
        "goals": [_goal(project, source_registry, ["codex-existing"])],
    }
    _write_json(source_registry, project_payload)
    global_registry = runtime_root / "registry.global.json"
    _write_json(
        global_registry,
        {
            **project_payload,
            "registry_role": "global-local",
        },
    )
    return runtime_root, source_registry, global_registry


def test_require_new_registration_is_atomic_under_concurrency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    barrier = threading.Barrier(2)

    def coordinated_probe(path: Path, *, create_parent: bool) -> dict[str, object]:
        assert create_parent is True
        if path == global_registry:
            barrier.wait(timeout=5)
        return {"ok": True, "path": str(path)}

    monkeypatch.setattr(registry_admin, "probe_registry_write_path", coordinated_probe)

    def register() -> dict[str, object]:
        return registry_admin.register_agent_via_source_registry(
            runtime_root_arg=str(runtime_root),
            goal_id=GOAL_ID,
            agent_ids=["codex-fresh"],
            require_new=True,
            execute=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register(), range(2)))

    successes = [result for result in results if result.get("ok") is True]
    collisions = [
        result
        for result in results
        if result.get("error_kind") == "agent_identity_already_registered"
    ]
    assert len(successes) == 1, results
    assert successes[0]["changed"] is True
    assert successes[0]["written"] is True
    assert successes[0]["partial_write"] is False
    assert successes[0]["global_sync"]["ok"] is True
    assert successes[0]["global_sync"]["phase"] == "commit"
    assert successes[0]["registration_readback"]["verified"] is True
    assert successes[0]["registration_readback"]["requested_agents"] == [
        "codex-fresh"
    ]
    assert "codex-fresh" in successes[0]["registration_readback"][
        "source_registered_agents"
    ]
    assert "codex-fresh" in successes[0]["registration_readback"][
        "global_registered_agents"
    ]
    assert len(collisions) == 1, results
    assert collisions[0]["changed"] is False
    assert collisions[0]["written"] is False
    assert collisions[0]["partial_write"] is False

    source_goal = json.loads(source_registry.read_text(encoding="utf-8"))["goals"][0]
    assert source_goal["coordination"]["registered_agents"] == [
        "codex-existing",
        "codex-fresh",
    ]


def test_registration_sync_integrity_is_preflighted_before_source_write(
    tmp_path: Path,
    capsys,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    source_payload = json.loads(source_registry.read_text(encoding="utf-8"))
    source_payload["goals"][0]["project_id"] = GOAL_ID
    _write_json(source_registry, source_payload)
    global_before = global_registry.read_text(encoding="utf-8")

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "register-agent",
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            "dsh-preflight-fixture",
            "--require-new",
            "--execute",
        ]
    ) == 1
    result = json.loads(capsys.readouterr().out)

    assert result["schema_version"] == "loopx_register_agent_v0"
    assert result["ok"] is False
    assert result["error_kind"] == "agent_registration_sync_preflight_failed"
    assert result["changed"] is False
    assert result["written"] is False
    assert result["partial_write"] is False
    assert result["global_sync"]["phase"] == "preflight"
    assert result["registration_readback"] == {
        "schema_version": "loopx_agent_registration_readback_v0",
        "performed": False,
        "verified": False,
    }
    source_after = json.loads(source_registry.read_text(encoding="utf-8"))
    assert source_after["goals"][0]["coordination"]["registered_agents"] == [
        "codex-existing"
    ]
    assert global_registry.read_text(encoding="utf-8") == global_before


def test_post_source_sync_exception_preserves_partial_write_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root, source_registry, _global_registry = _fixture(tmp_path)
    real_sync = registry_admin.sync_project_registry_to_global

    def fail_commit_sync(**kwargs):
        if kwargs.get("dry_run") is True:
            return real_sync(**kwargs)
        raise RuntimeError("fixture sync failure")

    monkeypatch.setattr(
        registry_admin,
        "sync_project_registry_to_global",
        fail_commit_sync,
    )

    result = registry_admin.register_agent_via_source_registry(
        runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID,
        agent_ids=["dsh-partial-fixture"],
        require_new=True,
        execute=True,
    )

    assert result["ok"] is False
    assert result["error_kind"] == "agent_registration_global_sync_failed"
    assert result["changed"] is True
    assert result["written"] is True
    assert result["partial_write"] is True
    assert result["global_sync"]["phase"] == "commit"
    assert result["registration_readback"]["performed"] is False
    source_goal = json.loads(source_registry.read_text(encoding="utf-8"))["goals"][0]
    assert source_goal["coordination"]["registered_agents"] == [
        "codex-existing",
        "dsh-partial-fixture",
    ]


def test_commit_sync_rejection_preserves_partial_write_and_readback_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    real_sync = registry_admin.sync_project_registry_to_global
    global_before = global_registry.read_text(encoding="utf-8")

    def reject_commit_sync(**kwargs):
        if kwargs.get("dry_run") is True:
            return real_sync(**kwargs)
        return {
            "ok": False,
            "wrote": False,
            "error_kind": "global_registry_sync_failed",
            "error": "fixture commit sync rejection",
        }

    monkeypatch.setattr(
        registry_admin,
        "sync_project_registry_to_global",
        reject_commit_sync,
    )

    result = registry_admin.register_agent_via_source_registry(
        runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID,
        agent_ids=["dsh-returned-failure-fixture"],
        require_new=True,
        execute=True,
    )

    assert result["ok"] is False
    assert result["error_kind"] == "global_registry_sync_failed"
    assert result["changed"] is True
    assert result["written"] is True
    assert result["partial_write"] is True
    assert result["global_sync"]["phase"] == "commit"
    assert result["registration_readback"]["performed"] is True
    assert result["registration_readback"]["verified"] is False
    source_goal = json.loads(source_registry.read_text(encoding="utf-8"))["goals"][0]
    assert source_goal["coordination"]["registered_agents"] == [
        "codex-existing",
        "dsh-returned-failure-fixture",
    ]
    assert global_registry.read_text(encoding="utf-8") == global_before


def test_successful_sync_claim_still_requires_exact_registration_readback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    real_sync = registry_admin.sync_project_registry_to_global
    global_before = global_registry.read_text(encoding="utf-8")

    def claim_commit_without_write(**kwargs):
        if kwargs.get("dry_run") is True:
            return real_sync(**kwargs)
        return {"ok": True, "wrote": False}

    monkeypatch.setattr(
        registry_admin,
        "sync_project_registry_to_global",
        claim_commit_without_write,
    )

    result = registry_admin.register_agent_via_source_registry(
        runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID,
        agent_ids=["dsh-readback-mismatch-fixture"],
        require_new=True,
        execute=True,
    )

    assert result["ok"] is False
    assert result["error_kind"] == "agent_registration_readback_failed"
    assert result["changed"] is True
    assert result["written"] is True
    assert result["partial_write"] is True
    assert result["global_sync"] == {"ok": True, "wrote": False, "phase": "commit"}
    assert result["registration_readback"]["performed"] is True
    assert result["registration_readback"]["verified"] is False
    assert result["registration_readback"]["source_registered_agents"] == [
        "codex-existing",
        "dsh-readback-mismatch-fixture",
    ]
    assert result["registration_readback"]["global_registered_agents"] == [
        "codex-existing"
    ]
    assert global_registry.read_text(encoding="utf-8") == global_before


def test_non_fresh_registration_remains_an_idempotent_verified_noop(
    tmp_path: Path,
) -> None:
    runtime_root, _source_registry, _global_registry = _fixture(tmp_path)

    result = registry_admin.register_agent_via_source_registry(
        runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID,
        agent_ids=["codex-existing"],
        require_new=False,
        execute=True,
    )

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["written"] is False
    assert result["partial_write"] is False
    assert result["global_sync"]["ok"] is True
    assert result["registration_readback"]["verified"] is True


def test_agent_and_thread_mutation_cli_envelopes_are_versioned(
    tmp_path: Path,
    capsys,
) -> None:
    runtime_root, _source_registry, _global_registry = _fixture(tmp_path)

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "register-agent",
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            "dsh-native-fixture",
            "--require-new",
            "--execute",
        ]
    ) == 0
    registered = json.loads(capsys.readouterr().out)
    assert registered["schema_version"] == "loopx_register_agent_v0"
    assert registered["registration_readback"]["verified"] is True

    for command, expected_status in (
        ("bind-agent-thread", "bound"),
        ("unbind-agent-thread", "missing"),
    ):
        assert main(
            [
                "--format",
                "json",
                "--runtime-root",
                str(runtime_root),
                command,
                "--goal-id",
                GOAL_ID,
                "--thread-id",
                "dsh-session-fixture",
                "--host-surface",
                "dsh-native",
                "--agent-id",
                "dsh-native-fixture",
                "--execute",
            ]
        ) == 0
        payload = json.loads(capsys.readouterr().out)
        assert (
            payload["schema_version"]
            == "loopx_thread_agent_binding_command_v0"
        )
        assert payload["host_surface"] == "deepseek-harness-native"
        assert payload["binding"]["status"] == expected_status


def test_thread_binding_write_denial_keeps_versioned_failure_envelope(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    runtime_root, source_registry, _global_registry = _fixture(tmp_path)
    source_before = source_registry.read_bytes()

    monkeypatch.setattr(
        registry_admin,
        "probe_registry_write_path",
        lambda _path, *, create_parent: {
            "ok": False,
            "create_parent": create_parent,
            "recommended_action": "repair fixture permissions",
        },
    )

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "bind-agent-thread",
            "--goal-id",
            GOAL_ID,
            "--thread-id",
            "dsh-session-write-denied",
            "--host-surface",
            "dsh-native",
            "--agent-id",
            "codex-existing",
            "--execute",
        ]
    ) == 1
    payload = json.loads(capsys.readouterr().out)

    assert payload == {
        "schema_version": "loopx_thread_agent_binding_command_v0",
        "ok": False,
        "dry_run": False,
        "execute": True,
        "goal_id": GOAL_ID,
        "changed": False,
        "written": False,
        "error_kind": "global_registry_write_denied",
        "global_registry_writability": {
            "ok": False,
            "create_parent": True,
            "recommended_action": "repair fixture permissions",
        },
        "recommended_action": "repair fixture permissions",
    }
    assert source_registry.read_bytes() == source_before
