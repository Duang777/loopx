from __future__ import annotations

import copy
import json

import pytest

from loopx.control_plane.testing.cli_output_budget import measure_cli_output
from loopx.control_plane.testing.cli_output_differential import (
    CLI_OUTPUT_FIXTURE_CONTRACT_VERSION,
    CLI_OUTPUT_PROBE_SCHEMA_VERSION,
    compare_cli_output_receipts,
    compare_external_cli_receipts,
)
from loopx.control_plane.testing.cli_output_semantics import (
    action_signature_coverages,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "row_id": "surface/status/small/json",
        "surface_id": "status",
        "variant_id": None,
        "scenario": "small",
        "format": "json",
        "qualification_policy": "absolute_hot_path",
        "chars": 40_000,
        "utf8_bytes": 40_000,
        "lines": 1_000,
        "compact_payload_chars": 20_000,
        "semantic_json_keys": ["status_contract", "attention_queue"],
        "json_shape_paths": ["$", "$.status_contract", "$.attention_queue"],
        "markdown_headings": [],
        "markdown_anchor": "# LoopX Status",
        "action_signature_sha256": "semantic-signature",
        "action_signature_coverages": ["turn_envelope_action_dimensions_v0"],
    }
    row.update(overrides)
    return row


def _receipt(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": CLI_OUTPUT_PROBE_SCHEMA_VERSION,
        "fixture_contract_version": CLI_OUTPUT_FIXTURE_CONTRACT_VERSION,
        "rows": list(rows),
    }


def _external_receipt(
    stdout: str, *, exit_code: int = 0, stderr: str = ""
) -> dict[str, object]:
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}


def _external_json_receipt(**payload: object) -> dict[str, object]:
    return _external_receipt(json.dumps(payload))


_EXTERNAL_ISO_PATHS = (("generated_at",),)
_EXTERNAL_RANDOM_ID_PATHS = {("request_id",): r"req_[0-9a-f]{8}"}


def test_measurement_records_semantic_shape_without_runtime_hash_noise() -> None:
    def payload(runtime_hash: str, source_hash: str) -> str:
        return json.dumps(
            {
                "action": {"todo_id": "todo_fixture"},
                "action_signature": {
                    "schema_version": "loopx_action_signature_v0",
                    "coverage": "turn_envelope_action_dimensions_v0",
                    "source_hash": runtime_hash,
                    "envelope_hash": runtime_hash,
                    "source_decision_hash": source_hash,
                    "matches": True,
                },
            }
        )

    first = measure_cli_output(
        payload("first-runtime", "first-source"), output_format="json"
    )
    second = measure_cli_output(
        payload("second-runtime", "second-source"),
        output_format="json",
    )
    assert "$.action.todo_id" in first["json_shape_paths"]
    assert first["action_signature_sha256"] == second["action_signature_sha256"]
    assert action_signature_coverages(json.loads(payload("first", "source"))) == [
        "turn_envelope_action_dimensions_v0",
    ]

    with_observability_field = json.loads(payload("third-runtime", "third-source"))
    with_observability_field["action_signature"]["diagnostic_note"] = "new"
    third = measure_cli_output(
        json.dumps(with_observability_field),
        output_format="json",
    )
    assert first["action_signature_sha256"] == third["action_signature_sha256"]

    without_hash_pair = json.loads(payload("fourth-runtime", "fourth-source"))
    del without_hash_pair["action_signature"]["source_hash"]
    del without_hash_pair["action_signature"]["envelope_hash"]
    fourth = measure_cli_output(json.dumps(without_hash_pair), output_format="json")
    assert first["action_signature_sha256"] != fourth["action_signature_sha256"]

    markdown = measure_cli_output(
        "# LoopX Status\n\n## Attention Queue\n",
        output_format="markdown",
    )
    assert markdown["markdown_headings"] == ["# LoopX Status", "## Attention Queue"]


def test_unchanged_large_inherited_baseline_passes() -> None:
    base = _receipt(_row())
    result = compare_cli_output_receipts(base, copy.deepcopy(base))
    assert result["ok"] is True
    assert result["failed_row_count"] == 0


def test_growth_above_policy_allowance_fails() -> None:
    base = _receipt(_row())
    candidate = _receipt(_row(chars=41_000))
    result = compare_cli_output_receipts(base, candidate)
    assert result["ok"] is False
    assert "chars grew" in result["rows"][0]["failures"][0]


def test_shrink_with_semantic_shape_retained_passes() -> None:
    base = _receipt(_row())
    candidate = _receipt(
        _row(chars=20_000, utf8_bytes=20_000, lines=500, compact_payload_chars=10_000)
    )
    assert compare_cli_output_receipts(base, candidate)["ok"] is True


