"""Validated Host-thread bindings for Goal-scoped Agent lanes.

Non-DSH Hosts keep the Goal-local v0 contract below.  The DSH integration uses
the strict, revisioned global authority defined in the second half of this
module; the two stores are deliberately never mirrored into each other.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .agent_registry import normalize_registered_agents
from .control_plane.todos.contract import normalize_todo_claimed_by
from .file_lock import exclusive_file_lock
from .history import load_registry
from .host_loop_activation import normalize_host_surface
from .registry import atomic_write_json, find_registry_goal
from .runtime import validate_goal_id_path_segment

THREAD_ID_MAX_LENGTH = 128
GOAL_ID_MAX_LENGTH = 256
THREAD_BINDING_SCHEMA_VERSION = "loopx_thread_agent_binding_v0"
DSH_HOST_SURFACE = "dsh"
DSH_BINDING_COLLECTION_KEY = "dsh_host_thread_bindings"
DSH_BINDING_COLLECTION_SCHEMA_VERSION = "loopx_dsh_host_thread_bindings_v1"
HOST_THREAD_BINDING_SCHEMA_VERSION = "loopx_host_thread_binding_v1"
HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION = (
    "loopx_host_thread_binding_command_v1"
)
JAVASCRIPT_SAFE_INTEGER_MAX = 9_007_199_254_740_991
DSH_THREAD_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DSH_GOAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
DSH_AGENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class DshBindingAuthorityError(ValueError):
    """Typed, public-safe rejection from the DSH binding authority."""

    def __init__(
        self,
        error_kind: str,
        *,
        binding: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(error_kind)
        self.error_kind = error_kind
        self.binding = binding


def normalize_thread_id(value: Any) -> str | None:
    """Return a bounded opaque host token, or None for an omitted token."""

    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    if len(token) > THREAD_ID_MAX_LENGTH:
        raise ValueError(f"thread_id must be at most {THREAD_ID_MAX_LENGTH} characters")
    if any(char.isspace() or ord(char) < 32 for char in token):
        raise ValueError(
            "thread_id must be a public-safe opaque token without whitespace"
        )
    if any(char in token for char in ("/", "\\", '"', "'")):
        raise ValueError("thread_id must not contain path or quoting characters")
    return token


def _normalized_host_surface(value: Any) -> str:
    raw_surface = str(value or "").strip()
    if not raw_surface:
        raise ValueError("host_surface is required for a thread binding")
    surface = normalize_host_surface(raw_surface)
    if len(surface) > 64 or any(char.isspace() for char in surface):
        raise ValueError("host_surface must be a compact public-safe token")
    return surface


def _bindings_for_goal(goal: dict[str, Any]) -> list[dict[str, str]]:
    coordination = goal.get("coordination")
    if not isinstance(coordination, dict):
        return []
    raw = coordination.get("thread_agent_bindings")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            thread_id = normalize_thread_id(item.get("thread_id"))
            host_surface = _normalized_host_surface(item.get("host_surface"))
            agent_id = normalize_todo_claimed_by(item.get("agent_id"))
        except ValueError:
            continue
        if thread_id and agent_id:
            result.append(
                {
                    "thread_id": thread_id,
                    "host_surface": host_surface,
                    "agent_id": agent_id,
                }
            )
    return result


def resolve_thread_agent_binding(
    goal: dict[str, Any] | None,
    *,
    host_surface: str,
    thread_id: str | None,
) -> dict[str, Any]:
    """Resolve a thread binding without guessing from registry order."""

    normalized_thread_id = normalize_thread_id(thread_id)
    normalized_surface = _normalized_host_surface(host_surface)
    base: dict[str, Any] = {
        "schema_version": THREAD_BINDING_SCHEMA_VERSION,
        "host_surface": normalized_surface,
        "thread_id": normalized_thread_id,
        "status": "unavailable" if not normalized_thread_id else "missing",
        "agent_id": None,
        "matches": [],
    }
    if not normalized_thread_id:
        return base
    matches = [
        item
        for item in _bindings_for_goal(goal or {})
        if item["host_surface"] == normalized_surface
        and item["thread_id"] == normalized_thread_id
    ]
    base["matches"] = matches
    agent_ids = sorted({item["agent_id"] for item in matches})
    if len(agent_ids) == 1:
        base["status"] = "bound"
        base["agent_id"] = agent_ids[0]
    elif len(agent_ids) > 1:
        base["status"] = "conflict"
        base["reason"] = "one thread is bound to multiple agent lanes"
    return base


def _merge_thread_binding_entries(
    current: list[dict[str, str]], entry: dict[str, str]
) -> list[dict[str, str]]:
    merged = [
        item
        for item in current
        if not (
            item["thread_id"] == entry["thread_id"]
            and item["host_surface"] == entry["host_surface"]
        )
    ]
    merged.append(entry)
    merged.sort(
        key=lambda item: (item["host_surface"], item["thread_id"], item["agent_id"])
    )
    return merged


def _binding_context(
    payload: dict[str, Any],
    *,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    goal = find_registry_goal(payload, goal_id)
    if goal is None:
        raise ValueError(f"goal_id not found in registry: {goal_id}")
    coordination = goal.get("coordination")
    coordination = coordination if isinstance(coordination, dict) else {}
    registered = coordination.get("registered_agents")
    registered_ids = {
        normalize_todo_claimed_by(item)
        for item in (registered if isinstance(registered, list) else [])
    }
    if agent_id not in registered_ids:
        raise ValueError(
            f"agent_id={agent_id!r} is not registered for goal {goal_id!r}"
        )
    current = _bindings_for_goal(goal)
    existing = resolve_thread_agent_binding(
        goal,
        host_surface=host_surface,
        thread_id=thread_id,
    )
    return goal, current, existing


def _prepare_binding(
    payload: dict[str, Any],
    *,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    goal, current, existing = _binding_context(
        payload,
        goal_id=goal_id,
        host_surface=host_surface,
        thread_id=thread_id,
        agent_id=agent_id,
    )
    if existing["status"] == "conflict":
        return (
            {
                "ok": False,
                "changed": False,
                "written": False,
                "error_kind": "thread_agent_binding_conflict",
                "binding": existing,
            },
            goal,
            current,
        )
    if existing["status"] == "bound" and existing["agent_id"] != agent_id:
        return (
            {
                "ok": False,
                "changed": False,
                "written": False,
                "error_kind": "thread_agent_binding_conflict",
                "error": "thread is already bound to a different agent; explicit unbind is required",
                "binding": existing,
            },
            goal,
            current,
        )

    entry = {"thread_id": thread_id, "host_surface": host_surface, "agent_id": agent_id}
    merged = _merge_thread_binding_entries(current, entry)
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": goal_id,
        "registry": "",
        "thread_id": thread_id,
        "host_surface": host_surface,
        "agent_id": agent_id,
        "changed": merged != current,
        "written": False,
        "binding": {
            "schema_version": THREAD_BINDING_SCHEMA_VERSION,
            **entry,
            "status": "bound",
        },
    }
    return result, goal, merged


def _prepare_unbinding(
    payload: dict[str, Any],
    *,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    goal, current, existing = _binding_context(
        payload,
        goal_id=goal_id,
        host_surface=host_surface,
        thread_id=thread_id,
        agent_id=agent_id,
    )
    result: dict[str, Any] = {
        "ok": True,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": goal_id,
        "registry": "",
        "thread_id": thread_id,
        "host_surface": host_surface,
        "agent_id": agent_id,
        "changed": False,
        "written": False,
        "binding": {
            "schema_version": THREAD_BINDING_SCHEMA_VERSION,
            "thread_id": thread_id,
            "host_surface": host_surface,
            "agent_id": None,
            "status": "missing",
        },
    }
    if existing["status"] == "conflict":
        result.update(
            {
                "ok": False,
                "error_kind": "thread_agent_binding_conflict",
                "binding": existing,
            }
        )
        return result, goal, current
    if existing["status"] == "missing":
        return result, goal, current
    if existing["agent_id"] != agent_id:
        result.update(
            {
                "ok": False,
                "error_kind": "thread_agent_binding_agent_mismatch",
                "error": (
                    "thread binding does not match expected agent: "
                    f"{existing['agent_id']} != {agent_id}"
                ),
                "binding": existing,
            }
        )
        return result, goal, current

    remaining = [
        item
        for item in current
        if not (
            item["thread_id"] == thread_id
            and item["host_surface"] == host_surface
        )
    ]
    result["changed"] = remaining != current
    return result, goal, remaining


def bind_thread_agent_in_registry(
    *,
    registry_path: Path,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> dict[str, Any]:
    """Preview or atomically bind an already registered agent to a host thread."""

    normalized_thread_id = normalize_thread_id(thread_id)
    if normalized_thread_id is None:
        raise ValueError("thread_id is required")
    normalized_surface = _normalized_host_surface(host_surface)
    normalized_agent = normalize_todo_claimed_by(agent_id)
    if not normalized_agent:
        raise ValueError("agent_id must be a public-safe registered agent id")

    if execute:
        with exclusive_file_lock(
            registry_path,
            agent_id=normalized_agent,
            operation="bind_agent_thread",
        ):
            latest = load_registry(registry_path)
            result, latest_goal, merged = _prepare_binding(
                latest,
                goal_id=goal_id,
                host_surface=normalized_surface,
                thread_id=normalized_thread_id,
                agent_id=normalized_agent,
                execute=True,
            )
            result["registry"] = str(registry_path)
            if not result["ok"] or not result["changed"]:
                return result
            coordination = latest_goal.get("coordination")
            coordination = coordination if isinstance(coordination, dict) else {}
            coordination["thread_agent_bindings"] = merged
            latest_goal["coordination"] = coordination
            atomic_write_json(registry_path, latest, preserve_mode=True)
            result["written"] = True
            return result

    payload = load_registry(registry_path)
    result, _goal, _merged = _prepare_binding(
        payload,
        goal_id=goal_id,
        host_surface=normalized_surface,
        thread_id=normalized_thread_id,
        agent_id=normalized_agent,
        execute=False,
    )
    result["registry"] = str(registry_path)
    return result


def unbind_thread_agent_in_registry(
    *,
    registry_path: Path,
    goal_id: str,
    host_surface: str,
    thread_id: str,
    agent_id: str,
    execute: bool,
) -> dict[str, Any]:
    """Preview or atomically remove one exact thread-to-agent binding."""

    normalized_thread_id = normalize_thread_id(thread_id)
    if normalized_thread_id is None:
        raise ValueError("thread_id is required")
    normalized_surface = _normalized_host_surface(host_surface)
    normalized_agent = normalize_todo_claimed_by(agent_id)
    if not normalized_agent:
        raise ValueError("agent_id must be a public-safe registered agent id")

    if execute:
        with exclusive_file_lock(
            registry_path,
            agent_id=normalized_agent,
            operation="unbind_agent_thread",
        ):
            latest = load_registry(registry_path)
            result, latest_goal, remaining = _prepare_unbinding(
                latest,
                goal_id=goal_id,
                host_surface=normalized_surface,
                thread_id=normalized_thread_id,
                agent_id=normalized_agent,
                execute=True,
            )
            result["registry"] = str(registry_path)
            if not result["ok"] or not result["changed"]:
                return result
            coordination = latest_goal.get("coordination")
            coordination = coordination if isinstance(coordination, dict) else {}
            coordination["thread_agent_bindings"] = remaining
            latest_goal["coordination"] = coordination
            atomic_write_json(registry_path, latest, preserve_mode=True)
            result["written"] = True
            return result

    payload = load_registry(registry_path)
    result, _goal, _remaining = _prepare_unbinding(
        payload,
        goal_id=goal_id,
        host_surface=normalized_surface,
        thread_id=normalized_thread_id,
        agent_id=normalized_agent,
        execute=False,
    )
    result["registry"] = str(registry_path)
    return result


def _dsh_result(
    *,
    binding: dict[str, Any] | None = None,
    error_kind: str | None = None,
    changed: bool = False,
    application: str = "no",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": HOST_THREAD_BINDING_COMMAND_SCHEMA_VERSION,
        "ok": error_kind is None,
        "changed": changed if error_kind is None else False,
        "application": application,
    }
    if error_kind is not None:
        result["error_kind"] = error_kind
    if binding is not None:
        result["binding"] = binding
    return result


def _dsh_exception_result(
    exc: DshBindingAuthorityError | OSError | ValueError,
    *,
    execute: bool = False,
) -> dict[str, Any]:
    if isinstance(exc, DshBindingAuthorityError):
        return _dsh_result(error_kind=exc.error_kind, binding=exc.binding)
    if isinstance(exc, OSError):
        return _dsh_result(
            error_kind="authority_unhealthy" if execute else "binding_home_unavailable",
            application="unknown" if execute else "no",
        )
    return _dsh_result(error_kind="authority_corrupt")


def _require_dsh_surface(value: Any) -> str:
    if value != DSH_HOST_SURFACE:
        raise DshBindingAuthorityError("invalid_target")
    return DSH_HOST_SURFACE


def _required_thread_id(value: Any) -> str:
    if not isinstance(value, str):
        raise DshBindingAuthorityError("invalid_target")
    try:
        thread_id = normalize_thread_id(value)
    except ValueError:
        thread_id = None
    if thread_id is None or not DSH_THREAD_ID_PATTERN.fullmatch(thread_id):
        raise DshBindingAuthorityError("invalid_target")
    return thread_id


def _normalized_goal_id(value: Any) -> str:
    if not isinstance(value, str):
        raise DshBindingAuthorityError("invalid_target")
    try:
        goal_id = validate_goal_id_path_segment(value)
    except ValueError as exc:
        raise DshBindingAuthorityError("invalid_target") from exc
    if len(goal_id) > GOAL_ID_MAX_LENGTH or not DSH_GOAL_ID_PATTERN.fullmatch(
        goal_id
    ):
        raise DshBindingAuthorityError("invalid_target")
    return goal_id


def _normalized_agent_id(value: Any) -> str:
    if not isinstance(value, str):
        raise DshBindingAuthorityError("invalid_target")
    agent_id = value
    if not DSH_AGENT_ID_PATTERN.fullmatch(agent_id):
        raise DshBindingAuthorityError("invalid_target")
    return agent_id


def _revision(value: Any, *, minimum: int = 0) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > JAVASCRIPT_SAFE_INTEGER_MAX
    ):
        raise DshBindingAuthorityError("invalid_target")
    return value


def _strict_target(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"goal_id", "agent_id"}:
        raise DshBindingAuthorityError("authority_corrupt")
    try:
        goal_id = _normalized_goal_id(value.get("goal_id"))
        agent_id = _normalized_agent_id(value.get("agent_id"))
    except DshBindingAuthorityError as exc:
        raise DshBindingAuthorityError("authority_corrupt") from exc
    if value.get("goal_id") != goal_id or value.get("agent_id") != agent_id:
        raise DshBindingAuthorityError("authority_corrupt")
    return {"goal_id": goal_id, "agent_id": agent_id}


def _strict_dsh_binding_row(
    value: Any,
    *,
    map_key: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DshBindingAuthorityError("authority_corrupt")
    state = value.get("state")
    expected_keys = {
        "schema_version",
        "host_surface",
        "thread_id",
        "revision",
        "state",
    }
    if state == "bound":
        expected_keys.add("target")
    elif state != "unbound":
        raise DshBindingAuthorityError("authority_corrupt")
    if set(value) != expected_keys:
        raise DshBindingAuthorityError("authority_corrupt")
    if value.get("schema_version") != HOST_THREAD_BINDING_SCHEMA_VERSION:
        raise DshBindingAuthorityError("authority_corrupt")
    if value.get("host_surface") != DSH_HOST_SURFACE:
        raise DshBindingAuthorityError("authority_corrupt")
    try:
        thread_id = _required_thread_id(value.get("thread_id"))
        _revision(value.get("revision"), minimum=1)
        if state == "bound":
            _strict_target(value.get("target"))
    except DshBindingAuthorityError as exc:
        raise DshBindingAuthorityError("authority_corrupt") from exc
    if thread_id != value.get("thread_id") or thread_id != map_key:
        raise DshBindingAuthorityError("authority_corrupt")
    return value


def strict_dsh_host_thread_bindings(
    payload: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Parse the complete DSH collection or reject the whole authority."""

    if DSH_BINDING_COLLECTION_KEY not in payload:
        raise DshBindingAuthorityError("binding_home_uninitialized")
    collection = payload.get(DSH_BINDING_COLLECTION_KEY)
    if not isinstance(collection, dict) or set(collection) != {
        "schema_version",
        "records",
    }:
        raise DshBindingAuthorityError("authority_corrupt")
    if collection.get("schema_version") != DSH_BINDING_COLLECTION_SCHEMA_VERSION:
        raise DshBindingAuthorityError("authority_corrupt")
    raw_records = collection.get("records")
    if not isinstance(raw_records, dict):
        raise DshBindingAuthorityError("authority_corrupt")

    records: dict[str, dict[str, Any]] = {}
    for raw_key, raw_row in raw_records.items():
        if not isinstance(raw_key, str):
            raise DshBindingAuthorityError("authority_corrupt")
        try:
            key = _required_thread_id(raw_key)
        except DshBindingAuthorityError as exc:
            raise DshBindingAuthorityError("authority_corrupt") from exc
        if key != raw_key:
            raise DshBindingAuthorityError("authority_corrupt")
        records[key] = _strict_dsh_binding_row(raw_row, map_key=key)
    return records


