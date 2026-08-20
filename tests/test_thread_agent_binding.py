from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopx.thread_agent_binding import (
    DSH_BINDING_COLLECTION_KEY,
    DSH_BINDING_COLLECTION_SCHEMA_VERSION,
    HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
    HOST_THREAD_BINDING_SCHEMA_VERSION,
    JAVASCRIPT_SAFE_INTEGER_MAX,
    bind_dsh_thread_agent_in_global_registry,
    bind_thread_agent_in_registry,
    normalize_thread_id,
    resolve_dsh_thread_agent_binding,
    resolve_thread_agent_binding,
    unbind_dsh_thread_agent_in_global_registry,
    unbind_thread_agent_in_registry,
)


def _registry(tmp_path: Path, agents: list[str]) -> Path:
    path = tmp_path / ".loopx" / "registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "goals": [
                    {
                        "id": "goal",
                        "coordination": {"registered_agents": agents},
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _dsh_authority(
    tmp_path: Path,
    agents: list[str] | None = None,
) -> tuple[Path, Path]:
    agents = agents or ["agent-a", "agent-b"]
    project = tmp_path / "project"
    source = project / ".loopx" / "registry.json"
    global_path = tmp_path / "runtime" / "registry.global.json"
    source.parent.mkdir(parents=True)
    global_path.parent.mkdir(parents=True)
    goal = {
        "id": "goal",
        "repo": str(project),
        "state_file": ".codex/goals/goal/ACTIVE_GOAL_STATE.md",
        "coordination": {"registered_agents": agents},
    }
    source.write_text(
        json.dumps({"schema_version": "0.1", "goals": [goal]}) + "\n",
        encoding="utf-8",
    )
    global_goal = {**goal, "source_registry": str(source)}
    global_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "registry_role": "global-local",
                "goals": [global_goal],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return source, global_path


def _bound_v1(
    *,
    thread_id: str,
    revision: int,
    goal_id: str = "goal",
    agent_id: str = "agent-a",
) -> dict[str, object]:
    return {
        "schema_version": HOST_THREAD_BINDING_SCHEMA_VERSION,
        "host_surface": "dsh",
        "thread_id": thread_id,
        "revision": revision,
        "state": "bound",
        "target": {"goal_id": goal_id, "agent_id": agent_id},
    }


def test_thread_id_is_bounded_and_opaque() -> None:
    assert normalize_thread_id(" thread-1 ") == "thread-1"
    assert normalize_thread_id(None) is None
    with pytest.raises(ValueError):
        normalize_thread_id("thread with spaces")
    with pytest.raises(ValueError):
        normalize_thread_id("x" * 129)


def test_binding_lookup_is_fail_closed_without_thread_id() -> None:
    goal = {
        "coordination": {
            "registered_agents": ["agent-a", "agent-b"],
            "thread_agent_bindings": [
                {
                    "thread_id": "thread-a",
                    "host_surface": "codex-app",
                    "agent_id": "agent-a",
                }
            ],
        }
    }
    assert (
        resolve_thread_agent_binding(goal, host_surface="codex-app", thread_id=None)[
            "status"
        ]
        == "unavailable"
    )
    assert (
        resolve_thread_agent_binding(
            goal, host_surface="codex-app", thread_id="thread-a"
        )["agent_id"]
        == "agent-a"
    )


def test_dsh_native_alias_shares_one_canonical_thread_binding(tmp_path: Path) -> None:
    path = _registry(tmp_path, ["agent-a"])
    result = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="dsh-native",
        thread_id="session-a",
        agent_id="agent-a",
        execute=True,
    )

    assert result["host_surface"] == "deepseek-harness-native"
    goal = json.loads(path.read_text(encoding="utf-8"))["goals"][0]
    canonical = resolve_thread_agent_binding(
        goal,
        host_surface="deepseek-harness-native",
        thread_id="session-a",
    )
    shorthand = resolve_thread_agent_binding(
        goal,
        host_surface="dsh-native",
        thread_id="session-a",
    )
    assert canonical["status"] == "bound"
    assert canonical["agent_id"] == "agent-a"
    assert shorthand == canonical


def test_external_dsh_aliases_share_the_existing_canonical_thread_binding(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a"])
    result = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="dsh",
        thread_id="session-external",
        agent_id="agent-a",
        execute=True,
    )

    assert result["host_surface"] == "deepseek-harness"
    goal = json.loads(path.read_text(encoding="utf-8"))["goals"][0]
    for spelling in (
        "deepseek-harness",
        "deepseek_harness",
        "deepseek harness",
        "dsh",
    ):
        resolved = resolve_thread_agent_binding(
            goal,
            host_surface=spelling,
            thread_id="session-external",
        )
        assert resolved["status"] == "bound"
        assert resolved["agent_id"] == "agent-a"


