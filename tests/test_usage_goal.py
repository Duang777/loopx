"""Host observer remains outside execution authority and never waits for HTTP."""
import json
import threading
import time

import pytest

from loopx import usage_goal, usage_ping


def test_telemetry_failure_cannot_replace_host_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_ping, "DEFAULT_RUNTIME_ROOT", tmp_path)
    usage_ping.state_path().write_text(json.dumps({"generation": "fixture", "consent": "enabled"}))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(usage_ping, "_detach", lambda _: (_ for _ in ()).throw(OSError("fixture failure")))
    with pytest.raises(ValueError, match="host failure"):
        with usage_goal.observe_goal_execution(tmp_path, "fixture-goal"):
            raise ValueError("host failure")


def test_disabled_observer_starts_no_worker_or_process(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_ping, "DEFAULT_RUNTIME_ROOT", tmp_path)
    usage_ping.state_path().write_text(json.dumps({"generation": "fixture", "consent": "disabled"}))
    monkeypatch.setattr(threading.Thread, "start", lambda _: pytest.fail("disabled worker"))
    monkeypatch.setattr(usage_ping, "_detach", lambda _: pytest.fail("disabled process"))
    with usage_goal.observe_goal_execution(tmp_path, "fixture-goal"):
        pass


def test_periodic_observation_does_not_need_turn_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_ping, "DEFAULT_RUNTIME_ROOT", tmp_path)
    usage_ping.state_path().write_text(json.dumps({"generation": "fixture", "consent": "enabled"}))
    for name in ("CI", "DO_NOT_TRACK", "LOOPX_USAGE_PING"):
        monkeypatch.delenv(name, raising=False)
    observed = []
    monkeypatch.setattr(usage_ping, "_detach", observed.append)
    # Accelerate only the observer's checkpoint interval, not clocks or threads.
    real_event = threading.Event
    from types import SimpleNamespace

    class CheckpointEvent:
        def __init__(self):
            self.event = real_event()

        def wait(self, seconds):
            return self.event.wait(0.01)

        def set(self):
            self.event.set()

    monkeypatch.setattr(usage_goal, "threading", SimpleNamespace(Event=CheckpointEvent, Lock=threading.Lock, Thread=threading.Thread))
    with usage_goal.observe_goal_execution(tmp_path, "private-goal"):
        deadline = time.monotonic() + 1
        while not observed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert observed, "unfinished Host should checkpoint"
    assert all(row["observation"]["start"] <= row["observation"]["end"] for row in observed)
    assert "private-goal" not in json.dumps(observed)
    assert str(tmp_path) not in json.dumps([row["observation"] for row in observed])
