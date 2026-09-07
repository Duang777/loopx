"""Private local store for provider-first Todo validation declarations."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ...registry import atomic_write_json, read_json
from .completion_validation_projection import (
    completion_validation_declaration,
    completion_validation_declaration_sha256,
)


DECLARATION_SCHEMA_VERSION = "loopx_todo_completion_validation_declaration_v0"
_PUBLIC_ID = re.compile(r"[A-Za-z0-9_.:-]+")


def _require_public_id(value: str, label: str) -> str:
    if not _PUBLIC_ID.fullmatch(value):
        raise ValueError(f"{label} must be a public-safe token")
    return value


def completion_validation_declaration_path(
    *, runtime_root: Path, goal_id: str, todo_id: str
) -> Path:
    return (
        runtime_root.expanduser().resolve(strict=False)
        / "goals"
        / _require_public_id(goal_id, "goal_id")
        / "todo-validation-declarations"
        / f"{_require_public_id(todo_id, 'todo_id')}.json"
    )


def persist_completion_validation_declaration(
    *,
    runtime_root: Path,
    goal_id: str,
    todo_id: str,
    declaration: Mapping[str, Any],
) -> str:
    normalized = completion_validation_declaration(dict(declaration))
    if normalized is None:
        raise ValueError("completion validation declaration is empty")
    digest = completion_validation_declaration_sha256(normalized)
    path = completion_validation_declaration_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
        todo_id=todo_id,
    )
    atomic_write_json(
        path,
        {
            "schema_version": DECLARATION_SCHEMA_VERSION,
            "goal_id": goal_id,
            "todo_id": todo_id,
            "declaration_sha256": digest,
            "declaration": normalized,
        },
        preserve_mode=True,
    )
    os.chmod(path, 0o600)
    return digest


def read_completion_validation_declaration(
    *, runtime_root: Path, goal_id: str, todo_id: str
) -> dict[str, Any] | None:
    path = completion_validation_declaration_path(
        runtime_root=runtime_root,
        goal_id=goal_id,
        todo_id=todo_id,
    )
    try:
        value = read_json(path)
    except FileNotFoundError:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("completion validation declaration store is not an object")
    declaration = value.get("declaration")
    if (
        value.get("schema_version") != DECLARATION_SCHEMA_VERSION
        or value.get("goal_id") != goal_id
        or value.get("todo_id") != todo_id
        or not isinstance(declaration, Mapping)
    ):
        raise ValueError("completion validation declaration store identity mismatch")
    normalized = completion_validation_declaration(dict(declaration))
    if normalized is None:
        raise ValueError("completion validation declaration store is empty")
    digest = completion_validation_declaration_sha256(normalized)
    if value.get("declaration_sha256") != digest:
        raise ValueError("completion validation declaration store digest mismatch")
    return normalized


def load_completion_validation_declarations(
    *,
    runtime_root: Path,
    goal_id: str,
    todos: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for todo in todos:
        if todo.get("completion_validation_required") is not True:
            continue
        todo_id = str(todo.get("todo_id") or "")
        declaration = read_completion_validation_declaration(
            runtime_root=runtime_root,
            goal_id=goal_id,
            todo_id=todo_id,
        )
        if declaration is not None:
            loaded[todo_id] = declaration
    return loaded


__all__ = [
    "DECLARATION_SCHEMA_VERSION",
    "completion_validation_declaration_path",
    "load_completion_validation_declarations",
    "persist_completion_validation_declaration",
    "read_completion_validation_declaration",
]
