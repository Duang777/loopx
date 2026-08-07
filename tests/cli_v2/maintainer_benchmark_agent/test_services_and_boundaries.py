from __future__ import annotations

from dataclasses import fields, replace
from typing import get_type_hints

import pytest

from loopx.application.agents import (
    CoreWorkerBridgeProvider,
    WorkerBridgeActiveUserIntervention,
    WorkerBridgeActiveUserInterventionRequest,
    WorkerBridgeActiveUserSimulatorIntervention,
    WorkerBridgeActiveUserSimulatorOutputRequest,
    WorkerBridgeContractRequest,
    WorkerBridgeInstallContract,
    WorkerBridgeOutcome,
    WorkerBridgeOutcomeRequest,
    WorkerBridgeProvider,
    WorkerBridgeService,
    parse_active_user_simulator_output,
)
from loopx.application.benchmarks import (
    BenchmarkArtifactInspection,
    BenchmarkArtifactInspectionRequest,
    BenchmarkCandidateSourceBoundary,
    BenchmarkCandidateSourceBoundaryRequest,
    BenchmarkInspectionProvider,
    BenchmarkInspectionService,
    BenchmarkParityCheck,
    BenchmarkParityCheckRequest,
    CoreBenchmarkInspectionProvider,
    CoreSplitControlBenchmarkProvider,
    SplitControlBenchmarkProvider,
    SplitControlBenchmarkService,
    SplitControlExecutionSeam,
    SplitControlExecutionSeamRequest,
    parse_benchmark_command_adapters,
    parse_benchmark_parity_run,
    parse_split_control_readiness,
)
from loopx.application.benchmarks.contracts import (
    SplitControlReadiness,
    SplitControlReadinessBoundary,
    SplitControlReadinessMatrix,
    SplitControlRoute,
)
from loopx.application.errors import (
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from loopx.application.maintenance import (
    CanaryProfilesRequest,
    CanaryProfilesResult,
    CanaryProvider,
    CanaryService,
    CanarySmokeProfilesRequest,
    CanarySmokeProfilesResult,
    CoreCanaryProvider,
)
from loopx.worker_bridge import (
    DEFAULT_WORKER_BRIDGE_BENCHMARK_RUN_JSON,
    DEFAULT_WORKER_BRIDGE_COUNTER_TRACE_JSON,
    DEFAULT_WORKER_BRIDGE_MODULE,
    DEFAULT_WORKER_BRIDGE_PYTHON_BIN,
    LOOPX_PROJECT_ROOT_PLACEHOLDER,
    LOOPX_RUNTIME_ROOT_PLACEHOLDER,
)

from .fixture_data import (
    active_user_simulator_output_fixture,
    command_adapter_fixture,
    parity_benchmark_run_fixture,
    split_control_readiness_fixture,
)


def _contract_request() -> WorkerBridgeContractRequest:
    return WorkerBridgeContractRequest(
        project_root=LOOPX_PROJECT_ROOT_PLACEHOLDER,
        runtime_root=LOOPX_RUNTIME_ROOT_PLACEHOLDER,
        python_bin=DEFAULT_WORKER_BRIDGE_PYTHON_BIN,
        module=DEFAULT_WORKER_BRIDGE_MODULE,
        scan_path=None,
        benchmark_run_json=DEFAULT_WORKER_BRIDGE_BENCHMARK_RUN_JSON,
        counter_trace_json=DEFAULT_WORKER_BRIDGE_COUNTER_TRACE_JSON,
        classification="fixture",
    )


def _seam_request() -> SplitControlExecutionSeamRequest:
    wrapper = command_adapter_fixture()
    return SplitControlExecutionSeamRequest(
        readiness=parse_split_control_readiness(
            split_control_readiness_fixture()
        ),
        command_adapters=parse_benchmark_command_adapters(
            wrapper["command_adapters"]
        ),
    )


def _intervention_request() -> WorkerBridgeActiveUserInterventionRequest:
    return WorkerBridgeActiveUserInterventionRequest(
        seq=7,
        message="Inspect public evidence.",
    )


def _simulator_request() -> WorkerBridgeActiveUserSimulatorOutputRequest:
    return WorkerBridgeActiveUserSimulatorOutputRequest(
        seq=8,
        simulator_output=parse_active_user_simulator_output(
            active_user_simulator_output_fixture()
        ),
    )


def _artifact_request() -> BenchmarkArtifactInspectionRequest:
    return BenchmarkArtifactInspectionRequest(
        artifact_paths=(
            "reports/result.compact.json",
            "runs/agent/trajectory.json",
        )
    )


def _source_request() -> BenchmarkCandidateSourceBoundaryRequest:
    return BenchmarkCandidateSourceBoundaryRequest(
        source_paths=("docs/benchmark.md", "runs/tasks/task.md")
    )


def _parity_request() -> BenchmarkParityCheckRequest:
    return BenchmarkParityCheckRequest(
        run=parse_benchmark_parity_run(parity_benchmark_run_fixture())
    )


def test_missing_providers_fail_closed_instead_of_binding_core_implicitly() -> None:
    with pytest.raises(CapabilityUnavailable):
        WorkerBridgeService(None).contract(_contract_request())
    with pytest.raises(CapabilityUnavailable):
        CanaryService(None).profiles(CanaryProfilesRequest())
    with pytest.raises(CapabilityUnavailable):
        SplitControlBenchmarkService(None).execution_seam(_seam_request())
    with pytest.raises(CapabilityUnavailable):
        BenchmarkInspectionService(None).classify_artifacts(_artifact_request())


def test_public_provider_ports_return_operation_specific_typed_results() -> None:
    assert get_type_hints(WorkerBridgeProvider.build_contract)["return"] is (
        WorkerBridgeInstallContract
    )
    assert get_type_hints(WorkerBridgeProvider.build_outcome)["return"] is (
        WorkerBridgeOutcome
    )
    assert get_type_hints(WorkerBridgeProvider.build_active_user_intervention)[
        "return"
    ] is WorkerBridgeActiveUserIntervention
    assert get_type_hints(WorkerBridgeProvider.build_active_user_simulator_output)[
        "return"
    ] is WorkerBridgeActiveUserSimulatorIntervention
    assert get_type_hints(CanaryProvider.profiles)["return"] is CanaryProfilesResult
    assert get_type_hints(CanaryProvider.smoke_profiles)["return"] is (
        CanarySmokeProfilesResult
    )
    assert get_type_hints(SplitControlBenchmarkProvider.execution_seam)[
        "return"
    ] is SplitControlExecutionSeam
    assert get_type_hints(BenchmarkInspectionProvider.classify_artifacts)[
        "return"
    ] is BenchmarkArtifactInspection
    assert get_type_hints(BenchmarkInspectionProvider.candidate_source_boundary)[
        "return"
    ] is BenchmarkCandidateSourceBoundary
    assert get_type_hints(BenchmarkInspectionProvider.parity_check)[
        "return"
    ] is BenchmarkParityCheck
    for result_type in (
        WorkerBridgeInstallContract,
        WorkerBridgeOutcome,
        CanaryProfilesResult,
        CanarySmokeProfilesResult,
        SplitControlExecutionSeam,
        WorkerBridgeActiveUserIntervention,
        WorkerBridgeActiveUserSimulatorIntervention,
        BenchmarkArtifactInspection,
        BenchmarkCandidateSourceBoundary,
        BenchmarkParityCheck,
    ):
        assert all("Mapping" not in str(field.type) for field in fields(result_type))


def test_row101_readiness_dto_retains_only_fields_consumed_by_seam() -> None:
    assert {field.name for field in fields(SplitControlReadiness)} == {
        "route",
        "readiness_matrix",
        "boundary",
    }
    assert {field.name for field in fields(SplitControlRoute)} == {
        "status",
        "default_for_cloud_host_runs",
        "local_agent_owns",
        "remote_executor_owns",
    }
    assert {field.name for field in fields(SplitControlReadinessMatrix)} == {
        "next_ready_batch_benchmark_ids"
    }
    assert {field.name for field in fields(SplitControlReadinessBoundary)} == {
        "codex_auth_sync_allowed",
        "credential_sync_allowed",
        "remote_codex_invocation_allowed",
        "remote_model_api_invocation_allowed",
        "raw_task_material_public",
    }


def test_each_retained_row101_input_branch_affects_output_or_legality() -> None:
    provider = CoreSplitControlBenchmarkProvider()
    request = _seam_request()
    baseline = provider.execution_seam(request)
    route = request.readiness.route
    matrix = request.readiness.readiness_matrix
    boundary = request.readiness.boundary

    no_cloud_default = provider.execution_seam(
        replace(
            request,
            readiness=replace(
                request.readiness,
                route=replace(route, default_for_cloud_host_runs=True),
            ),
        )
    )
    assert no_cloud_default.default_for_cloud_host_runs is True

    local_owner = provider.execution_seam(
        replace(
            request,
            readiness=replace(
                request.readiness,
                route=replace(route, local_agent_owns=("fixture_local",)),
            ),
        )
    )
    assert local_owner.execution_cases[0].local_driver_contract.owns == (
        "fixture_local",
    )

    remote_owner = provider.execution_seam(
        replace(
            request,
            readiness=replace(
                request.readiness,
                route=replace(route, remote_executor_owns=("fixture_remote",)),
            ),
        )
    )
    assert remote_owner.execution_cases[0].remote_sandbox_contract.owns == (
        "fixture_remote",
    )

    no_cases = provider.execution_seam(
        replace(
            request,
            readiness=replace(
                request.readiness,
                readiness_matrix=replace(
                    matrix,
                    next_ready_batch_benchmark_ids=(),
                ),
            ),
        )
    )
    assert no_cases.ready_to_execute is False
    assert no_cases.blockers == ("launch_plan_has_no_cases",)

    unsafe_projection = provider.execution_seam(
        replace(
            request,
            readiness=replace(
                request.readiness,
                boundary=replace(
                    boundary,
                    credential_sync_allowed=True,
                    remote_codex_invocation_allowed=True,
                    remote_model_api_invocation_allowed=True,
                    raw_task_material_public=True,
                    codex_auth_sync_allowed=True,
                ),
            ),
        )
    )
    assert unsafe_projection.boundary.codex_auth_stays_local is False
    assert unsafe_projection.boundary.credential_sync_allowed is True
    assert unsafe_projection.boundary.remote_codex_invocation_allowed is True
    assert unsafe_projection.boundary.remote_model_api_invocation_allowed is True
    assert unsafe_projection.boundary.raw_task_material_public is True
    assert baseline.boundary.credential_sync_allowed is False


def test_malformed_readiness_and_adapter_json_fail_with_typed_errors() -> None:
    readiness = split_control_readiness_fixture()
    readiness["unknown"] = True
    with pytest.raises(ValidationFailed):
        parse_split_control_readiness(readiness)

    wrong_type = split_control_readiness_fixture()
    wrong_type["route"]["default_for_cloud_host_runs"] = "false"
    with pytest.raises(StateUnavailable):
        parse_split_control_readiness(wrong_type)

    with pytest.raises(ValidationFailed):
        parse_benchmark_command_adapters(
            {
                "terminal-bench@2.0": {
                    "command_adapter_ready": True,
                    "result_reducer_ready": True,
                    "shell_command": "forbidden",
                }
            }
        )

    malformed_simulator = active_user_simulator_output_fixture()
    malformed_simulator["unknown"] = True
    with pytest.raises(ValidationFailed):
        parse_active_user_simulator_output(malformed_simulator)

    malformed_run = parity_benchmark_run_fixture()
    malformed_run["schema_version"] = "not_benchmark_run_v0"
    with pytest.raises(ValidationFailed):
        parse_benchmark_parity_run(malformed_run)


def test_services_reject_malformed_or_side_effecting_provider_results() -> None:
    class InvalidWorker:
        def build_contract(self, request):
            del request
            return object()

        def build_outcome(self, request):
            del request
            return object()

    with pytest.raises(StateUnavailable):
        WorkerBridgeService(InvalidWorker()).outcome(WorkerBridgeOutcomeRequest())

    canary_result = CoreCanaryProvider().profiles(CanaryProfilesRequest())

    class ExecutingCanary:
        def profiles(self, request):
            del request
            return replace(canary_result, executes_checks=True)

        def smoke_profiles(self, request):
            del request
            return CoreCanaryProvider().smoke_profiles(
                CanarySmokeProfilesRequest()
            )

    with pytest.raises(StateUnavailable):
        CanaryService(ExecutingCanary()).profiles(CanaryProfilesRequest())

    seam = CoreSplitControlBenchmarkProvider().execution_seam(_seam_request())

    class UnsafeBenchmark:
        def execution_seam(self, request):
            del request
            return replace(
                seam,
                boundary=replace(seam.boundary, upload_allowed=True),
            )

    with pytest.raises(StateUnavailable):
        SplitControlBenchmarkService(UnsafeBenchmark()).execution_seam(
            _seam_request()
        )

    intervention = CoreWorkerBridgeProvider().build_active_user_intervention(
        _intervention_request()
    )

    class UnsafeIntervention:
        def build_active_user_intervention(self, request):
            del request
            return replace(intervention, hidden_tests_visible=True)

    with pytest.raises(StateUnavailable):
        WorkerBridgeService(UnsafeIntervention()).active_user_intervention(
            _intervention_request()
        )

    simulator_intervention = (
        CoreWorkerBridgeProvider().build_active_user_simulator_output(
            _simulator_request()
        )
    )

    class UnsafeSimulatorIntervention:
        def build_active_user_simulator_output(self, request):
            del request
            return replace(
                simulator_intervention,
                formal_treatment_eligible=False,
            )

    with pytest.raises(StateUnavailable):
        WorkerBridgeService(
            UnsafeSimulatorIntervention()
        ).active_user_simulator_output(_simulator_request())

    inspection_provider = CoreBenchmarkInspectionProvider()
    artifacts = inspection_provider.classify_artifacts(_artifact_request())

    class UnsafeInspection:
        def classify_artifacts(self, request):
            del request
            return replace(artifacts, path_recorded=True)

        def candidate_source_boundary(self, request):
            del request
            return inspection_provider.candidate_source_boundary(
                _source_request()
            )

        def parity_check(self, request):
            del request
            return inspection_provider.parity_check(_parity_request())

    with pytest.raises(StateUnavailable):
        BenchmarkInspectionService(UnsafeInspection()).classify_artifacts(
            _artifact_request()
        )

    sources = inspection_provider.candidate_source_boundary(_source_request())

    class UnsafeSources(UnsafeInspection):
        def candidate_source_boundary(self, request):
            del request
            return replace(
                sources,
                read_boundary=replace(
                    sources.read_boundary,
                    files_opened=True,
                ),
            )

    with pytest.raises(StateUnavailable):
        BenchmarkInspectionService(
            UnsafeSources()
        ).candidate_source_boundary(_source_request())

    parity = inspection_provider.parity_check(_parity_request())

    class UnsafeParity(UnsafeInspection):
        def parity_check(self, request):
            del request
            return replace(
                parity,
                read_boundary=replace(parity.read_boundary, raw_logs_read=True),
            )

    with pytest.raises(StateUnavailable):
        BenchmarkInspectionService(UnsafeParity()).parity_check(
            _parity_request()
        )


def test_core_provider_packet_projection_rejects_missing_fields(
    monkeypatch,
) -> None:
    import loopx.application.agents.provider as agent_provider
    import loopx.application.benchmarks.provider as benchmark_provider
    import loopx.application.maintenance.provider as maintenance_provider

    monkeypatch.setattr(
        agent_provider,
        "build_worker_bridge_outcome",
        lambda **_kwargs: {"ok": True},
    )
    with pytest.raises(StateUnavailable):
        CoreWorkerBridgeProvider().build_outcome(WorkerBridgeOutcomeRequest())

    monkeypatch.setattr(
        maintenance_provider,
        "build_canary_smoke_suite_profiles",
        lambda: {"ok": True},
    )
    with pytest.raises(StateUnavailable):
        CoreCanaryProvider().smoke_profiles(CanarySmokeProfilesRequest())

    monkeypatch.setattr(
        benchmark_provider,
        "build_split_control_remote_executor_execution_seam",
        lambda *_args, **_kwargs: {
            "schema_version": "benchmark_split_control_remote_executor_execution_seam_v1"
        },
    )
    with pytest.raises(StateUnavailable):
        CoreSplitControlBenchmarkProvider().execution_seam(_seam_request())

    monkeypatch.setattr(
        agent_provider,
        "build_active_user_intervention",
        lambda **_kwargs: {"ok": True},
    )
    with pytest.raises(StateUnavailable):
        CoreWorkerBridgeProvider().build_active_user_intervention(
            _intervention_request()
        )

    monkeypatch.setattr(
        benchmark_provider,
        "filter_public_benchmark_artifact_paths",
        lambda *_args, **_kwargs: {"schema_version": "invalid"},
    )
    with pytest.raises(StateUnavailable):
        CoreBenchmarkInspectionProvider().classify_artifacts(
            _artifact_request()
        )
