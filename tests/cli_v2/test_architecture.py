from __future__ import annotations

import ast
from pathlib import Path


PACKAGE_ROOT = Path(__file__).parents[2] / "loopx" / "cli_v2"
FORBIDDEN_PREFIXES = (
    "loopx.cli",
    "loopx.cli_commands",
    "loopx.control_plane",
    "loopx.history",
    "loopx.quota",
    "loopx.status",
    "loopx.todos",
)


def test_cli_v2_has_no_legacy_handler_or_core_imports() -> None:
    violations: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if module == "loopx.cli_contract" or module.startswith(
                    "loopx.cli_contract."
                ):
                    continue
                if any(
                    module == prefix or module.startswith(prefix + ".")
                    for prefix in FORBIDDEN_PREFIXES
                ):
                    violations.append(f"{path.relative_to(PACKAGE_ROOT)}: {module}")
    assert not violations, violations


def test_cli_v2_never_mentions_legacy_handler_fallback() -> None:
    violations = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("handle_status_command", "handle_todo_command", "cli.main"):
            if forbidden in source:
                violations.append(f"{path.relative_to(PACKAGE_ROOT)}: {forbidden}")
    assert not violations, violations
