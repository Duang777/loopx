"""Explicit FastAPI routes over the LoopX Application public surface."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from loopx.application import (
    GoalConfigurationPatch,
    QuotaBudget,
    QuotaMutationPlan,
    RevisionConflict,
    TodoCompletion,
    TodoUpdatePatch,
    TurnExecutionMode,
    TurnHost,
    TurnPlanRequest,
    ValidationFailed,
    WriteContext,
    WriteCorrectness,
)

from .errors import HttpAdapterError
from .schemas import (
    CapabilityListResponse,
    CapabilityResponse,
    ConfigurationApplyRequest,
    ConfigurationApplyResultResponse,
    ConfigurationPlanResponse,
    ConfigurationPreviewRequest,
    ControlSessionResponse,
    EmptyJsonRequest,
    ErrorResponse,
    GoalListResponse,
    GoalOverviewResponse,
    GoalSummaryResponse,
    HealthResponse,
    HistoryPageResponse,
    LeaseAcquireRequest,
    LeaseReleaseRequest,
    LeaseRenewRequest,
    OperatorConfirmationRequest,
    OperatorStatusResponse,
    QuotaApplyRequest,
    QuotaApplyResultResponse,
    QuotaDecisionResponse,
    QuotaMutationPlanResponse,
    QuotaSpendPreviewRequest,
    QuotaVoidPreviewRequest,
    TaskLeaseInspectionResponse,
    TaskLeaseMutationResultResponse,
    TodoClaimRequest,
    TodoCompleteApplyRequest,
    TodoCompletePreviewRequest,
    TodoCompletionPlanResponse,
    TodoListResponse,
    TodoMutationResultResponse,
    TodoUpdateRequest,
    TurnPlanRequestBody,
    TurnPlanResponse,
    model_payload,
)
from .security import CONTROL_SESSION_HEADER, ServerProfile
from .serialization import conditional_response, stable_etag, wire_model
from .sessions import (
    InvalidControlSession,
    OperatorAuthorityDenied,
    OperatorSlotOccupied,
    OperatorSnapshot,
)


_ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
_CONDITIONAL_RESPONSES = {
    **_ERROR_RESPONSES,
    304: {"description": "Projection has not changed for If-None-Match."},
}


def _operator_session_header(
    control_session_id: Annotated[str, Header(alias=CONTROL_SESSION_HEADER)],
) -> str:
    return control_session_id


_OPERATOR_SESSION_DEPENDENCY = Depends(_operator_session_header)


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get(
        "/health",
        response_model=HealthResponse,
        operation_id="http.health",
    )
    def health(request: Request) -> HealthResponse:
        settings = request.app.state.loopx_http_settings
        static_available = bool(
            settings.static_dir is not None
            and settings.static_dir.is_dir()
            and (settings.static_dir / "index.html").is_file()
        )
        return HealthResponse(
            profile=settings.profile.value,
            static_assets="available" if static_available else "unavailable",
        )

    @router.post(
        "/control-sessions",
        response_model=ControlSessionResponse,
        responses=_ERROR_RESPONSES,
        operation_id="http.control_sessions.create",
        status_code=201,
    )
    def create_control_session(
        request: Request,
        _body: EmptyJsonRequest,
    ) -> ControlSessionResponse:
        sessions = request.app.state.loopx_control_sessions
        session_id = sessions.issue()
        return _control_session_response(
            request,
            session_id=session_id,
            role="viewer",
        )

    @router.get(
        "/operator",
        response_model=OperatorStatusResponse,
        responses=_ERROR_RESPONSES,
        operation_id="http.operator.status",
    )
    def operator_status(
        request: Request,
        control_session_id: str | None = Header(
            default=None,
            alias=CONTROL_SESSION_HEADER,
        ),
    ) -> OperatorStatusResponse:
        sessions = request.app.state.loopx_control_sessions
        if control_session_id is None:
            snapshot = OperatorSnapshot(
                role="viewer",
                operator_slot_occupied=sessions.operator_session_id is not None,
                changed=False,
            )
        else:
            try:
                snapshot = sessions.snapshot(control_session_id)
            except InvalidControlSession as exc:
                raise HttpAdapterError(
                    code="invalid_control_session",
                    message=f"A valid {CONTROL_SESSION_HEADER} header is required.",
                    status_code=401,
                ) from exc
        return _operator_response(request, snapshot)

    @router.post(
        "/operator/acquire",
        response_model=OperatorStatusResponse,
        responses=_ERROR_RESPONSES,
        operation_id="http.operator.acquire",
    )
    def acquire_operator(
        request: Request,
        _body: OperatorConfirmationRequest,
        control_session_id: str = Header(alias=CONTROL_SESSION_HEADER),
    ) -> OperatorStatusResponse:
        sessions = request.app.state.loopx_control_sessions
        try:
            snapshot = sessions.acquire(control_session_id)
        except OperatorSlotOccupied as exc:
            raise HttpAdapterError(
                code="operator_slot_occupied",
                message="Another control session currently holds the operator slot.",
                status_code=409,
                details={"takeover_available": True},
            ) from exc
        return _operator_response(request, snapshot)

    @router.post(
        "/operator/takeover",
        response_model=OperatorStatusResponse,
        responses=_ERROR_RESPONSES,
        operation_id="http.operator.takeover",
    )
    def takeover_operator(
        request: Request,
        _body: OperatorConfirmationRequest,
        control_session_id: str = Header(alias=CONTROL_SESSION_HEADER),
    ) -> OperatorStatusResponse:
        sessions = request.app.state.loopx_control_sessions
        return _operator_response(request, sessions.takeover(control_session_id))

    @router.post(
        "/operator/release",
        response_model=OperatorStatusResponse,
        responses=_ERROR_RESPONSES,
        operation_id="http.operator.release",
    )
    def release_operator(
        request: Request,
        _body: OperatorConfirmationRequest,
        control_session_id: str = Header(alias=CONTROL_SESSION_HEADER),
    ) -> OperatorStatusResponse:
        sessions = request.app.state.loopx_control_sessions
        try:
            snapshot = sessions.release(control_session_id)
        except OperatorAuthorityDenied as exc:
            raise HttpAdapterError(
                code="operator_required",
                message="The current control session does not hold the operator slot.",
                status_code=403,
            ) from exc
        return _operator_response(request, snapshot)

    @router.get(
        "/capabilities",
        response_model=CapabilityListResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="application.describe_capabilities",
    )
    def capabilities(
        request: Request,
        response: Response,
    ) -> Any:
        application = request.app.state.loopx_application
        descriptions = application.describe_capabilities()
        payload = CapabilityListResponse(
            profile=request.app.state.loopx_http_settings.profile.value,
            capabilities=[
                wire_model(CapabilityResponse, description)
                for description in descriptions
            ],
        )
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material=payload,
        )

    @router.get(
        "/goals",
        response_model=GoalListResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="application.list_goals",
    )
    def list_goals(request: Request, response: Response) -> Any:
        application = request.app.state.loopx_application
        goals = [wire_model(GoalSummaryResponse, item) for item in application.list_goals()]
        revision_material = [
            {"goal_id": item.goal_id, "revision": item.revision}
            for item in goals
        ]
        revision = stable_etag(revision_material).strip('"')
        payload = GoalListResponse(
            generated_at=(
                goals[0].generated_at
                if goals
                else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),
            revision=revision,
            goals=goals,
        )
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material=revision_material,
        )

    @router.get(
        "/goals/{goal_id}/overview",
        response_model=GoalOverviewResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="goal.overview",
    )
    def goal_overview(
        goal_id: str,
        request: Request,
        response: Response,
    ) -> Any:
        overview = _goal(request, goal_id).overview()
        payload = wire_model(GoalOverviewResponse, overview)
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material={"goal_id": payload.goal_id, "revision": payload.revision},
        )

    @router.get(
        "/goals/{goal_id}/history",
        response_model=HistoryPageResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="goal.history.list",
    )
    def goal_history(
        goal_id: str,
        request: Request,
        response: Response,
        page_size: int = Query(default=20, ge=1, le=100),
        page_token: str | None = Query(default=None),
    ) -> Any:
        page = _goal(request, goal_id).history.list(
            page_size=page_size,
            page_token=page_token,
        )
        payload = wire_model(HistoryPageResponse, page)
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material={
                "goal_id": payload.goal_id,
                "revision": payload.revision,
                "page_token": page_token,
                "page_size": page_size,
            },
        )

    @router.post(
        "/goals/{goal_id}/configuration/preview",
        response_model=ConfigurationPlanResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.configuration.preview",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def preview_configuration(
        goal_id: str,
        request: Request,
        body: ConfigurationPreviewRequest,
    ) -> ConfigurationPlanResponse:
        plan = _goal(request, goal_id).configuration.preview(
            _configuration_patch(body.patch)
        )
        return wire_model(ConfigurationPlanResponse, plan)

    @router.post(
        "/goals/{goal_id}/configuration/apply",
        response_model=ConfigurationApplyResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.configuration.apply",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def apply_configuration(
        goal_id: str,
        request: Request,
        body: ConfigurationApplyRequest,
    ) -> ConfigurationApplyResultResponse:
        result = _goal(request, goal_id).configuration.apply(
            _configuration_patch(body.patch),
            plan_hash=body.plan_hash,
            write_context=_write_context(body.write_context),
        )
        return wire_model(ConfigurationApplyResultResponse, result)

    @router.get(
        "/goals/{goal_id}/todos",
        response_model=TodoListResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="goal.todos.list",
    )
    def list_todos(
        goal_id: str,
        request: Request,
        response: Response,
        role: str | None = Query(default=None),
        status: str | None = Query(default=None),
        todo_id: str | None = Query(default=None),
        agent_id: str | None = Query(default=None),
    ) -> Any:
        result = _goal(request, goal_id).todos.list(
            role=role,
            status=status,
            todo_id=todo_id,
            agent_id=agent_id,
        )
        payload = wire_model(TodoListResponse, result)
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material={
                "goal_id": payload.goal_id,
                "revision": payload.revision,
                "filters": [role, status, todo_id, agent_id],
            },
        )

    @router.post(
        "/goals/{goal_id}/todos/{todo_id}/claim",
        response_model=TodoMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.todos.claim",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def claim_todo(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: TodoClaimRequest,
    ) -> TodoMutationResultResponse:
        result = _goal(request, goal_id).todos.claim(
            todo_id,
            write_context=_write_context(body.write_context),
        )
        return wire_model(TodoMutationResultResponse, result)

    @router.patch(
        "/goals/{goal_id}/todos/{todo_id}",
        response_model=TodoMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.todos.update",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def update_todo(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: TodoUpdateRequest,
    ) -> TodoMutationResultResponse:
        result = _goal(request, goal_id).todos.update(
            todo_id,
            TodoUpdatePatch(**model_payload(body.patch)),
            write_context=_write_context(body.write_context),
        )
        return wire_model(TodoMutationResultResponse, result)

    @router.post(
        "/goals/{goal_id}/todos/{todo_id}/complete/preview",
        response_model=TodoCompletionPlanResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.todos.complete.preview",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def preview_todo_completion(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: TodoCompletePreviewRequest,
    ) -> TodoCompletionPlanResponse:
        plan = _goal(request, goal_id).todos.preview_complete(
            todo_id,
            _todo_completion(body.completion),
            actor=body.actor,
        )
        return wire_model(TodoCompletionPlanResponse, plan)

    @router.post(
        "/goals/{goal_id}/todos/{todo_id}/complete/apply",
        response_model=TodoMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.todos.complete.apply",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def apply_todo_completion(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: TodoCompleteApplyRequest,
    ) -> TodoMutationResultResponse:
        supplied = body.plan
        if supplied.goal_id != goal_id or supplied.todo_id != todo_id:
            raise ValidationFailed(details={"field": "plan", "reason": "identity_mismatch"})
        service = _goal(request, goal_id).todos
        current = service.preview_complete(
            todo_id,
            _todo_completion(supplied.completion),
            actor=supplied.actor,
        )
        if (
            supplied.plan_hash != current.plan_hash
            or supplied.revision != current.revision
        ):
            raise RevisionConflict(
                details={
                    "goal_id": goal_id,
                    "expected_revision": supplied.revision,
                    "current_revision": current.revision,
                    "reason": "plan_stale",
                }
            )
        result = service.apply_complete(
            current,
            write_context=_write_context(body.write_context),
        )
        return wire_model(TodoMutationResultResponse, result)

    @router.get(
        "/goals/{goal_id}/leases/{todo_id}",
        response_model=TaskLeaseInspectionResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="goal.lease.inspect",
    )
    def inspect_lease(
        goal_id: str,
        todo_id: str,
        request: Request,
        response: Response,
    ) -> Any:
        inspection = _goal(request, goal_id).leases.inspect(todo_id)
        payload = wire_model(TaskLeaseInspectionResponse, inspection)
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material={
                "goal_id": payload.goal_id,
                "todo_id": payload.todo_id,
                "active": payload.active,
                "lease_revision": payload.lease.revision if payload.lease else None,
            },
        )

    @router.post(
        "/goals/{goal_id}/leases/{todo_id}/acquire",
        response_model=TaskLeaseMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.lease.acquire",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def acquire_lease(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: LeaseAcquireRequest,
    ) -> TaskLeaseMutationResultResponse:
        result = _goal(request, goal_id).leases.acquire(
            todo_id,
            write_context=_write_context(body.write_context),
            ttl_seconds=body.ttl_seconds,
            write_scopes=tuple(body.write_scopes),
        )
        return wire_model(TaskLeaseMutationResultResponse, result)

    @router.post(
        "/goals/{goal_id}/leases/{todo_id}/renew",
        response_model=TaskLeaseMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.lease.renew",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def renew_lease(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: LeaseRenewRequest,
    ) -> TaskLeaseMutationResultResponse:
        result = _goal(request, goal_id).leases.renew(
            todo_id,
            write_context=_write_context(body.write_context),
            ttl_seconds=body.ttl_seconds,
        )
        return wire_model(TaskLeaseMutationResultResponse, result)

    @router.post(
        "/goals/{goal_id}/leases/{todo_id}/release",
        response_model=TaskLeaseMutationResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.lease.release",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def release_lease(
        goal_id: str,
        todo_id: str,
        request: Request,
        body: LeaseReleaseRequest,
    ) -> TaskLeaseMutationResultResponse:
        result = _goal(request, goal_id).leases.release(
            todo_id,
            write_context=_write_context(body.write_context),
        )
        return wire_model(TaskLeaseMutationResultResponse, result)

    @router.get(
        "/goals/{goal_id}/quota/should-run",
        response_model=QuotaDecisionResponse,
        responses=_CONDITIONAL_RESPONSES,
        operation_id="goal.quota.should_run",
    )
    def quota_should_run(
        goal_id: str,
        request: Request,
        response: Response,
        agent_id: str | None = Query(default=None),
    ) -> Any:
        decision = _goal(request, goal_id).quota.should_run(agent_id=agent_id)
        payload = wire_model(QuotaDecisionResponse, decision)
        return conditional_response(
            request,
            response,
            payload=payload,
            etag_material={
                "goal_id": payload.goal_id,
                "agent_id": payload.agent_id,
                "revision": payload.revision,
            },
        )

    @router.post(
        "/goals/{goal_id}/quota/spend/preview",
        response_model=QuotaMutationPlanResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.quota.spend.preview",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def preview_quota_spend(
        goal_id: str,
        request: Request,
        body: QuotaSpendPreviewRequest,
    ) -> QuotaMutationPlanResponse:
        plan = _goal(request, goal_id).quota.preview_spend(
            slots=body.slots,
            agent_id=body.agent_id,
            source=body.source,
        )
        return wire_model(QuotaMutationPlanResponse, plan)

    @router.post(
        "/goals/{goal_id}/quota/spend/apply",
        response_model=QuotaApplyResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.quota.spend.apply",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def apply_quota_spend(
        goal_id: str,
        request: Request,
        body: QuotaApplyRequest,
    ) -> QuotaApplyResultResponse:
        result = _goal(request, goal_id).quota.apply_spend(
            _quota_plan(body.plan),
            write_context=_write_context(body.write_context),
        )
        return wire_model(QuotaApplyResultResponse, result)

    @router.post(
        "/goals/{goal_id}/quota/void/preview",
        response_model=QuotaMutationPlanResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.quota.void.preview",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def preview_quota_void(
        goal_id: str,
        request: Request,
        body: QuotaVoidPreviewRequest,
    ) -> QuotaMutationPlanResponse:
        plan = _goal(request, goal_id).quota.preview_void(
            voided_run_generated_at=body.voided_run_generated_at,
            reason_summary=body.reason_summary,
            agent_id=body.agent_id,
            source=body.source,
        )
        return wire_model(QuotaMutationPlanResponse, plan)

    @router.post(
        "/goals/{goal_id}/quota/void/apply",
        response_model=QuotaApplyResultResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.quota.void.apply",
        dependencies=[_OPERATOR_SESSION_DEPENDENCY],
    )
    def apply_quota_void(
        goal_id: str,
        request: Request,
        body: QuotaApplyRequest,
    ) -> QuotaApplyResultResponse:
        result = _goal(request, goal_id).quota.apply_void(
            _quota_plan(body.plan),
            write_context=_write_context(body.write_context),
        )
        return wire_model(QuotaApplyResultResponse, result)

    @router.post(
        "/goals/{goal_id}/turns/plan",
        response_model=TurnPlanResponse,
        responses=_ERROR_RESPONSES,
        operation_id="goal.turn.plan",
    )
    def plan_turn(
        goal_id: str,
        request: Request,
        body: TurnPlanRequestBody,
    ) -> TurnPlanResponse:
        plan = _goal(request, goal_id).turns.plan(
            TurnPlanRequest(
                agent_id=body.agent_id,
                turn_instance_id=body.turn_instance_id,
                host=TurnHost(body.host),
                execution_mode=TurnExecutionMode(body.execution_mode),
                scheduler_owner=body.scheduler_owner,
                session_binding=body.session_binding,
            )
        )
        return wire_model(TurnPlanResponse, plan)

    return router


def _goal(request: Request, goal_id: str) -> Any:
    return request.app.state.loopx_application.get_goal(goal_id)


def _control_session_response(
    request: Request,
    *,
    session_id: str,
    role: str,
) -> ControlSessionResponse:
    settings = request.app.state.loopx_http_settings
    occupied = request.app.state.loopx_control_sessions.operator_session_id is not None
    operator_enabled = settings.profile is ServerProfile.LOCAL_OPERATOR
    return ControlSessionResponse(
        control_session_id=session_id,
        role=role,
        profile=settings.profile.value,
        operator_slot_occupied=occupied,
        can_acquire=operator_enabled and not occupied,
        can_takeover=operator_enabled and occupied and role != "operator",
    )


def _operator_response(
    request: Request,
    snapshot: OperatorSnapshot,
) -> OperatorStatusResponse:
    profile = request.app.state.loopx_http_settings.profile
    enabled = profile is ServerProfile.LOCAL_OPERATOR
    return OperatorStatusResponse(
        role=snapshot.role,
        profile=profile.value,
        operator_slot_occupied=snapshot.operator_slot_occupied,
        changed=snapshot.changed,
        can_acquire=enabled and not snapshot.operator_slot_occupied,
        can_takeover=(
            enabled
            and snapshot.operator_slot_occupied
            and snapshot.role != "operator"
        ),
    )


def _configuration_patch(value: Any) -> GoalConfigurationPatch:
    return GoalConfigurationPatch(**model_payload(value))


def _write_context(value: Any) -> WriteContext:
    return WriteContext(**model_payload(value))


def _todo_completion(value: Any) -> TodoCompletion:
    return TodoCompletion(**model_payload(value))


def _quota_plan(value: QuotaMutationPlanResponse) -> QuotaMutationPlan:
    payload = model_payload(value)
    before = QuotaBudget(**payload.pop("before"))
    after_payload = payload.pop("after")
    correctness = WriteCorrectness(**payload.pop("correctness"))
    return QuotaMutationPlan(
        **payload,
        before=before,
        after=QuotaBudget(**after_payload) if after_payload is not None else None,
        correctness=correctness,
    )
