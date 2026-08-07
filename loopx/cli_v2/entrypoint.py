from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

from loopx import __version__
from loopx.application import (
    ApplicationContext,
    ApplicationError,
    LoopXApplication,
    Profile,
)
from loopx.cli_contract import (
    MarkdownRenderer,
    build_root_parser,
    default_cli_registry,
    emit_payload,
    resolve_cli_registry,
    resolve_global_output_format,
    user_supplied_registry,
)
from loopx.help_surface import render_concise_help, top_level_help_requested

from .core import CORE_COHORT
from .registrar import (
    ApplicationFacade,
    CohortRegistrar,
    CommandOutcome,
    CommandRegistry,
)


ApplicationFactory = Callable[[argparse.Namespace, Path], ApplicationFacade]
DEFAULT_COHORTS = (CORE_COHORT,)


def build_parser(
    cohorts: Sequence[CohortRegistrar] = DEFAULT_COHORTS,
) -> argparse.ArgumentParser:
    registry = CommandRegistry(cohorts)
    parser, subparsers = build_root_parser(
        description="LoopX application CLI v2.",
        version=f"loopx {__version__}",
    )
    parser.set_defaults(registry=str(default_cli_registry()))
    for cohort in cohorts:
        cohort.register_arguments(subparsers)
    setattr(parser, "_loopx_v2_registry", registry)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    application_factory: ApplicationFactory | None = None,
    cohorts: Sequence[CohortRegistrar] = DEFAULT_COHORTS,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    output = stdout or sys.stdout
    if raw_argv == ["--version"]:
        output.write(f"loopx {__version__}\n")
        return 0
    if top_level_help_requested(raw_argv):
        output.write(render_concise_help("loopx-v2"))
        return 0

    parser = build_parser(cohorts)
    args = parser.parse_args(raw_argv)
    args.format = resolve_global_output_format(args)
    registry_path = resolve_cli_registry(
        str(args.registry),
        runtime_root_value=args.runtime_root,
        explicitly_supplied=user_supplied_registry(raw_argv),
    )
    registry = getattr(parser, "_loopx_v2_registry")
    binding = registry.resolve(args)
    if binding is None:
        outcome_payload = {
            "title": "LoopX CLI v2",
            "ok": False,
            "schema_version": "loopx_cli_v2_result_v1",
            "error": {
                "code": "cli_v2_pending_migration",
                "message": "This executable surface has not migrated to a typed Application operation.",
                "details": {"command": _command_label(args)},
                "retryable": False,
            },
        }
        emit_payload(outcome_payload, format_name=args.format, stdout=output)
        return 2

    try:
        factory = application_factory or _default_application_factory
        application = factory(args, registry_path)
        outcome = binding.handler(args, application)
    except ApplicationError as exc:
        if binding.application_error_mapper is not None:
            outcome = binding.application_error_mapper(exc, args, registry_path)
            _emit_outcome(
                outcome,
                binding_renderer=binding.markdown_renderer,
                format_name=args.format,
                stdout=output,
            )
            return outcome.exit_code
        emit_payload(
            {
                "title": "LoopX CLI v2",
                "ok": False,
                "schema_version": "loopx_cli_v2_result_v1",
                "application_operation": binding.application_operation,
                "error": exc.to_dict(),
            },
            format_name=args.format,
            stdout=output,
        )
        return 1
    except (TypeError, ValueError) as exc:
        emit_payload(
            {
                "title": "LoopX CLI v2",
                "ok": False,
                "schema_version": "loopx_cli_v2_result_v1",
                "application_operation": binding.application_operation,
                "error": {
                    "code": "validation_failed",
                    "message": str(exc),
                    "details": {"command": _command_label(args)},
                    "retryable": False,
                },
            },
            format_name=args.format,
            stdout=output,
        )
        return 1

    _emit_outcome(
        outcome,
        binding_renderer=binding.markdown_renderer,
        format_name=args.format,
        stdout=output,
    )
    return outcome.exit_code


def _emit_outcome(
    outcome: CommandOutcome,
    *,
    binding_renderer: MarkdownRenderer | None,
    format_name: str,
    stdout: IO[str],
) -> None:
    renderer = (
        outcome.markdown_renderer
        if outcome.markdown_renderer is not None
        else binding_renderer
    )
    if renderer is not None and not callable(renderer):  # pragma: no cover - guarded
        raise TypeError("CLI v2 markdown renderer must be callable")
    emit_payload(
        outcome.payload,
        format_name=format_name,
        stdout=stdout,
        markdown_renderer=renderer,
    )


def _default_application_factory(
    args: argparse.Namespace,
    registry_path: Path,
) -> LoopXApplication:
    scan_values = tuple(getattr(args, "scan_path", None) or ())
    if not scan_values and getattr(args, "scan_root", None):
        scan_values = (args.scan_root,)
    return LoopXApplication(
        ApplicationContext(
            registry_path=registry_path,
            runtime_root_override=args.runtime_root,
            profile=Profile.CLI,
            scan_roots=tuple(Path(value).expanduser() for value in scan_values),
        )
    )


def _command_label(args: argparse.Namespace) -> str:
    parts = [str(args.command)]
    for name, value in sorted(vars(args).items()):
        if name.endswith("_command") and name != "command" and value is not None:
            parts.append(str(value))
    return " ".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