@pytest.mark.parametrize(
    ("candidate", "failure_fragment"),
    [
        (_row(semantic_json_keys=["status_contract"]), "semantic_json_keys removed"),
        (
            _row(action_signature_sha256="changed"),
            "action_signature semantic digest changed",
        ),
    ],
)
def test_smaller_candidate_still_fails_when_semantics_are_removed(
    candidate: dict[str, object],
    failure_fragment: str,
) -> None:
    candidate.update(chars=20_000, utf8_bytes=20_000, lines=500)
    result = compare_cli_output_receipts(_receipt(_row()), _receipt(candidate))
    assert result["ok"] is False
    assert any(failure_fragment in failure for failure in result["rows"][0]["failures"])


def test_declared_action_signature_coverage_migration_requires_review() -> None:
    candidate = _row(
        action_signature_sha256="versioned-semantic-signature",
        action_signature_coverages=["turn_envelope_action_dimensions_v1"],
    )

    result = compare_cli_output_receipts(_receipt(_row()), _receipt(candidate))

    assert result["ok"] is True
    assert result["review_required"] is True
    assert result["rows"][0]["review_signals"] == [
        "action_signature coverage migrated: "
        "turn_envelope_action_dimensions_v0 -> turn_envelope_action_dimensions_v1"
    ]


def test_unknown_action_signature_coverage_migration_fails_closed() -> None:
    candidate = _row(
        action_signature_sha256="unknown-semantic-signature",
        action_signature_coverages=["turn_envelope_action_dimensions_v2"],
    )

    result = compare_cli_output_receipts(_receipt(_row()), _receipt(candidate))

    assert result["ok"] is False
    assert result["rows"][0]["failures"] == ["action_signature semantic digest changed"]


def test_observed_shape_removal_is_a_review_signal_not_a_permanent_red_light() -> None:
    candidate = _row(json_shape_paths=["$", "$.status_contract"])
    candidate.update(chars=20_000, utf8_bytes=20_000, lines=500)
    result = compare_cli_output_receipts(_receipt(_row()), _receipt(candidate))
    assert result["ok"] is True
    assert result["review_required"] is True
    assert "json_shape_paths removed" in result["rows"][0]["review_signals"][0]


def test_markdown_heading_removal_requires_review() -> None:
    base_row = _row(
        row_id="surface/status/small/markdown",
        format="markdown",
        chars=2_000,
        utf8_bytes=2_000,
        lines=30,
        compact_payload_chars=None,
        semantic_json_keys=[],
        json_shape_paths=[],
        markdown_headings=["# LoopX Status", "## Attention Queue"],
        action_signature_sha256=None,
    )
    candidate = copy.deepcopy(base_row)
    candidate["markdown_headings"] = ["# LoopX Status"]
    result = compare_cli_output_receipts(_receipt(base_row), _receipt(candidate))
    assert result["ok"] is True
    assert result["review_required"] is True
    assert "markdown_headings removed" in result["rows"][0]["review_signals"][0]


def test_candidate_only_row_is_allowed_but_base_row_removal_fails() -> None:
    extra = _row(row_id="surface/new/small/json", surface_id="new")
    candidate_only = compare_cli_output_receipts(_receipt(), _receipt(extra))
    assert candidate_only["ok"] is True
    assert candidate_only["candidate_only_row_count"] == 1

    removed = compare_cli_output_receipts(_receipt(_row()), _receipt())
    assert removed["ok"] is False
    assert "missing from candidate" in removed["rows"][0]["failures"][0]


def test_fixture_contract_mismatch_fails_closed() -> None:
    candidate = _receipt(_row())
    candidate["fixture_contract_version"] = "different"
    with pytest.raises(ValueError, match="fixture_contract_version"):
        compare_cli_output_receipts(_receipt(_row()), candidate)


def test_external_json_receipt_normalizes_only_declared_runtime_values() -> None:
    baseline = _external_json_receipt(
        status="ready",
        generated_at="2026-08-07T10:11:12Z",
        request_id="req_a1b2c3d4",
        artifact="fixture-baseline/report.json",
    )
    candidate = _external_json_receipt(
        artifact="fixture-candidate/report.json",
        request_id="req_0123abcd",
        generated_at="2026-08-07T10:12:13+00:00",
        status="ready",
    )

    assert (
        compare_external_cli_receipts(
            baseline,
            candidate,
            output_format="json",
            baseline_temp_root="fixture-baseline",
            candidate_temp_root="fixture-candidate",
            iso_time_paths=_EXTERNAL_ISO_PATHS,
            random_id_paths=_EXTERNAL_RANDOM_ID_PATHS,
        )
        == []
    )