def _require_global_registry_payload(payload: Any) -> dict[str, Any]:
    schema_version = (
        payload.get("schema_version") if isinstance(payload, dict) else None
    )
    if (
        not isinstance(payload, dict)
        or not isinstance(schema_version, str)
        or not schema_version.strip()
        or not isinstance(payload.get("goals"), list)
    ):
        raise DshBindingAuthorityError("authority_corrupt")
    return payload


def _exact_goal(payload: dict[str, Any], goal_id: str) -> dict[str, Any]:
    matches = [
        item
        for item in payload.get("goals", [])
        if isinstance(item, dict) and str(item.get("id") or "") == goal_id
    ]
    if len(matches) != 1:
        raise DshBindingAuthorityError("authority_unhealthy")
    return matches[0]


def _source_registry_path(
    global_goal: dict[str, Any],
    *,
    global_path: Path,
) -> Path:
    source = str(global_goal.get("source_registry") or "").strip()
    repo = str(global_goal.get("repo") or "").strip()
    if not source or not repo:
        raise DshBindingAuthorityError("authority_unhealthy")
    repo_path = Path(repo).expanduser()
    if not repo_path.is_absolute():
        repo_path = global_path.parent / repo_path
    source_path = Path(source).expanduser()
    if not source_path.is_absolute():
        source_path = repo_path / source_path
    try:
        source_path = source_path.resolve()
        repo_path = repo_path.resolve()
        source_path.relative_to(repo_path)
    except (OSError, ValueError) as exc:
        raise DshBindingAuthorityError("authority_unhealthy") from exc
    if source_path == global_path.expanduser().resolve():
        raise DshBindingAuthorityError("authority_unhealthy")
    return source_path


