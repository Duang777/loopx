from __future__ import annotations

import base64
import json
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import loopx.application.goals.history as history_module
from loopx.application import (
    ApplicationContext,
    RevisionConflict,
    StateUnavailable,
    ValidationFailed,
    WriteContext,
)
from loopx.application.goals.history import (
    GoalHistoryService,
    HistoryEntry,
    HistoryPage,
)
from loopx.application.goals.quota import GoalQuotaService
from loopx.control_plane.runtime.runtime_projection_route import (
    resolve_goal_source_runtime_route,
)
from loopx.history import collect_history

from .fixtures import PRIMARY_AGENT_ID, PRIMARY_GOAL_ID, materialize_closed_loop_fixture
from .fixtures.closed_loop import FIXED_UTC_TIME, ClosedLoopFixture


FORBIDDEN_HISTORY_FIELDS = {
    "health_check",
    "index_path",
    "json_path",
    "logs",
    "markdown_path",
    "payload",
    "raw",
    "recommended_action",
    "registry",
    "repo",
    "runtime_root",
    "state",
    "state_file",
}
SECRET_LIKE_TEXT = "sk-" + "1" * 16


def _context(
    fixture: ClosedLoopFixture,
    *,
    resolver: Any = resolve_goal_source_runtime_route,
) -> ApplicationContext:
    return ApplicationContext(
        registry_path=fixture.registry_path,
        runtime_root_override=str(fixture.runtime_root),
        scan_roots=(fixture.project,),
        clock=lambda: FIXED_UTC_TIME,
        resolve_goal_route=resolver,
    )


def _write_context(revision: str, key: str) -> WriteContext:
    return WriteContext(
        actor="application-history-test",
        idempotency_key=key,
        expected_revision=revision,
    )


def _append_spend_and_void(
    fixture: ClosedLoopFixture,
    *,
    event_time: str,
) -> None:
    quota = GoalQuotaService(_context(fixture), PRIMARY_GOAL_ID)
    spend = quota.preview_spend(agent_id=PRIMARY_AGENT_ID)
    spent = quota.apply_spend(
        spend,
        write_context=_write_context(spend.revision, "history-spend-001"),
    )
    void = quota.preview_void(
        voided_run_generated_at=spent.event_generated_at,
        reason_summary="Correct one duplicate fixture spend.",
        agent_id=PRIMARY_AGENT_ID,
    )
    voided = quota.apply_void(
        void,
        write_context=_write_context(void.revision, "history-void-001"),
    )
    assert spent.event_generated_at == voided.event_generated_at == event_time


def _assert_public_page(page: HistoryPage, fixture: ClosedLoopFixture) -> None:
    payload = asdict(page)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert FORBIDDEN_HISTORY_FIELDS.isdisjoint(payload)
    assert all(
        not isinstance(getattr(page, field.name), dict) for field in fields(page)
    )
    for item in page.items:
        assert isinstance(item, HistoryEntry)
        assert FORBIDDEN_HISTORY_FIELDS.isdisjoint(asdict(item))
        assert all(
            not isinstance(getattr(item, field.name), dict) for field in fields(item)
        )
    for path in (
        fixture.root,
        fixture.project,
        fixture.registry_path,
        fixture.runtime_root,
        *fixture.state_files.values(),
    ):
        assert str(path) not in serialized


