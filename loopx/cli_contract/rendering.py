"""Transport-level serialization shared without sharing business dispatch."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import IO, TypeAlias, cast


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
MarkdownRenderer: TypeAlias = Callable[[dict[str, JsonValue]], str]


def print_compatible_markdown_renderer(
    renderer: MarkdownRenderer,
) -> MarkdownRenderer:
    """Adapt ``print(renderer(payload))`` byte semantics to ``emit_payload``.

    The legacy CLI always appends one newline after the renderer result, even
    when that result already ends in a newline. Exact compatibility bindings
    select this adapter instead of encoding a complete document in payload data.
    """

    if not callable(renderer):
        raise TypeError("markdown renderer must be callable")

    def render_with_print_newline(payload: dict[str, JsonValue]) -> str:
        return renderer(payload) + "\n"

    return render_with_print_newline


def to_json_value(value: object) -> JsonValue:
    """Serialize typed Application DTOs without leaking object internals."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            descriptor.name: to_json_value(getattr(value, descriptor.name))
            for descriptor in fields(value)
        }
    if isinstance(value, (Mapping, MappingProxyType)):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    raise TypeError(f"unsupported CLI payload value: {type(value).__name__}")


def emit_payload(
    payload: Mapping[str, object],
    *,
    format_name: str,
    stdout: IO[str],
    markdown_renderer: MarkdownRenderer | None = None,
) -> None:
    serialized = to_json_value(payload)
    if not isinstance(serialized, dict):  # pragma: no cover - Mapping guarantees this
        raise TypeError("CLI payload must serialize to an object")
    typed_payload = cast(dict[str, JsonValue], serialized)
    if format_name == "json":
        stdout.write(json.dumps(typed_payload, ensure_ascii=False, indent=2) + "\n")
        return
    renderer = (
        markdown_renderer
        if markdown_renderer is not None
        else render_compatibility_markdown
    )
    rendered = renderer(typed_payload)
    stdout.write(rendered)
    if not rendered.endswith("\n"):
        stdout.write("\n")


def render_compatibility_markdown(payload: dict[str, JsonValue]) -> str:
    """Render a deterministic local compatibility view for typed DTOs."""

    title = str(payload.get("title") or "LoopX CLI v2")
    lines = [f"# {title}"]
    for key, value in payload.items():
        if key == "title":
            continue
        _append_markdown(lines, key, value, indent=0)
    return "\n".join(lines)


def _append_markdown(
    lines: list[str],
    key: str,
    value: JsonValue,
    *,
    indent: int,
) -> None:
    prefix = "  " * indent
    if isinstance(value, dict):
        lines.append(f"{prefix}- {key}:")
        for child_key, child_value in value.items():
            _append_markdown(lines, child_key, child_value, indent=indent + 1)
        return
    if isinstance(value, list):
        lines.append(f"{prefix}- {key}:")
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for child_key, child_value in item.items():
                    _append_markdown(
                        lines,
                        child_key,
                        child_value,
                        indent=indent + 2,
                    )
            else:
                lines.append(f"{prefix}  - `{_scalar(item)}`")
        return
    lines.append(f"{prefix}- {key}: `{_scalar(value)}`")


def _scalar(value: JsonScalar) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
