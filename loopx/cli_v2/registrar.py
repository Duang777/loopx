"""Frozen composition contract for independently migrated CLI v2 cohorts."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loopx.application import ApplicationError
from loopx.cli_contract import MarkdownRenderer


CLI_V2_REGISTRAR_SCHEMA_VERSION = "loopx_cli_v2_registrar_v1"


class ApplicationFacade(Protocol):
    """Minimal structural type used by transport handlers and test fakes."""

    def list_goals(self) -> tuple[object, ...]: ...

    def get_goal(self, goal_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    payload: Mapping[str, object]
    exit_code: int = 0
    markdown_renderer: MarkdownRenderer | None = None

    def __post_init__(self) -> None:
        if self.markdown_renderer is not None and not callable(self.markdown_renderer):
            raise TypeError("markdown_renderer must be callable")


CommandHandler = Callable[[argparse.Namespace, ApplicationFacade], CommandOutcome]
ApplicationErrorMapper = Callable[
    [ApplicationError, argparse.Namespace, Path],
    CommandOutcome,
]
ArgumentRegistrar = Callable[
    [argparse._SubParsersAction],
    None,
]


@dataclass(frozen=True, slots=True)
class SelectorMatch:
    """One finite argparse selector, including an implicit ``None`` default."""

    dest: str
    value: str | None

    def __post_init__(self) -> None:
        dest = self.dest.strip()
        if not dest or dest != self.dest:
            raise ValueError("selector dest must be a normalized non-empty token")


@dataclass(frozen=True, slots=True)
class CommandBinding:
    """One executable command/selector variant mapped to an Application operation."""

    command: str
    application_operation: str
    handler: CommandHandler
    selectors: tuple[SelectorMatch, ...] = ()
    markdown_renderer: MarkdownRenderer | None = None
    application_error_mapper: ApplicationErrorMapper | None = None

    def __post_init__(self) -> None:
        if not self.command.strip() or " " in self.command:
            raise ValueError("binding command must be one top-level argparse token")
        if not self.application_operation.strip():
            raise ValueError("binding application_operation must be non-empty")
        if not callable(self.handler):
            raise TypeError("binding handler must be callable")
        if self.markdown_renderer is not None and not callable(self.markdown_renderer):
            raise TypeError("binding markdown_renderer must be callable")
        if self.application_error_mapper is not None and not callable(
            self.application_error_mapper
        ):
            raise TypeError("application_error_mapper must be callable")
        selectors = tuple(sorted(self.selectors, key=lambda selector: selector.dest))
        if len({selector.dest for selector in selectors}) != len(selectors):
            raise ValueError("binding selector destinations must be unique")
        object.__setattr__(self, "selectors", selectors)

    @property
    def route_key(self) -> tuple[str, tuple[tuple[str, str | None], ...]]:
        return self.command, tuple(
            (selector.dest, selector.value) for selector in self.selectors
        )

    def matches(self, args: argparse.Namespace) -> bool:
        if getattr(args, "command", None) != self.command:
            return False
        return all(
            getattr(args, selector.dest, None) == selector.value
            for selector in self.selectors
        )


@dataclass(frozen=True, slots=True)
class CohortRegistrar:
    """Shard-owned parser + dispatch contribution used by T7 composition."""

    cohort_id: str
    register_arguments: ArgumentRegistrar
    bindings: tuple[CommandBinding, ...]

    def __post_init__(self) -> None:
        cohort_id = self.cohort_id.strip()
        if not cohort_id or cohort_id != self.cohort_id:
            raise ValueError("cohort_id must be a normalized non-empty token")
        if not callable(self.register_arguments):
            raise TypeError("register_arguments must be callable")
        object.__setattr__(self, "bindings", tuple(self.bindings))


class CommandRegistry:
    """Immutable, collision-checked aggregate of shard-owned bindings."""

    __slots__ = ("_bindings", "_cohort_ids")

    def __init__(self, cohorts: Sequence[CohortRegistrar]) -> None:
        cohort_ids: list[str] = []
        bindings: list[CommandBinding] = []
        owner_by_route: dict[
            tuple[str, tuple[tuple[str, str | None], ...]],
            str,
        ] = {}
        for cohort in cohorts:
            if cohort.cohort_id in cohort_ids:
                raise ValueError(f"duplicate CLI v2 cohort: {cohort.cohort_id}")
            cohort_ids.append(cohort.cohort_id)
            for binding in cohort.bindings:
                previous = owner_by_route.get(binding.route_key)
                if previous is not None:
                    raise ValueError(
                        "duplicate CLI v2 route "
                        f"{binding.route_key!r}: {previous}, {cohort.cohort_id}"
                    )
                owner_by_route[binding.route_key] = cohort.cohort_id
                bindings.append(binding)
        self._bindings = tuple(bindings)
        self._cohort_ids = tuple(cohort_ids)

    @property
    def cohort_ids(self) -> tuple[str, ...]:
        return self._cohort_ids

    @property
    def bindings(self) -> tuple[CommandBinding, ...]:
        return self._bindings

    def resolve(self, args: argparse.Namespace) -> CommandBinding | None:
        matches = [binding for binding in self._bindings if binding.matches(args)]
        if len(matches) > 1:
            raise RuntimeError(
                f"ambiguous CLI v2 dispatch for {getattr(args, 'command', None)!r}"
            )
        return matches[0] if matches else None
