from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PUBLIC_GIT_HISTORY_WINDOW_CONFIG_SCHEMA_VERSION = (
    "public_git_history_window_config_v0"
)
PUBLIC_GIT_HISTORY_WINDOW_POLICY_SCHEMA_VERSION = (
    "public_git_history_window_policy_v0"
)

_CONFIG_FIELDS = {
    "schema_version",
    "timezone",
    "blocked_windows",
    "public_repositories_only",
    "collaboration_writes_allowed",
}
_WINDOW_FIELDS = {"window_id", "start", "end"}
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _strict_mapping(
    value: object,
    *,
    label: str,
    allowed: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    unknown = sorted(str(key) for key in value if str(key) not in allowed)
    if unknown:
        raise ValueError(f"{label} has unsupported fields: {', '.join(unknown)}")
    return value


def _time(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _TIME_RE.fullmatch(text):
        raise ValueError(f"{label} must use 24-hour HH:MM")
    return text


def normalize_public_git_history_window_config(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    raw = _strict_mapping(payload, label="config", allowed=_CONFIG_FIELDS)
    if raw.get("schema_version") != PUBLIC_GIT_HISTORY_WINDOW_CONFIG_SCHEMA_VERSION:
        raise ValueError(
            "config schema_version must be "
            f"{PUBLIC_GIT_HISTORY_WINDOW_CONFIG_SCHEMA_VERSION}"
        )
    timezone = str(raw.get("timezone") or "").strip()
    if not timezone:
        raise ValueError("config timezone must be present")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("config timezone is unavailable") from exc

    windows_value = raw.get("blocked_windows")
    if not isinstance(windows_value, list) or not windows_value:
        raise ValueError("config blocked_windows must be a non-empty list")
    windows: list[dict[str, str]] = []
    window_ids: set[str] = set()
    for index, value in enumerate(windows_value):
        window = _strict_mapping(
            value,
            label=f"blocked_windows[{index}]",
            allowed=_WINDOW_FIELDS,
        )
        window_id = str(window.get("window_id") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", window_id):
            raise ValueError(
                f"blocked_windows[{index}].window_id must be a public-safe token"
            )
        if window_id in window_ids:
            raise ValueError(f"duplicate blocked window id: {window_id}")
        start = _time(window.get("start"), label=f"blocked_windows[{index}].start")
        end = _time(window.get("end"), label=f"blocked_windows[{index}].end")
        if start == end:
            raise ValueError("blocked window start and end must differ")
        window_ids.add(window_id)
        windows.append({"window_id": window_id, "start": start, "end": end})

    public_only = raw.get("public_repositories_only", True)
    collaboration_allowed = raw.get("collaboration_writes_allowed", True)
    if not isinstance(public_only, bool):
        raise TypeError("config public_repositories_only must be a boolean")
    if collaboration_allowed is not True:
        raise ValueError(
            "config collaboration_writes_allowed must be true; collaboration writes "
            "are outside this capability"
        )
    return {
        "schema_version": PUBLIC_GIT_HISTORY_WINDOW_POLICY_SCHEMA_VERSION,
        "enabled": True,
        "timezone": timezone,
        "blocked_windows": windows,
        "public_repositories_only": public_only,
        "collaboration_writes_allowed": True,
    }


def public_git_history_window_goal_policy(goal: Mapping[str, Any]) -> dict[str, Any]:
    control_plane_value = goal.get("control_plane")
    control_plane: Mapping[str, Any] = (
        control_plane_value if isinstance(control_plane_value, Mapping) else {}
    )
    raw_value = control_plane.get("public_git_history_window")
    raw: Mapping[str, Any] = raw_value if isinstance(raw_value, Mapping) else {}
    return {
        "schema_version": PUBLIC_GIT_HISTORY_WINDOW_POLICY_SCHEMA_VERSION,
        "enabled": raw.get("enabled") is True,
        "config_path": str(raw.get("config_path") or "").strip() or None,
    }


def public_git_history_window_goal_policy_summary(
    goal: Mapping[str, Any],
) -> dict[str, Any]:
    policy = public_git_history_window_goal_policy(goal)
    return {
        "enabled": policy["enabled"],
        "config_pointer_registered": bool(policy["config_path"]),
    }


def _require_ignored_untracked(project: Path, relative: Path) -> None:
    tracked = subprocess.run(
        ["git", "-C", str(project), "ls-files", "--error-unmatch", "--", str(relative)],
        capture_output=True,
        check=False,
    )
    ignored = subprocess.run(
        ["git", "-C", str(project), "check-ignore", "--quiet", "--", str(relative)],
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0 or ignored.returncode != 0:
        raise ValueError(
            "public Git history window config must be ignored and untracked"
        )


def load_public_git_history_window_config(
    *,
    project: Path,
    config_path: str,
) -> dict[str, Any]:
    root = project.expanduser().resolve()
    if not root.is_dir():
        raise ValueError("goal project directory does not exist")
    path = (root / config_path).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("public Git history window config escapes the goal project") from exc
    if relative.parts[:2] != (".loopx", "config") or path.suffix != ".json":
        raise ValueError(
            "public Git history window config must be under .loopx/config/"
        )
    _require_ignored_untracked(root, relative)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("public Git history window config is unavailable") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("public Git history window config must be an object")
    return normalize_public_git_history_window_config(payload)
