from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from loopx.application import (
    ApplicationContext,
    GoalOverview,
    GoalStatus,
    LoopXApplication,
    StateUnavailable,
)
from loopx.control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)

from .fixtures import PRIMARY_GOAL_ID, materialize_closed_loop_fixture
from .fixtures.closed_loop import (
    FIXED_UTC_TIME,
)


FIXED_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
PRIVATE_STATE_SENTINEL = "owner-private-status-payload-must-not-leak"
STATUS_FIELDS = {
    "attention_status",
    "generated_at",
    "goal_id",
    "revision",
    "route_status",
    "routed_to_source_registry",
    "status",
}
OVERVIEW_FIELDS = STATUS_FIELDS | {
    "adapter_kind",
    "adapter_status",
    "domain",
}


def _assert_path_free_scalar_projection(
    projection: GoalStatus | GoalOverview,
    *,
    expected_fields: set[str],
    forbidden_paths: tuple[Path, ...],
) -> None:
    payload = asdict(projection)

    assert set(payload) == expected_fields
    assert all(
        value is None or isinstance(value, (bool, str)) for value in payload.values()
    )
    assert not {
        "active_state",
        "payload",
        "registry",
        "runtime_root",
        "source_registry",
        "state_file",
    }.intersection(payload)

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert PRIVATE_STATE_SENTINEL not in serialized
    for path in forbidden_paths:
        assert str(path) not in serialized


def test_goal_status_reads_are_typed_fresh_and_route_revalidated(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    route_calls: list[str] = []

    def counting_resolver(
        *,
        registry_path: Path,
        goal_id: str,
        runtime_root_override: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route_calls.append(goal_id)
        return resolve_goal_source_runtime_route(
            registry_path=registry_path,
            goal_id=goal_id,
            runtime_root_override=runtime_root_override,
            registry=registry,
        )

    context = ApplicationContext(
        registry_path=fixture.registry_path,
        runtime_root_override=str(fixture.runtime_root),
        scan_roots=(fixture.project,),
        clock=lambda: FIXED_NOW,
        resolve_goal_route=counting_resolver,
    )
    handle = LoopXApplication(context).get_goal(PRIMARY_GOAL_ID)
    assert route_calls == [PRIMARY_GOAL_ID]

    status = handle.status()
    assert route_calls == [PRIMARY_GOAL_ID] * 2
    overview = handle.overview()
    assert route_calls == [PRIMARY_GOAL_ID] * 3

    assert isinstance(status, GoalStatus)
    assert isinstance(overview, GoalOverview)
    assert status.goal_id == overview.goal_id == PRIMARY_GOAL_ID
    assert status.status == overview.status == "active"
    assert status.generated_at == overview.generated_at == FIXED_UTC_TIME
    assert status.revision == overview.revision
    assert status.revision.startswith("sha256:")
    assert overview.domain == "todo-lifecycle-fixture"
    assert overview.adapter_kind == "generic_project_goal_v0"
    assert overview.adapter_status == "connected"

    forbidden_paths = (
        fixture.root,
        fixture.project,
        fixture.registry_path,
        fixture.runtime_root,
        fixture.state_files[PRIMARY_GOAL_ID],
    )
    _assert_path_free_scalar_projection(
        status,
        expected_fields=STATUS_FIELDS,
        forbidden_paths=forbidden_paths,
    )
    _assert_path_free_scalar_projection(
        overview,
        expected_fields=OVERVIEW_FIELDS,
        forbidden_paths=forbidden_paths,
    )

    state_file = fixture.state_files[PRIMARY_GOAL_ID]
    state_file.write_text(
        state_file.read_text(encoding="utf-8")
        + f"\n<!-- {PRIVATE_STATE_SENTINEL} -->\n",
        encoding="utf-8",
    )

    refreshed = handle.status()

    assert route_calls == [PRIMARY_GOAL_ID] * 4
    assert refreshed.generated_at == FIXED_UTC_TIME
    assert refreshed.status == status.status
    assert refreshed.revision != status.revision
    _assert_path_free_scalar_projection(
        refreshed,
        expected_fields=STATUS_FIELDS,
        forbidden_paths=forbidden_paths,
    )


def test_malformed_canonical_status_state_raises_typed_error(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    malformed_registry = tmp_path / "malformed-source" / ".loopx" / "registry.json"
    malformed_registry.parent.mkdir(parents=True)
    malformed_registry.write_text("{not-json\n", encoding="utf-8")

    def malformed_source_resolver(
        *,
        registry_path: Path,
        goal_id: str,
        runtime_root_override: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del registry_path, goal_id, runtime_root_override, registry
        return {
            "status": "source_registry",
            "source_registry": str(malformed_registry),
            "source_runtime_root": str(fixture.runtime_root),
            "routed_to_source_registry": True,
        }

    handle = LoopXApplication(
        ApplicationContext(
            registry_path=fixture.registry_path,
            scan_roots=(fixture.project,),
            clock=lambda: FIXED_NOW,
            resolve_goal_route=malformed_source_resolver,
        )
    ).get_goal(PRIMARY_GOAL_ID)

    for read in (handle.status, handle.overview):
        with pytest.raises(StateUnavailable) as raised:
            read()

        error = raised.value
        assert error.code == "state_unavailable"
        assert error.retryable is True
        assert dict(error.details) == {
            "goal_id": PRIMARY_GOAL_ID,
            "resource": "canonical_source",
        }
        serialized = json.dumps(error.to_dict(), ensure_ascii=False, sort_keys=True)
        assert str(malformed_registry) not in serialized
        assert "{not-json" not in serialized
