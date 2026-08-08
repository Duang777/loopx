from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .chat import (
    CHAT_AGENT_RESPONSE_SCHEMA_VERSION,
    CHAT_REVIEW_CLOSE_TAG,
    CHAT_REVIEW_OPEN_TAG,
    parse_agent_response,
)


class CodexChatAgentError(RuntimeError):
    def __init__(self, message: str, *, gate: dict[str, str]) -> None:
        super().__init__(message)
        self.gate = gate


def _host_tool_gate(summary: str, next_action: str) -> dict[str, str]:
    return {
        "kind": "host_tool_gate",
        "summary": summary,
        "next_action": next_action,
    }


def _approval_gate(summary: str) -> dict[str, str]:
    return {
        "kind": "approval_gate",
        "summary": summary,
        "next_action": "Review the request in the active host before continuing.",
    }


def _reader(stream: Any, messages: "queue.Queue[dict[str, Any] | Exception]") -> None:
    try:
        for line in stream:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception as exc:  # pragma: no cover - defensive transport path.
                messages.put(exc)
                continue
            if isinstance(payload, dict):
                messages.put(payload)
    finally:
        messages.put(EOFError("Codex app-server stream closed"))


def _extract_id(result: dict[str, Any], container: str, fallback: str) -> str:
    nested = result.get(container)
    if isinstance(nested, dict):
        value = nested.get("id") or nested.get(fallback)
        return str(value or "")
    return str(result.get(fallback) or "")


def _event_turn_id(message: dict[str, Any]) -> str:
    params = message.get("params")
    if not isinstance(params, dict):
        return ""
    turn = params.get("turn")
    if isinstance(turn, dict):
        return str(turn.get("id") or turn.get("turnId") or "")
    return str(params.get("turnId") or "")


def _event_thread_id(message: dict[str, Any]) -> str:
    params = message.get("params")
    return str(params.get("threadId") or "") if isinstance(params, dict) else ""


def _agent_item_text(message: dict[str, Any]) -> str:
    params = message.get("params")
    if not isinstance(params, dict):
        return ""
    item = params.get("item")
    if not isinstance(item, dict) or item.get("type") != "agentMessage":
        return ""
    content = item.get("content")
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in {"text", "outputText"}
        )
    return str(item.get("text") or "")


def _turn_prompt(user_message: str) -> str:
    envelope = {
        "schema_version": CHAT_AGENT_RESPONSE_SCHEMA_VERSION,
        "message": "Short answer for the operator.",
        "proposals": [
            {
                "kind": "todo",
                "text": "One bounded Todo.",
                "priority": "P1",
                "rationale": "Why this is the next safe step.",
            }
        ],
        "gate": None,
    }
    return (
        "You are the read-only planning agent inside LoopX Chat. Work only from the project root. "
        "Inspect the repository and LoopX public-safe status with read-only commands when useful. "
        "Do not edit files, mutate LoopX state, create commits, send messages, or request elevated access. "
        "If you encounter an identity, approval, or host-tool gate, stop and describe it in gate. "
        "Reply in Chinese unless the operator asks for another language. Keep proposals bounded and reviewable. "
        "Finish with exactly one machine-readable envelope using these tags and shape:\n"
        f"{CHAT_REVIEW_OPEN_TAG}{json.dumps(envelope, ensure_ascii=False)}{CHAT_REVIEW_CLOSE_TAG}\n\n"
        f"Operator user message:\n{user_message.strip()}"
    )


