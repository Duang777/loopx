from __future__ import annotations

import json
from pathlib import Path


CORE_PATH = Path(__file__).parents[1] / "fixtures" / "cli_v2_parity" / "core.json"
PARITY_ROOT = CORE_PATH.parent
TYPED_CORE_ROWS = {
    "status",
    "todo list",
    "todo claim",
    "todo update",
    "todo complete",
    "task-lease acquire",
    "task-lease renew",
    "task-lease release",
    "task-lease inspect",
    "quota status",
    "quota plan",
    "quota should-run",
    "quota spend-slot",
    "quota void-slot",
}


def test_typed_core_rows_truthfully_record_the_remaining_external_parity_gap() -> None:
    payload = json.loads(CORE_PATH.read_text(encoding="utf-8"))
    rows = {row["command"]: {**payload["defaults"], **row} for row in payload["commands"]}

    assert TYPED_CORE_ROWS <= rows.keys()
    for command in sorted(TYPED_CORE_ROWS):
        row = rows[command]
        assert row["application_operation"]
        assert row["migration_status"] == "pending_migration"
        assert "success" in row["scenario_coverage"]
        assert {"json", "markdown", "stdout", "exit_code"} <= set(
            row["output_coverage"]
        )
        assert "typed_semantics_passed; cli_compatibility_view_missing" in row["evidence"]


def test_all_manifests_never_label_unwired_rows_as_migration_defects() -> None:
    for path in sorted(PARITY_ROOT.glob("*.json")):
        if path.name == "schema.json":
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = [{**payload["defaults"], **row} for row in payload["commands"]]
        assert all(
            row["migration_status"] == "pending"
            for row in rows
            if row["application_operation"] is None
        ), path.name
        assert all(
            row["application_operation"] is not None
            for row in rows
            if row["migration_status"] in {"pending_migration", "migrated"}
        ), path.name
        for row in rows:
            if row["migration_status"] != "migrated":
                continue
            assert "success" in row["scenario_coverage"], path.name
            if "error" not in row["scenario_coverage"]:
                assert "no_legal_failure_surface" in row["evidence"], (
                    path.name,
                    row["command"],
                )
            assert {"json", "markdown", "stdout", "stderr", "exit_code"} <= set(
                row["output_coverage"]
            ), path.name
            assert "typed_semantics_passed; cli_compatibility_view_missing" not in row[
                "evidence"
            ], path.name


def test_state_comparison_claims_have_isolated_differential_evidence() -> None:
    payload = json.loads(CORE_PATH.read_text(encoding="utf-8"))
    rows = {row["command"]: {**payload["defaults"], **row} for row in payload["commands"]}
    compared = {
        command
        for command, row in rows.items()
        if row["state_side_effect_comparison"]
    }

    assert compared == {"todo update", "task-lease release", "quota spend-slot"}
    for command in compared:
        assert any("test_state_semantics_parity.py" in item for item in rows[command]["evidence"])
