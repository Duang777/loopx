from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from ..errors import (
    ApplicationError,
    CapabilityUnavailable,
    StateUnavailable,
    ValidationFailed,
)
from .contracts import (
    BenchmarkArtifactInspection,
    BenchmarkArtifactInspectionRequest,
    BenchmarkCandidateSourceBoundary,
    BenchmarkCandidateSourceBoundaryRequest,
    BenchmarkParityCasePathKind,
    BenchmarkParityCheck,
    BenchmarkParityCheckRequest,
    SplitControlExecutionSeam,
    SplitControlExecutionSeamRequest,
)
from .provider import (
    BenchmarkInspectionProvider,
    CoreBenchmarkInspectionProvider,
    CoreSplitControlBenchmarkProvider,
    SplitControlBenchmarkProvider,
)


ResultT = TypeVar("ResultT")


class SplitControlBenchmarkService:
    __slots__ = ("_provider",)

    def __init__(
        self,
        provider: SplitControlBenchmarkProvider | None,
    ) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> SplitControlBenchmarkService:
        return cls(CoreSplitControlBenchmarkProvider())

    def execution_seam(
        self,
        request: SplitControlExecutionSeamRequest,
    ) -> SplitControlExecutionSeam:
        if not isinstance(request, SplitControlExecutionSeamRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.benchmarks.split_control.execution_seam"
        )
        result = self._invoke(lambda: provider.execution_seam(request))
        if not isinstance(result, SplitControlExecutionSeam):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "execution_seam"}
            )
        boundary = result.boundary
        if any(
            (
                boundary.upload_allowed,
                boundary.submit_allowed,
                boundary.shell_commands_embedded,
                boundary.argv_embedded,
                boundary.raw_task_text_public,
                boundary.raw_logs_public,
                boundary.raw_trajectory_public,
            )
        ):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "public_boundary"}
            )
        return result

    def _require_provider(self, operation: str) -> SplitControlBenchmarkProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": operation,
                    "provider": "split_control_benchmark",
                }
            )
        return self._provider

    @staticmethod
    def _invoke(call: Callable[[], ResultT]) -> ResultT:
        try:
            return call()
        except ApplicationError:
            raise
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "benchmark", "cause": type(exc).__name__}
            ) from exc


