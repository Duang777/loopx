from __future__ import annotations

import argparse

import pytest

from loopx.cli import build_parser as build_legacy_parser
from loopx.cli_v2 import build_parser as build_v2_parser
from loopx.cli_v2.registrar import (
    CohortRegistrar,
    CommandBinding,
    CommandOutcome,
    CommandRegistry,
    SelectorMatch,
)


def _handler(_args: argparse.Namespace, _application: object) -> CommandOutcome:
    return CommandOutcome({"ok": True})


def _arguments(
    subparsers: argparse._SubParsersAction,
) -> None:
    parser = subparsers.add_parser("nested")
    parser.add_argument("phase", choices=["preview", "apply"])
    parser.add_argument("mode", nargs="?", choices=["fast", "safe"])


def test_multi_selector_routes_match_all_values_in_canonical_order() -> None:
    binding = CommandBinding(
        command="nested",
        selectors=(
            SelectorMatch("mode", None),
            SelectorMatch("phase", "preview"),
        ),
        application_operation="root.nested.preview",
        handler=_handler,
    )

    assert binding.route_key == (
        "nested",
        (("mode", None), ("phase", "preview")),
    )
    assert binding.matches(
        argparse.Namespace(command="nested", phase="preview", mode=None)
    )
    assert not binding.matches(
        argparse.Namespace(command="nested", phase="apply", mode=None)
    )
    assert not binding.matches(
        argparse.Namespace(command="nested", phase="preview", mode="safe")
    )


def test_registrar_rejects_semantic_route_collision_despite_selector_order() -> None:
    first = CommandBinding(
        command="nested",
        selectors=(
            SelectorMatch("phase", "preview"),
            SelectorMatch("mode", None),
        ),
        application_operation="root.nested.preview",
        handler=_handler,
    )
    reordered = CommandBinding(
        command="nested",
        selectors=(
            SelectorMatch("mode", None),
            SelectorMatch("phase", "preview"),
        ),
        application_operation="root.nested.preview.other",
        handler=_handler,
    )

    with pytest.raises(ValueError, match="duplicate CLI v2 route"):
        CommandRegistry(
            (
                CohortRegistrar("one", _arguments, (first,)),
                CohortRegistrar("two", _arguments, (reordered,)),
            )
        )


def test_registrar_rejects_duplicate_cohort_and_selector_dest() -> None:
    with pytest.raises(ValueError, match="selector destinations"):
        CommandBinding(
            command="nested",
            selectors=(
                SelectorMatch("phase", "preview"),
                SelectorMatch("phase", "apply"),
            ),
            application_operation="root.nested",
            handler=_handler,
        )

    cohort = CohortRegistrar("same", _arguments, ())
    with pytest.raises(ValueError, match="duplicate CLI v2 cohort"):
        CommandRegistry((cohort, cohort))


@pytest.mark.parametrize(
    "argv",
    (
        ("status", "--goal-id", "goal-one"),
        ("configure-goal", "--goal-id", "goal-one", "--quota-compute", "0.5"),
        ("todo", "list", "--goal-id", "goal-one", "--status", "open"),
        (
            "task-lease",
            "inspect",
            "--goal-id",
            "goal-one",
            "--todo-id",
            "todo_one",
        ),
        ("quota", "should-run", "--goal-id", "goal-one", "--agent-id", "agent-one"),
        (
            "turn",
            "plan",
            "--goal-id",
            "goal-one",
            "--agent-id",
            "agent-one",
            "--turn-instance-id",
            "turn-one",
        ),
        ("history", "--goal-id", "goal-one", "--limit", "5"),
    ),
)
def test_core_parser_namespace_is_a_behavior_preserving_legacy_slice(
    argv: tuple[str, ...],
) -> None:
    legacy = vars(build_legacy_parser().parse_args(argv))
    v2 = vars(build_v2_parser().parse_args(argv))

    assert {key: legacy[key] for key in v2} == v2
