from __future__ import annotations

import builtins
import io
import json
import os
import socket
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from loopx.application.agents import (
    AgentProviders,
    AgentServices,
    CoreWorkerBridgeProvider,
)
from loopx.application.benchmarks import (
    BenchmarkProviders,
    BenchmarkServices,
    CoreBenchmarkInspectionProvider,
    CoreSplitControlBenchmarkProvider,
)
from loopx.application.maintenance import (
    CoreCanaryProvider,
    MaintenanceProviders,
    MaintenanceServices,
)
from loopx.cli_v2.entrypoint import main as v2_main
from loopx.cli_v2.maintainer_benchmark_agent import (
    MAINTAINER_BENCHMARK_AGENT_COHORT,
)
from loopx.cli_v2.maintainer_benchmark_agent.handlers import (
    handle_active_user_intervention,
    handle_benchmark_artifact_inspection,
    handle_benchmark_candidate_source_boundary,
    handle_benchmark_parity_check,
    handle_worker_bridge_contract,
    handle_worker_bridge_outcome,
)
from loopx.control_plane.testing.cli_output_differential import (
    compare_external_cli_receipts,
)
from loopx.entrypoint import main as legacy_main

from .fixture_data import (
    active_user_simulator_output_fixture,
    command_adapter_fixture,
    parity_benchmark_run_fixture,
    split_control_readiness_fixture,
)


REPOSITORY_ROOT = Path(__file__).parents[3]


@dataclass(frozen=True)
class _Root:
    agents: AgentServices
    maintenance: MaintenanceServices
    benchmarks: BenchmarkServices


class _WorkerProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = CoreWorkerBridgeProvider()

    def build_contract(self, request):
        self.calls.append("contract")
        return self.delegate.build_contract(request)

    def build_outcome(self, request):
        self.calls.append("outcome")
        return self.delegate.build_outcome(request)

    def build_active_user_intervention(self, request):
        self.calls.append("active_user_intervention")
        return self.delegate.build_active_user_intervention(request)

    def build_active_user_simulator_output(self, request):
        self.calls.append("active_user_simulator_output")
        return self.delegate.build_active_user_simulator_output(request)


class _CanaryProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = CoreCanaryProvider()

    def profiles(self, request):
        self.calls.append("profiles")
        return self.delegate.profiles(request)

    def smoke_profiles(self, request):
        self.calls.append("smoke_profiles")
        return self.delegate.smoke_profiles(request)


class _BenchmarkProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = CoreSplitControlBenchmarkProvider()

    def execution_seam(self, request):
        self.calls.append("execution_seam")
        return self.delegate.execution_seam(request)


class _BenchmarkInspectionProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.delegate = CoreBenchmarkInspectionProvider()

    def classify_artifacts(self, request):
        self.calls.append("classify_artifacts")
        return self.delegate.classify_artifacts(request)

    def candidate_source_boundary(self, request):
        self.calls.append("candidate_source_boundary")
        return self.delegate.candidate_source_boundary(request)

    def parity_check(self, request):
        self.calls.append("parity_check")
        return self.delegate.parity_check(request)


def _root(
    *,
    worker=None,
    canary=None,
    benchmark=None,
    inspection=None,
) -> _Root:
    return _Root(
        agents=AgentServices(
            AgentProviders(worker_bridge=worker or CoreWorkerBridgeProvider())
        ),
        maintenance=MaintenanceServices(
            MaintenanceProviders(canary=canary or CoreCanaryProvider())
        ),
        benchmarks=BenchmarkServices(
            BenchmarkProviders(
                split_control=benchmark or CoreSplitControlBenchmarkProvider(),
                inspection=inspection or CoreBenchmarkInspectionProvider(),
            )
        ),
    )


def _write_benchmark_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    readiness = tmp_path / "readiness.json"
    adapters = tmp_path / "adapters.json"
    readiness.write_text(
        json.dumps(split_control_readiness_fixture()),
        encoding="utf-8",
    )
    adapters.write_text(
        json.dumps(command_adapter_fixture()),
        encoding="utf-8",
    )
    return readiness, adapters


def _write_second_batch_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    simulator = tmp_path / "simulator-output.json"
    benchmark_run = tmp_path / "benchmark-run.json"
    simulator.write_text(
        json.dumps(active_user_simulator_output_fixture()),
        encoding="utf-8",
    )
    benchmark_run.write_text(
        json.dumps(parity_benchmark_run_fixture()),
        encoding="utf-8",
    )
    return simulator, benchmark_run