def _goal_membership(goal: dict[str, Any]) -> list[str]:
    coordination = goal.get("coordination")
    if not isinstance(coordination, dict):
        raise DshBindingAuthorityError("authority_unhealthy")
    raw_agents = coordination.get("registered_agents")
    agents = normalize_registered_agents(raw_agents)
    if not isinstance(raw_agents, list) or raw_agents != agents:
        raise DshBindingAuthorityError("authority_unhealthy")
    return agents


def _source_membership(source_path: Path, goal_id: str) -> list[str]:
    try:
        payload = _require_global_registry_payload(load_registry(source_path))
        return _goal_membership(_exact_goal(payload, goal_id))
    except (OSError, ValueError) as exc:
        raise DshBindingAuthorityError("authority_unhealthy") from exc


def _target_context(
    payload: dict[str, Any],
    *,
    global_path: Path,
    target: dict[str, str],
) -> None:
    global_goal = _exact_goal(payload, target["goal_id"])
    source_path = _source_registry_path(global_goal, global_path=global_path)
    source_agents = _source_membership(source_path, target["goal_id"])
    if (
        source_agents != _goal_membership(global_goal)
        or target["agent_id"] not in source_agents
    ):
        raise DshBindingAuthorityError("authority_unhealthy")


def _read_global_registry(global_path: Path) -> dict[str, Any]:
    if not global_path.exists():
        raise DshBindingAuthorityError("binding_home_unavailable")
    try:
        return _require_global_registry_payload(load_registry(global_path))
    except OSError as exc:
        raise DshBindingAuthorityError("binding_home_unavailable") from exc
    except ValueError as exc:
        raise DshBindingAuthorityError("authority_corrupt") from exc


