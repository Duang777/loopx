from __future__ import annotations

import argparse
import json
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from loopx import __version__
from loopx.capabilities.auto_research.cli import rewrite_auto_research_question_argv
from loopx.cli import build_parser
from loopx.cli_v2.capability_extension_presentation import (
    CAPABILITY_EXTENSION_PRESENTATION_COHORT,
)
from loopx.cli_v2.core import CORE_COHORT
from loopx.cli_v2.maintainer_benchmark_agent import (
    MAINTAINER_BENCHMARK_AGENT_COHORT,
)
from loopx.cli_v2.project_system_registry import PROJECT_SYSTEM_REGISTRY_COHORT
from loopx.cli_v2.registrar import CommandBinding, CommandRegistry
from loopx.entrypoint import main as entrypoint_main
from loopx.help_surface import top_level_help_requested


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "cli_v2_parity"
REPOSITORY_ROOT = Path(__file__).parents[2]
SHARD_PATHS = tuple(
    FIXTURE_ROOT / name
    for name in (
        "core.json",
        "project-system-registry.json",
        "capability-extension-presentation.json",
        "maintainer-benchmark-agent.json",
    )
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _subparser_actions(
    parser: argparse.ArgumentParser,
) -> list[argparse._SubParsersAction[argparse.ArgumentParser]]:
    return [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]


SelectorOption = tuple[
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
    dict[str, Any],
]

PREPARSE_REWRITE_ALIASES = {
    "auto-research contract": [
        {
            "source_argv": ["auto-research", "<question>"],
            "target_argv": ["auto-research", "contract", "<question>"],
        }
    ]
}


def _finite_positional_selector_actions(
    parser: argparse.ArgumentParser,
) -> list[argparse.Action]:
    selectors: list[argparse.Action] = []
    for action in parser._actions:
        if action.option_strings or isinstance(action, argparse._SubParsersAction):
            continue
        if action.choices is None:
            continue
        assert action.nargs in {None, "?"}, (
            f"{parser.prog!r} selector {action.dest!r} uses non-finite "
            f"nargs={action.nargs!r}"
        )
        selectors.append(action)
    return selectors


def _selector_options(action: argparse.Action) -> list[SelectorOption]:
    choices = list(action.choices or ())
    assert choices, f"selector {action.dest!r} must expose at least one choice"
    assert all(isinstance(choice, str) for choice in choices), (
        f"selector {action.dest!r} choices must be CLI tokens"
    )

    options: list[SelectorOption] = []
    if action.nargs == "?" and action.default not in choices:
        assert action.default is None or isinstance(action.default, str), (
            f"selector {action.dest!r} default must be a CLI token or null"
        )
        options.append(
            (
                (),
                ((),),
                {
                    "dest": action.dest,
                    "value": action.default,
                    "implicit_default": True,
                },
            )
        )

    for choice in choices:
        invocation_tokens: tuple[tuple[str, ...], ...] = ((choice,),)
        metadata: dict[str, Any] = {"dest": action.dest, "value": choice}
        if action.nargs == "?" and action.default == choice:
            invocation_tokens = (*invocation_tokens, ())
            metadata["implicit_default"] = True
        options.append(((choice,), invocation_tokens, metadata))
    return options


def _leaf_inventory_rows(
    parser: argparse.ArgumentParser,
    canonical_path: tuple[str, ...],
    invocation_paths: tuple[tuple[str, ...], ...],
) -> list[dict[str, Any]]:
    selector_actions = _finite_positional_selector_actions(parser)
    if not selector_actions:
        selector_combinations: tuple[tuple[SelectorOption, ...], ...] = ((),)
    else:
        selector_combinations = tuple(
            product(*(_selector_options(action) for action in selector_actions))
        )

    rows: list[dict[str, Any]] = []
    for selector_combination in selector_combinations:
        canonical_suffix = tuple(
            token
            for canonical_tokens, _invocation_tokens, _metadata in selector_combination
            for token in canonical_tokens
        )
        command_path = (*canonical_path, *canonical_suffix)
        suffix_paths = (
            tuple(
                tuple(token for token_group in groups for token in token_group)
                for groups in product(*(option[1] for option in selector_combination))
            )
            if selector_combination
            else ((),)
        )
        all_invocation_paths = {
            (*path, *suffix) for path in invocation_paths for suffix in suffix_paths
        }

        row: dict[str, Any] = {"command": " ".join(command_path)}
        aliases = sorted(
            " ".join(path) for path in all_invocation_paths if path != command_path
        )
        if aliases:
            row["aliases"] = aliases
        if selector_combination:
            row["selectors"] = [option[2] for option in selector_combination]
        rows.append(row)
    return rows


def _parser_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def walk(
        parser: argparse.ArgumentParser,
        canonical_path: tuple[str, ...],
        invocation_paths: tuple[tuple[str, ...], ...],
    ) -> None:
        subparser_actions = _subparser_actions(parser)
        assert len(subparser_actions) <= 1, (
            f"{parser.prog!r} has multiple subparser actions; inventory traversal "
            "must define their execution semantics before accepting this shape"
        )
        if not subparser_actions:
            assert canonical_path, "the root parser cannot be an executable leaf"
            rows.extend(_leaf_inventory_rows(parser, canonical_path, invocation_paths))
            return

        action = subparser_actions[0]
        if not action.required:
            for row in _leaf_inventory_rows(
                parser,
                canonical_path,
                invocation_paths,
            ):
                row["subparser_base"] = {
                    "dest": action.dest,
                    "value": action.default,
                }
                rows.append(row)
        parser_groups: list[tuple[argparse.ArgumentParser, list[str]]] = []
        group_indexes: dict[int, int] = {}
        for name, child_parser in action.choices.items():
            parser_id = id(child_parser)
            group_index = group_indexes.get(parser_id)
            if group_index is None:
                group_indexes[parser_id] = len(parser_groups)
                parser_groups.append((child_parser, [name]))
            else:
                parser_groups[group_index][1].append(name)

        for child_parser, names in parser_groups:
            canonical_name = names[0]
            child_canonical_path = (*canonical_path, canonical_name)
            child_invocation_paths = tuple(
                (*path, name) for path in invocation_paths for name in names
            )
            walk(child_parser, child_canonical_path, child_invocation_paths)

    walk(build_parser(), (), ((),))
    rows_by_command = {row["command"]: row for row in rows}
    assert len(rows_by_command) == len(rows), "CLI canonical inventory rows collide"
    for command, aliases in PREPARSE_REWRITE_ALIASES.items():
        rows_by_command[command]["rewrite_aliases"] = aliases
    return rows


def _validated_fixture_payloads() -> list[dict[str, Any]]:
    schema = _read_json(FIXTURE_ROOT / "schema.json")
    validator = Draft202012Validator(schema)
    ownership = schema["x-shard-ownership"]
    assert ownership["policy"] == "shard-only"
    assert ownership["central_files_read_only"] == [
        "tests/cli_v2/test_command_inventory.py",
        "tests/fixtures/cli_v2_parity/schema.json",
    ]
    assert ownership["shard_editable_files"] == {
        path.stem: path.relative_to(REPOSITORY_ROOT).as_posix() for path in SHARD_PATHS
    }
    payloads: list[dict[str, Any]] = []
    for path in SHARD_PATHS:
        payload = _read_json(path)
        validator.validate(payload)
        assert payload["shard"] == path.stem
        payloads.append(payload)
    return payloads


def _fixture_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in _validated_fixture_payloads():
        rows.extend(
            {**payload["defaults"], **command} for command in payload["commands"]
        )
    return rows


def _fixture_root_invocations() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for payload in _validated_fixture_payloads():
        rows.extend(
            {**payload["defaults"], **invocation}
            for invocation in payload.get("root_invocations", [])
        )
    return rows


def _binding_label(binding: CommandBinding) -> str:
    if not binding.selectors:
        return binding.command
    assert len(binding.selectors) == 1, (
        "canonical labels for multi-selector bindings need explicit CLI ordering"
    )
    selector_value = binding.selectors[0].value
    return (
        binding.command
        if selector_value is None
        else f"{binding.command} {selector_value}"
    )


def test_every_canonical_command_belongs_to_exactly_one_valid_shard() -> None:
    rows = _fixture_rows()
    memberships = Counter(row["command"] for row in rows)

    duplicates = sorted(
        command
        for command, membership_count in memberships.items()
        if membership_count != 1
    )
    assert not duplicates, f"canonical commands must occur in one shard: {duplicates}"


def test_typed_application_bindings_exactly_match_manifest_operations() -> None:
    """Keep independently owned cohort registrars and parity rows as one truth."""

    registry = CommandRegistry(
        (
            CORE_COHORT,
            PROJECT_SYSTEM_REGISTRY_COHORT,
            CAPABILITY_EXTENSION_PRESENTATION_COHORT,
            MAINTAINER_BENCHMARK_AGENT_COHORT,
        )
    )
    bindings_by_command = {
        _binding_label(binding): binding.application_operation
        for binding in registry.bindings
    }
    assert len(bindings_by_command) == len(registry.bindings), (
        "typed CLI v2 bindings must have unique canonical command labels"
    )

    manifest_by_command = {
        row["command"]: row["application_operation"]
        for row in _fixture_rows()
        if row["application_operation"] is not None
    }
    assert bindings_by_command == manifest_by_command


def test_argparse_executable_alias_and_selector_inventory_matches_fixtures() -> None:
    actual_rows = _parser_inventory()
    fixture_rows = _fixture_rows()
    actual_by_command = {row["command"]: row for row in actual_rows}
    fixture_by_command = {row["command"]: row for row in fixture_rows}

    assert len(actual_by_command) == len(actual_rows), (
        "argparse canonical invocations collide"
    )
    assert len(fixture_by_command) == len(fixture_rows), (
        "fixture rows collide across shards"
    )

    missing = sorted(actual_by_command.keys() - fixture_by_command.keys())
    stale = sorted(fixture_by_command.keys() - actual_by_command.keys())
    assert not missing, (
        f"new executable argparse invocations need a shard assignment: {missing}"
    )
    assert not stale, f"fixture rows no longer executable through argparse: {stale}"

    for command in sorted(actual_by_command):
        fixture_surface = {
            key: value
            for key, value in fixture_by_command[command].items()
            if key
            in {
                "command",
                "aliases",
                "selectors",
                "subparser_base",
                "rewrite_aliases",
            }
        }
        assert fixture_surface == actual_by_command[command], command


def test_optional_subparser_base_rows_are_parseable() -> None:
    parser = build_parser()
    base_rows = [row for row in _parser_inventory() if "subparser_base" in row]

    assert base_rows, "the current CLI has an optional subparser parent"
    for row in base_rows:
        parsed = parser.parse_args(row["command"].split())
        metadata = row["subparser_base"]
        assert getattr(parsed, metadata["dest"]) == metadata["value"], row["command"]


def test_preparse_rewrite_aliases_match_the_real_rewrite_contract() -> None:
    rewrite_rows = [row for row in _fixture_rows() if row.get("rewrite_aliases")]
    assert [row["command"] for row in rewrite_rows] == ["auto-research contract"]

    question = "Which public strategy should be evaluated?"
    placeholder = "<question>"
    alias = rewrite_rows[0]["rewrite_aliases"][0]
    source_argv = [
        question if token == placeholder else token for token in alias["source_argv"]
    ]
    target_argv = [
        question if token == placeholder else token for token in alias["target_argv"]
    ]

    canonical_tokens = rewrite_rows[0]["command"].split()
    assert alias["target_argv"][: len(canonical_tokens)] == canonical_tokens
    assert rewrite_auto_research_question_argv(source_argv) == target_argv
    assert rewrite_auto_research_question_argv(
        ["auto-research", "--format", "json", question]
    ) == ["auto-research", "--format", "json", "contract", question]
    assert rewrite_auto_research_question_argv(
        ["auto-research", "--format=json", question]
    ) == ["auto-research", "--format=json", "contract", question]
    assert rewrite_auto_research_question_argv(target_argv) == target_argv

    parsed = build_parser().parse_args(target_argv)
    assert parsed.auto_research_command == "contract"
    assert parsed.open_question == question


def test_root_concise_help_surface_matches_the_real_help_detector() -> None:
    root_ownership = [
        (payload["shard"], invocation["surface"])
        for payload in _validated_fixture_payloads()
        for invocation in payload.get("root_invocations", [])
    ]
    assert root_ownership == [
        ("core", "concise-help"),
        ("core", "version"),
    ]

    invocation_rows = _fixture_root_invocations()
    root_rows = {row["surface"]: row for row in invocation_rows}
    assert len(root_rows) == len(invocation_rows)
    help_row = root_rows["concise-help"]
    help_argv = [help_row["argv"], *help_row["argv_aliases"]]

    assert help_argv == [
        [],
        ["-h"],
        ["--help"],
        ["--format", "json", "--help"],
        ["--format=json", "--help"],
    ]
    assert all(top_level_help_requested(argv) for argv in help_argv)
    assert not top_level_help_requested(["status", "--help"])


def test_root_version_surface_uses_the_lightweight_entrypoint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root_rows = {row["surface"]: row for row in _fixture_root_invocations()}
    version_row = root_rows["version"]

    assert version_row["argv"] == ["--version"]
    assert entrypoint_main(version_row["argv"]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"loopx {__version__}\n"
    assert captured.err == ""