def _cases(tmp_path: Path) -> tuple[list[str], ...]:
    readiness, adapters = _write_benchmark_fixtures(tmp_path)
    simulator, benchmark_run = _write_second_batch_fixtures(tmp_path)
    return (
        ["--format", "json", "worker-bridge", "contract"],
        [
            "--format",
            "json",
            "worker-bridge",
            "outcome",
            "--worker-cli-call-total",
            "2",
            "--counter-trace-present",
            "--runner-return-completed",
            "--official-score-completed",
            "--official-score-value",
            "1",
        ],
        ["--format", "json", "canary", "profiles"],
        ["--format", "json", "canary", "smoke-profiles"],
        [
            "--format",
            "json",
            "worker-bridge",
            "active-user-intervention",
            "--seq",
            "7",
            "--message",
            "Inspect the public failure summary.",
        ],
        [
            "--format",
            "json",
            "worker-bridge",
            "active-user-simulator-output",
            "--seq",
            "8",
            "--simulator-output-json",
            str(simulator),
        ],
        [
            "--format",
            "json",
            "benchmark",
            "split-control-execution-seam",
            "--readiness-json",
            str(readiness),
            "--command-adapter-json",
            str(adapters),
        ],
        [
            "--format",
            "json",
            "benchmark",
            "parity-check",
            "--benchmark-run-json",
            str(benchmark_run),
        ],
        [
            "--format",
            "json",
            "benchmark",
            "classify-artifacts",
            "reports/result.compact.json",
            "runs/agent/trajectory.json",
        ],
        [
            "--format",
            "json",
            "benchmark",
            "candidate-source-boundary",
            "docs/benchmark.md",
            "runs/tasks/task.md",
        ],
    )


def test_all_ten_bindings_dispatch_to_explicit_typed_providers(
    tmp_path: Path,
) -> None:
    worker = _WorkerProvider()
    canary = _CanaryProvider()
    benchmark = _BenchmarkProvider()
    inspection = _BenchmarkInspectionProvider()
    root = _root(
        worker=worker,
        canary=canary,
        benchmark=benchmark,
        inspection=inspection,
    )
    for argv in _cases(tmp_path):
        output = io.StringIO()
        assert (
            v2_main(
                argv,
                application_factory=lambda _args, _registry: root,
                cohorts=(MAINTAINER_BENCHMARK_AGENT_COHORT,),
                stdout=output,
            )
            == 0
        )
        assert isinstance(json.loads(output.getvalue()), dict)
    assert worker.calls == [
        "contract",
        "outcome",
        "active_user_intervention",
        "active_user_simulator_output",
    ]
    assert canary.calls == ["profiles", "smoke_profiles"]
    assert benchmark.calls == ["execution_seam"]
    assert inspection.calls == [
        "parity_check",
        "classify_artifacts",
        "candidate_source_boundary",
    ]


def _capture_exit_code(call: Callable[[], int]) -> int:
    try:
        return call()
    except SystemExit as exc:
        if not isinstance(exc.code, int):
            raise AssertionError("argparse returned a non-integer exit code") from exc
        return exc.code


def _legacy_receipt(argv: list[str]) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = _capture_exit_code(lambda: legacy_main(argv))
    return {
        "exit_code": exit_code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }


def _v2_receipt(argv: list[str], root: _Root) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = _capture_exit_code(
            lambda: v2_main(
                argv,
                application_factory=lambda _args, _registry: root,
                cohorts=(MAINTAINER_BENCHMARK_AGENT_COHORT,),
                stdout=stdout,
                stderr=stderr,
            )
        )
    return {
        "exit_code": exit_code,
        "stdout": stdout.getvalue(),
        "stderr": stderr.getvalue(),
    }


def test_json_stdout_stderr_and_exit_differential_for_safe_batches(
    tmp_path: Path,
) -> None:
    root = _root()
    for argv in _cases(tmp_path):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, root)
        assert candidate == legacy, argv
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="json",
        ) == [], argv


def test_classify_artifacts_json_and_markdown_receipts_are_exact() -> None:
    base_argv = [
        "benchmark",
        "classify-artifacts",
        "reports/result.compact.json",
        "runs/agent/trajectory.json",
        "--adapter-kind",
        "terminal-bench",
        "--allow-public-filename",
        "summary.json",
    ]
    for format_name in ("json", "markdown"):
        argv = ["--format", format_name, *base_argv]
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == 0
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format=format_name,
        ) == []