def _append_index_record(
    fixture: ClosedLoopFixture,
    record: dict[str, object],
) -> None:
    index_path = (
        fixture.runtime_root / "goals" / PRIMARY_GOAL_ID / "runs" / "index.jsonl"
    )
    with index_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def test_history_is_compact_verified_paged_and_revalidates_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    event_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    monkeypatch.setattr(
        "loopx.control_plane.quota.slot_accounting._now_local",
        lambda: event_time,
    )
    _append_spend_and_void(fixture, event_time=event_time)
    route_calls: list[tuple[str, str | None]] = []

    def counting_resolver(
        *,
        registry_path: Path,
        goal_id: str,
        runtime_root_override: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route_calls.append((goal_id, runtime_root_override))
        return resolve_goal_source_runtime_route(
            registry_path=registry_path,
            goal_id=goal_id,
            runtime_root_override=runtime_root_override,
            registry=registry,
        )

    history = GoalHistoryService(
        context=_context(fixture, resolver=counting_resolver),
        goal_id=PRIMARY_GOAL_ID,
    )
    first = history.list(page_size=2)

    assert isinstance(first, HistoryPage)
    assert first.generated_at == FIXED_UTC_TIME
    assert first.revision.startswith("sha256:")
    assert first.total_count == 3
    assert len(first.items) == 2
    assert first.next_page_token is not None
    assert {item.classification for item in first.items} == {
        "quota_slot_spent",
        "quota_slot_voided",
    }
    assert all(item.artifacts_verified for item in first.items)
    assert all(item.json_available for item in first.items)
    assert all(item.markdown_available for item in first.items)
    assert all(item.run_id.startswith("sha256:") for item in first.items)
    _assert_public_page(first, fixture)

    second = history.list(page_size=2, page_token=first.next_page_token)

    assert second.generated_at == FIXED_UTC_TIME
    assert second.revision == first.revision
    assert second.total_count == first.total_count
    assert second.next_page_token is None
    assert len(second.items) == 1
    assert second.items[0].classification == "application_fixture_ready"
    assert second.items[0].artifacts_verified is True
    assert {item.run_id for item in first.items}.isdisjoint(
        item.run_id for item in second.items
    )
    assert route_calls == [
        (PRIMARY_GOAL_ID, None),
        (PRIMARY_GOAL_ID, None),
    ]
    _assert_public_page(second, fixture)


def test_history_cursor_rejects_mutated_history_and_malformed_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    event_time = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    monkeypatch.setattr(
        "loopx.control_plane.quota.slot_accounting._now_local",
        lambda: event_time,
    )
    _append_spend_and_void(fixture, event_time=event_time)
    context = _context(fixture)
    history = GoalHistoryService(context=context, goal_id=PRIMARY_GOAL_ID)
    first = history.list(page_size=1)
    assert first.next_page_token is not None

    quota = GoalQuotaService(context=context, goal_id=PRIMARY_GOAL_ID)
    new_spend = quota.preview_spend(agent_id=PRIMARY_AGENT_ID)
    quota.apply_spend(
        new_spend,
        write_context=_write_context(new_spend.revision, "history-spend-002"),
    )

    with pytest.raises(RevisionConflict) as stale:
        history.list(page_size=1, page_token=first.next_page_token)
    assert stale.value.details["goal_id"] == PRIMARY_GOAL_ID
    assert stale.value.details["expected_revision"] == first.revision
    assert stale.value.details["current_revision"] != first.revision

    with pytest.raises(ValidationFailed) as malformed:
        history.list(page_size=1, page_token="not-a-valid-token!")
    assert malformed.value.details == {"field": "page_token"}

    token = first.next_page_token
    assert token is not None
    decoded = json.loads(
        base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    )
    decoded["revision"] = history.list(page_size=1).revision
    decoded["offset"] = 999
    out_of_range = (
        base64.urlsafe_b64encode(
            json.dumps(decoded, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    with pytest.raises(ValidationFailed) as invalid_offset:
        history.list(page_size=1, page_token=out_of_range)
    assert invalid_offset.value.details == {
        "field": "page_token",
        "reason": "offset_out_of_range",
    }


def test_history_projection_filters_paths_and_secret_like_fields(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    artifact = fixture.receipt_paths["history"]
    _append_index_record(
        fixture,
        {
            "generated_at": "2099-01-02T03:04:05+00:00",
            "goal_id": PRIMARY_GOAL_ID,
            "classification": f"Inspect {fixture.registry_path}",
            "agent_id": SECRET_LIKE_TEXT,
            "delivery_outcome": f"Bearer {'a' * 24}",
            "progress_scope": f"path={fixture.runtime_root}",
            "json_path": str(artifact),
            "markdown_path": str(artifact),
        },
    )
    history = GoalHistoryService(
        context=_context(fixture),
        goal_id=PRIMARY_GOAL_ID,
    )

    first = history.list(page_size=1)
    repeated = history.list(page_size=1)

    assert first == repeated
    assert first.total_count == 2
    assert first.next_page_token is not None
    entry = first.items[0]
    assert entry.classification == "unknown"
    assert entry.agent_id is None
    assert entry.delivery_outcome is None
    assert entry.progress_scope is None
    assert entry.artifacts_verified is True
    serialized = json.dumps(asdict(first), ensure_ascii=False, sort_keys=True)
    assert SECRET_LIKE_TEXT not in serialized
    assert "Bearer" not in serialized
    assert str(fixture.registry_path) not in serialized
    assert str(fixture.runtime_root) not in serialized


def test_collect_history_semantic_page_is_opt_in_and_keeps_legacy_payload(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    artifact = fixture.receipt_paths["history"]
    for index in range(2):
        _append_index_record(
            fixture,
            {
                "generated_at": (
                    datetime(2099, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
                ).isoformat(),
                "goal_id": PRIMARY_GOAL_ID,
                "classification": f"semantic_page_fixture_{index}",
                "json_path": str(artifact),
                "markdown_path": str(artifact),
            },
        )

    legacy = collect_history(
        registry_path=fixture.registry_path,
        runtime_root=fixture.runtime_root,
        goal_id=PRIMARY_GOAL_ID,
        limit=2,
        include_runtime_goals=False,
    )
    paged = collect_history(
        registry_path=fixture.registry_path,
        runtime_root=fixture.runtime_root,
        goal_id=PRIMARY_GOAL_ID,
        limit=1,
        include_runtime_goals=False,
        semantic_page_offset=1,
    )

    assert set(legacy) == {
        "ok",
        "registry",
        "runtime_root",
        "goal_filter",
        "goal_count",
        "run_count",
        "goals",
        "runs",
    }
    assert "semantic_page" not in legacy
    assert paged["runs"] == legacy["runs"][1:2]
    assert paged["run_count"] == 3
    assert paged["semantic_page"] == {
        "schema_version": "history_semantic_page_v1",
        "offset": 1,
        "limit": 1,
        "total_count": 3,
        "revision": paged["semantic_page"]["revision"],
    }
    assert paged["semantic_page"]["revision"].startswith("sha256:")


def test_history_projects_only_requested_rows_from_large_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    artifact = fixture.receipt_paths["history"]
    start = datetime(2099, 1, 1, tzinfo=timezone.utc)
    for index in range(250):
        _append_index_record(
            fixture,
            {
                "generated_at": (start + timedelta(seconds=index)).isoformat(),
                "goal_id": PRIMARY_GOAL_ID,
                "classification": f"large_history_fixture_{index}",
                "json_path": str(artifact),
                "markdown_path": str(artifact),
            },
        )

    projected_runs: list[str] = []
    original_entry = history_module._entry

    def counting_entry(run: Any) -> HistoryEntry:
        projected_runs.append(str(run.get("generated_at")))
        return original_entry(run)

    monkeypatch.setattr(history_module, "_entry", counting_entry)
    page = GoalHistoryService(
        context=_context(fixture),
        goal_id=PRIMARY_GOAL_ID,
    ).list(page_size=3)

    assert page.total_count == 251
    assert len(page.items) == 3
    assert len(projected_runs) == 3
    assert page.next_page_token is not None


def test_history_cursor_revision_covers_rows_outside_current_page(
    tmp_path: Path,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    artifact = fixture.receipt_paths["history"]
    _append_index_record(
        fixture,
        {
            "generated_at": "2099-01-01T00:00:00+00:00",
            "goal_id": PRIMARY_GOAL_ID,
            "classification": "new_history_fixture",
            "json_path": str(artifact),
            "markdown_path": str(artifact),
        },
    )
    history = GoalHistoryService(
        context=_context(fixture),
        goal_id=PRIMARY_GOAL_ID,
    )
    first = history.list(page_size=1)
    assert first.next_page_token is not None

    _append_index_record(
        fixture,
        {
            "generated_at": "2000-01-01T00:00:00+00:00",
            "goal_id": PRIMARY_GOAL_ID,
            "classification": "old_history_fixture",
            "json_path": str(artifact),
            "markdown_path": str(artifact),
        },
    )
    current = history.list(page_size=1)
    assert current.items == first.items
    assert current.revision != first.revision
    with pytest.raises(RevisionConflict):
        history.list(page_size=1, page_token=first.next_page_token)


@pytest.mark.parametrize(
    "unsafe_kind",
    ["secret", "absolute_path"],
)
def test_history_unsafe_timestamp_raises_typed_state_error(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    unsafe_timestamp = (
        f"{'to' + 'ken='}{'a' * 16}"
        if unsafe_kind == "secret"
        else str(fixture.root / "private-run")
    )
    _append_index_record(
        fixture,
        {
            "generated_at": unsafe_timestamp,
            "goal_id": PRIMARY_GOAL_ID,
            "classification": "unsafe_timestamp_fixture",
        },
    )
    history = GoalHistoryService(
        context=_context(fixture),
        goal_id=PRIMARY_GOAL_ID,
    )

    with pytest.raises(StateUnavailable) as raised:
        history.list()

    assert raised.value.details == {
        "resource": "goal_history",
        "cause": "invalid_timestamp",
    }


@pytest.mark.parametrize("page_size", [0, 101, True])
def test_history_rejects_invalid_page_size(
    tmp_path: Path,
    page_size: object,
) -> None:
    fixture = materialize_closed_loop_fixture(tmp_path)
    history = GoalHistoryService(
        context=_context(fixture),
        goal_id=PRIMARY_GOAL_ID,
    )

    with pytest.raises(ValidationFailed) as error:
        history.list(page_size=page_size)  # type: ignore[arg-type]

    assert error.value.details == {"field": "page_size"}