def test_binding_is_idempotent_and_conflicts_fail_closed(tmp_path: Path) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    first = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-a",
        execute=True,
    )
    assert first["ok"] is True
    assert first["written"] is True
    second = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-a",
        execute=True,
    )
    assert second["ok"] is True
    assert second["changed"] is False
    conflict = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-a",
        agent_id="agent-b",
        execute=True,
    )
    assert conflict["ok"] is False
    assert conflict["error_kind"] == "thread_agent_binding_conflict"
    payload = json.loads(path.read_text(encoding="utf-8"))
    bindings = payload["goals"][0]["coordination"]["thread_agent_bindings"]
    assert bindings == [
        {"thread_id": "thread-a", "host_surface": "codex-app", "agent_id": "agent-a"}
    ]


def test_unbind_removes_only_the_exact_thread_and_preserves_agent_registration(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    for thread_id in ("thread-current", "thread-other"):
        bound = bind_thread_agent_in_registry(
            registry_path=path,
            goal_id="goal",
            host_surface="codex-app",
            thread_id=thread_id,
            agent_id="agent-b",
            execute=True,
        )
        assert bound["ok"] is True

    before_preview = path.read_bytes()
    preview = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=False,
    )
    assert preview["ok"] is True
    assert preview["changed"] is True
    assert preview["written"] is False
    assert path.read_bytes() == before_preview

    unbound = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=True,
    )

    assert unbound["ok"] is True
    assert unbound["changed"] is True
    assert unbound["written"] is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    goal = payload["goals"][0]
    assert goal["coordination"]["registered_agents"] == ["agent-a", "agent-b"]
    assert goal["coordination"]["thread_agent_bindings"] == [
        {
            "thread_id": "thread-other",
            "host_surface": "codex-app",
            "agent_id": "agent-b",
        }
    ]
    assert resolve_thread_agent_binding(
        goal,
        host_surface="codex-app",
        thread_id="thread-current",
    )["status"] == "missing"
    assert resolve_thread_agent_binding(
        goal,
        host_surface="codex-app",
        thread_id="thread-other",
    )["agent_id"] == "agent-b"

    rebound = bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-a",
        execute=True,
    )
    assert rebound["ok"] is True


def test_unbind_is_idempotent_and_expected_agent_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    path = _registry(tmp_path, ["agent-a", "agent-b"])
    assert bind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-b",
        execute=True,
    )["ok"] is True
    before = path.read_bytes()

    mismatch = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-current",
        agent_id="agent-a",
        execute=True,
    )
    assert mismatch["ok"] is False
    assert mismatch["error_kind"] == "thread_agent_binding_agent_mismatch"
    assert path.read_bytes() == before

    missing = unbind_thread_agent_in_registry(
        registry_path=path,
        goal_id="goal",
        host_surface="codex-app",
        thread_id="thread-missing",
        agent_id="agent-b",
        execute=True,
    )
    assert missing["ok"] is True
    assert missing["changed"] is False
    assert path.read_bytes() == before


def test_dsh_v1_first_bind_freezes_wire_shape_and_does_not_write_goal_local_copy(
    tmp_path: Path,
) -> None:
    source, global_path = _dsh_authority(tmp_path)
    expected_binding = _bound_v1(thread_id="session-a", revision=1)
    legacy_binding = {
        "thread_id": "session-a",
        "host_surface": "deepseek-harness",
        "agent_id": "agent-b",
    }
    for path in (source, global_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["goals"][0]["coordination"]["thread_agent_bindings"] = [
            legacy_binding
        ]
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    result = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=0,
        execute=True,
    )

    assert result == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": True,
        "changed": True,
        "application": "yes",
        "binding": expected_binding,
    }
    global_payload = json.loads(global_path.read_text(encoding="utf-8"))
    assert global_payload[DSH_BINDING_COLLECTION_KEY] == {
        "schema_version": DSH_BINDING_COLLECTION_SCHEMA_VERSION,
        "records": {"session-a": expected_binding},
    }
    source_goal = json.loads(source.read_text(encoding="utf-8"))["goals"][0]
    assert source_goal["coordination"]["thread_agent_bindings"] == [legacy_binding]
    assert global_payload["goals"][0]["coordination"]["thread_agent_bindings"] == [
        legacy_binding
    ]


def test_dsh_v1_cas_precedes_idempotence_and_current_cas_is_no_write(
    tmp_path: Path,
) -> None:
    _source, global_path = _dsh_authority(tmp_path)
    first = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=0,
        execute=True,
    )
    assert first["ok"] is True
    before = global_path.read_bytes()

    stale = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=0,
        execute=True,
    )
    assert stale == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": False,
        "changed": False,
        "application": "no",
        "error_kind": "revision_conflict",
        "binding": _bound_v1(thread_id="session-a", revision=1),
    }
    assert global_path.read_bytes() == before

    idempotent = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=1,
        execute=True,
    )
    assert idempotent == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": True,
        "changed": False,
        "application": "no",
        "binding": _bound_v1(thread_id="session-a", revision=1),
    }
    assert global_path.read_bytes() == before