class BenchmarkInspectionService:
    __slots__ = ("_provider",)

    def __init__(self, provider: BenchmarkInspectionProvider | None) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> BenchmarkInspectionService:
        return cls(CoreBenchmarkInspectionProvider())

    def classify_artifacts(
        self,
        request: BenchmarkArtifactInspectionRequest,
    ) -> BenchmarkArtifactInspection:
        if not isinstance(request, BenchmarkArtifactInspectionRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.benchmarks.inspection.classify_artifacts"
        )
        result = self._invoke(lambda: provider.classify_artifacts(request))
        if not isinstance(result, BenchmarkArtifactInspection):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "artifact_inspection"}
            )
        boundary = result.public_boundary
        classifications = result.classifications
        if (
            result.schema_version != "benchmark_artifact_path_filter_v0"
            or result.path_recorded
            or boundary.full_paths_recorded
            or boundary.raw_task_text_read
            or boundary.trajectory_or_origin_log_read
            or result.allowed_to_read_count
            != sum(item.allowed_to_read for item in classifications)
            or result.blocked_count
            != sum(not item.allowed_to_read for item in classifications)
            or result.allowed_to_read_count
            != len(result.allowed_artifact_basenames)
            or result.blocked_count != len(result.blocked_artifact_basenames)
            or result.blocked_count
            != sum(item.count for item in result.blocked_reasons)
            or any(
                item.path_recorded or not self._safe_basename(item.basename)
                for item in classifications
            )
            or any(
                not self._safe_basename(item)
                for item in (
                    *result.allowed_artifact_basenames,
                    *result.blocked_artifact_basenames,
                )
            )
        ):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "artifact_boundary"}
            )
        return result

    def candidate_source_boundary(
        self,
        request: BenchmarkCandidateSourceBoundaryRequest,
    ) -> BenchmarkCandidateSourceBoundary:
        if not isinstance(request, BenchmarkCandidateSourceBoundaryRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.benchmarks.inspection.candidate_source_boundary"
        )
        result = self._invoke(
            lambda: provider.candidate_source_boundary(request)
        )
        if not isinstance(result, BenchmarkCandidateSourceBoundary):
            raise StateUnavailable(
                details={
                    "resource": "benchmark",
                    "field": "candidate_source_boundary",
                }
            )
        boundary = result.read_boundary
        classifications = result.classifications
        if (
            result.schema_version != "benchmark_candidate_source_boundary_v0"
            or result.path_recorded
            or any(
                (
                    boundary.files_opened,
                    boundary.raw_artifacts_read,
                    boundary.task_text_read,
                    boundary.trajectory_read,
                    boundary.codex_transcript_read,
                    boundary.local_paths_recorded,
                )
            )
            or result.allowed_source_count
            != sum(item.allowed_for_candidate_selection for item in classifications)
            or result.blocked_source_count
            != sum(
                not item.allowed_for_candidate_selection
                for item in classifications
            )
            or result.allowed_source_count != len(result.allowed_source_basenames)
            or result.blocked_source_count != len(result.blocked_source_basenames)
            or result.blocked_source_count
            != sum(item.count for item in result.blocked_reasons)
            or result.clean != (result.blocked_source_count == 0)
            or any(
                item.path_recorded or not self._safe_basename(item.basename)
                for item in classifications
            )
            or any(
                not self._safe_basename(item)
                for item in (
                    *result.allowed_source_basenames,
                    *result.blocked_source_basenames,
                )
            )
        ):
            raise StateUnavailable(
                details={
                    "resource": "benchmark",
                    "field": "candidate_source_read_boundary",
                }
            )
        return result

    def parity_check(
        self,
        request: BenchmarkParityCheckRequest,
    ) -> BenchmarkParityCheck:
        if not isinstance(request, BenchmarkParityCheckRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.benchmarks.inspection.parity_check"
        )
        result = self._invoke(lambda: provider.parity_check(request))
        if not isinstance(result, BenchmarkParityCheck):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "parity_check"}
            )
        boundary = result.read_boundary
        counts = result.loopx_cli_call_counts
        state_counts = result.stateful_lifecycle_counts
        if (
            result.schema_version
            != "benchmark_codex_app_parity_posthoc_check_v0"
            or result.parity_target != "codex_app_loopx_product_path"
            or not boundary.compact_benchmark_run_only
            or any(
                (
                    boundary.raw_task_text_read,
                    boundary.raw_logs_read,
                    boundary.raw_trajectory_read,
                    boundary.verifier_output_read,
                    boundary.credentials_read,
                    boundary.local_paths_recorded,
                )
            )
            or min(
                counts.status,
                counts.quota_should_run,
                counts.todo_list,
                counts.history,
                counts.check,
                counts.todo_claim,
                counts.todo_update,
                counts.refresh_state,
                counts.quota_spend,
                counts.case_result,
                counts.total,
                state_counts.state_reads,
                state_counts.state_writes,
            )
            < 0
            or result.case_goal_state.canonical_path_present
            != (
                result.case_goal_state.path_kind
                is BenchmarkParityCasePathKind.CANONICAL
            )
            or (
                result.full_product_claim_allowed
                and (
                    result.missing_evidence
                    or result.safety_failures
                    or not all(
                        (
                            result.safety_checks.raw_task_text_absent,
                            result.safety_checks.raw_reward_feedback_absent,
                            result.safety_checks.raw_verifier_output_absent,
                            result.safety_checks.raw_agent_trajectory_absent,
                        )
                    )
                )
            )
        ):
            raise StateUnavailable(
                details={"resource": "benchmark", "field": "parity_boundary"}
            )
        return result

    def _require_provider(self, operation: str) -> BenchmarkInspectionProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={
                    "operation": operation,
                    "provider": "benchmark_inspection",
                }
            )
        return self._provider

    @staticmethod
    def _safe_basename(value: str) -> bool:
        return "/" not in value and "\\" not in value

    @staticmethod
    def _invoke(call: Callable[[], ResultT]) -> ResultT:
        try:
            return call()
        except ApplicationError:
            raise
        except ValueError as exc:
            raise ValidationFailed(str(exc)) from exc
        except OSError as exc:
            raise StateUnavailable(
                details={"resource": "benchmark", "cause": type(exc).__name__}
            ) from exc
