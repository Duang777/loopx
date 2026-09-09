import json
from pathlib import Path

import pytest

from loopx.event_sourced_state import (
    TODO_ADDED,
    AppendOnlyStateEventStore,
    StateEventError,
    make_state_event,
)


def test_load_observes_events_appended_by_another_store(tmp_path: Path) -> None:
    event_log = tmp_path / "events.jsonl"
    reader = AppendOnlyStateEventStore(event_log)
    writer = AppendOnlyStateEventStore(event_log)
    assert reader.load() == []

    appended = writer.append(
        make_state_event(
            event_id="evt-concurrent-writer",
            goal_id="goal-a",
            event_type=TODO_ADDED,
            refs={"todo_id": "todo_concurrent_writer"},
            payload={"role": "agent", "title": "Observe the durable event."},
            recorded_at="2026-09-06T00:00:00Z",
        )
    )

    assert appended["append_sequence"] == 1
    assert reader.load() == [appended]


@pytest.mark.parametrize("sequence", [True, False, 1.5, "2"])
def test_load_rejects_non_integer_append_sequence(tmp_path: Path, sequence: object) -> None:
    event_log = tmp_path / "events.jsonl"
    event = make_state_event(
        event_id="evt-bool-sequence",
        goal_id="goal-a",
        event_type=TODO_ADDED,
        refs={"todo_id": "todo_bool_sequence"},
        payload={"role": "agent", "title": "Reject corrupt sequence."},
        recorded_at="2026-09-07T00:00:00Z",
    )
    event["append_sequence"] = sequence
    event_log.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(StateEventError, match="append_sequence must be an integer"):
        AppendOnlyStateEventStore(event_log).load()