def test_dsh_v1_switch_unbind_and_same_target_rebind_advance_one_revision(
    tmp_path: Path,
) -> None:
    source, global_path = _dsh_authority(tmp_path)
    for path in (source, global_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        second_goal = {
            **payload["goals"][0],
            "id": "goal-b",
            "state_file": ".codex/goals/goal-b/ACTIVE_GOAL_STATE.md",
        }
        payload["goals"].append(second_goal)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=0,
        execute=True,
    )["ok"] is True

    switched = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal-b",
        agent_id="agent-a",
        expected_revision=1,
        execute=True,
    )
    assert switched["binding"] == _bound_v1(
        thread_id="session-a",
        revision=2,
        goal_id="goal-b",
    )
    assert switched["changed"] is True
    stored_after_switch = json.loads(global_path.read_text(encoding="utf-8"))[
        DSH_BINDING_COLLECTION_KEY
    ]["records"]["session-a"]
    assert stored_after_switch == switched["binding"]

    unbound = unbind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        expected_revision=2,
        execute=True,
    )
    tombstone = {
        "schema_version": HOST_THREAD_BINDING_SCHEMA_VERSION,
        "host_surface": "dsh",
        "thread_id": "session-a",
        "revision": 3,
        "state": "unbound",
    }
    assert unbound == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": True,
        "changed": True,
        "application": "yes",
        "binding": tombstone,
    }
    assert resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )["binding"] == tombstone

    rebound = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=3,
        execute=True,
    )
    assert rebound["binding"] == _bound_v1(thread_id="session-a", revision=4)


def test_dsh_v1_resolve_failures_are_bounded_and_fail_closed(tmp_path: Path) -> None:
    _source, global_path = _dsh_authority(tmp_path)
    invalid_surface = resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="DSH",
        thread_id="session-a",
    )
    assert invalid_surface["error_kind"] == "invalid_target"
    missing_home = resolve_dsh_thread_agent_binding(
        global_path=tmp_path / "missing" / "registry.global.json",
        host_surface="dsh",
        thread_id="session-a",
    )
    assert missing_home == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": False,
        "changed": False,
        "application": "no",
        "error_kind": "binding_home_unavailable",
    }
    uninitialized = resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )
    assert uninitialized["error_kind"] == "binding_home_uninitialized"

    payload = json.loads(global_path.read_text(encoding="utf-8"))
    payload[DSH_BINDING_COLLECTION_KEY] = {
        "schema_version": DSH_BINDING_COLLECTION_SCHEMA_VERSION,
        "records": {},
    }
    global_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    not_found = resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )
    assert not_found["error_kind"] == "binding_not_found"

    payload[DSH_BINDING_COLLECTION_KEY]["unexpected"] = True
    global_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    corrupt = resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )
    assert corrupt == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": False,
        "changed": False,
        "application": "no",
        "error_kind": "authority_corrupt",
    }

    malformed = _bound_v1(thread_id="session-a", revision=1)
    malformed["revision"] = True
    payload[DSH_BINDING_COLLECTION_KEY] = {
        "schema_version": DSH_BINDING_COLLECTION_SCHEMA_VERSION,
        "records": {"session-a": malformed},
    }
    global_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    assert resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )["error_kind"] == "authority_corrupt"


def test_dsh_v1_exact_unbind_allows_dangling_target(tmp_path: Path) -> None:
    source, global_path = _dsh_authority(tmp_path)
    assert bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-a",
        expected_revision=0,
        execute=True,
    )["ok"] is True
    source_payload = json.loads(source.read_text(encoding="utf-8"))
    source_payload["goals"][0]["coordination"]["registered_agents"] = ["agent-b"]
    source.write_text(json.dumps(source_payload) + "\n", encoding="utf-8")

    unhealthy = resolve_dsh_thread_agent_binding(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
    )
    assert unhealthy["error_kind"] == "authority_unhealthy"
    assert unhealthy["binding"] == _bound_v1(thread_id="session-a", revision=1)

    unbound = unbind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        expected_revision=1,
        execute=True,
    )
    assert unbound["ok"] is True
    assert unbound["binding"]["state"] == "unbound"
    assert unbound["binding"]["revision"] == 2


def test_dsh_v1_revision_overflow_is_typed_and_does_not_write(tmp_path: Path) -> None:
    _source, global_path = _dsh_authority(tmp_path)
    payload = json.loads(global_path.read_text(encoding="utf-8"))
    binding = _bound_v1(
        thread_id="session-a",
        revision=JAVASCRIPT_SAFE_INTEGER_MAX,
    )
    payload[DSH_BINDING_COLLECTION_KEY] = {
        "schema_version": DSH_BINDING_COLLECTION_SCHEMA_VERSION,
        "records": {"session-a": binding},
    }
    global_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    before = global_path.read_bytes()

    exhausted = bind_dsh_thread_agent_in_global_registry(
        global_path=global_path,
        host_surface="dsh",
        thread_id="session-a",
        goal_id="goal",
        agent_id="agent-b",
        expected_revision=JAVASCRIPT_SAFE_INTEGER_MAX,
        execute=True,
    )
    assert exhausted == {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": False,
        "changed": False,
        "application": "no",
        "error_kind": "authority_exhausted",
        "binding": binding,
    }
    assert global_path.read_bytes() == before
