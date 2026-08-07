from __future__ import annotations

import argparse
from collections.abc import Callable

from loopx.project_skill_delivery import PROJECT_SKILL_SURFACES

from .architecture import build_material_lifecycle_architecture_packet
from .markdown import render_material_lifecycle_markdown
from .project_skill import (
    install_project_material_skill,
    inspect_project_material_skill,
    uninstall_project_material_skill,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def register_material_lifecycle_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "material-lifecycle",
        help="Inspect the backup-safe material inventory and rerank contract.",
    )
    commands = parser.add_subparsers(
        dest="material_lifecycle_command",
        required=True,
    )
    architecture = commands.add_parser(
        "architecture",
        help="Render the default-off Stage-0 Material Lifecycle contract.",
    )
    add_subcommand_format(architecture)
    skill_status = commands.add_parser(
        "skill-status",
        help="Inspect the project-local managed loopx-material skill.",
    )
    skill_status.add_argument("--project", default=".")
    skill_status.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    add_subcommand_format(skill_status)
    install_skill = commands.add_parser(
        "install-skill",
        help="Preview or install the managed loopx-material skill into one connected project.",
    )
    install_skill.add_argument("--project", default=".")
    install_skill.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    install_skill.add_argument("--execute", action="store_true")
    add_subcommand_format(install_skill)
    uninstall_skill = commands.add_parser(
        "uninstall-skill",
        help="Preview or uninstall the managed loopx-material skill from one project.",
    )
    uninstall_skill.add_argument("--project", default=".")
    uninstall_skill.add_argument(
        "--surface",
        action="append",
        choices=PROJECT_SKILL_SURFACES,
    )
    uninstall_skill.add_argument("--execute", action="store_true")
    add_subcommand_format(uninstall_skill)


def handle_material_lifecycle_command(
    args: argparse.Namespace,
    *,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "material-lifecycle":
        return None
    try:
        if args.material_lifecycle_command == "architecture":
            payload = build_material_lifecycle_architecture_packet()
        elif args.material_lifecycle_command == "skill-status":
            payload = inspect_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
            )
        elif args.material_lifecycle_command == "install-skill":
            payload = install_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
                execute=args.execute,
            )
        else:
            payload = uninstall_project_material_skill(
                args.project,
                surfaces=tuple(args.surface or ("codex",)),
                execute=args.execute,
            )
    except (OSError, ValueError) as exc:
        payload = {
            "ok": False,
            "status": "blocked",
            "skill_id": "loopx-material",
            "error": str(exc),
            "surfaces": [],
        }
        print_payload(
            payload,
            output_format(args),
            render_material_lifecycle_markdown,
        )
        return 2
    print_payload(
        payload,
        output_format(args),
        render_material_lifecycle_markdown,
    )
    return 0
