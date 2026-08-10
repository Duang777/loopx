#!/usr/bin/env python3
"""Smoke-test the persistent read-only Codex app-server chat seam."""

from __future__ import annotations

import json
import stat
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from loopx.chat_agent import (  # noqa: E402
    CodexChatAgentError,
    CodexChatAgentSession,
)


FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import sys
import time

turn_count = 0
goal_status = "inactive"
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialized":
        continue
    if method == "initialize":
        result = {"serverInfo": {"name": "fake-codex"}}
    elif method in {"thread/start", "thread/resume"}:
        params = message.get("params", {})
        if params.get("sandbox") != "read-only" or params.get("approvalPolicy") != "never":
            print(json.dumps({
                "id": request_id,
                "error": {"code": -32602, "message": "unsafe chat boundary"},
            }), flush=True)
            continue
        result = {"thread": {"id": "thread-loopx-chat"}}
    elif method == "thread/goal/set":
        goal_status = "active"
        result = {"goal": {"threadId": "thread-loopx-chat", "status": "active"}}
    elif method == "thread/goal/get":
        result = {"goal": {"threadId": "thread-loopx-chat", "status": goal_status}}
    elif method == "turn/start":
        turn_count += 1
        params = message.get("params", {})
        prompt = params.get("input", [{}])[0].get("text", "")
        if "<loopx-review-json>" not in prompt or "user message" not in prompt:
            print(json.dumps({
                "id": request_id,
                "error": {"code": -32602, "message": "missing review contract"},
            }), flush=True)
            continue
        turn_id = f"turn-loopx-chat-{turn_count}"
        print(json.dumps({
            "method": "turn/started",
            "params": {
                "threadId": "thread-loopx-chat",
                "turn": {"id": turn_id, "status": "inProgress"},
            },
        }), flush=True)
        result = {"turn": {"id": turn_id, "status": "running"}}
        print(json.dumps({"id": request_id, "result": result}), flush=True)
        if "force idle timeout" in prompt:
            continue
        if "activity keeps alive" in prompt:
            for index in range(3):
                time.sleep(0.1)
                print(json.dumps({
                    "method": "item/started",
                    "params": {"threadId": "thread-loopx-chat", "turnId": turn_id, "item": {"id": f"work-{index}"}},
                }), flush=True)
        visible_answer = "Reviewed " + params.get("cwd", "") + ".\n"
        response = (
            visible_answer + '<loopx-review-json>'
            + json.dumps({
                "schema_version": "loopx_chat_agent_response_v0",
                "message": visible_answer.strip(),
                "proposals": [{
                    "kind": "todo",
                    "text": "[P1] Add the selected review flow.",
                    "priority": "P1",
                    "rationale": "This is the smallest reviewable step.",
                }],
                "gate": None,
            })
            + '</loopx-review-json>'
        )
        marker_split = response.index("<loopx-review-json>") + 7
        for chunk in (response[:marker_split], response[marker_split:]):
            print(json.dumps({
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": "thread-loopx-chat",
                    "turnId": turn_id,
                    "itemId": f"item-{turn_count}",
                    "delta": chunk,
                },
            }), flush=True)
        print(json.dumps({
            "method": "turn/completed",
            "params": {
                "threadId": "thread-loopx-chat",
                "turn": {"id": turn_id, "status": "completed"},
            },
        }), flush=True)
        continue
    elif method == "turn/interrupt":
        result = {}
    else:
        result = {}
    print(json.dumps({"id": request_id, "result": result}), flush=True)
'''


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loopx-chat-agent-") as raw_tmp:
        root = Path(raw_tmp)
        fake_codex = root / "codex"
        fake_codex.write_text(FAKE_CODEX, encoding="utf-8")
        fake_codex.chmod(fake_codex.stat().st_mode | stat.S_IXUSR)

        session = CodexChatAgentSession.start(
            codex_bin=str(fake_codex),
            work_dir=root,
            goal_id="loopx-chat-smoke",
            objective="Keep the review loop bounded.",
            response_timeout_sec=3.0,
        )
        try:
            observed = []
            result = session.send(
                "user message: suggest the next bounded step",
                on_event=lambda kind, payload: observed.append((kind, payload)),
            )
        finally:
            session.close()

        assert result["message"] == "Reviewed [project].", result
        assert result["proposals"] == [
            {
                "kind": "todo",
                "text": "[P1] Add the selected review flow.",
                "priority": "P1",
                "rationale": "This is the smallest reviewable step.",
            }
        ], result
        assert result["gate"] is None, result
        assert str(root) not in json.dumps(result), result
        visible = "".join(
            str(payload.get("text") or "")
            for kind, payload in observed
            if kind == "answer.delta"
        )
        assert visible.strip() == "Reviewed [project].", observed
        assert "<loopx-review-json>" not in visible, visible
        assert not any(kind == "assistant.delta" for kind, _ in observed), observed
        delta_index = next(index for index, item in enumerate(observed) if item[0] == "answer.delta")
        completed_phase_index = next(
            index
            for index, item in enumerate(observed)
            if item[0] == "agent.phase" and item[1].get("method") == "turn/completed"
        )
        assert delta_index < completed_phase_index, observed

        resumed = CodexChatAgentSession.start(
            codex_bin=str(fake_codex),
            work_dir=root,
            goal_id="loopx-chat-smoke",
            objective="Keep the review loop bounded.",
            resume_thread_id="thread-loopx-chat",
            response_timeout_sec=3.0,
        )
        assert resumed.thread_id == "thread-loopx-chat"
        resumed.close()

        active_session = CodexChatAgentSession.start(
            codex_bin=str(fake_codex),
            work_dir=root,
            goal_id="loopx-chat-smoke",
            objective="Keep the review loop bounded.",
            response_timeout_sec=3.0,
            idle_timeout_sec=0.15,
            hard_timeout_sec=2.0,
        )
        try:
            active_result = active_session.send("activity keeps alive")
        finally:
            active_session.close()
        assert active_result["proposals"], active_result

        timeout_session = CodexChatAgentSession.start(
            codex_bin=str(fake_codex),
            work_dir=root,
            goal_id="loopx-chat-smoke",
            objective="Keep the review loop bounded.",
            response_timeout_sec=3.0,
            idle_timeout_sec=0.2,
            hard_timeout_sec=2.0,
        )
        try:
            timeout_session.send("force idle timeout")
        except CodexChatAgentError as exc:
            assert exc.gate["kind"] == "host_tool_gate", exc.gate
            assert exc.error_code == "idle_timeout", exc.error_code
            assert "activity" in exc.gate["summary"], exc.gate
        else:
            raise AssertionError("Codex timeout must stop at a recoverable host-tool gate")
        finally:
            timeout_session.close()

        try:
            CodexChatAgentSession.start(
                codex_bin=str(root / "missing-codex"),
                work_dir=root,
                goal_id="loopx-chat-smoke",
                objective="Keep the review loop bounded.",
                response_timeout_sec=0.2,
            )
        except CodexChatAgentError as exc:
            assert exc.gate["kind"] == "host_tool_gate", exc.gate
            assert "Codex" in exc.gate["summary"], exc.gate
        else:
            raise AssertionError("missing Codex binary must stop at a host-tool gate")

    print("loopx-chat-agent-smoke: ok")


if __name__ == "__main__":
    main()
