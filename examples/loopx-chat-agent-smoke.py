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

turn_count = 0
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialized":
        continue
    if method == "initialize":
        result = {"serverInfo": {"name": "fake-codex"}}
    elif method == "thread/start":
        params = message.get("params", {})
        if params.get("sandbox") != "read-only" or params.get("approvalPolicy") != "never":
            print(json.dumps({
                "id": request_id,
                "error": {"code": -32602, "message": "unsafe chat boundary"},
            }), flush=True)
            continue
        result = {"thread": {"id": "thread-loopx-chat"}}
    elif method == "thread/goal/set":
        result = {"goal": {"threadId": "thread-loopx-chat", "status": "active"}}
    elif method == "thread/goal/get":
        result = {"goal": {"threadId": "thread-loopx-chat", "status": "active"}}
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
        if "force timeout" in prompt:
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
        response = (
            '<loopx-review-json>'
            + json.dumps({
                "schema_version": "loopx_chat_agent_response_v0",
                "message": "Reviewed " + params.get("cwd", "") + ".",
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
        print(json.dumps({
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-loopx-chat",
                "turnId": turn_id,
                "itemId": f"item-{turn_count}",
                "delta": response,
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
            result = session.send("user message: suggest the next bounded step")
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

        timeout_session = CodexChatAgentSession.start(
            codex_bin=str(fake_codex),
            work_dir=root,
            goal_id="loopx-chat-smoke",
            objective="Keep the review loop bounded.",
            response_timeout_sec=0.2,
        )
        try:
            timeout_session.send("force timeout")
        except CodexChatAgentError as exc:
            assert exc.gate["kind"] == "host_tool_gate", exc.gate
            assert "timed out" in exc.gate["summary"], exc.gate
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