@dataclass
class CodexChatAgentSession:
    process: subprocess.Popen[str]
    messages: "queue.Queue[dict[str, Any] | Exception]"
    thread_id: str
    work_dir: Path
    response_timeout_sec: float = 120.0
    next_request_id: int = 5
    _pending_events: list[dict[str, Any]] = field(default_factory=list, repr=False)

    @classmethod
    def start(
        cls,
        *,
        codex_bin: str,
        work_dir: Path,
        goal_id: str,
        objective: str,
        response_timeout_sec: float = 120.0,
    ) -> "CodexChatAgentSession":
        resolved = shutil.which(codex_bin)
        if not resolved:
            raise CodexChatAgentError(
                "Codex executable is unavailable",
                gate=_host_tool_gate(
                    "Codex host tool is unavailable for LoopX Chat.",
                    "Install or select a working Codex CLI, then start LoopX Chat again.",
                ),
            )
        root = work_dir.resolve()
        try:
            process = subprocess.Popen(
                [resolved, "app-server", "--listen", "stdio://", "--enable", "goals"],
                cwd=str(root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise CodexChatAgentError(
                "Codex app-server could not start",
                gate=_host_tool_gate(
                    "Codex app-server could not start for LoopX Chat.",
                    "Verify the Codex CLI installation and app-server support.",
                ),
            ) from exc

        messages: "queue.Queue[dict[str, Any] | Exception]" = queue.Queue()
        assert process.stdout is not None
        reader = threading.Thread(target=_reader, args=(process.stdout, messages), daemon=True)
        reader.start()
        session = cls(
            process=process,
            messages=messages,
            thread_id="",
            work_dir=root,
            response_timeout_sec=response_timeout_sec,
        )
        try:
            session._request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "loopx_chat",
                        "title": "LoopX Chat",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
                request_id=1,
            )
            session._notify("initialized", {})
            thread_result = session._request(
                "thread/start",
                {
                    "cwd": str(root),
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                },
                request_id=2,
            )
            session.thread_id = _extract_id(thread_result, "thread", "threadId")
            if not session.thread_id:
                raise session._runtime_error("Codex app-server did not return a thread id.")
            session._request(
                "thread/goal/set",
                {
                    "threadId": session.thread_id,
                    "objective": f"{goal_id}: {objective}",
                    "status": "active",
                },
                request_id=3,
            )
            goal_result = session._request(
                "thread/goal/get",
                {"threadId": session.thread_id},
                request_id=4,
            )
            goal = goal_result.get("goal")
            status = str(goal.get("status") or "") if isinstance(goal, dict) else ""
            if status != "active":
                raise session._runtime_error("Codex did not confirm an active Goal session.")
            return session
        except Exception:
            session.close()
            raise

    def _runtime_error(self, summary: str) -> CodexChatAgentError:
        return CodexChatAgentError(
            summary,
            gate=_host_tool_gate(
                summary,
                "Check the Codex app-server host capability, then retry the session.",
            ),
        )

    def _write(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise self._runtime_error("Codex app-server input stream is closed.")
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise self._runtime_error("Codex app-server input stream closed unexpectedly.") from exc

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"method": method, "params": params})

    def _next_message(self, *, deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise self._runtime_error("Codex app-server timed out.")
        try:
            message = self.messages.get(timeout=min(0.5, remaining))
        except queue.Empty:
            return self._next_message(deadline=deadline)
        if isinstance(message, EOFError):
            raise self._runtime_error("Codex app-server closed before completing the request.")
        if isinstance(message, Exception):
            raise self._runtime_error("Codex app-server returned an unreadable response.")
        return message

    def _check_server_gate(self, message: dict[str, Any]) -> None:
        if message.get("id") is not None and message.get("method"):
            raise CodexChatAgentError(
                "Codex app-server requested host approval",
                gate=_approval_gate("Codex requested host approval during a read-only chat turn."),
            )

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        request_id: int | None = None,
    ) -> dict[str, Any]:
        if request_id is None:
            request_id = self.next_request_id
            self.next_request_id += 1
        self._write({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.response_timeout_sec
        while True:
            message = self._next_message(deadline=deadline)
            if message.get("id") == request_id:
                if message.get("error"):
                    raise self._runtime_error(f"Codex app-server rejected {method}.")
                result = message.get("result")
                return result if isinstance(result, dict) else {}
            self._check_server_gate(message)
            self._pending_events.append(message)

    def send(self, user_message: str) -> dict[str, Any]:
        text = " ".join(str(user_message or "").split())
        if not text:
            raise ValueError("user message is required")
        request_id = self.next_request_id
        turn_result = self._request(
            "turn/start",
            {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": _turn_prompt(text)}],
                "cwd": str(self.work_dir),
                "approvalPolicy": "never",
            },
            request_id=request_id,
        )
        self.next_request_id = request_id + 1
        turn_id = _extract_id(turn_result, "turn", "turnId")
        parts: list[str] = []
        pending = self._pending_events
        self._pending_events = []
        deadline = time.monotonic() + self.response_timeout_sec
        while True:
            message = pending.pop(0) if pending else self._next_message(deadline=deadline)
            self._check_server_gate(message)
            event_thread_id = _event_thread_id(message)
            event_turn_id = _event_turn_id(message)
            if event_thread_id and event_thread_id != self.thread_id:
                continue
            if message.get("method") == "turn/started" and event_turn_id:
                turn_id = event_turn_id
            if event_turn_id and turn_id and event_turn_id != turn_id:
                continue
            method = str(message.get("method") or "")
            params = message.get("params")
            if method == "item/agentMessage/delta" and isinstance(params, dict):
                delta = params.get("delta")
                if isinstance(delta, str):
                    parts.append(delta)
            elif method == "item/completed":
                item_text = _agent_item_text(message)
                if item_text and not parts:
                    parts.append(item_text)
            elif method == "turn/completed":
                break
            elif method == "error":
                raise self._runtime_error("Codex app-server reported a turn error.")
        return parse_agent_response("".join(parts), protected_paths=[self.work_dir])

    def close(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)

    def __enter__(self) -> "CodexChatAgentSession":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
