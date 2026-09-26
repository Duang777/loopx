"""Best-effort Host observation transport; TS owns union, limits and consent.

Not an execution controller. Only confirmed 60-second prefixes survive a crash;
there is no open interval that a later process can extrapolate indefinitely.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from collections.abc import Iterator

from . import usage_ping


@contextmanager
def observe_goal_execution(runtime_root: Path, goal_id: str) -> Iterator[None]:
    stop = threading.Event()
    publish = None
    try:
        # This is only a scheduling hint. TS rechecks consent, environment,
        # notice and generation under the same lock used by disable.
        path = usage_ping.state_path()
        state = json.loads(path.read_text())
        generation = state.get("generation")
        if (goal_id and generation and state.get("consent") != "disabled"
                and os.environ.get("LOOPX_USAGE_PING") != "0"
                and os.environ.get("DO_NOT_TRACK") != "1"
                and os.environ.get("CI") != "true"):
            key = hashlib.sha256(json.dumps([generation, str(runtime_root.resolve()), goal_id]).encode()).hexdigest()
            wall = time.time_ns() // 1_000_000
            origin = time.monotonic()
            previous = 0
            lock = threading.Lock()

            def checkpoint() -> None:
                nonlocal previous
                try:
                    if not lock.acquire(blocking=False):
                        return
                    try:
                        elapsed = int((time.monotonic() - origin) * 1000)
                        # Scheduling suspension is not proven execution. Drop a
                        # delayed prefix rather than calling hours asleep work.
                        start = wall + previous
                        previous = elapsed
                        usage_ping._detach(usage_ping._request(
                            "goal", path, generation=generation,
                            observation={"key": key, "start": start, "end": wall + elapsed},
                        ))
                    finally:
                        lock.release()
                except Exception:
                    pass

            def periodically() -> None:
                while not stop.wait(60):
                    checkpoint()

            publish = checkpoint
            worker = threading.Thread(target=periodically, daemon=True, name="loopx-usage-goal")
            worker.start()
    except Exception:
        pass
    try:
        yield
    finally:
        stop.set()
        # No join or HTTP await on the business path. A racing checkpoint is
        # harmless: the TS interval union deduplicates it.
        if publish is not None:
            publish()