def resolve_dsh_thread_agent_binding(
    *,
    global_path: Path,
    host_surface: str,
    thread_id: str,
) -> dict[str, Any]:
    """Resolve one exact DSH Host key and validate its Goal-Agent target."""

    try:
        _require_dsh_surface(host_surface)
        normalized_thread_id = _required_thread_id(thread_id)
        payload = _read_global_registry(global_path)
        records = strict_dsh_host_thread_bindings(payload)
        binding = records.get(normalized_thread_id)
        if binding is None:
            raise DshBindingAuthorityError("binding_not_found")
        if binding["state"] == "bound":
            try:
                _target_context(
                    payload,
                    global_path=global_path,
                    target=binding["target"],
                )
            except DshBindingAuthorityError as exc:
                raise DshBindingAuthorityError(
                    "authority_unhealthy",
                    binding=binding,
                ) from exc
        return _dsh_result(binding=binding)
    except (DshBindingAuthorityError, OSError, ValueError) as exc:
        return _dsh_exception_result(exc)


def _binding_row(
    thread_id: str,
    revision: int,
    target: dict[str, str] | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "schema_version": HOST_THREAD_BINDING_SCHEMA_VERSION,
        "host_surface": DSH_HOST_SURFACE,
        "thread_id": thread_id,
        "revision": revision,
        "state": "bound" if target is not None else "unbound",
    }
    if target is not None:
        row["target"] = target
    return row


