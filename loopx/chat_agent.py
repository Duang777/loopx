from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .chat import (
    CHAT_AGENT_RESPONSE_SCHEMA_VERSION,
    CHAT_REVIEW_CLOSE_TAG,
    CHAT_REVIEW_OPEN_TAG,
    parse_agent_response,
)


class CodexChatAgentError(RuntimeError):
    def __init__(self, message: str, *, gate: dict[str, str], error_code: str = "host_gate") -> None:
        super().__init__(message)
        self.gate = gate
        self.error_code = error_code


class CodexChatTimeoutError(CodexChatAgentError):
    pass


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
        "First write the concise operator-facing answer as normal text. "
        "Finish with exactly one machine-readable envelope using these tags and shape. "
        "Do not put any visible answer after the closing tag:\n"
        f"{CHAT_REVIEW_OPEN_TAG}{json.dumps(envelope, ensure_ascii=False)}{CHAT_REVIEW_CLOSE_TAG}\n\n"
        f"Operator user message:\n{user_message.strip()}"
    )


class _VisibleResponseFilter:
    """Keep the final review envelope out of operator-visible deltas."""

    def __init__(self) -> None:
        self.pending = ""
        self.hidden = False

    def feed(self, chunk: str) -> str:
        if self.hidden:
            return ""
        self.pending += chunk
        marker_at = self.pending.find(CHAT_REVIEW_OPEN_TAG)
        if marker_at >= 0:
            visible = self.pending[:marker_at]
            self.pending = ""
            self.hidden = True
            return visible
        suffix_length = 0
        limit = min(len(self.pending), len(CHAT_REVIEW_OPEN_TAG) - 1)
        for length in range(1, limit + 1):
            if self.pending.endswith(CHAT_REVIEW_OPEN_TAG[:length]):
                suffix_length = length
        if suffix_length:
            visible = self.pending[:-suffix_length]
            self.pending = self.pending[-suffix_length:]
            return visible
        visible = self.pending
        self.pending = ""
        return visible

    def finish(self) -> str:
        if self.hidden:
            return ""
        visible = self.pending
        self.pending = ""
        return visible


@dataclass
class CodexChatAgentSession:
    process: subprocess.Popen[str]
    messages: "queue.Queue[dict[str, Any] | Exception]"
    thread_id: str
    work_dir: Path
    response_timeout_sec: float = 30.0
    idle_timeout_sec: float = 180.0
    hard_timeout_sec: float = 900.0
    next_request_id: int = 5
    current_turn_id: str = ""
    _pending_events: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _write_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _request_id_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def start(
        cls,
        *,
        codex_bin: str,
        work_dir: Path,
        goal_id: str,
        objective: str,
        response_timeout_sec: float = 30.0,
        idle_timeout_sec: float = 180.0,
        hard_timeout_sec: float = 900.0,
        resume_thread_id: str | None = None,
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
            idle_timeout_sec=idle_timeout_sec,
            hard_timeout_sec=hard_timeout_sec,
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
                "thread/resume" if resume_thread_id else "thread/start",
                {
                    **({"threadId": resume_thread_id, "excludeTurns": True} if resume_thread_id else {}),
                    "cwd": str(root),
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                },
                request_id=2,
            )
            session.thread_id = _extract_id(thread_result, "thread", "threadId")
            if not session.thread_id:
                raise session._runtime_error("Codex app-server did not return a thread id.")
            if resume_thread_id and session.thread_id != resume_thread_id:
                raise session._runtime_error("Codex app-server resumed an unexpected thread.")
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
            session.next_request_id = 5
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
            with self._write_lock:
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

    def interrupt(self, turn_id: str | None = None) -> None:
        selected_turn_id = str(turn_id or self.current_turn_id or "")
        if not selected_turn_id:
            return
        with self._request_id_lock:
            request_id = self.next_request_id
            self.next_request_id += 1
        self._write(
            {
                "id": request_id,
                "method": "turn/interrupt",
                "params": {"threadId": self.thread_id, "turnId": selected_turn_id},
            }
        )

    def send(
        self,
        user_message: str,
        *,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        text = " ".join(str(user_message or "").split())
        if not text:
            raise ValueError("user message is required")
        with self._request_id_lock:
            request_id = self.next_request_id
            self.next_request_id += 1
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
        turn_id = _extract_id(turn_result, "turn", "turnId")
        self.current_turn_id = turn_id
        if on_event:
            on_event("turn.started", {"upstream_turn_id": turn_id})
        parts: list[str] = []
        display_filter = _VisibleResponseFilter()
        pending = self._pending_events
        self._pending_events = []
        started_at = time.monotonic()
        last_activity_at = started_at
        while True:
            now = time.monotonic()
            if now - started_at >= self.hard_timeout_sec:
                raise self._timeout_error("hard_timeout", "Codex Chat turn reached its hard time limit.")
            if now - last_activity_at >= self.idle_timeout_sec:
                raise self._timeout_error("idle_timeout", "Codex Chat turn stopped producing activity.")
            deadline = min(started_at + self.hard_timeout_sec, last_activity_at + self.idle_timeout_sec)
            try:
                message = pending.pop(0) if pending else self._next_message(deadline=deadline)
            except CodexChatAgentError:
                now = time.monotonic()
                if now - started_at >= self.hard_timeout_sec:
                    raise self._timeout_error(
                        "hard_timeout",
                        "Codex Chat turn reached its hard time limit.",
                    )
                if now - last_activity_at >= self.idle_timeout_sec:
                    raise self._timeout_error(
                        "idle_timeout",
                        "Codex Chat turn stopped producing activity.",
                    )
                raise
            last_activity_at = time.monotonic()
            self._check_server_gate(message)
            event_thread_id = _event_thread_id(message)
            event_turn_id = _event_turn_id(message)
            if event_thread_id and event_thread_id != self.thread_id:
                continue
            if message.get("method") == "turn/started" and event_turn_id:
                turn_id = event_turn_id
                self.current_turn_id = turn_id
            if event_turn_id and turn_id and event_turn_id != turn_id:
                continue
            method = str(message.get("method") or "")
            params = message.get("params")
            if on_event:
                on_event("turn.activity", {"method": method})
            if method == "item/agentMessage/delta" and isinstance(params, dict):
                delta = params.get("delta")
                if isinstance(delta, str):
                    parts.append(delta)
                    visible = display_filter.feed(delta)
                    if visible and on_event:
                        on_event("assistant.delta", {"text": visible})
            elif method == "item/completed":
                item_text = _agent_item_text(message)
                if item_text and not parts:
                    parts.append(item_text)
            elif method == "turn/completed":
                break
            elif method == "error":
                raise self._runtime_error("Codex app-server reported a turn error.")
        trailing = display_filter.finish()
        if trailing and on_event:
            on_event("assistant.delta", {"text": trailing})
        raw_response = "".join(parts)
        response = parse_agent_response(raw_response, protected_paths=[self.work_dir])
        if on_event:
            if CHAT_REVIEW_OPEN_TAG not in raw_response or CHAT_REVIEW_CLOSE_TAG not in raw_response:
                on_event("protocol.warning", {"error_code": "missing_review_envelope"})
            on_event("assistant.final", {"response": response})
        self.current_turn_id = ""
        return response

    def _timeout_error(self, error_code: str, summary: str) -> CodexChatTimeoutError:
        return CodexChatTimeoutError(
            summary,
            error_code=error_code,
            gate=_host_tool_gate(summary, "Interrupt the turn or retry in the same session."),
        )

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
