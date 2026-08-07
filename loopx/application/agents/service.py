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
    WorkerBridgeActiveUserIntervention,
    WorkerBridgeActiveUserInterventionRequest,
    WorkerBridgeActiveUserSimulatorIntervention,
    WorkerBridgeActiveUserSimulatorOutputRequest,
    WorkerBridgeContractRequest,
    WorkerBridgeInstallContract,
    WorkerBridgeOutcome,
    WorkerBridgeOutcomeRequest,
)
from .provider import CoreWorkerBridgeProvider, WorkerBridgeProvider


ResultT = TypeVar("ResultT")


class WorkerBridgeService:
    __slots__ = ("_provider",)

    def __init__(self, provider: WorkerBridgeProvider | None) -> None:
        self._provider = provider

    @classmethod
    def builtin(cls) -> WorkerBridgeService:
        return cls(CoreWorkerBridgeProvider())

    def contract(
        self,
        request: WorkerBridgeContractRequest,
    ) -> WorkerBridgeInstallContract:
        if not isinstance(request, WorkerBridgeContractRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider("application.agents.worker_bridge.contract")
        result = self._invoke(lambda: provider.build_contract(request))
        if not isinstance(result, WorkerBridgeInstallContract):
            raise StateUnavailable(
                details={"resource": "worker_bridge", "field": "contract"}
            )
        return result

    def outcome(self, request: WorkerBridgeOutcomeRequest) -> WorkerBridgeOutcome:
        if not isinstance(request, WorkerBridgeOutcomeRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider("application.agents.worker_bridge.outcome")
        result = self._invoke(lambda: provider.build_outcome(request))
        if not isinstance(result, WorkerBridgeOutcome):
            raise StateUnavailable(
                details={"resource": "worker_bridge", "field": "outcome"}
            )
        return result

    def active_user_intervention(
        self,
        request: WorkerBridgeActiveUserInterventionRequest,
    ) -> WorkerBridgeActiveUserIntervention:
        if not isinstance(request, WorkerBridgeActiveUserInterventionRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.agents.worker_bridge.active_user_intervention"
        )
        result = self._invoke(
            lambda: provider.build_active_user_intervention(request)
        )
        if not isinstance(result, WorkerBridgeActiveUserIntervention):
            raise StateUnavailable(
                details={
                    "resource": "worker_bridge",
                    "field": "active_user_intervention",
                }
            )
        self._require_safe_intervention(result)
        return result

    def active_user_simulator_output(
        self,
        request: WorkerBridgeActiveUserSimulatorOutputRequest,
    ) -> WorkerBridgeActiveUserSimulatorIntervention:
        if not isinstance(request, WorkerBridgeActiveUserSimulatorOutputRequest):
            raise ValidationFailed(details={"field": "request"})
        provider = self._require_provider(
            "application.agents.worker_bridge.active_user_simulator_output"
        )
        result = self._invoke(
            lambda: provider.build_active_user_simulator_output(request)
        )
        if not isinstance(result, WorkerBridgeActiveUserSimulatorIntervention):
            raise StateUnavailable(
                details={
                    "resource": "worker_bridge",
                    "field": "active_user_simulator_output",
                }
            )
        self._require_safe_intervention(result.intervention)
        audit = result.no_oracle_audit
        if (
            result.simulator_output_schema_version
            != "loopx_active_user_simulator_output_v0"
            or result.intervention.channel != "codex_cli_user_simulator"
            or result.controller_authored_message
            or not result.formal_treatment_eligible
            or result.manual_controller_feed
            or not result.visible_evidence_basis
            or any(
                (
                    audit.hidden_tests_visible,
                    audit.expected_solution_visible,
                    audit.benchmark_answer_key_visible,
                    audit.credential_values_visible,
                    audit.private_material_visible,
                    audit.solution_patch_visible,
                )
            )
        ):
            raise StateUnavailable(
                details={
                    "resource": "worker_bridge",
                    "field": "active_user_simulator_boundary",
                }
            )
        return result

    def _require_provider(self, operation: str) -> WorkerBridgeProvider:
        if self._provider is None:
            raise CapabilityUnavailable(
                details={"operation": operation, "provider": "worker_bridge"}
            )
        return self._provider

    @staticmethod
    def _require_safe_intervention(
        result: WorkerBridgeActiveUserIntervention,
    ) -> None:
        if (
            not result.ok
            or result.schema_version != "loopx_active_user_intervention_v0"
            or result.channel_surface
            != "loopx_active_user_external_update_loop_v0"
            or result.seq < 0
            or not result.oracle_free
            or any(
                (
                    result.hidden_tests_visible,
                    result.expected_solution_visible,
                    result.credential_values_visible,
                    result.private_material_visible,
                    result.official_score_claim_allowed,
                    result.leaderboard_claim_allowed,
                )
            )
        ):
            raise StateUnavailable(
                details={
                    "resource": "worker_bridge",
                    "field": "active_user_public_boundary",
                }
            )

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
                details={
                    "resource": "worker_bridge",
                    "cause": type(exc).__name__,
                }
            ) from exc
