"""Application-only LoopX CLI v2 adapter."""

from .entrypoint import build_parser, main
from .registrar import (
    CLI_V2_REGISTRAR_SCHEMA_VERSION,
    CohortRegistrar,
    CommandBinding,
    CommandOutcome,
    CommandRegistry,
    SelectorMatch,
)

__all__ = [
    "CLI_V2_REGISTRAR_SCHEMA_VERSION",
    "CohortRegistrar",
    "CommandBinding",
    "CommandOutcome",
    "CommandRegistry",
    "SelectorMatch",
    "build_parser",
    "main",
]
