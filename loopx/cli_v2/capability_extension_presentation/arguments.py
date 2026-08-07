from __future__ import annotations

import argparse

from loopx.capabilities.content_ops.cli import register_content_ops_commands
from loopx.capabilities.decision_context.cli import (
    register_decision_context_commands,
)
from loopx.capabilities.material_lifecycle.cli import (
    register_material_lifecycle_commands,
)
from loopx.capabilities.reward_memory.cli import register_reward_memory_commands
from loopx.capabilities.semantic_preference.cli import (
    register_semantic_preference_commands,
)
from loopx.capabilities.value_connectors.cli import (
    register_value_connector_commands,
)
from loopx.cli_contract import add_subcommand_format

from .extension_adapter import KNOWN_BUNDLED_EXTENSION_IDS


def register_arguments(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    _register_capability(subparsers)
    _register_extension(subparsers)
    register_content_ops_commands(subparsers, add_subcommand_format)
    register_decision_context_commands(subparsers, add_subcommand_format)
    register_material_lifecycle_commands(subparsers, add_subcommand_format)
    register_reward_memory_commands(subparsers, add_subcommand_format)
    register_semantic_preference_commands(subparsers, add_subcommand_format)
    register_value_connector_commands(subparsers, add_subcommand_format)
    _register_presentation(subparsers)


def _register_capability(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "capability",
        help="Inspect real LoopX product capability paths.",
    )
    commands = parser.add_subparsers(dest="capability_command", required=True)
    list_parser = commands.add_parser(
        "list",
        help="List implemented product capability paths.",
    )
    add_subcommand_format(list_parser)
    _add_extension_manifest_argument(list_parser)
    show = commands.add_parser(
        "show",
        help="Show CLI, protocol, smoke, and boundary details for a capability.",
    )
    add_subcommand_format(show)
    show.add_argument("capability_id", help="Capability id to inspect.")
    _add_extension_manifest_argument(show)


def _add_extension_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--extension-manifest",
        action="append",
        default=[],
        help=(
            "Declare one extension manifest for this catalog read without "
            "installing or enabling it. Repeat for multiple manifests."
        ),
    )
    parser.set_defaults(capability_operation_parser=parser)


def _register_extension(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "extension",
        help="Manage explicitly enabled subprocess extension providers.",
    )
    commands = parser.add_subparsers(dest="extension_command", required=True)

    init = commands.add_parser(
        "init",
        help="Preview or create a minimal independently packaged extension starter.",
    )
    add_subcommand_format(init)
    init.add_argument("extension_id")
    init.add_argument(
        "--destination",
        help="Target directory. Defaults to packages/<extension-id>.",
    )
    init.add_argument("--version", default="0.1.0")
    init.add_argument("--execute", action="store_true")

    list_parser = commands.add_parser("list", help="List installed extensions.")
    _add_extension_common(list_parser)

    for command in ("install", "upgrade"):
        operation = commands.add_parser(
            command,
            help=(
                "Register a preinstalled extension after its doctor passes."
                if command == "install"
                else "Activate a new manifest revision after its doctor passes."
            ),
        )
        _add_extension_common(operation)
        source = operation.add_mutually_exclusive_group(required=True)
        source.add_argument("--manifest")
        source.add_argument("--bundled", choices=KNOWN_BUNDLED_EXTENSION_IDS)
        operation.add_argument("--execute", action="store_true")

    for command in ("enable", "disable", "rollback", "doctor"):
        operation = commands.add_parser(command)
        _add_extension_common(operation)
        operation.add_argument("extension_id")
        if command != "doctor":
            operation.add_argument("--execute", action="store_true")
        else:
            operation.add_argument(
                "--execute",
                action="store_true",
                help="Run the configured read-only provider probe.",
            )

    run = commands.add_parser(
        "run",
        help="Invoke one enabled standalone extension through its managed runtime.",
    )
    _add_extension_common(run)
    run.add_argument("extension_id")
    run.add_argument(
        "--input-json",
        required=True,
        help="Path to one provider request JSON object, or '-' for stdin.",
    )
    run.add_argument("--execute", action="store_true")


def _add_extension_common(parser: argparse.ArgumentParser) -> None:
    add_subcommand_format(parser)
    parser.add_argument(
        "--state-file",
        dest="extension_state_file",
        help="Override the local extension activation state file.",
    )


def _register_presentation(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = subparsers.add_parser(
        "presentation",
        help="Package and verify provider-neutral static presentation artifacts.",
    )
    commands = parser.add_subparsers(dest="presentation_command", required=True)

    package = commands.add_parser(
        "package",
        help="Create stable latest/revision artifacts and a deploy receipt from a built site.",
    )
    add_subcommand_format(package)
    package.add_argument(
        "--site-dir",
        required=True,
        help="Already-built public-safe site directory.",
    )
    package.add_argument(
        "--output-dir",
        required=True,
        help="Local publish artifact directory.",
    )
    package.add_argument("--state-dir", help="Local deploy receipt state directory.")
    package.add_argument("--site-id", required=True, help="Stable public-safe site id.")
    package.add_argument(
        "--entry-path",
        default="index.html",
        help="Relative primary HTML entry.",
    )
    package.add_argument(
        "--revision",
        help="Public-safe immutable revision id; defaults to the content digest.",
    )
    package.add_argument(
        "--publisher",
        choices=["local", "github-pages"],
        default="local",
        help="Optional publisher URL adapter. Local packaging is always available.",
    )
    package.add_argument(
        "--base-url",
        help="HTTPS deployment root required by github-pages.",
    )
    for flag in ("desktop-visual-check", "mobile-visual-check", "link-check"):
        package.add_argument(f"--{flag}", required=True, choices=["passed"])
    package.add_argument(
        "--execute",
        action="store_true",
        help="Write the local artifact and receipt state.",
    )

    rollback = commands.add_parser(
        "rollback",
        help="Prepare the latest artifact from a retained previous revision.",
    )
    add_subcommand_format(rollback)
    rollback.add_argument(
        "--output-dir",
        required=True,
        help="Existing local publish artifact directory.",
    )
    rollback.add_argument("--state-dir", help="Local deploy receipt state directory.")
    rollback.add_argument(
        "--revision",
        help="Target retained revision; defaults to previous_revision.",
    )
    rollback.add_argument(
        "--execute",
        action="store_true",
        help="Write the rollback artifact and receipt state.",
    )

    verify = commands.add_parser(
        "verify-readback",
        help="Compare a remote HTTP deploy receipt with the local packaged receipt.",
    )
    add_subcommand_format(verify)
    verify.add_argument(
        "--output-dir",
        required=True,
        help="Existing local publish artifact directory.",
    )
    verify.add_argument("--state-dir", help="Local deploy receipt state directory.")
    verify.add_argument(
        "--receipt-url",
        help="Remote receipt URL; defaults to the publisher latest URL.",
    )
    verify.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Bounded HTTP readback attempts (1-10).",
    )
    verify.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between attempts (0-30 seconds).",
    )
    verify.add_argument(
        "--execute",
        action="store_true",
        help="Persist the verified readback receipt locally.",
    )