def test_classify_artifacts_help_and_missing_argument_receipts_are_exact() -> None:
    for argv, expected_exit in (
        (["benchmark", "classify-artifacts", "--help"], 0),
        (["benchmark", "classify-artifacts"], 2),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_classify_artifacts_handler_is_format_agnostic() -> None:
    class FormatGuardArgs:
        artifact_paths = ("reports/result.compact.json",)
        adapter_kind = "default"
        allow_public_filename: tuple[str, ...] = ()

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

    outcome = handle_benchmark_artifact_inspection(FormatGuardArgs(), _root())
    assert outcome.exit_code == 0
    assert outcome.payload["allowed_artifact_basenames"] == [
        "result.compact.json"
    ]


def _forbid_read_write_process_or_network(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("benchmark boundary crossed its no-I/O contract")

    monkeypatch.setattr(builtins, "open", forbidden)
    for method in (
        "open",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "touch",
        "mkdir",
        "rename",
        "replace",
        "unlink",
    ):
        monkeypatch.setattr(Path, method, forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)


def test_worker_bridge_contract_json_markdown_paths_and_side_effects_are_exact(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    public_argv = [
        "worker-bridge",
        "contract",
        "--project-root",
        "/workspace/loopx",
        "--runtime-root",
        "/runtime/loopx",
        "--python-bin",
        "/usr/bin/python3",
        "--module",
        "loopx.cli",
        "--scan-path",
        "/workspace/loopx/loopx/benchmark.py",
        "--benchmark-run-json",
        "/worker-public/benchmark-run.json",
        "--counter-trace-json",
        "/worker-public/counter-trace.jsonl",
        "--classification",
        "public_fixture",
    ]
    for format_name in ("json", "markdown"):
        argv = ["--format", format_name, *public_argv]
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == 0
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format=format_name,
        ) == []
        rendered = str(candidate["stdout"])
        assert str(REPOSITORY_ROOT) not in rendered
        if format_name == "json":
            payload = json.loads(rendered)
            assert payload["project_root"] == "/workspace/loopx"
            assert payload["runtime_root"] == "/runtime/loopx"
            assert payload["active_user_external_update_mount"][
                "raw_host_path_recorded"
            ] is False
            assert payload["boundary"] == {
                "real_run": False,
                "submit_eligible": False,
                "no_upload": True,
                "credential_values_recorded": False,
                "raw_paths_required_in_public_artifacts": False,
            }


def test_worker_bridge_contract_help_and_argparse_error_are_exact() -> None:
    for argv, expected_exit in (
        (["worker-bridge", "contract", "--help"], 0),
        (["worker-bridge", "contract", "--project-root"], 2),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_worker_bridge_contract_handler_is_format_agnostic_and_success_only() -> None:
    class FormatGuardArgs:
        project_root = "/workspace/loopx"
        worker_bridge_runtime_root = "/runtime/loopx"
        python_bin = "/usr/bin/python3"
        module = "loopx.cli"
        scan_path = "/workspace/loopx/loopx/benchmark.py"
        benchmark_run_json = "/worker-public/benchmark-run.json"
        counter_trace_json = "/worker-public/counter-trace.jsonl"
        classification = "public_fixture"

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

    outcome = handle_worker_bridge_contract(FormatGuardArgs(), _root())
    assert outcome.exit_code == 0
    assert outcome.payload["ok"] is True
    assert outcome.payload["project_root"] == "/workspace/loopx"


def test_worker_bridge_outcome_complete_and_incomplete_receipts_are_exact(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    scenarios = (
        ([], False, "worker_bridge_evidence_missing", "not_ready"),
        (
            [
                "--worker-cli-call-total",
                "2",
                "--counter-trace-present",
                "--runner-return-completed",
                "--official-score-completed",
                "--official-score-value",
                "1",
            ],
            True,
            "completed",
            "completed",
        ),
    )
    expected_json_keys = [
        "ok",
        "schema_version",
        "bridge_surface",
        "worker_bridge_verified",
        "runner_return_status",
        "official_score_status",
        "worker_loopx_cli_call_total",
        "required_worker_loopx_cli_call_total_min",
        "counter_trace_present",
        "runner_return_completed",
        "official_score_completed",
        "official_score_value",
        "side_effect_audit_passed",
        "wall_time_policy",
        "failure_attribution_labels",
        "claim_boundary",
        "next_action",
        "trace_publicness",
        "raw_paths_recorded",
        "raw_trace_recorded",
        "credential_values_recorded",
    ]
    for scenario, verified, runner_status, score_status in scenarios:
        for format_name in ("json", "markdown"):
            argv = [
                "--format",
                format_name,
                "worker-bridge",
                "outcome",
                *scenario,
            ]
            legacy = _legacy_receipt(argv)
            candidate = _v2_receipt(argv, _root())
            assert legacy["exit_code"] == 0
            assert candidate == legacy
            assert compare_external_cli_receipts(
                legacy,
                candidate,
                output_format=format_name,
            ) == []
            assert candidate["stderr"] == ""
            rendered = str(candidate["stdout"])
            if format_name == "json":
                assert rendered.endswith("\n")
                payload = json.loads(rendered)
                assert list(payload) == expected_json_keys
                assert payload["ok"] is True
                assert payload["worker_bridge_verified"] is verified
                assert payload["runner_return_status"] == runner_status
                assert payload["official_score_status"] == score_status
                assert payload["raw_paths_recorded"] is False
                assert payload["raw_trace_recorded"] is False
                assert payload["credential_values_recorded"] is False
            else:
                assert rendered.endswith("\n\n")


def test_worker_bridge_outcome_help_and_argparse_error_are_exact() -> None:
    for argv, expected_exit in (
        (["worker-bridge", "outcome", "--help"], 0),
        (
            [
                "worker-bridge",
                "outcome",
                "--worker-cli-call-total",
                "not-an-int",
            ],
            2,
        ),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_worker_bridge_outcome_handler_is_format_agnostic() -> None:
    class FormatGuardArgs:
        required_worker_cli_call_total_min = 1
        interrupted = False
        interrupt_reason = ""
        wall_time_seconds = None
        wall_time_limit_seconds = 900.0
        side_effect_audit_failed = False

        def __init__(self, *, complete: bool) -> None:
            self.worker_cli_call_total = 2 if complete else 0
            self.counter_trace_present = complete
            self.runner_return_completed = complete
            self.official_score_completed = complete
            self.official_score_value = 1.0 if complete else None

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

    complete = handle_worker_bridge_outcome(
        FormatGuardArgs(complete=True),
        _root(),
    )
    assert complete.exit_code == 0
    assert complete.payload["ok"] is True
    assert complete.payload["worker_bridge_verified"] is True
    assert complete.payload["runner_return_status"] == "completed"

    incomplete = handle_worker_bridge_outcome(
        FormatGuardArgs(complete=False),
        _root(),
    )
    assert incomplete.exit_code == 0
    assert incomplete.payload["ok"] is True
    assert incomplete.payload["worker_bridge_verified"] is False
    assert (
        incomplete.payload["runner_return_status"]
        == "worker_bridge_evidence_missing"
    )


def test_active_user_intervention_json_markdown_and_boundaries_are_exact(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    base_argv = [
        "worker-bridge",
        "active-user-intervention",
        "--seq",
        "7",
        "--message",
        "Inspect public evidence.",
        "--trigger",
        "public_progress_or_stall_signal",
        "--channel",
        "codex_cli_user_simulator",
        "--before-worker-start",
    ]
    expected_keys = [
        "ok",
        "schema_version",
        "channel_surface",
        "seq",
        "channel",
        "type",
        "trigger",
        "message",
        "created_after_worker_start",
        "oracle_free",
        "hidden_tests_visible",
        "expected_solution_visible",
        "credential_values_visible",
        "private_material_visible",
        "official_score_claim_allowed",
        "leaderboard_claim_allowed",
    ]
    for format_name in ("json", "markdown"):
        argv = ["--format", format_name, *base_argv]
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == 0
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format=format_name,
        ) == []
        assert candidate["stderr"] == ""
        rendered = str(candidate["stdout"])
        if format_name == "json":
            assert rendered.endswith("\n")
            payload = json.loads(rendered)
            assert list(payload) == expected_keys
            assert payload["message"] == "Inspect public evidence."
            assert payload["created_after_worker_start"] is False
            assert payload["oracle_free"] is True
            for boundary_key in (
                "hidden_tests_visible",
                "expected_solution_visible",
                "credential_values_visible",
                "private_material_visible",
                "official_score_claim_allowed",
                "leaderboard_claim_allowed",
            ):
                assert payload[boundary_key] is False
        else:
            assert rendered.endswith("\n\n")
            assert "Inspect public evidence." not in rendered


def test_active_user_intervention_jsonl_override_is_exact(monkeypatch) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    command = [
        "worker-bridge",
        "active-user-intervention",
        "--seq",
        "8",
        "--message",
        "Continue from public evidence only.",
        "--jsonl",
    ]
    cases = (
        command,
        ["--format", "json", *command],
        ["--format", "markdown", *command],
        [*command[:-1], "--format", "json", "--jsonl"],
    )
    for argv in cases:
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == 0
        assert candidate == legacy
        assert candidate["stderr"] == ""
        rendered = str(candidate["stdout"])
        assert rendered.count("\n") == 1
        payload = json.loads(rendered)
        assert list(payload) == sorted(payload)
        assert payload["message"] == "Continue from public evidence only."
        assert payload["oracle_free"] is True
        assert payload["private_material_visible"] is False


def test_active_user_intervention_invalid_private_text_is_exact_and_not_echoed(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    private_text = "Inspect .local/private-simulator-transcript"
    command = [
        "worker-bridge",
        "active-user-intervention",
        "--seq",
        "9",
        "--message",
        private_text,
    ]
    cases = (
        (["--format", "json", *command], "json"),
        (["--format", "markdown", *command], "markdown"),
        ([*command, "--jsonl"], "markdown"),
        (["--format", "json", *command, "--jsonl"], "json"),
    )
    for argv, format_name in cases:
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == 1
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format=format_name,
        ) == []
        assert candidate["stderr"] == ""
        rendered = str(candidate["stdout"])
        assert private_text not in rendered
        assert "private-simulator-transcript" not in rendered
        if format_name == "json":
            payload = json.loads(rendered)
            assert list(payload) == ["ok", "mode", "error"]
            assert payload == {
                "ok": False,
                "mode": "worker-bridge",
                "error": "message contains a non-public marker",
            }
        else:
            assert rendered.endswith("\n\n")


def test_active_user_intervention_help_and_argparse_error_are_exact() -> None:
    for argv, expected_exit in (
        (["worker-bridge", "active-user-intervention", "--help"], 0),
        (["worker-bridge", "active-user-intervention", "--seq", "7"], 2),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_active_user_intervention_handler_is_transport_agnostic() -> None:
    class FormatGuardArgs:
        seq = 10
        message = "Use public progress evidence."
        trigger = "public_progress_or_stall_signal"
        channel = "codex_cli_user_simulator"
        before_worker_start = False

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

        @property
        def jsonl(self) -> bool:
            raise AssertionError("typed handler read args.jsonl")

    outcome = handle_active_user_intervention(FormatGuardArgs(), _root())
    assert outcome.exit_code == 0
    assert outcome.payload["ok"] is True
    assert outcome.payload["oracle_free"] is True
    assert outcome.payload["created_after_worker_start"] is True
    assert outcome.payload["hidden_tests_visible"] is False
    assert outcome.payload["expected_solution_visible"] is False
    assert outcome.payload["credential_values_visible"] is False
    assert outcome.payload["private_material_visible"] is False
    assert outcome.payload["official_score_claim_allowed"] is False
    assert outcome.payload["leaderboard_claim_allowed"] is False


def test_parity_check_json_and_markdown_success_and_failure_are_exact(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "benchmark-run.json"
    invalid = tmp_path / "invalid-benchmark-run.json"
    valid.write_text(json.dumps(parity_benchmark_run_fixture()), encoding="utf-8")
    invalid.write_text("{}", encoding="utf-8")
    for path, expected_exit in ((valid, 0), (invalid, 1)):
        for format_name in ("json", "markdown"):
            argv = [
                "--format",
                format_name,
                "benchmark",
                "parity-check",
                "--benchmark-run-json",
                str(path),
            ]
            legacy = _legacy_receipt(argv)
            candidate = _v2_receipt(argv, _root())
            assert legacy["exit_code"] == expected_exit
            assert candidate == legacy
            assert compare_external_cli_receipts(
                legacy,
                candidate,
                output_format=format_name,
            ) == []


def test_parity_check_help_and_missing_argument_receipts_are_exact() -> None:
    for argv, expected_exit in (
        (["benchmark", "parity-check", "--help"], 0),
        (["benchmark", "parity-check"], 2),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_parity_check_handler_is_format_agnostic(tmp_path: Path) -> None:
    benchmark_run = tmp_path / "benchmark-run.json"
    benchmark_run.write_text(
        json.dumps(parity_benchmark_run_fixture()),
        encoding="utf-8",
    )

    class FormatGuardArgs:
        benchmark_run_json = str(benchmark_run)

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

    outcome = handle_benchmark_parity_check(FormatGuardArgs(), _root())
    assert outcome.exit_code == 0
    assert outcome.payload["ok"] is True


def test_parity_check_only_reads_compact_input_and_has_no_side_effects(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    scenarios = (
        (json.dumps(parity_benchmark_run_fixture()), 0),
        ("{}", 1),
    )
    for raw_input, expected_exit in scenarios:
        for format_name in ("json", "markdown"):
            argv = [
                "--format",
                format_name,
                "benchmark",
                "parity-check",
                "--benchmark-run-json",
                "-",
            ]
            monkeypatch.setattr(sys, "stdin", io.StringIO(raw_input))
            legacy = _legacy_receipt(argv)
            monkeypatch.setattr(sys, "stdin", io.StringIO(raw_input))
            candidate = _v2_receipt(argv, _root())
            assert legacy["exit_code"] == expected_exit
            assert candidate == legacy
            rendered = str(candidate["stdout"])
            assert "/app/.codex/goals/fixture" not in rendered
            if format_name == "json" and expected_exit == 0:
                payload = json.loads(rendered)["codex_app_parity_posthoc_check"]
                assert payload["read_boundary"] == {
                    "compact_benchmark_run_only": True,
                    "raw_task_text_read": False,
                    "raw_logs_read": False,
                    "raw_trajectory_read": False,
                    "verifier_output_read": False,
                    "credentials_read": False,
                    "local_paths_recorded": False,
                }


def test_classify_artifacts_has_no_read_write_process_network_or_path_leak(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    private_paths = (
        "/owner-private/run-42/reports/result.compact.json",
        "/owner-private/run-42/raw/trajectory.json",
    )
    for format_name in ("json", "markdown"):
        output = io.StringIO()
        assert (
            v2_main(
                [
                    "--format",
                    format_name,
                    "benchmark",
                    "classify-artifacts",
                    *private_paths,
                ],
                application_factory=lambda _args, _registry: _root(),
                cohorts=(MAINTAINER_BENCHMARK_AGENT_COHORT,),
                stdout=output,
            )
            == 0
        )
        rendered = output.getvalue()
        assert "owner-private" not in rendered
        assert all(path not in rendered for path in private_paths)


def test_candidate_source_json_and_markdown_success_and_error_are_exact() -> None:
    scenarios = (
        (["docs/benchmark.md"], 0),
        (["docs/benchmark.md", "runs/tasks/task.md", "--require-clean"], 1),
    )
    for scenario_argv, expected_exit in scenarios:
        for format_name in ("json", "markdown"):
            argv = [
                "--format",
                format_name,
                "benchmark",
                "candidate-source-boundary",
                *scenario_argv,
            ]
            legacy = _legacy_receipt(argv)
            candidate = _v2_receipt(argv, _root())
            assert legacy["exit_code"] == expected_exit
            assert candidate == legacy
            assert compare_external_cli_receipts(
                legacy,
                candidate,
                output_format=format_name,
            ) == []


def test_candidate_source_help_and_missing_argument_receipts_are_exact() -> None:
    for argv, expected_exit in (
        (["benchmark", "candidate-source-boundary", "--help"], 0),
        (["benchmark", "candidate-source-boundary"], 2),
    ):
        legacy = _legacy_receipt(argv)
        candidate = _v2_receipt(argv, _root())
        assert legacy["exit_code"] == expected_exit
        assert candidate == legacy
        assert compare_external_cli_receipts(
            legacy,
            candidate,
            output_format="markdown",
        ) == []


def test_candidate_source_handler_is_format_agnostic() -> None:
    class FormatGuardArgs:
        source_paths = ("docs/benchmark.md",)
        adapter_kind = "default"
        allow_public_filename: tuple[str, ...] = ()
        require_clean = False

        @property
        def format(self) -> str:
            raise AssertionError("transport handler read args.format")

    outcome = handle_benchmark_candidate_source_boundary(
        FormatGuardArgs(),
        _root(),
    )
    assert outcome.exit_code == 0
    assert outcome.payload["clean"] is True
    assert outcome.payload["allowed_source_basenames"] == ["benchmark.md"]


def test_candidate_source_has_no_read_write_process_network_or_path_leak(
    monkeypatch,
) -> None:
    _forbid_read_write_process_or_network(monkeypatch)
    scenarios = (
        (
            "/sensitive-origin/reference/docs/benchmark.md",
            0,
            False,
        ),
        (
            "/sensitive-origin/runs/tasks/task.md",
            1,
            True,
        ),
    )
    for source_path, expected_exit, require_clean in scenarios:
        for format_name in ("json", "markdown"):
            argv = [
                "--format",
                format_name,
                "benchmark",
                "candidate-source-boundary",
                source_path,
            ]
            if require_clean:
                argv.append("--require-clean")
            legacy = _legacy_receipt(argv)
            candidate = _v2_receipt(argv, _root())
            assert legacy["exit_code"] == expected_exit
            assert candidate == legacy
            rendered = str(candidate["stdout"])
            assert "sensitive-origin" not in rendered
            assert source_path not in rendered
            if format_name == "json":
                payload = json.loads(rendered)
                assert payload["path_recorded"] is False
                assert not any(payload["read_boundary"].values())


def test_safe_batches_have_no_process_network_or_shell_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("safe T7C first batch attempted an external call")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    root = _root()
    payloads: list[dict[str, object]] = []
    for argv in _cases(tmp_path):
        output = io.StringIO()
        assert (
            v2_main(
                argv,
                application_factory=lambda _args, _registry: root,
                cohorts=(MAINTAINER_BENCHMARK_AGENT_COHORT,),
                stdout=output,
            )
            == 0
        )
        payloads.append(json.loads(output.getvalue()))

    assert payloads[2]["executes_checks"] is False
    assert payloads[3]["executes_checks"] is False
    assert payloads[3]["writes_evidence"] is False
    assert payloads[4]["official_score_claim_allowed"] is False
    assert payloads[4]["leaderboard_claim_allowed"] is False
    assert payloads[5]["formal_treatment_eligible"] is True
    assert not any(payloads[5]["no_oracle_audit"].values())
    seam = payloads[6]
    assert seam["dry_run"] is True
    assert seam["boundary"]["upload_allowed"] is False
    assert seam["boundary"]["submit_allowed"] is False
    assert seam["boundary"]["shell_commands_embedded"] is False
    assert seam["boundary"]["argv_embedded"] is False
    assert seam["read_boundary"] == {
        "compact_only": True,
        "readiness_json_read": True,
        "command_adapter_json_read": True,
        "command_adapter_wrapper_unwrapped": True,
        "raw_task_text_read": False,
        "raw_logs_read": False,
        "trajectory_read": False,
        "shell_commands_read": False,
        "docker_invoked": False,
        "model_api_invoked": False,
        "upload_invoked": False,
        "submit_invoked": False,
    }
    parity = payloads[7]["codex_app_parity_posthoc_check"]
    assert parity["read_boundary"] == {
        "compact_benchmark_run_only": True,
        "raw_task_text_read": False,
        "raw_logs_read": False,
        "raw_trajectory_read": False,
        "verifier_output_read": False,
        "credentials_read": False,
        "local_paths_recorded": False,
    }
    assert payloads[8]["public_boundary"]["full_paths_recorded"] is False
    assert payloads[9]["read_boundary"]["files_opened"] is False

    benchmark_text = json.dumps(payloads[7:10], sort_keys=True)
    for raw_input in (
        "/app/.codex/goals/fixture/ACTIVE_GOAL_STATE.md",
        "reports/result.compact.json",
        "runs/agent/trajectory.json",
        "docs/benchmark.md",
        "runs/tasks/task.md",
    ):
        assert raw_input not in benchmark_text

    def nested_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                key
                for child in value.values()
                for key in nested_keys(child)
            }
        if isinstance(value, list):
            return {
                key for child in value for key in nested_keys(child)
            }
        return set()

    second_batch_keys = nested_keys(payloads[4:6] + payloads[7:10])
    assert not any("argv" in key or "shell" in key for key in second_batch_keys)
    assert not any(key.startswith("upload") for key in second_batch_keys)
    assert not any(key.startswith("submit") for key in second_batch_keys)
