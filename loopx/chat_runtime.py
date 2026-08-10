"""Runtime-neutral orchestration for durable LoopX Chat sessions."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable, Protocol

from .chat_acp import ACPStdioAdapter
from .chat_agent import CodexChatAgentError, CodexChatAgentSession, CodexChatTimeoutError
from .chat_endpoints import AgentEndpointRegistry
from .chat_store import ChatSessionStore, utc_now
from .chat_providers import ClaudeCodeAdapter, direct_model_from_environment


EventSink = Callable[[str, dict[str, Any]], None]
TERMINAL_TURN_STATES = {"completed", "interrupted", "timed_out", "failed"}


class ChatRuntimeAdapter(Protocol):
    @property
    def upstream_thread_id(self) -> str: ...

    def capabilities(self) -> dict[str, Any]: ...
    def start_turn(self, message: str, event_sink: EventSink) -> dict[str, Any]: ...
    def interrupt_turn(self, turn_id: str | None = None) -> None: ...
    def close_session(self) -> None: ...
    def healthcheck(self) -> bool: ...


@dataclass
class CodexAppServerAdapter:
    session: CodexChatAgentSession

    @property
    def upstream_thread_id(self) -> str:
        return self.session.thread_id

    @classmethod
    def start(
        cls,
        *,
        codex_bin: str,
        work_dir: Path,
        goal_id: str,
        objective: str,
        resume_thread_id: str | None = None,
        startup_timeout_sec: float = 30.0,
        idle_timeout_sec: float = 180.0,
        hard_timeout_sec: float = 900.0,
    ) -> "CodexAppServerAdapter":
        return cls(
            CodexChatAgentSession.start(
                codex_bin=codex_bin,
                work_dir=work_dir,
                goal_id=goal_id,
                objective=objective,
                response_timeout_sec=startup_timeout_sec,
                idle_timeout_sec=idle_timeout_sec,
                hard_timeout_sec=hard_timeout_sec,
                resume_thread_id=resume_thread_id,
            )
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "adapter_kind": "codex_app_server",
            "streaming": True,
            "resume": True,
            "interrupt": True,
        }

    def start_turn(self, message: str, event_sink: EventSink) -> dict[str, Any]:
        return self.session.send(message, on_event=event_sink)

    def interrupt_turn(self, turn_id: str | None = None) -> None:
        self.session.interrupt(turn_id)

    def close_session(self) -> None:
        self.session.close()

    def healthcheck(self) -> bool:
        return self.session.process.poll() is None


class ChatRuntimeController:
    def __init__(
        self,
        *,
        store: ChatSessionStore,
        codex_bin: str,
        claude_bin: str = "claude",
        startup_timeout_sec: float = 30.0,
        idle_timeout_sec: float = 180.0,
        hard_timeout_sec: float = 900.0,
        endpoint_registry: AgentEndpointRegistry | None = None,
    ) -> None:
        self.store = store
        self.codex_bin = codex_bin
        self.claude_bin = claude_bin
        self.startup_timeout_sec = startup_timeout_sec
        self.idle_timeout_sec = idle_timeout_sec
        self.hard_timeout_sec = hard_timeout_sec
        self.endpoint_registry = endpoint_registry or AgentEndpointRegistry(store.root)
        self.adapters: dict[str, ChatRuntimeAdapter] = {}
        self.cancelled_turns: set[tuple[str, str]] = set()
        self.lock = threading.RLock()
        self.session_open_locks: dict[tuple[str, str, str], threading.Lock] = {}

    def capabilities(self) -> list[dict[str, Any]]:
        builtins = [
            {
                "agent_id": "codex",
                "display_name": "Codex",
                "adapter_kind": "codex_app_server",
                "available": bool(shutil.which(self.codex_bin)),
                "streaming": True,
                "resume": True,
                "interrupt": True,
                "tool_calls": True,
                "trust_scope": "read_only",
                "source": "builtin",
            },
            {
                "agent_id": "claude-code",
                "display_name": "Claude Code",
                "adapter_kind": "claude_code_cli",
                "available": bool(shutil.which(self.claude_bin)),
                "streaming": True,
                "resume": True,
                "interrupt": True,
                "tool_calls": True,
                "trust_scope": "read_only",
                "source": "builtin",
            },
            {
                "agent_id": "anthropic-api",
                "display_name": "Claude API",
                "adapter_kind": "anthropic_messages_api",
                "available": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
                "streaming": False,
                "resume": True,
                "interrupt": False,
                "tool_calls": False,
                "trust_scope": "model_only",
                "source": "builtin",
            },
            {
                "agent_id": "openai-api",
                "display_name": "OpenAI API",
                "adapter_kind": "openai_messages_api",
                "available": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
                "streaming": False,
                "resume": True,
                "interrupt": False,
                "tool_calls": False,
                "trust_scope": "model_only",
                "source": "builtin",
            },
        ]
        return [*builtins, *(endpoint.public_summary() for endpoint in self.endpoint_registry.list())]

    def _start_adapter(
        self,
        *,
        agent_id: str,
        work_dir: Path,
        goal_id: str,
        objective: str,
        resume_thread_id: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> ChatRuntimeAdapter:
        if agent_id == "codex":
            history_context = ""
            if history:
                history_lines = [
                    f"{item.get('role', 'user')}: {str(item.get('content') or '').strip()}"
                    for item in history[-12:]
                    if str(item.get("content") or "").strip()
                ]
                if history_lines:
                    history_context = "\nPrevious visible Chat messages:\n" + "\n".join(history_lines)
            return CodexAppServerAdapter.start(
                codex_bin=self.codex_bin,
                work_dir=work_dir,
                goal_id=goal_id,
                objective=f"{objective}{history_context}",
                resume_thread_id=resume_thread_id,
                startup_timeout_sec=self.startup_timeout_sec,
                idle_timeout_sec=self.idle_timeout_sec,
                hard_timeout_sec=self.hard_timeout_sec,
            )
        if agent_id == "claude-code":
            return ClaudeCodeAdapter.start(
                claude_bin=self.claude_bin,
                work_dir=work_dir,
                resume_thread_id=resume_thread_id,
                tool_scope="read_only",
                context_summary=f"{goal_id}: {objective}".strip(),
            )
        if agent_id in {"anthropic-api", "openai-api"}:
            return direct_model_from_environment(
                provider="anthropic" if agent_id == "anthropic-api" else "openai",
                work_dir=work_dir,
                session_id=resume_thread_id,
                history=history,
            )
        endpoint = self.endpoint_registry.get(agent_id)
        if endpoint is not None:
            return ACPStdioAdapter.start(
                command=endpoint.command,
                work_dir=work_dir,
                agent_work_dir=endpoint.mapped_work_dir(work_dir),
                resume_thread_id=resume_thread_id,
                startup_timeout_sec=self.startup_timeout_sec,
                idle_timeout_sec=self.idle_timeout_sec,
                hard_timeout_sec=self.hard_timeout_sec,
            )
        raise ValueError(f"unknown Agent endpoint: {agent_id}")

    def open_session(
        self,
        *,
        goal_id: str,
        agent_id: str,
        work_dir: Path,
        objective: str,
        mode: str,
        channel_id: str | None = None,
        agent_goal_id: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        capability = next((item for item in self.capabilities() if item["agent_id"] == agent_id), None)
        if capability is None:
            raise ValueError(f"unknown Agent endpoint: {agent_id}")
        if not capability["available"]:
            raise ValueError(f"Agent endpoint is unavailable: {agent_id}")
        if mode not in {"resume_latest", "new"}:
            raise ValueError("mode must be resume_latest or new")
        selected_channel = channel_id or f"goal.{goal_id}"
        route_goal_id = "*" if selected_channel == "manager" else goal_id
        route_key = (route_goal_id, agent_id, selected_channel)
        with self.lock:
            route_lock = self.session_open_locks.setdefault(route_key, threading.Lock())
        with route_lock:
            if mode == "resume_latest":
                latest = self.store.latest_session(
                    goal_id=None if selected_channel == "manager" else goal_id,
                    agent_id=agent_id,
                    channel_id=selected_channel,
                )
                if latest is not None:
                    self._ensure_adapter(latest, work_dir=work_dir, objective=objective)
                    return latest, True
            adapter = self._start_adapter(
                agent_id=agent_id,
                work_dir=work_dir,
                goal_id=agent_goal_id or goal_id,
                objective=objective,
            )
            persisted = self.store.create_session(
                goal_id=goal_id,
                agent_id=agent_id,
                adapter_kind=str(capability["adapter_kind"]),
                upstream_thread_id=adapter.upstream_thread_id,
                upstream_mode="chat" if agent_id == "codex" else "default",
                channel_id=selected_channel,
            )
            with self.lock:
                self.adapters[persisted["session_id"]] = adapter
            return persisted, False

    def _ensure_adapter(
        self,
        session: dict[str, Any],
        *,
        work_dir: Path,
        objective: str,
    ) -> ChatRuntimeAdapter:
        session_id = str(session["session_id"])
        with self.lock:
            current = self.adapters.get(session_id)
            if current is not None and current.healthcheck():
                return current
            if current is not None:
                current.close_session()
                self.adapters.pop(session_id, None)
        self.store.update_session(session_id, status="resuming", last_error_code=None)
        active_turn_id = session.get("active_turn_id")
        if active_turn_id:
            active = self.store.load_turn(session_id, str(active_turn_id))
            if active and active.get("status") not in TERMINAL_TURN_STATES:
                self.store.update_turn(
                    session_id,
                    str(active_turn_id),
                    status="failed",
                    error_code="server_restarted",
                    error="LoopX Chat restarted before this turn completed.",
                    completed_at=utc_now(),
                )
                self.store.append_event(
                    session_id,
                    str(active_turn_id),
                    kind="turn.failed",
                    payload={"error_code": "server_restarted"},
                )
        try:
            stored_messages = self.store.messages(session_id)
            history = [
                {
                    "role": "assistant" if item.get("role") == "agent" else "user",
                    "content": str(item.get("text") or ""),
                }
                for item in stored_messages
                if item.get("role") in {"user", "agent"}
            ]
            legacy_codex_goal_thread = (
                session.get("agent_id") == "codex"
                and session.get("upstream_mode") != "chat"
            )
            retry_failed_claude_session = (
                session.get("agent_id") == "claude-code"
                and (
                    session.get("last_error_code") == "provider_unavailable"
                    or bool(stored_messages and stored_messages[-1].get("role") == "error")
                )
            )
            adapter = self._start_adapter(
                agent_id=str(session["agent_id"]),
                work_dir=work_dir,
                goal_id=(
                    "loopx-manager"
                    if session.get("channel_id") == "manager"
                    else str(session["goal_id"])
                ),
                objective=objective,
                resume_thread_id=(
                    None
                    if legacy_codex_goal_thread or retry_failed_claude_session
                    else str(session["upstream_thread_id"])
                ),
                history=(
                    history
                    if legacy_codex_goal_thread or retry_failed_claude_session
                    or session.get("agent_id") in {"anthropic-api", "openai-api"}
                    else None
                ),
            )
        except Exception as exc:
            self.store.update_session(
                session_id,
                status="resume_failed",
                active_turn_id=None,
                last_error_code="resume_failed",
            )
            gate = exc.gate if isinstance(exc, CodexChatAgentError) else None
            raise CodexChatAgentError(
                "The previous Agent conversation could not be restored.",
                error_code="resume_failed",
                gate=gate,
            ) from exc
        with self.lock:
            self.adapters[session_id] = adapter
        self.store.update_session(
            session_id,
            status="ready",
            active_turn_id=None,
            upstream_thread_id=adapter.upstream_thread_id,
            upstream_mode=(
                "chat"
                if session.get("agent_id") == "codex"
                else str(session.get("upstream_mode") or "default")
            ),
            last_activity_at=utc_now(),
            last_error_code=None,
        )
        return adapter

    def submit_turn(
        self,
        *,
        session_id: str,
        client_turn_id: str,
        message: str,
        work_dir: Path,
        objective: str,
    ) -> tuple[dict[str, Any], bool]:
        session = self.store.load_session(session_id)
        if session is None:
            raise KeyError("chat session was not found")
        adapter = self._ensure_adapter(session, work_dir=work_dir, objective=objective)
        turn, created = self.store.create_turn(
            session_id,
            client_turn_id=client_turn_id,
            message=message,
        )
        if not created:
            return turn, False
        worker = threading.Thread(
            target=self._run_turn,
            kwargs={
                "session_id": session_id,
                "turn_id": str(turn["turn_id"]),
                "message": message,
                "adapter": adapter,
            },
            daemon=True,
        )
        worker.start()
        return turn, True

    def _run_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: str,
        adapter: ChatRuntimeAdapter,
    ) -> None:
        started = utc_now()
        self.store.update_turn(session_id, turn_id, status="starting", started_at=started)

        def consume_interrupted() -> bool:
            key = (session_id, turn_id)
            with self.lock:
                if key not in self.cancelled_turns:
                    return False
                self.cancelled_turns.discard(key)
                return True

        def event_sink(kind: str, payload: dict[str, Any]) -> None:
            with self.lock:
                if (session_id, turn_id) in self.cancelled_turns:
                    return
            now = utc_now()
            changes: dict[str, Any] = {"last_activity_at": now}
            current_turn = self.store.load_turn(session_id, turn_id) or {}
            if not current_turn.get("first_event_at"):
                changes["first_event_at"] = now
            if kind in {"answer.delta", "assistant.delta"}:
                changes["delta_count"] = int(current_turn.get("delta_count") or 0) + 1
            if kind == "turn.started":
                changes.update(status="running", upstream_turn_id=payload.get("upstream_turn_id"))
            self.store.update_turn(session_id, turn_id, **changes)
            self.store.update_session(session_id, last_activity_at=now)
            self.store.append_event(session_id, turn_id, kind=kind, payload=payload)

        try:
            response = adapter.start_turn(message, event_sink)
            if consume_interrupted():
                return
            if response.get("message"):
                self.store.append_message(
                    session_id,
                    role="agent",
                    text=str(response["message"]),
                    turn_id=turn_id,
                )
            if adapter.upstream_thread_id != str((self.store.load_session(session_id) or {}).get("upstream_thread_id") or ""):
                self.store.update_session(session_id, upstream_thread_id=adapter.upstream_thread_id)
            for proposal in response.get("proposals") or []:
                self.store.append_event(session_id, turn_id, kind="proposal.ready", payload={"proposal": proposal})
            if response.get("gate"):
                self.store.append_event(session_id, turn_id, kind="gate.ready", payload={"gate": response["gate"]})
            completed = utc_now()
            self.store.update_turn(
                session_id,
                turn_id,
                status="completed",
                response=response,
                completed_at=completed,
                last_activity_at=completed,
            )
            self.store.append_event(session_id, turn_id, kind="turn.completed", payload={"response": response})
            self.store.update_session(
                session_id,
                status="ready",
                active_turn_id=None,
                last_activity_at=completed,
                last_error_code=None,
            )
        except CodexChatTimeoutError as exc:
            if consume_interrupted():
                return
            try:
                adapter.interrupt_turn()
            except Exception:
                pass
            self._fail_turn(session_id, turn_id, exc.error_code, str(exc), status="timed_out")
        except CodexChatAgentError as exc:
            if consume_interrupted():
                return
            self._fail_turn(session_id, turn_id, exc.error_code, str(exc), status="failed", gate=exc.gate)
            if not adapter.healthcheck():
                with self.lock:
                    self.adapters.pop(session_id, None)
                self.store.update_session(session_id, status="stale", last_error_code="transport_disconnected")
        except Exception as exc:  # noqa: BLE001 - preserve compact runtime failure.
            if consume_interrupted():
                return
            self._fail_turn(session_id, turn_id, "runtime_error", str(exc), status="failed")

    def _fail_turn(
        self,
        session_id: str,
        turn_id: str,
        error_code: str,
        message: str,
        *,
        status: str,
        gate: dict[str, Any] | None = None,
    ) -> None:
        completed = utc_now()
        self.store.update_turn(
            session_id,
            turn_id,
            status=status,
            error_code=error_code,
            error=message,
            completed_at=completed,
            last_activity_at=completed,
        )
        payload: dict[str, Any] = {"error_code": error_code, "message": message}
        if gate:
            payload["gate"] = gate
        self.store.append_event(session_id, turn_id, kind="turn.failed", payload=payload)
        self.store.append_message(session_id, role="error", text=message, turn_id=turn_id)
        self.store.update_session(
            session_id,
            status="ready",
            active_turn_id=None,
            last_activity_at=completed,
            last_error_code=error_code,
        )

    def interrupt_turn(self, *, session_id: str, turn_id: str) -> dict[str, Any]:
        turn = self.store.load_turn(session_id, turn_id)
        if turn is None:
            raise KeyError("chat turn was not found")
        if turn.get("status") in TERMINAL_TURN_STATES:
            return turn
        with self.lock:
            adapter = self.adapters.get(session_id)
        self.store.update_turn(session_id, turn_id, status="interrupting")
        with self.lock:
            self.cancelled_turns.add((session_id, turn_id))
        if adapter is not None:
            try:
                adapter.interrupt_turn(str(turn.get("upstream_turn_id") or "") or None)
            except Exception:
                pass
        completed = utc_now()
        updated = self.store.update_turn(
            session_id,
            turn_id,
            status="interrupted",
            completed_at=completed,
            last_activity_at=completed,
        )
        self.store.append_event(session_id, turn_id, kind="turn.interrupted", payload={})
        self.store.append_message(
            session_id,
            role="agent",
            text="已中断。你可以在当前会话继续发送消息。",
            turn_id=turn_id,
        )
        self.store.update_session(session_id, status="ready", active_turn_id=None, last_activity_at=completed)
        return updated

    def wait_for_turn(self, *, session_id: str, turn_id: str, timeout_sec: float = 920.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            turn = self.store.load_turn(session_id, turn_id)
            if turn is None:
                raise KeyError("chat turn was not found")
            if turn.get("status") in TERMINAL_TURN_STATES:
                return turn
            time.sleep(0.02)
        raise TimeoutError("chat turn wait timed out")

    def close_session(self, session_id: str) -> bool:
        session = self.store.load_session(session_id)
        if session is None:
            return False
        with self.lock:
            adapter = self.adapters.pop(session_id, None)
        if adapter is not None:
            adapter.close_session()
        self.store.update_session(session_id, status="closed", active_turn_id=None)
        return True

    def close(self) -> None:
        with self.lock:
            adapters = list(self.adapters.values())
            self.adapters.clear()
        for adapter in adapters:
            adapter.close_session()
