from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from loopx import paths as loopx_paths
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


def test_dsh_binding_home_selection_is_exact_and_fail_closed(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project_registry = tmp_path / "project" / ".loopx" / "registry.json"
    default_root = tmp_path / "default-runtime"
    custom_root = tmp_path / "custom-runtime"
    explicit_root = tmp_path / "explicit-runtime"
    payload: dict[str, object] = {"schema_version": "0.1", "goals": []}
    _write_json(project_registry, payload)
    monkeypatch.setattr(loopx_paths, "DEFAULT_RUNTIME_ROOT", default_root)

    assert registry_admin.dsh_binding_global_registry(
        registry_path=project_registry,
        runtime_root_arg=None,
    ) == default_root / "registry.global.json"
    binding = {
        "schema_version": "loopx_host_thread_binding_v1",
        "host_surface": "dsh",
        "thread_id": "root-selection-session",
        "revision": 1,
        "state": "unbound",
    }
    authority = {
        "schema_version": "0.1",
        "goals": [],
        "dsh_host_thread_bindings": {
            "schema_version": "loopx_dsh_host_thread_bindings_v1",
            "records": {"root-selection-session": binding},
        },
    }
    _write_json(default_root / "registry.global.json", authority)
    assert main(
        [
            "--format",
            "json",
            "--registry",
            str(project_registry),
            "resolve-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "root-selection-session",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["binding"] == binding

    payload["common_runtime_root"] = str(custom_root)
    _write_json(project_registry, payload)
    custom_binding = {**binding, "revision": 2}
    authority["dsh_host_thread_bindings"]["records"] = {
        "root-selection-session": custom_binding
    }
    _write_json(custom_root / "registry.global.json", authority)
    assert registry_admin.dsh_binding_global_registry(
        registry_path=project_registry,
        runtime_root_arg=None,
    ) == custom_root / "registry.global.json"
    assert main(
        [
            "--format",
            "json",
            "--registry",
            str(project_registry),
            "resolve-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "root-selection-session",
        ]
    ) == 0
    assert json.loads(capsys.readouterr().out)["binding"] == custom_binding

    payload["common_runtime_root"] = [str(custom_root), str(explicit_root)]
    _write_json(project_registry, payload)
    assert registry_admin.dsh_binding_global_registry(
        registry_path=project_registry,
        runtime_root_arg=str(explicit_root),
    ) == explicit_root / "registry.global.json"
    with pytest.raises(registry_admin.DshBindingAuthorityError) as ambiguous:
        registry_admin.dsh_binding_global_registry(
            registry_path=project_registry,
            runtime_root_arg=None,
        )
    assert ambiguous.value.error_kind == "binding_home_unavailable"
    with pytest.raises(registry_admin.DshBindingAuthorityError) as missing:
        registry_admin.dsh_binding_global_registry(
            registry_path=tmp_path / "missing" / ".loopx" / "registry.json",
            runtime_root_arg=None,
        )
    assert missing.value.error_kind == "binding_home_unavailable"


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


def test_dsh_thread_binding_cli_uses_the_strict_global_v1_contract(
    tmp_path: Path,
    capsys,
) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "bind-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "dsh-session-v1",
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            "codex-existing",
            "--expected-revision",
            "0",
            "--execute",
        ]
    ) == 0
    bound = json.loads(capsys.readouterr().out)
    expected_binding = {
        "schema_version": "loopx_host_thread_binding_v1",
        "host_surface": "dsh",
        "thread_id": "dsh-session-v1",
        "revision": 1,
        "state": "bound",
        "target": {"goal_id": GOAL_ID, "agent_id": "codex-existing"},
    }
    assert bound == {
        "schema_version": "loopx_host_thread_binding_command_v1",
        "ok": True,
        "changed": True,
        "application": "yes",
        "binding": expected_binding,
    }
    assert "thread_agent_bindings" not in json.loads(
        source_registry.read_text(encoding="utf-8")
    )["goals"][0]["coordination"]

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "resolve-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "dsh-session-v1",
        ]
    ) == 0
    resolved = json.loads(capsys.readouterr().out)
    assert resolved == {
        "schema_version": "loopx_host_thread_binding_command_v1",
        "ok": True,
        "changed": False,
        "application": "no",
        "binding": expected_binding,
    }

    assert main(
        [
            "--format",
            "json",
            "--runtime-root",
            str(runtime_root),
            "unbind-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "dsh-session-v1",
            "--expected-revision",
            "1",
            "--execute",
        ]
    ) == 0
    unbound = json.loads(capsys.readouterr().out)
    assert unbound == {
        "schema_version": "loopx_host_thread_binding_command_v1",
        "ok": True,
        "changed": True,
        "application": "yes",
        "binding": {
            "schema_version": "loopx_host_thread_binding_v1",
            "host_surface": "dsh",
            "thread_id": "dsh-session-v1",
            "revision": 2,
            "state": "unbound",
        },
    }
    stored = json.loads(global_registry.read_text(encoding="utf-8"))
    assert stored["dsh_host_thread_bindings"]["records"]["dsh-session-v1"] == unbound[
        "binding"
    ]


def test_dsh_cli_requires_cas_and_does_not_leak_binding_home(
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
            "bind-agent-thread",
            "--host-surface",
            "dsh",
            "--thread-id",
            "dsh-session-no-cas",
            "--goal-id",
            GOAL_ID,
            "--agent-id",
            "codex-existing",
            "--execute",
        ]
    ) == 1
    rejected = json.loads(capsys.readouterr().out)
    assert rejected == {
        "schema_version": "loopx_host_thread_binding_command_v1",
        "ok": False,
        "changed": False,
        "application": "no",
        "error_kind": "invalid_target",
    }
    assert str(runtime_root) not in json.dumps(rejected)


def test_fresh_registration_survives_a_failed_dsh_binding_cas(tmp_path: Path) -> None:
    runtime_root, source_registry, global_registry = _fixture(tmp_path)
    first = registry_admin.bind_dsh_thread_agent_in_global_registry(
        global_path=global_registry,
        host_surface="dsh",
        thread_id="dsh-session-registration",
        goal_id=GOAL_ID,
        agent_id="codex-existing",
        expected_revision=0,
        execute=True,
    )
    assert first["ok"] is True

    registered = registry_admin.register_agent_via_source_registry(
        runtime_root_arg=str(runtime_root),
        goal_id=GOAL_ID,
        agent_ids=["dsh-fresh-unbound"],
        require_new=True,
        execute=True,
    )
    assert registered["registration_readback"]["verified"] is True
    rejected = registry_admin.bind_dsh_thread_agent_in_global_registry(
        global_path=global_registry,
        host_surface="dsh",
        thread_id="dsh-session-registration",
        goal_id=GOAL_ID,
        agent_id="dsh-fresh-unbound",
        expected_revision=0,
        execute=True,
    )
    assert rejected["error_kind"] == "revision_conflict"
    assert rejected["binding"] == first["binding"]

    for path in (source_registry, global_registry):
        goal = json.loads(path.read_text(encoding="utf-8"))["goals"][0]
        assert "dsh-fresh-unbound" in goal["coordination"]["registered_agents"]
    assert "thread_agent_bindings" not in json.loads(
        source_registry.read_text(encoding="utf-8")
    )["goals"][0]["coordination"]


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
