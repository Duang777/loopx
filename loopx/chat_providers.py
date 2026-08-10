"""Private runtime adapters for Claude Code and direct model providers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any, Callable
from urllib import request
import uuid

from .chat import VisibleResponseStreamFilter, parse_agent_response
from .chat_agent import CodexChatAgentError, _host_tool_gate, _turn_prompt


EventSink = Callable[[str, dict[str, Any]], None]


def _provider_error(label: str, next_action: str) -> CodexChatAgentError:
    return CodexChatAgentError(
        f"{label} is unavailable for LoopX Chat.",
        error_code="provider_unavailable",
        gate=_host_tool_gate(f"{label} is unavailable for LoopX Chat.", next_action),
    )


@dataclass
class ClaudeCodeAdapter:
    claude_bin: str
    work_dir: Path
    session_id: str
    tool_scope: str = "read_only"
    resumed: bool = False
    current_process: subprocess.Popen[str] | None = field(default=None, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @property
    def upstream_thread_id(self) -> str:
        return self.session_id

    @classmethod
    def start(
        cls,
        *,
        claude_bin: str,
        work_dir: Path,
        resume_thread_id: str | None = None,
        tool_scope: str = "read_only",
    ) -> "ClaudeCodeAdapter":
        resolved = shutil.which(claude_bin)
        if not resolved:
            raise _provider_error(
                "Claude Code",
                "Install Claude Code or select another healthy Agent endpoint.",
            )
        if tool_scope not in {"read_only", "disabled"}:
            raise ValueError("Claude Code tool_scope must be read_only or disabled")
        return cls(
            claude_bin=resolved,
            work_dir=work_dir.resolve(),
            session_id=resume_thread_id or str(uuid.uuid4()),
            tool_scope=tool_scope,
            resumed=bool(resume_thread_id),
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "adapter_kind": "claude_code_cli",
            "streaming": True,
            "resume": True,
            "interrupt": True,
            "tool_calls": self.tool_scope != "disabled",
            "tool_scope": self.tool_scope,
        }

    def start_turn(self, message: str, event_sink: EventSink) -> dict[str, Any]:
        command = [
            self.claude_bin,
            "--print",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--permission-mode",
            "plan",
            "--tools",
            "Read,Glob,Grep" if self.tool_scope == "read_only" else "",
            "--disable-slash-commands",
        ]
        if self.resumed:
            command.extend(["--resume", self.session_id])
        else:
            command.extend(["--session-id", self.session_id])
        command.append(_turn_prompt(message))
        event_sink("turn.started", {"upstream_turn_id": self.session_id})
        event_sink("agent.phase", {"label": "正在连接 Claude Code"})
        try:
            process = subprocess.Popen(
                command,
                cwd=str(self.work_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise _provider_error("Claude Code", "Check the local Claude Code installation.") from exc
        with self.lock:
            self.current_process = process
        parts: list[str] = []
        result_text = ""
        display_filter = VisibleResponseStreamFilter(protected_paths=[self.work_dir])
        visible_delta_count = 0
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                session_id = payload.get("session_id")
                if isinstance(session_id, str) and session_id:
                    self.session_id = session_id
                if payload.get("type") == "stream_event":
                    event = payload.get("event")
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == "content_block_start":
                        block = event.get("content_block")
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            event_sink("agent.phase", {"label": "Claude Code 正在检查上下文"})
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta")
                        if isinstance(delta, dict) and delta.get("type") == "text_delta":
                            chunk = str(delta.get("text") or "")
                            parts.append(chunk)
                            visible = display_filter.feed(chunk)
                            if visible:
                                visible_delta_count += 1
                                event_sink("answer.delta", {"text": visible})
                elif payload.get("type") == "result":
                    result_text = str(payload.get("result") or "")
            return_code = process.wait()
            if return_code != 0:
                raise _provider_error("Claude Code", "Sign in to Claude Code and retry this session.")
        finally:
            with self.lock:
                self.current_process = None
        raw_response = "".join(parts) or result_text
        if not parts and result_text:
            visible = display_filter.feed(result_text)
            if visible:
                visible_delta_count += 1
                event_sink("answer.delta", {"text": visible})
        visible_tail = display_filter.finish()
        if visible_tail:
            visible_delta_count += 1
            event_sink("answer.delta", {"text": visible_tail})
        response = parse_agent_response(raw_response, protected_paths=[self.work_dir])
        self.resumed = True
        event_sink("agent.phase", {"label": "正在整理回答"})
        if visible_delta_count == 0:
            event_sink("answer.delta", {"text": str(response.get("message") or "")})
        event_sink("answer.final", {"response": response})
        return response

    def interrupt_turn(self, turn_id: str | None = None) -> None:
        del turn_id
        with self.lock:
            process = self.current_process
        if process is not None and process.poll() is None:
            process.terminate()

    def close_session(self) -> None:
        self.interrupt_turn()

    def healthcheck(self) -> bool:
        return bool(shutil.which(self.claude_bin))


@dataclass
class DirectModelAdapter:
    provider: str
    model: str
    api_key: str = field(repr=False)
    work_dir: Path
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    history: list[dict[str, str]] = field(default_factory=list)
    timeout_sec: float = 180.0

    @property
    def upstream_thread_id(self) -> str:
        return self.session_id

    def capabilities(self) -> dict[str, Any]:
        return {
            "adapter_kind": f"{self.provider}_messages_api",
            "streaming": False,
            "resume": True,
            "interrupt": False,
        }

    def _post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        encoded = json.dumps(body).encode("utf-8")
        req = request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_sec) as response:  # noqa: S310 - fixed provider URL.
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise _provider_error(
                self.provider.title(),
                "Check the local credential reference, network, and selected model.",
            ) from exc
        if not isinstance(payload, dict):
            raise _provider_error(self.provider.title(), "Select another healthy Agent endpoint.")
        return payload

    def start_turn(self, message: str, event_sink: EventSink) -> dict[str, Any]:
        event_sink("turn.started", {"upstream_turn_id": self.session_id})
        event_sink("agent.phase", {"label": f"正在连接 {self.provider.title()}"})
        prompt = _turn_prompt(message)
        if self.provider == "anthropic":
            messages = [*self.history, {"role": "user", "content": prompt}]
            payload = self._post(
                "https://api.anthropic.com/v1/messages",
                {"model": self.model, "max_tokens": 2048, "messages": messages},
                {
                    "content-type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            content = payload.get("content")
            raw_response = "".join(
                str(block.get("text") or "")
                for block in content if isinstance(block, dict) and block.get("type") == "text"
            ) if isinstance(content, list) else ""
        elif self.provider == "openai":
            messages = [*self.history, {"role": "user", "content": prompt}]
            payload = self._post(
                "https://api.openai.com/v1/responses",
                {"model": self.model, "input": messages},
                {"content-type": "application/json", "authorization": f"Bearer {self.api_key}"},
            )
            raw_response = str(payload.get("output_text") or "")
            if not raw_response and isinstance(payload.get("output"), list):
                raw_response = "".join(
                    str(part.get("text") or "")
                    for item in payload["output"] if isinstance(item, dict)
                    for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
                )
        else:
            raise ValueError(f"unsupported direct model provider: {self.provider}")
        response = parse_agent_response(raw_response, protected_paths=[self.work_dir])
        self.history.extend([
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": raw_response},
        ])
        event_sink("agent.phase", {"label": "正在整理回答"})
        event_sink("answer.delta", {"text": str(response.get("message") or "")})
        event_sink("answer.final", {"response": response})
        return response

    def interrupt_turn(self, turn_id: str | None = None) -> None:
        del turn_id

    def close_session(self) -> None:
        return None

    def healthcheck(self) -> bool:
        return bool(self.api_key)


def direct_model_from_environment(
    *,
    provider: str,
    work_dir: Path,
    session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> DirectModelAdapter:
    if provider == "anthropic":
        key_name = "ANTHROPIC_API_KEY"
        model = os.environ.get("LOOPX_ANTHROPIC_MODEL", "claude-sonnet-4-5")
    elif provider == "openai":
        key_name = "OPENAI_API_KEY"
        model = os.environ.get("LOOPX_OPENAI_MODEL", "gpt-5")
    else:
        raise ValueError(f"unsupported direct model provider: {provider}")
    api_key = os.environ.get(key_name, "").strip()
    if not api_key:
        raise _provider_error(provider.title(), f"Set {key_name} in the LoopX Chat process environment.")
    return DirectModelAdapter(
        provider=provider,
        model=model,
        api_key=api_key,
        work_dir=work_dir.resolve(),
        session_id=session_id or uuid.uuid4().hex,
        history=list(history or []),
    )
