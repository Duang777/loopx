"""Shared, behavior-preserving command-line compatibility contracts."""

from .parser import (
    LoopXArgumentParser,
    add_subcommand_format,
    build_root_parser,
    output_format,
    resolve_global_output_format,
    user_supplied_registry,
)
from .paths import default_cli_registry, resolve_cli_registry
from .rendering import (
    JsonValue,
    MarkdownRenderer,
    emit_payload,
    print_compatible_markdown_renderer,
    render_compatibility_markdown,
    to_json_value,
)

__all__ = [
    "JsonValue",
    "LoopXArgumentParser",
    "MarkdownRenderer",
    "add_subcommand_format",
    "build_root_parser",
    "default_cli_registry",
    "emit_payload",
    "output_format",
    "print_compatible_markdown_renderer",
    "render_compatibility_markdown",
    "resolve_global_output_format",
    "resolve_cli_registry",
    "to_json_value",
    "user_supplied_registry",
]