def _write_dsh_records(
    payload: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    updated = dict(payload)
    updated[DSH_BINDING_COLLECTION_KEY] = {
        "schema_version": DSH_BINDING_COLLECTION_SCHEMA_VERSION,
        "records": records,
    }
    return updated


def _binding_reduction(
    payload: dict[str, Any],
    *,
    thread_id: str,
    expected_revision: int,
    target: dict[str, str] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    _require_global_registry_payload(payload)
    try:
        records = strict_dsh_host_thread_bindings(payload)
    except DshBindingAuthorityError as exc:
        if not (
            target is not None
            and expected_revision == 0
            and exc.error_kind == "binding_home_uninitialized"
        ):
            raise
        records = {}
    current = records.get(thread_id)
    if current is None and target is None:
        raise DshBindingAuthorityError("binding_not_found")
    current_revision = current["revision"] if current else 0
    if expected_revision != current_revision:
        raise DshBindingAuthorityError("revision_conflict", binding=current)
    matches = current is not None and (
        (target is None and current["state"] == "unbound")
        or (
            target is not None
            and current["state"] == "bound"
            and current["target"] == target
        )
    )
    if matches:
        return payload, _dsh_result(binding=current)
    if current_revision >= JAVASCRIPT_SAFE_INTEGER_MAX:
        raise DshBindingAuthorityError("authority_exhausted", binding=current)
    binding = _binding_row(thread_id, current_revision + 1, target)
    return (
        _write_dsh_records(payload, {**records, thread_id: binding}),
        _dsh_result(binding=binding, changed=True, application="yes"),
    )


def _run_global_binding_reduction(
    *,
    global_path: Path,
    operation: str,
    initial: dict[str, Any],
    reducer: Any,
    execute: bool,
) -> dict[str, Any]:
    if not execute:
        receipt = reducer(initial).receipt
        receipt["application"] = "no"
        return receipt
    from .global_registry import mutate_global_registry

    mutation = mutate_global_registry(global_path, operation, reducer)
    receipt = mutation["receipt"]
    if receipt["changed"] and not mutation["wrote"]:
        return _dsh_result(error_kind="authority_unhealthy", application="unknown")
    return receipt


def bind_dsh_thread_agent_in_global_registry(
    *,
    global_path: Path,
    host_surface: str,
    thread_id: str,
    goal_id: str,
    agent_id: str,
    expected_revision: int,
    execute: bool,
) -> dict[str, Any]:
    """CAS-bind or atomically switch one DSH Host key."""

    try:
        _require_dsh_surface(host_surface)
        normalized_thread_id = _required_thread_id(thread_id)
        normalized_target = {
            "goal_id": _normalized_goal_id(goal_id),
            "agent_id": _normalized_agent_id(agent_id),
        }
        normalized_revision = _revision(expected_revision)
        initial = _read_global_registry(global_path)
        global_goal = _exact_goal(initial, normalized_target["goal_id"])
        source_path = _source_registry_path(global_goal, global_path=global_path)

        from .global_registry import (
            GlobalRegistryReduction,
            route_snapshot,
        )

        initial_route = route_snapshot(global_goal)
        with exclusive_file_lock(
            source_path,
            agent_id=normalized_target["agent_id"],
            operation="bind_dsh_agent_thread",
        ):
            source_agents = _source_membership(
                source_path,
                normalized_target["goal_id"],
            )
            if normalized_target["agent_id"] not in source_agents:
                raise DshBindingAuthorityError("invalid_target")

            def reduce(current: dict[str, Any]) -> GlobalRegistryReduction:
                _require_global_registry_payload(current)
                current_goal = _exact_goal(current, normalized_target["goal_id"])
                if route_snapshot(current_goal) != initial_route:
                    raise DshBindingAuthorityError("authority_unhealthy")
                current_source = _source_registry_path(
                    current_goal,
                    global_path=global_path,
                )
                if current_source != source_path:
                    raise DshBindingAuthorityError("authority_unhealthy")
                if _goal_membership(current_goal) != source_agents:
                    raise DshBindingAuthorityError("authority_unhealthy")
                updated, receipt = _binding_reduction(
                    current,
                    thread_id=normalized_thread_id,
                    expected_revision=normalized_revision,
                    target=normalized_target,
                )
                return GlobalRegistryReduction(payload=updated, receipt=receipt)

            return _run_global_binding_reduction(
                global_path=global_path,
                operation="bind_dsh_agent_thread",
                initial=initial,
                reducer=reduce,
                execute=execute,
            )
    except (DshBindingAuthorityError, OSError, ValueError) as exc:
        return _dsh_exception_result(exc, execute=execute)


def unbind_dsh_thread_agent_in_global_registry(
    *,
    global_path: Path,
    host_surface: str,
    thread_id: str,
    expected_revision: int,
    execute: bool,
) -> dict[str, Any]:
    """CAS-unbind one exact DSH key, preserving a permanent tombstone."""

    try:
        _require_dsh_surface(host_surface)
        normalized_thread_id = _required_thread_id(thread_id)
        normalized_revision = _revision(expected_revision)
        initial = _read_global_registry(global_path)

        from .global_registry import GlobalRegistryReduction

        def reduce(current: dict[str, Any]) -> GlobalRegistryReduction:
            updated, receipt = _binding_reduction(
                current,
                thread_id=normalized_thread_id,
                expected_revision=normalized_revision,
                target=None,
            )
            return GlobalRegistryReduction(payload=updated, receipt=receipt)

        return _run_global_binding_reduction(
            global_path=global_path,
            operation="unbind_dsh_agent_thread",
            initial=initial,
            reducer=reduce,
            execute=execute,
        )
    except (DshBindingAuthorityError, OSError, ValueError) as exc:
        return _dsh_exception_result(exc, execute=execute)


def live_dsh_binding_references(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return bounded live references, rejecting a malformed collection."""

    if DSH_BINDING_COLLECTION_KEY not in payload:
        return []
    records = strict_dsh_host_thread_bindings(payload)
    return [
        {
            "thread_id": row["thread_id"],
            "revision": row["revision"],
            "goal_id": row["target"]["goal_id"],
            "agent_id": row["target"]["agent_id"],
        }
        for row in records.values()
        if row["state"] == "bound"
    ]
