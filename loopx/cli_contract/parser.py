"""Stable argparse primitives shared by the legacy and v2 adapters.

This module intentionally owns only syntax and compatibility decisions.  It does
not select or invoke a business handler.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


class LoopXArgumentParser(argparse.ArgumentParser):
    """Require complete option names across the automation-facing CLI."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)


def build_root_parser(
    *,
    description: str,
    version: str,
) -> tuple[
    LoopXArgumentParser,
    argparse._SubParsersAction[argparse.ArgumentParser],
]:
    """Create the shared root parser without registering business cohorts."""

    parser = LoopXArgumentParser(description=description)
    parser.add_argument("--version", action="version", version=version)
    parser.add_argument(
        "--registry",
        help="Path to a project-local registry.",
    )
    parser.add_argument("--runtime-root", help="Override registry common_runtime_root.")
    parser.add_argument("--format", choices=["markdown", "json"])
    subparsers = parser.add_subparsers(dest="command", required=True)
    return parser, subparsers


def add_subcommand_format(arg_parser: argparse.ArgumentParser) -> None:
    arg_parser.add_argument(
        "--format",
        dest="subcommand_format",
        choices=["markdown", "json"],
        help=(
            "Output format for this subcommand. Equivalent to global --format "
            "before the command."
        ),
    )


def output_format(args: argparse.Namespace, *local_dests: str) -> str:
    for dest in (*local_dests, "subcommand_format"):
        value = getattr(args, dest, None)
        if value:
            return str(value)
    return str(getattr(args, "format", None) or "markdown")


def resolve_global_output_format(args: argparse.Namespace) -> str:
    if getattr(args, "format", None):
        return str(args.format)
    if args.command == "quota" and getattr(args, "quota_command", None) == "should-run":
        return "json"
    return "markdown"


def user_supplied_registry(
    argv: Sequence[str] | None,
    *,
    process_argv: Sequence[str] | None = None,
) -> bool:
    values = (
        tuple(sys.argv[1:] if process_argv is None else process_argv)
        if argv is None
        else tuple(argv)
    )
    return any(value == "--registry" or value.startswith("--registry=") for value in values)
