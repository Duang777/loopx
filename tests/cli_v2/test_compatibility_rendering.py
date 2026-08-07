from __future__ import annotations

import argparse
import json
from io import StringIO
from pathlib import Path

import pytest

from loopx.application import ApplicationError, ValidationFailed
from loopx.cli_contract import (
    JsonValue,
    emit_payload,
    print_compatible_markdown_renderer,
)
from loopx.cli_v2 import main
from loopx.cli_v2.registrar import (
    CohortRegistrar,
    CommandBinding,
    CommandOutcome,
)


def _register_arguments(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser("rendered")
    subparsers.add_parser("mapped-error")


def _render_success(payload: dict[str, JsonValue]) -> str:
    return f"# Exact success\n\n- value: `{payload['value']}`\n"


def _render_error(payload: dict[str, JsonValue]) -> str:
    return f"# Exact error\n\n- code: `{payload['error']}`\n"


def _success_handler(
    _args: argparse.Namespace,
    _application: object,
) -> CommandOutcome:
    return CommandOutcome({"ok": True, "value": "fixture"})


def _error_handler(
    _args: argparse.Namespace,
    _application: object,
) -> CommandOutcome:
    raise ValidationFailed(details={"field": "fixture"})


def _map_application_error(
    error: ApplicationError,
    _args: argparse.Namespace,
    _registry_path: Path,
) -> CommandOutcome:
    return CommandOutcome(
        {"ok": False, "error": error.code},
        exit_code=7,
        markdown_renderer=print_compatible_markdown_renderer(_render_error),
    )


COMPATIBILITY_COHORT = CohortRegistrar(
    cohort_id="compatibility-rendering-fixture",
    register_arguments=_register_arguments,
    bindings=(
        CommandBinding(
            command="rendered",
            application_operation="fixture.rendered",
            handler=_success_handler,
            markdown_renderer=print_compatible_markdown_renderer(_render_success),
        ),
        CommandBinding(
            command="mapped-error",
            application_operation="fixture.mapped_error",
            handler=_error_handler,
            markdown_renderer=print_compatible_markdown_renderer(_render_success),
            application_error_mapper=_map_application_error,
        ),
    ),
)


def _run(tmp_path: Path, *argv: str) -> tuple[int, str]:
    output = StringIO()
    code = main(
        [
            "--registry",
            str(tmp_path / "registry.json"),
            *argv,
        ],
        application_factory=lambda _args, _registry: object(),
        cohorts=(COMPATIBILITY_COHORT,),
        stdout=output,
    )
    return code, output.getvalue()


def test_binding_renderer_preserves_exact_markdown_without_changing_json(
    tmp_path: Path,
) -> None:
    markdown_code, markdown = _run(
        tmp_path,
        "--format",
        "markdown",
        "rendered",
    )
    json_code, raw_json = _run(tmp_path, "--format", "json", "rendered")

    assert markdown_code == json_code == 0
    assert markdown == "# Exact success\n\n- value: `fixture`\n\n"
    assert json.loads(raw_json) == {"ok": True, "value": "fixture"}


def test_binding_error_mapper_can_select_a_distinct_exact_renderer(
    tmp_path: Path,
) -> None:
    markdown_code, markdown = _run(
        tmp_path,
        "--format",
        "markdown",
        "mapped-error",
    )
    json_code, raw_json = _run(tmp_path, "--format", "json", "mapped-error")

    assert markdown_code == json_code == 7
    assert markdown == "# Exact error\n\n- code: `validation_failed`\n\n"
    assert json.loads(raw_json) == {
        "ok": False,
        "error": "validation_failed",
    }


def test_renderer_and_error_mapper_contracts_fail_fast() -> None:
    with pytest.raises(TypeError, match="markdown_renderer"):
        CommandOutcome({}, markdown_renderer=object())  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="application_error_mapper"):
        CommandBinding(
            command="rendered",
            application_operation="fixture.invalid",
            handler=_success_handler,
            application_error_mapper=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("rendered", "expected"),
    (("document", "document\n"), ("document\n", "document\n\n")),
)
def test_print_compatible_renderer_preserves_prints_extra_newline(
    rendered: str,
    expected: str,
) -> None:
    adapter = print_compatible_markdown_renderer(lambda _payload: rendered)

    assert adapter({}) == expected


def test_explicit_falsey_callable_renderer_is_not_replaced() -> None:
    class FalseyRenderer:
        def __bool__(self) -> bool:
            return False

        def __call__(self, _payload: dict[str, JsonValue]) -> str:
            return "# Explicit falsey renderer\n"

    output = StringIO()
    emit_payload(
        {"ok": True},
        format_name="markdown",
        stdout=output,
        markdown_renderer=FalseyRenderer(),
    )

    assert output.getvalue() == "# Explicit falsey renderer\n"
