"""Canonical owner-confirmed deletion for stopped Goals."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from ..projects.registry_codec import (
    ProjectRegistryTransaction,
    project_registry_transaction,
)
from ...configuration_transaction import configuration_payload_revision
from ...file_lock import (
    EFFECT_MUTATION_LOCK_SUFFIX,
    exclusive_cross_runtime_file_lock,
    exclusive_file_lock,
    lock_holder_path,
    lock_incident_path,
)
from ...history import load_registry
from ...registry import atomic_write_json, read_json
from ...registry_writability import probe_registry_write_path
from ..runtime.time import now_local_iso
from .activation import GoalActivationState, goal_activation_state
from .activation_service import (
    GoalActivationAuthorityRouteMode,
    _goal_activation_source_identity,
    _goal_or_none,
    _same_path,
    _source_and_target,
    _source_status,
)


GOAL_DELETION_SCHEMA_VERSION = "loopx_goal_deletion_v1"
GOAL_DELETION_SOURCE_BASIS_SCHEMA_VERSION = "loopx_goal_deletion_source_basis_v1"
GOAL_DELETION_STATE_FINGERPRINT_SCHEMA_VERSION = (
    "loopx_goal_deletion_state_fingerprint_v1"
)
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _require_opaque_id(value: str, *, field: str) -> str:
    """Reject any value that is not a compact opaque id; safe for path segments."""

    token = str(value or "").strip()
    if not _OPAQUE_ID.fullmatch(token):
        raise ValueError(f"{field} must be a compact opaque id")
    return token


def _registry_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registry_identity(path: Path) -> str:
    return configuration_payload_revision(
        {"registry_path": str(path.expanduser().resolve())}
    ).removeprefix("sha256:")


def _source_basis(route: dict[str, Any]) -> dict[str, str]:
    source_registry = Path(route["declared_source_registry"])
    try:
        source_content = source_registry.read_bytes()
    except OSError:
        source_content = (
            f"unavailable:{route['source_status']}:{_registry_identity(source_registry)}"
        ).encode()
    return {
        "schema_version": GOAL_DELETION_SOURCE_BASIS_SCHEMA_VERSION,
        "source_identity": _goal_activation_source_identity(source_registry),
        "source_content_sha256": hashlib.sha256(source_content).hexdigest(),
        "route_mode": str(route["route_mode"]),
    }


def _state_fingerprint(
    *,
    goal_id: str,
    source_basis: Mapping[str, str],
    target_registry: Path,
) -> str:
    return configuration_payload_revision(
        {
            "schema_version": GOAL_DELETION_STATE_FINGERPRINT_SCHEMA_VERSION,
            "goal_id": goal_id,
            "source_basis": dict(source_basis),
            "target_identity": _registry_identity(target_registry),
            "target_content_sha256": _registry_fingerprint(target_registry),
        }
    ).removeprefix("sha256:")


def _normalize_source_basis(value: Mapping[str, Any] | None) -> dict[str, str] | None:
    if value is None:
        return None
    schema_version = str(value.get("schema_version") or "")
    source_identity = str(value.get("source_identity") or "")
    source_content_sha256 = str(value.get("source_content_sha256") or "")
    route_mode = str(value.get("route_mode") or "")
    if schema_version != GOAL_DELETION_SOURCE_BASIS_SCHEMA_VERSION:
        raise ValueError("expected source basis has an unsupported schema version")
    if not _SHA256.fullmatch(source_identity):
        raise ValueError("expected source identity must be a SHA-256 digest")
    if not _SHA256.fullmatch(source_content_sha256):
        raise ValueError("expected source content digest must be a SHA-256 digest")
    if route_mode not in {mode.value for mode in GoalActivationAuthorityRouteMode}:
        raise ValueError("expected source route mode is unsupported")
    return {
        "schema_version": schema_version,
        "source_identity": source_identity,
        "source_content_sha256": source_content_sha256,
        "route_mode": route_mode,
    }


def _mark_stale(
    payload: dict[str, Any],
    *,
    current_state_fingerprint: str,
    current_source_basis: Mapping[str, str],
) -> None:
    payload.update(
        {
            "ok": False,
            "stale": True,
            "error_kind": "goal_registry_changed",
            "error": (
                "Goal source or registry route changed after preview; "
                "regenerate the deletion preview"
            ),
            "current_state_fingerprint": current_state_fingerprint,
            "observed_state_fingerprint": current_state_fingerprint,
            "source_basis": dict(current_source_basis),
        }
    )


def _missing_state_fingerprint(*, goal_id: str, registry_path: Path) -> str:
    target_content_sha256 = (
        _registry_fingerprint(registry_path) if registry_path.is_file() else None
    )
    return configuration_payload_revision(
        {
            "schema_version": GOAL_DELETION_STATE_FINGERPRINT_SCHEMA_VERSION,
            "goal_id": goal_id,
            "deletion_state": "missing",
            "target_identity": _registry_identity(registry_path),
            "target_content_sha256": target_content_sha256,
        }
    ).removeprefix("sha256:")


def _missing_stale_payload(
    *,
    goal_id: str,
    registry_path: Path,
    execute: bool,
    expected_state_fingerprint: str | None,
) -> dict[str, Any]:
    current_fingerprint = _missing_state_fingerprint(
        goal_id=goal_id,
        registry_path=registry_path,
    )
    return {
        "ok": False,
        "schema_version": GOAL_DELETION_SCHEMA_VERSION,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": goal_id,
        "target_global_registry": str(registry_path),
        "expected_state_fingerprint": expected_state_fingerprint,
        "observed_state_fingerprint": current_fingerprint,
        "current_state_fingerprint": current_fingerprint,
        "written": False,
        "partial_write": False,
        "backup_paths": [],
        "readback": {
            "source_missing": True,
            "global_missing": True,
            "verified": False,
        },
        "stale": True,
        "error_kind": "goal_registry_changed",
        "error": "Goal disappeared after preview; regenerate the deletion preview",
    }


def _backup_path(path: Path, timestamp: str, nonce: str) -> Path:
    compact_timestamp = timestamp.replace(":", "").replace("-", "")
    return path.with_name(
        f"{path.name}.goal-delete-{compact_timestamp}-{nonce}.bak"
    )


def _create_backup(path: Path, *, timestamp: str) -> Path:
    """Create an independent snapshot without ever overwriting an old backup."""

    source_path = path.expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise ValueError(f"registry path is not a regular file: {source_path}")
    for _ in range(8):
        backup = _backup_path(source_path, timestamp, uuid.uuid4().hex)
        try:
            descriptor = os.open(
                backup,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            continue
        try:
            with source_path.open("rb") as source, os.fdopen(descriptor, "wb") as target:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            shutil.copystat(source_path, backup)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        return backup
    raise FileExistsError(f"could not allocate a unique Goal deletion backup for {source_path}")


def _remove_goal(payload: dict[str, Any], goal_id: str) -> tuple[dict[str, Any], bool]:
    goals = payload.get("goals")
    if not isinstance(goals, list):
        raise ValueError("registry goals must be a list")
    retained = [
        goal
        for goal in goals
        if not (isinstance(goal, dict) and str(goal.get("id") or "") == goal_id)
    ]
    changed = len(retained) != len(goals)
    updated = dict(payload)
    updated["goals"] = retained
    if changed:
        updated["updated_at"] = now_local_iso()
    return updated, changed


def _resolve_route(
    goal_id: str,
    registry_path: Path,
    *,
    require_stopped: bool = True,
) -> dict[str, Any]:
    route = _source_and_target(
        registry_path=registry_path,
        goal_id=goal_id,
        target_state=GoalActivationState.STOPPED,
        runtime_root_override=None,
    )
    source_available = route.mode is not GoalActivationAuthorityRouteMode.ORPHANED_GLOBAL_STOP_FALLBACK
    source_payload = load_registry(route.source_registry) if source_available else None
    target_payload = read_json(route.target_registry)
    source_goal = _goal_or_none(source_payload, goal_id) if source_payload else None
    target_goal = _goal_or_none(target_payload, goal_id)
    goal = source_goal or target_goal
    if goal is None:
        raise ValueError(f"goal id not found in registry: {goal_id}")
    if require_stopped and goal_activation_state(goal) is not GoalActivationState.STOPPED:
        raise ValueError("stop the Goal before deleting it")
    if target_goal is None:
        raise ValueError("global registry does not contain the Goal projection")
    declared_source_registry = route.source_registry
    if (
        route.mode is GoalActivationAuthorityRouteMode.ORPHANED_GLOBAL_STOP_FALLBACK
    ):
        source_ref = str(target_goal.get("source_registry") or "").strip()
        if source_ref:
            declared_source_registry = Path(source_ref).expanduser().resolve()
    return {
        "source_registry": route.source_registry,
        "declared_source_registry": declared_source_registry,
        "target_registry": route.target_registry,
        "source_available": source_available,
        "source_status": route.source_status.value,
        "source_goal": source_goal,
        "target_goal": target_goal,
        "same_registry": _same_path(route.source_registry, route.target_registry),
        "route_mode": route.mode.value,
    }


def _check_writability(paths: list[Path]) -> dict[str, Any] | None:
    writability = [
        probe_registry_write_path(path, create_parent=False) for path in paths
    ]
    return next((item for item in writability if not item.get("ok")), None)


def _orphan_source_lock_error(path: Path) -> str | None:
    parent = path.parent
    if parent.exists() and (not parent.is_dir() or parent.is_symlink()):
        return "Goal source registry parent is unavailable for safe locking"
    kernel_lock = path.with_name(f"{path.name}.lock")
    lock_artifacts = {
        kernel_lock,
        lock_holder_path(path),
        lock_incident_path(path),
        Path(f"{path}{EFFECT_MUTATION_LOCK_SUFFIX}"),
    }
    if any(
        artifact.is_symlink()
        or (artifact.exists() and not artifact.is_file())
        for artifact in lock_artifacts
    ):
        return "Goal source registry lock path is unsafe"
    return None


def _route_matches_locked_paths(
    route: Mapping[str, Any],
    *,
    source_registry: Path,
    declared_source_registry: Path,
    target_registry: Path,
    source_available: bool,
    same_registry: bool,
) -> bool:
    return (
        _same_path(Path(route["source_registry"]), source_registry)
        and _same_path(
            Path(route["declared_source_registry"]),
            declared_source_registry,
        )
        and _same_path(Path(route["target_registry"]), target_registry)
        and bool(route["source_available"]) is source_available
        and bool(route["same_registry"]) is same_registry
    )


def _validated_locked_route_snapshot(
    *,
    requested_registry: Path,
    source_registry: Path,
    declared_source_registry: Path,
    target_registry: Path,
    source_available: bool,
    same_registry: bool,
    goal_id: str,
    expected_state_fingerprint: str | None,
    expected_source_basis: Mapping[str, str] | None,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str], str] | None:
    try:
        locked_route, current_source_basis, current_fingerprint = _route_snapshot(
            goal_id=goal_id,
            requested_registry=requested_registry,
        )
    except ValueError as exc:
        if str(exc) != f"goal id not found in registry: {goal_id}":
            raise
        payload.update(
            _missing_stale_payload(
                goal_id=goal_id,
                registry_path=requested_registry,
                execute=True,
                expected_state_fingerprint=expected_state_fingerprint,
            )
        )
        return None
    route_changed = not _route_matches_locked_paths(
        locked_route,
        source_registry=source_registry,
        declared_source_registry=declared_source_registry,
        target_registry=target_registry,
        source_available=source_available,
        same_registry=same_registry,
    )
    if route_changed or (
        expected_state_fingerprint is not None
        and current_fingerprint != expected_state_fingerprint
    ) or (
        expected_source_basis is not None
        and current_source_basis != expected_source_basis
    ):
        _mark_stale(
            payload,
            current_state_fingerprint=current_fingerprint,
            current_source_basis=current_source_basis,
        )
        return None
    return locked_route, current_source_basis, current_fingerprint


def _route_snapshot(
    *,
    goal_id: str,
    requested_registry: Path,
) -> tuple[dict[str, Any], dict[str, str], str]:
    route = _resolve_route(
        goal_id,
        requested_registry,
        require_stopped=False,
    )
    source_basis = _source_basis(route)
    return (
        route,
        source_basis,
        _state_fingerprint(
            goal_id=goal_id,
            source_basis=source_basis,
            target_registry=Path(route["target_registry"]),
        ),
    )


def _load_locked_payloads(
    *,
    requested_registry: Path,
    source_registry: Path,
    declared_source_registry: Path,
    target_registry: Path,
    source_available: bool,
    same_registry: bool,
    goal_id: str,
    expected_state_fingerprint: str | None,
    expected_source_basis: Mapping[str, str] | None,
    payload: dict[str, Any],
) -> tuple[dict[Path, dict[str, Any]], dict[str, str], str] | None:
    current_source = (
        read_json(source_registry)
        if source_available and same_registry
        else load_registry(source_registry)
        if source_available
        else None
    )
    current_target = read_json(target_registry)
    snapshot = _validated_locked_route_snapshot(
        requested_registry=requested_registry,
        source_registry=source_registry,
        declared_source_registry=declared_source_registry,
        target_registry=target_registry,
        source_available=source_available,
        same_registry=same_registry,
        goal_id=goal_id,
        expected_state_fingerprint=expected_state_fingerprint,
        expected_source_basis=expected_source_basis,
        payload=payload,
    )
    if snapshot is None:
        return None
    _, current_source_basis, current_fingerprint = snapshot

    source_goal = _goal_or_none(current_source, goal_id) if current_source else None
    target_goal = _goal_or_none(current_target, goal_id)
    locked_goal = source_goal or target_goal
    if locked_goal is None or target_goal is None:
        raise ValueError("Goal disappeared before deletion; refresh and retry")
    if goal_activation_state(locked_goal) is not GoalActivationState.STOPPED:
        raise ValueError("Goal activation changed; stop the Goal before deleting it")
    current_payloads = {target_registry: current_target}
    if source_available and not same_registry:
        if current_source is None or source_goal is None:
            raise ValueError("Goal source registry changed; refresh and retry")
        current_payloads[source_registry] = current_source
    return current_payloads, current_source_basis, current_fingerprint


def _updated_payloads(
    current_payloads: dict[Path, dict[str, Any]], goal_id: str
) -> dict[Path, dict[str, Any]]:
    updated_payloads: dict[Path, dict[str, Any]] = {}
    for path, current in current_payloads.items():
        updated, changed = _remove_goal(current, goal_id)
        if not changed:
            raise ValueError("Goal disappeared before deletion; refresh and retry")
        updated_payloads[path] = updated
    return updated_payloads


def _write_deletion(
    *,
    current_payloads: dict[Path, dict[str, Any]],
    updated_payloads: dict[Path, dict[str, Any]],
    source_registry: Path,
    declared_source_registry: Path,
    target_registry: Path,
    source_available: bool,
    locked_source_basis: Mapping[str, str],
    goal_id: str,
    payload: dict[str, Any],
    source_transaction: ProjectRegistryTransaction | None,
) -> None:
    written_paths: list[Path] = []
    try:
        timestamp = now_local_iso()
        for path in current_payloads:
            backup = _create_backup(path, timestamp=timestamp)
            payload["backup_paths"].append(str(backup))
        for path in sorted(updated_payloads, key=lambda item: str(item)):
            _write_locked_registry(
                path=path,
                updated=updated_payloads[path],
                source_registry=source_registry,
                source_transaction=source_transaction,
            )
            written_paths.append(path)
        source_missing = (
            _goal_or_none(load_registry(source_registry), goal_id) is None
            if source_available
            else _source_basis(
                {
                    "declared_source_registry": declared_source_registry,
                    "source_status": _source_status(
                        declared_source_registry,
                        goal_id=goal_id,
                    ).value,
                    "route_mode": locked_source_basis["route_mode"],
                }
            )
            == locked_source_basis
        )
        target_after = read_json(target_registry)
        global_missing = _goal_or_none(target_after, goal_id) is None
        if not source_missing or not global_missing:
            raise ValueError("Goal deletion readback did not verify")
        payload["readback"] = {
            "source_missing": source_missing,
            "global_missing": global_missing,
            "verified": source_missing and global_missing,
        }
        payload["written"] = bool(written_paths)
        payload["ok"] = True
        payload["partial_write"] = False
    except Exception:
        for path in reversed(written_paths):
            _restore_locked_registry(
                path=path,
                current=current_payloads[path],
                source_registry=source_registry,
                source_transaction=source_transaction,
            )
        raise


def _write_locked_registry(
    *,
    path: Path,
    updated: dict[str, Any],
    source_registry: Path,
    source_transaction: ProjectRegistryTransaction | None,
) -> None:
    if source_transaction is not None and _same_path(path, source_registry):
        source_transaction.commit(updated)
        return
    atomic_write_json(path, updated, preserve_mode=True)


def _restore_locked_registry(
    *,
    path: Path,
    current: dict[str, Any],
    source_registry: Path,
    source_transaction: ProjectRegistryTransaction | None,
) -> None:
    if source_transaction is not None and _same_path(path, source_registry):
        source_transaction.restore()
        return
    atomic_write_json(path, current, preserve_mode=True)


def _execute_deletion(
    *,
    requested_registry: Path,
    source_registry: Path,
    declared_source_registry: Path,
    target_registry: Path,
    source_available: bool,
    same_registry: bool,
    goal_id: str,
    expected_state_fingerprint: str | None,
    expected_source_basis: Mapping[str, str] | None,
    payload: dict[str, Any],
) -> None:
    """Apply deletion and read it back while registry locks are held."""

    locked_source_registry = (
        source_registry if source_available else declared_source_registry
    )
    with ExitStack() as stack:
        source_transaction = None
        if not _same_path(locked_source_registry, target_registry):
            if source_available and not same_registry:
                source_transaction = stack.enter_context(
                    project_registry_transaction(
                        locked_source_registry,
                        operation="delete_stopped_goal",
                    )
                )
            else:
                stack.enter_context(
                    exclusive_cross_runtime_file_lock(
                        locked_source_registry,
                        operation="delete_stopped_goal",
                    )
                )
        stack.enter_context(
            exclusive_file_lock(target_registry, operation="delete_stopped_goal")
        )
        locked_state = _load_locked_payloads(
            requested_registry=requested_registry,
            source_registry=source_registry,
            declared_source_registry=declared_source_registry,
            target_registry=target_registry,
            source_available=source_available,
            same_registry=same_registry,
            goal_id=goal_id,
            expected_state_fingerprint=expected_state_fingerprint,
            expected_source_basis=expected_source_basis,
            payload=payload,
        )
        if locked_state is None:
            return
        current_payloads, locked_source_basis, locked_state_fingerprint = locked_state
        updated_payloads = _updated_payloads(current_payloads, goal_id)
        if (
            _validated_locked_route_snapshot(
                requested_registry=requested_registry,
                source_registry=source_registry,
                declared_source_registry=declared_source_registry,
                target_registry=target_registry,
                source_available=source_available,
                same_registry=same_registry,
                goal_id=goal_id,
                expected_state_fingerprint=locked_state_fingerprint,
                expected_source_basis=locked_source_basis,
                payload=payload,
            )
            is None
        ):
            return
        _write_deletion(
            current_payloads=current_payloads,
            updated_payloads=updated_payloads,
            source_registry=source_registry,
            declared_source_registry=declared_source_registry,
            target_registry=target_registry,
            source_available=source_available,
            locked_source_basis=locked_source_basis,
            goal_id=goal_id,
            payload=payload,
            source_transaction=source_transaction,
        )


def delete_stopped_goal(
    *,
    registry_path: Path,
    goal_id: str,
    execute: bool = False,
    expected_state_fingerprint: str | None = None,
    expected_source_basis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview or permanently remove one stopped Goal from its registries.

    Goal data such as state files and project files is intentionally retained;
    deletion removes only the registry entries that make the Goal visible to
    the LoopX control plane. Expected state and source values are checked again
    while both registry locks are held.
    """

    normalized_goal_id = _require_opaque_id(goal_id, field="goal_id")
    requested_registry = Path(registry_path)
    normalized_fingerprint = str(expected_state_fingerprint or "").strip() or None
    if normalized_fingerprint is not None and not _SHA256.fullmatch(
        normalized_fingerprint
    ):
        raise ValueError("expected state fingerprint must be a SHA-256 digest")
    normalized_source_basis = _normalize_source_basis(expected_source_basis)
    try:
        route = _resolve_route(
            normalized_goal_id,
            requested_registry,
            require_stopped=False,
        )
    except ValueError as exc:
        if (
            normalized_fingerprint is None
            or str(exc) != f"goal id not found in registry: {normalized_goal_id}"
        ):
            raise
        return _missing_stale_payload(
            goal_id=normalized_goal_id,
            registry_path=requested_registry,
            execute=execute,
            expected_state_fingerprint=normalized_fingerprint,
        )
    observed_source_basis = _source_basis(route)
    observed_fingerprint = _state_fingerprint(
        goal_id=normalized_goal_id,
        source_basis=observed_source_basis,
        target_registry=route["target_registry"],
    )

    payload: dict[str, Any] = {
        "ok": True,
        "schema_version": GOAL_DELETION_SCHEMA_VERSION,
        "dry_run": not execute,
        "execute": execute,
        "goal_id": normalized_goal_id,
        "source_registry": str(route["source_registry"]),
        "target_global_registry": str(route["target_registry"]),
        "source_registry_present": route["source_goal"] is not None,
        "global_registry_present": route["target_goal"] is not None,
        "source_basis": observed_source_basis,
        "authority_route_mode": route["route_mode"],
        "expected_state_fingerprint": normalized_fingerprint,
        "observed_state_fingerprint": observed_fingerprint,
        "written": False,
        "partial_write": False,
        "backup_paths": [],
        "readback": {
            "source_missing": route["source_goal"] is None,
            "global_missing": False,
            "verified": False,
        },
    }
    if (
        normalized_fingerprint is not None
        and observed_fingerprint != normalized_fingerprint
    ) or (
        normalized_source_basis is not None
        and observed_source_basis != normalized_source_basis
    ):
        _mark_stale(
            payload,
            current_state_fingerprint=observed_fingerprint,
            current_source_basis=observed_source_basis,
        )
        return payload
    goal = route["source_goal"] or route["target_goal"]
    if goal_activation_state(goal) is not GoalActivationState.STOPPED:
        raise ValueError("stop the Goal before deleting it")
    if not execute:
        return payload

    if not route["source_available"]:
        lock_error = _orphan_source_lock_error(route["declared_source_registry"])
        if lock_error is not None:
            payload.update(
                {
                    "ok": False,
                    "error_kind": "goal_source_lock_unavailable",
                    "error": lock_error,
                    "recommended_action": (
                        "Repair the Goal source registry route before deleting "
                        "this Goal."
                    ),
                }
            )
            return payload

    paths = [route["target_registry"]]
    if not route["same_registry"]:
        paths.append(route["source_registry"])
    writability = _check_writability(paths)
    if writability is not None:
        payload.update(
            {
                "ok": False,
                "error_kind": "goal_registry_write_denied",
                "error": str(writability.get("error") or "Goal registry is not writable"),
                "recommended_action": writability.get("recommended_action"),
            }
        )
        return payload

    _execute_deletion(
        requested_registry=requested_registry,
        source_registry=route["source_registry"],
        declared_source_registry=route["declared_source_registry"],
        target_registry=route["target_registry"],
        source_available=route["source_available"],
        same_registry=route["same_registry"],
        goal_id=normalized_goal_id,
        expected_state_fingerprint=normalized_fingerprint,
        expected_source_basis=normalized_source_basis,
        payload=payload,
    )
    return payload
