from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from loopx.application import (
    ApplicationContext,
    CapabilityDescription,
    CapabilityKind,
    CapabilityScope,
    CapabilityUnavailableReason,
    GoalOverview,
    GoalSummary,
    LoopXApplication,
    Profile,
    StateUnavailable,
)
from loopx.http_server import create_app
from examples.control_plane.todo_lifecycle_fixtures import (
    GOAL_ID as PRIMARY_GOAL_ID,
    write_fixture,
)


ORIGIN = "http://127.0.0.1:8765"


class _Goal:
    def __init__(self, overview: GoalOverview) -> None:
        self._overview = overview

    def overview(self) -> GoalOverview:
        return self._overview


class _ReadApplication:
    def __init__(self, *, fail_goal: bool = False) -> None:
        self.fail_goal = fail_goal
        self.overview = GoalOverview(
            goal_id="goal-alpha",
            status="active",
            attention_status=None,
            domain="product",
            adapter_kind="local",
            adapter_status="ready",
            generated_at="2026-08-07T00:00:00Z",
            revision="sha256:overview",
            route_status="canonical",
            routed_to_source_registry=False,
        )

    def describe_capabilities(self) -> tuple[CapabilityDescription, ...]:
        return (
            CapabilityDescription(
                capability_id="goal.turn.run_once",
                scope=CapabilityScope.GOAL,
                kind=CapabilityKind.EXECUTE,
                available=False,
                supports_preview=True,
                requires_preview=True,
                unavailable_reason=CapabilityUnavailableReason(
                    code="profile_execution_denied",
                    message="HTTP profiles do not permit Turn execution.",
                    details={"profile": "http_local_operator"},
                ),
            ),
        )

    def list_goals(self) -> tuple[GoalSummary, ...]:
        return (
            GoalSummary(
                goal_id="goal-alpha",
                status="active",
                domain="product",
                generated_at="2026-08-07T00:00:00Z",
                revision="sha256:goal",
            ),
        )

    def get_goal(self, goal_id: str) -> _Goal:
        if self.fail_goal:
            raise StateUnavailable(
                details={
                    "registry_path": "/Users/private/.loopx/registry.json",
                    "raw_log": "secret traceback",
                    "resource": "goal_status",
                }
            )
        assert goal_id == "goal-alpha"
        return _Goal(self.overview)


def _client(application: object | None = None) -> TestClient:
    return TestClient(
        create_app(application or _ReadApplication(), profile="local_operator"),
        base_url=ORIGIN,
    )


def test_capabilities_transparently_include_unavailable_run_once() -> None:
    response = _client().get("/api/v1/capabilities")
    assert response.status_code == 200
    capability = response.json()["capabilities"][0]
    assert capability["capability_id"] == "goal.turn.run_once"
    assert capability["kind"] == "execute"
    assert capability["available"] is False
    assert capability["unavailable_reason"]["code"] == "profile_execution_denied"


def test_goal_projections_emit_stable_etag_and_support_304() -> None:
    client = _client()
    first = client.get("/api/v1/goals")
    assert first.status_code == 200
    assert first.headers["etag"].startswith('"sha256:')
    unchanged = client.get(
        "/api/v1/goals",
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert unchanged.status_code == 304
    assert unchanged.content == b""

    overview = client.get("/api/v1/goals/goal-alpha/overview")
    unchanged_overview = client.get(
        "/api/v1/goals/goal-alpha/overview",
        headers={"If-None-Match": overview.headers["etag"]},
    )
    assert unchanged_overview.status_code == 304


def test_expected_application_errors_are_public_safe() -> None:
    response = _client(_ReadApplication(fail_goal=True)).get(
        "/api/v1/goals/goal-alpha/overview"
    )
    assert response.status_code == 503
    text = response.text
    assert "/Users/private" not in text
    assert "secret traceback" not in text
    assert response.json()["error"]["details"]["registry_path"] == "[redacted]"
    assert response.json()["error"]["details"]["raw_log"] == "[redacted]"


def test_openapi_is_31_unique_and_never_exposes_turn_execution_or_generic_rpc() -> None:
    schema = create_app(_ReadApplication()).openapi()
    assert schema["openapi"].startswith("3.1")
    paths = schema["paths"]
    assert "/api/v1/goals/{goal_id}/turns/plan" in paths
    serialized_paths = "\n".join(paths)
    assert "run_once" not in serialized_paths
    assert "run-once" not in serialized_paths
    assert "command" not in serialized_paths
    assert "dispatch" not in serialized_paths
    operation_ids = [
        operation["operationId"]
        for methods in paths.values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert "goal.turn.plan" in operation_ids
    assert "goal.turn.run_once" not in operation_ids


def test_missing_static_build_reports_diagnostic_without_old_page_fallback() -> None:
    response = _client().get("/")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "static_assets_unavailable"


def test_real_application_fixture_maps_read_projections_without_private_paths(
    tmp_path: Path,
) -> None:
    registry_path, _state_file = write_fixture(tmp_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    runtime_root = Path(registry["common_runtime_root"])
    project = registry_path.parent.parent
    application = LoopXApplication(
        ApplicationContext(
            registry_path=registry_path,
            runtime_root_override=str(runtime_root),
            scan_roots=(project,),
            profile=Profile.HTTP_READ_ONLY,
            clock=lambda: datetime(2026, 8, 7, tzinfo=timezone.utc),
        )
    )
    client = TestClient(
        create_app(application, profile="read_only"),
        base_url=ORIGIN,
    )

    todos = client.get(f"/api/v1/goals/{PRIMARY_GOAL_ID}/todos")
    todo_id = todos.json()["items"][0]["todo_id"]
    responses = (
        client.get("/api/v1/goals"),
        client.get(f"/api/v1/goals/{PRIMARY_GOAL_ID}/overview"),
        todos,
        client.get(f"/api/v1/goals/{PRIMARY_GOAL_ID}/history?page_size=10"),
        client.get(f"/api/v1/goals/{PRIMARY_GOAL_ID}/quota/should-run"),
        client.get(f"/api/v1/goals/{PRIMARY_GOAL_ID}/leases/{todo_id}"),
    )
    assert [response.status_code for response in responses] == [200] * len(responses)
    serialized = "\n".join(response.text for response in responses)
    assert str(tmp_path) not in serialized
    assert str(registry_path) not in serialized
    assert str(runtime_root) not in serialized