def test_external_json_receipt_does_not_hide_business_field_changes() -> None:
    baseline = _external_json_receipt(
        status="ready",
        generated_at="2026-08-07T10:11:12Z",
        request_id="req_a1b2c3d4",
    )
    candidate = _external_json_receipt(
        status="blocked",
        generated_at="2026-08-07T10:12:13Z",
        request_id="req_0123abcd",
    )

    assert compare_external_cli_receipts(
        baseline,
        candidate,
        output_format="json",
        iso_time_paths=_EXTERNAL_ISO_PATHS,
        random_id_paths=_EXTERNAL_RANDOM_ID_PATHS,
    ) == ["stdout"]


@pytest.mark.parametrize(
    ("candidate_payload", "failure"),
    [
        (
            {"request_id": "req_0123abcd"},
            "normalization path is missing",
        ),
        (
            {"generated_at": "2026-08-07T10:12:13Z", "request_id": 123},
            "normalization path is not a string",
        ),
        (
            {
                "generated_at": "2026-08-07T10:12:13Z",
                "request_id": "ordinary-business-value",
            },
            "normalization value failed validation",
        ),
        (
            {"generated_at": "not-a-time", "request_id": "req_0123abcd"},
            "normalization value failed validation",
        ),
    ],
)
def test_external_json_receipt_normalization_paths_fail_closed(
    candidate_payload: dict[str, object],
    failure: str,
) -> None:
    baseline = _external_json_receipt(
        generated_at="2026-08-07T10:11:12Z",
        request_id="req_a1b2c3d4",
    )

    with pytest.raises(ValueError, match=failure):
        compare_external_cli_receipts(
            baseline,
            _external_receipt(json.dumps(candidate_payload)),
            output_format="json",
            iso_time_paths=_EXTERNAL_ISO_PATHS,
            random_id_paths=_EXTERNAL_RANDOM_ID_PATHS,
        )


@pytest.mark.parametrize(
    ("baseline_stdout", "candidate_stdout", "failure"),
    [
        (
            '{"status":"ready"}',
            '{"status":"blocked","status":"ready"}',
            "duplicate JSON object key: status",
        ),
        ('{"value":0}', '{"value":NaN}', "non-standard JSON constant: NaN"),
        (
            '{"value":0}',
            '{"value":Infinity}',
            "non-standard JSON constant: Infinity",
        ),
        (
            '{"value":0}',
            '{"value":-Infinity}',
            "non-standard JSON constant: -Infinity",
        ),
    ],
)
def test_external_json_receipt_rejects_ambiguous_or_nonstandard_json(
    baseline_stdout: str,
    candidate_stdout: str,
    failure: str,
) -> None:
    with pytest.raises(ValueError, match=failure):
        compare_external_cli_receipts(
            _external_receipt(baseline_stdout),
            _external_receipt(candidate_stdout),
            output_format="json",
        )


@pytest.mark.parametrize("output_format", ["markdown", "text"])
def test_external_text_receipt_only_replaces_declared_temp_roots(
    output_format: str,
) -> None:
    baseline = _external_receipt("artifact: fixture-baseline/report\nid: stable\n")
    candidate = _external_receipt("artifact: fixture-candidate/report\nid: stable\n")
    assert compare_external_cli_receipts(
        baseline, candidate, output_format=output_format
    ) == ["stdout"]
    assert (
        compare_external_cli_receipts(
            baseline,
            candidate,
            output_format=output_format,
            baseline_temp_root="fixture-baseline",
            candidate_temp_root="fixture-candidate",
        )
        == []
    )

    changed = _external_receipt("artifact: fixture-candidate/report\nid: changed\n")
    assert compare_external_cli_receipts(
        baseline,
        changed,
        output_format=output_format,
        baseline_temp_root="fixture-baseline",
        candidate_temp_root="fixture-candidate",
    ) == ["stdout"]
    with pytest.raises(ValueError, match="only supported for JSON"):
        compare_external_cli_receipts(
            baseline,
            candidate,
            output_format=output_format,
            iso_time_paths=(("generated_at",),),
        )


def test_external_receipt_detects_exit_code_and_stderr_changes() -> None:
    baseline = _external_receipt("same output\n")
    candidate = _external_receipt(
        "same output\n", exit_code=2, stderr="unexpected warning\n"
    )

    assert compare_external_cli_receipts(baseline, candidate, output_format="text") == [
        "exit_code",
        "stderr",
    ]
