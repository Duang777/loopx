"""CLI-only registry selection compatibility rules."""

from __future__ import annotations

from pathlib import Path

from loopx.paths import DEFAULT_RUNTIME_ROOT, default_registry_path, global_registry_path


def default_cli_registry() -> Path:
    return default_registry_path()


def resolve_cli_registry(
    registry_value: str,
    *,
    runtime_root_value: str | None,
    explicitly_supplied: bool,
) -> Path:
    registry_path = Path(registry_value).expanduser()
    if explicitly_supplied or registry_path.exists():
        return registry_path
    runtime_root = (
        Path(runtime_root_value).expanduser()
        if runtime_root_value
        else DEFAULT_RUNTIME_ROOT
    )
    fallback = global_registry_path(runtime_root)
    return fallback if fallback.exists() else registry_path
