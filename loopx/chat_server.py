from __future__ import annotations

import json
import mimetypes
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .chat import (
    TodoReviewPreviewConflict,
    apply_todo_review_preview,
    build_todo_review_preview,
    redact_local_paths,
)
from .chat_agent import CodexChatAgentError
from .chat_runtime import ChatRuntimeController, TERMINAL_TURN_STATES
from .chat_store import ChatSessionStore
from .history import load_registry
from .paths import resolve_runtime_root
from .registry import registry_goals, resolve_state_file
from .state_projection import build_active_state_structured_projection
from .status_server import is_loopback_host, is_loopback_origin


DEFAULT_CHAT_HOST = "127.0.0.1"
DEFAULT_CHAT_PORT = 8767
DEFAULT_CHAT_PATH = "/chat/"
DEFAULT_CHAT_STATUS_PATH = "/status.json"
CHAT_CAPABILITIES_PATH = "/api/chat/capabilities"
CHAT_SESSIONS_PATH = "/api/chat/sessions"
CHAT_TODO_DRY_RUN_PATH = "/api/chat/todo/dry-run"
CHAT_TODO_APPLY_PATH = "/api/chat/todo/apply"


def default_chat_assets_dir() -> Path:
    return Path(__file__).resolve().parent / "web" / "chat"


def _compact_text(value: Any, *, limit: int = 600) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


def _active_state_section(state_text: str, heading: str) -> str:
    marker = f"## {heading}"
    start = state_text.find(marker)
    if start < 0:
        return ""
    content_start = start + len(marker)
    end = state_text.find("\n## ", content_start)
    section = state_text[content_start : end if end >= 0 else None]
    lines = [
        line.strip().removeprefix("- ").strip()
        for line in section.splitlines()
        if line.strip() and not line.lstrip().startswith("<!--")
    ]
    return _compact_text(" ".join(lines))


def _goal_public_context(registry: dict[str, Any], goal: dict[str, Any]) -> dict[str, Any]:
    goal_id = str(goal.get("id") or "")
    project = Path(str(goal.get("repo") or ".")).expanduser().resolve()
    objective = ""
    title = goal_id
    state_path = resolve_state_file(project, goal.get("state_file"))
    if state_path is not None and state_path.exists():
        try:
            state_text = state_path.read_text(encoding="utf-8")
            objective = _active_state_section(state_text, "Objective")
            title_line = next(
                (line[2:].strip() for line in state_text.splitlines() if line.startswith("# ")),
                "",
            )
            projected_title = _compact_text(title_line, limit=160)
            if projected_title.casefold() in {"active goal state", "active state"}:
                projected_title = goal_id
            title = projected_title or title
        except OSError:
            pass
    return {
        "goal_id": goal_id,
        "title": title,
        "objective": objective or _compact_text(goal.get("domain"), limit=200),
        "project": project,
        "runtime_root": resolve_runtime_root(registry),
    }


def _compact_todo(item: dict[str, Any], *, protected_paths: list[Path]) -> dict[str, Any]:
    return {
        "todo_id": _compact_text(item.get("todo_id"), limit=100) or None,
        "role": _compact_text(item.get("role"), limit=40) or None,
        "status": _compact_text(item.get("status"), limit=40) or ("done" if item.get("done") else "open"),
        "priority": _compact_text(item.get("priority"), limit=60) or None,
        "text": _compact_text(
            redact_local_paths(str(item.get("text") or item.get("title") or ""), protected_paths=protected_paths)
        ),
        "action_kind": _compact_text(item.get("action_kind"), limit=100) or None,
        "task_class": _compact_text(item.get("task_class"), limit=100) or None,
        "claimed_by": _compact_text(item.get("claimed_by"), limit=100) or None,
        "evidence": _compact_text(
            redact_local_paths(str(item.get("evidence") or item.get("note") or ""), protected_paths=protected_paths)
        )
        or None,
    }


def _goal_todos(queue_item: dict[str, Any], *, protected_paths: list[Path]) -> list[dict[str, Any]]:
    project_asset = queue_item.get("project_asset")
    asset = project_asset if isinstance(project_asset, dict) else {}
    todos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for role in ("user", "agent"):
        group = queue_item.get(f"{role}_todos")
        if not isinstance(group, dict):
            group = asset.get(f"{role}_todos")
        items = group.get("items") if isinstance(group, dict) else []
        for raw in items if isinstance(items, list) else []:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item.setdefault("role", role)
            compact = _compact_todo(item, protected_paths=protected_paths)
            key = str(compact.get("todo_id") or compact.get("text") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            todos.append(compact)
    return todos[:40]


def build_chat_status_projection(
    *,
    registry: dict[str, Any],
    status_payload: dict[str, Any],
    selected_goal_id: str | None,
) -> dict[str, Any]:
    queue = status_payload.get("attention_queue")
    queue_items = queue.get("items") if isinstance(queue, dict) else []
    queue_by_goal = {
        str(item.get("goal_id") or ""): item
        for item in queue_items if isinstance(queue_items, list) and isinstance(item, dict)
    }
    goals: list[dict[str, Any]] = []
    for raw_goal in registry_goals(registry):
        goal_id = str(raw_goal.get("id") or "")
        context = _goal_public_context(registry, raw_goal)
        protected_paths = [context["project"], context["runtime_root"]]
        item = queue_by_goal.get(goal_id, {})
        asset_raw = item.get("project_asset") if isinstance(item, dict) else {}
        asset = asset_raw if isinstance(asset_raw, dict) else {}
        todos = _goal_todos(item, protected_paths=protected_paths) if isinstance(item, dict) else []
        open_todos = [todo for todo in todos if todo.get("status") not in {"done", "completed", "closed"}]
        top_todo = next((todo for todo in open_todos if todo.get("role") == "agent"), None)
        if top_todo is None and open_todos:
            top_todo = open_todos[0]
        waiting_on = _compact_text(item.get("waiting_on"), limit=80) if isinstance(item, dict) else ""
        raw_gate = asset.get("gate") or item.get("status") if isinstance(item, dict) else ""
        raw_next_action = asset.get("next_action") or item.get("recommended_action") if isinstance(item, dict) else ""
        evidence = [
            str(todo.get("evidence"))
            for todo in todos
            if todo.get("evidence")
        ][:4]
        latest_validation = asset.get("latest_validation")
        if isinstance(latest_validation, dict) and latest_validation.get("summary"):
            evidence.insert(0, _compact_text(latest_validation.get("summary")))
        quota = item.get("quota") if isinstance(item, dict) and isinstance(item.get("quota"), dict) else {}
        goals.append(
            {
                "goal_id": goal_id,
                "title": context["title"],
                "objective": redact_local_paths(context["objective"], protected_paths=protected_paths),
                "status": _compact_text(item.get("status"), limit=100)
                if isinstance(item, dict)
                else _compact_text(raw_goal.get("status"), limit=100),
                "waiting_on": waiting_on or None,
                "severity": _compact_text(item.get("severity"), limit=60)
                if isinstance(item, dict)
                else None,
                "gate": _compact_text(
                    redact_local_paths(str(raw_gate or "clear"), protected_paths=protected_paths),
                    limit=240,
                ),
                "next_action": _compact_text(
                    redact_local_paths(
                        str(raw_next_action or "Review the next bounded proposal."),
                        protected_paths=protected_paths,
                    )
                ),
                "top_todo": top_todo,
                "todos": todos,
                "evidence": [
                    _compact_text(redact_local_paths(value, protected_paths=protected_paths))
                    for value in evidence
                    if value
                ],
                "quota": {
                    "state": _compact_text(quota.get("state"), limit=80) or None,
                    "spent_slots": quota.get("spent_slots"),
                    "allowed_slots": quota.get("allowed_slots"),
                    "reason": _compact_text(quota.get("reason"), limit=240) or None,
                },
            }
        )
    effective_selected = selected_goal_id or (goals[0]["goal_id"] if len(goals) == 1 else None)
    return {
        "ok": bool(status_payload.get("ok", True)),
        "schema_version": "loopx_chat_status_v0",
        "selected_goal_id": effective_selected,
        "goal_count": len(goals),
        "goals": goals,
    }


def build_bounded_chat_status_projection(
    *,
    registry: dict[str, Any],
    selected_goal_id: str | None,
) -> dict[str, Any]:
    """Build Chat's first-screen projection from bounded local state only."""

    items: list[dict[str, Any]] = []
    for raw_goal in registry_goals(registry):
        goal_id = str(raw_goal.get("id") or "")
        project = Path(str(raw_goal.get("repo") or ".")).expanduser().resolve()
        state_path = resolve_state_file(project, raw_goal.get("state_file"))
        state_text = ""
        if state_path is not None and state_path.is_file():
            try:
                state_text = state_path.read_text(encoding="utf-8")
            except OSError:
                state_text = ""
        structured = build_active_state_structured_projection(
            state_text,
            goal_id=goal_id,
        )
        frontmatter = structured.get("frontmatter")
        frontmatter = frontmatter if isinstance(frontmatter, dict) else {}
        todos = structured.get("todos")
        todos = todos if isinstance(todos, dict) else {}
        user_todos = todos.get("user")
        user_todos = user_todos if isinstance(user_todos, dict) else {"items": [], "open_count": 0}
        agent_todos = todos.get("agent")
        agent_todos = agent_todos if isinstance(agent_todos, dict) else {"items": [], "open_count": 0}
        user_open = int(user_todos.get("open_count") or 0)
        agent_open = int(agent_todos.get("open_count") or 0)
        next_action = structured.get("next_action")
        next_action = next_action if isinstance(next_action, dict) else {}
        next_action_text = _compact_text(next_action.get("first"))
        waiting_on = _compact_text(frontmatter.get("waiting_on"), limit=80)
        if not waiting_on:
            if user_open:
                waiting_on = "user_or_controller"
            elif agent_open:
                waiting_on = "codex"
        gate = _compact_text(frontmatter.get("gate"), limit=120)
        if not gate:
            gate = "user_review_required" if user_open else "clear"
        items.append(
            {
                "goal_id": goal_id,
                "status": _compact_text(frontmatter.get("status"), limit=100)
                or _compact_text(raw_goal.get("status"), limit=100),
                "waiting_on": waiting_on or None,
                "severity": "action" if user_open or agent_open else "info",
                "recommended_action": next_action_text or "Review the next bounded proposal.",
                "user_todos": user_todos,
                "agent_todos": agent_todos,
                "project_asset": {
                    "gate": gate,
                    "next_action": next_action_text or "Review the next bounded proposal.",
                    "user_todos": user_todos,
                    "agent_todos": agent_todos,
                },
            }
        )
    return build_chat_status_projection(
        registry=registry,
        status_payload={"ok": True, "attention_queue": {"items": items}},
        selected_goal_id=selected_goal_id,
    )


class ChatHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    registry_path: Path
    runtime_root_override: str | None
    scan_roots: list[Path]
    limit: int
    selected_goal_id: str | None
    codex_bin: str
    assets_dir: Path
    verbose: bool
    chat_store: ChatSessionStore
    runtime_controller: ChatRuntimeController

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def server_close(self) -> None:
        if hasattr(self, "runtime_controller"):
            self.runtime_controller.close()
        super().server_close()


class ChatRequestHandler(BaseHTTPRequestHandler):
    server: ChatHTTPServer

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(
        self,
        message: str,
        *,
        status: int = 400,
        gate: dict[str, str] | None = None,
        error_code: str | None = None,
        session_invalidated: bool = False,
        turn_replay_safe: bool = False,
        todo_receipt: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"ok": False, "error": _compact_text(message)}
        if error_code:
            payload["error_code"] = _compact_text(error_code, limit=80)
        if gate:
            payload["gate"] = gate
        if session_invalidated:
            payload["session_invalidated"] = True
        if turn_replay_safe:
            payload["turn_replay_safe"] = True
        if todo_receipt:
            payload["todo_receipt"] = todo_receipt
        self._send_json(payload, status=status)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            raise ValueError("request body is empty")
        if length > 64_000:
            raise ValueError("request body is too large")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _require_loopback_origin(self) -> bool:
        if is_loopback_origin(self.headers.get("Origin")):
            return True
        self._send_error("LoopX Chat only accepts loopback browser origins.", status=403)
        return False

    def _registry_and_goal(self, goal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        registry = load_registry(self.server.registry_path)
        goal = next((item for item in registry_goals(registry) if str(item.get("id") or "") == goal_id), None)
        if goal is None:
            raise ValueError("goal_id was not found in the active LoopX registry")
        return registry, goal

    def _serve_asset(self, path: str) -> None:
        relative = "index.html" if path in {"/chat", "/chat/"} else path.removeprefix("/chat/")
        root = self.server.assets_dir.resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            self._send_error("unknown asset", status=404)
            return
        if not target.is_file():
            self._send_error("unknown asset", status=404)
            return
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header(
            "Content-Type",
            f"{content_type}; charset=utf-8"
            if content_type.startswith("text/")
            else content_type,
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _status(self) -> None:
        try:
            registry = load_registry(self.server.registry_path)
            projection = build_bounded_chat_status_projection(
                registry=registry,
                selected_goal_id=self.server.selected_goal_id,
            )
        except Exception:
            self._send_error("LoopX status could not be projected for Chat.", status=500)
            return
        self._send_json(projection)

    def _create_session(self) -> None:
        try:
            body = self._read_json()
            unknown = set(body) - {"goal_id", "agent_id", "mode"}
            if unknown:
                raise ValueError("unknown session field")
            goal_id = _compact_text(body.get("goal_id"), limit=160) or self.server.selected_goal_id or ""
            if not goal_id:
                raise ValueError("goal_id is required when multiple Goals are available")
            agent_id = _compact_text(body.get("agent_id"), limit=80) or "codex"
            mode = _compact_text(body.get("mode"), limit=40) or "resume_latest"
            registry, goal = self._registry_and_goal(goal_id)
            context = _goal_public_context(registry, goal)
            project = context["project"]
            if not project.is_dir():
                raise CodexChatAgentError(
                    "The Goal project root is unavailable.",
                    gate={
                        "kind": "host_tool_gate",
                        "summary": "The Goal project root is unavailable on this host.",
                        "next_action": "Reconnect the Goal from its project root, then retry.",
                    },
                )
            session, resumed = self.server.runtime_controller.open_session(
                goal_id=goal_id,
                agent_id=agent_id,
                work_dir=project,
                objective=str(context["objective"] or context["title"]),
                mode=mode,
            )
        except CodexChatAgentError as exc:
            self._send_error(str(exc), status=424, gate=exc.gate, error_code=exc.error_code)
            return
        except Exception as exc:  # noqa: BLE001 - compact local validation error.
            self._send_error(str(exc))
            return
        public = self.server.chat_store.public_session(session)
        self._send_json(
            {
                "ok": True,
                "schema_version": "loopx_chat_session_v1",
                "session_id": public["session_id"],
                "goal_id": goal_id,
                "agent_id": agent_id,
                "resumed": resumed,
                "session": public,
            },
            status=200 if resumed else 201,
        )

    def _session_turn(self, session_id: str) -> None:
        session = self.server.chat_store.load_session(session_id)
        if session is None or session.get("status") == "closed":
            self._send_error(
                "chat session was not found",
                status=404,
                session_invalidated=True,
                turn_replay_safe=True,
            )
            return
        try:
            body = self._read_json()
            if set(body) - {"message", "client_turn_id"}:
                raise ValueError("unknown turn field")
            message = str(body.get("message") or "").strip()
            if not message:
                raise ValueError("message is required")
            client_turn_id = _compact_text(body.get("client_turn_id"), limit=160) or uuid.uuid4().hex
            registry, goal = self._registry_and_goal(str(session["goal_id"]))
            context = _goal_public_context(registry, goal)
            turn, created = self.server.runtime_controller.submit_turn(
                session_id=session_id,
                client_turn_id=client_turn_id,
                message=message,
                work_dir=context["project"],
                objective=str(context["objective"] or context["title"]),
            )
            if body.get("client_turn_id"):
                turn_id = str(turn["turn_id"])
                self._send_json(
                    {
                        "ok": True,
                        "schema_version": "loopx_chat_turn_accepted_v1",
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "created": created,
                        "status": turn["status"],
                        "events_url": f"{CHAT_SESSIONS_PATH}/{session_id}/turns/{turn_id}/events",
                    },
                    status=202,
                )
                return
            completed = self.server.runtime_controller.wait_for_turn(
                session_id=session_id,
                turn_id=str(turn["turn_id"]),
            )
            if completed.get("status") != "completed":
                self._send_error(
                    str(completed.get("error") or "Agent turn failed."),
                    status=424,
                    gate=(
                        completed.get("gate")
                        if isinstance(completed.get("gate"), dict)
                        else None
                    ),
                )
                return
            response = completed.get("response")
        except CodexChatAgentError as exc:
            self._send_error(
                str(exc),
                status=424,
                gate=exc.gate,
            )
            return
        except RuntimeError as exc:
            self._send_json(
                {
                    "ok": False,
                    "error": "another turn is already running for this session",
                    "active_turn_id": str(exc),
                },
                status=409,
            )
            return
        except KeyError:
            self._send_error("chat session was not found", status=404, session_invalidated=True)
            return
        except Exception as exc:  # noqa: BLE001 - compact local validation error.
            self._send_error(str(exc))
            return
        self._send_json(
            {
                "ok": True,
                "schema_version": "loopx_chat_turn_v0",
                "session_id": session_id,
                "goal_id": session["goal_id"],
                "response": response,
            }
        )

    def _session_snapshot(self, session_id: str) -> None:
        try:
            self._send_json(self.server.chat_store.session_snapshot(session_id))
        except KeyError:
            self._send_error("chat session was not found", status=404)

    def _list_sessions(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        goal_id = _compact_text((query.get("goal_id") or [""])[0], limit=160) or None
        agent_id = _compact_text((query.get("agent_id") or [""])[0], limit=80) or None
        self._send_json(
            {
                "ok": True,
                "schema_version": "loopx_chat_session_list_v1",
                "sessions": self.server.chat_store.list_sessions(goal_id=goal_id, agent_id=agent_id),
            }
        )

    def _turn_events(self, session_id: str, turn_id: str) -> None:
        if self.server.chat_store.load_turn(session_id, turn_id) is None:
            self._send_error("chat turn was not found", status=404)
            return
        last_event_id = self.headers.get("Last-Event-ID")
        query = parse_qs(urlparse(self.path).query)
        if not last_event_id:
            last_event_id = (query.get("after") or [None])[0]
        if str(last_event_id or "0") != "0":
            turn = self.server.chat_store.load_turn(session_id, turn_id) or {}
            self.server.chat_store.update_turn(
                session_id,
                turn_id,
                sse_reconnect_count=int(turn.get("sse_reconnect_count") or 0) + 1,
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        cursor = str(last_event_id or "0")
        heartbeat_at = time.monotonic()
        try:
            while True:
                events = self.server.chat_store.events_after(session_id, turn_id, cursor)
                for event in events:
                    cursor = str(event["event_id"])
                    data = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(
                        f"id: {cursor}\nevent: {event['kind']}\ndata: {data}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()
                turn = self.server.chat_store.load_turn(session_id, turn_id)
                if turn is None or (turn.get("status") in TERMINAL_TURN_STATES and not events):
                    self.close_connection = True
                    break
                if time.monotonic() - heartbeat_at >= 15.0:
                    heartbeat = json.dumps({"kind": "heartbeat", "created_at": time.time()})
                    self.wfile.write(f"event: heartbeat\ndata: {heartbeat}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    heartbeat_at = time.monotonic()
                time.sleep(0.05)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _interrupt_turn(self, session_id: str, turn_id: str) -> None:
        try:
            turn = self.server.runtime_controller.interrupt_turn(session_id=session_id, turn_id=turn_id)
        except KeyError:
            self._send_error("chat turn was not found", status=404)
            return
        except CodexChatAgentError as exc:
            self._send_error(str(exc), status=424, gate=exc.gate)
            return
        self._send_json(
            {
                "ok": True,
                "schema_version": "loopx_chat_turn_interrupt_v1",
                "session_id": session_id,
                "turn_id": turn_id,
                "status": turn["status"],
            }
        )

    def _todo(self, *, apply: bool) -> None:
        try:
            body = self._read_json()
            allowed = {"goal_id", "text", "preview_id"} if apply else {"goal_id", "text"}
            if set(body) - allowed:
                raise ValueError("unknown Todo review field")
            goal_id = _compact_text(body.get("goal_id"), limit=160)
            text = str(body.get("text") or "")
            if not goal_id:
                raise ValueError("goal_id is required")
            self._registry_and_goal(goal_id)
            if apply:
                payload = apply_todo_review_preview(
                    registry_path=self.server.registry_path,
                    goal_id=goal_id,
                    text=text,
                    preview_id=str(body.get("preview_id") or ""),
                )
            else:
                payload = build_todo_review_preview(
                    registry_path=self.server.registry_path,
                    goal_id=goal_id,
                    text=text,
                )
        except TodoReviewPreviewConflict as exc:
            self._send_error(str(exc), status=409, todo_receipt=exc.receipt)
            return
        except ValueError as exc:
            self._send_error(str(exc), status=400)
            return
        except Exception:
            self._send_error("Todo review could not be completed.", status=400)
            return
        self._send_json(payload)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json({"ok": True})
            return
        if path == CHAT_CAPABILITIES_PATH:
            self._send_json(
                {
                    "ok": True,
                    "schema_version": "loopx_chat_capabilities_v1",
                    "agent_backend": "codex_app_server",
                    "sandbox": "read-only",
                    "approval_policy": "never",
                    "todo_write": "preview_locked",
                    "goal_id": self.server.selected_goal_id,
                    "streaming": True,
                    "resume": True,
                    "interrupt": True,
                    "adapters": self.server.runtime_controller.capabilities(),
                }
            )
            return
        if path == CHAT_SESSIONS_PATH:
            self._list_sessions()
            return
        session_parts = path.strip("/").split("/")
        if len(session_parts) == 4 and session_parts[:3] == ["api", "chat", "sessions"]:
            self._session_snapshot(session_parts[3])
            return
        if (
            len(session_parts) == 7
            and session_parts[:3] == ["api", "chat", "sessions"]
            and session_parts[4] == "turns"
            and session_parts[6] == "events"
        ):
            self._turn_events(session_parts[3], session_parts[5])
            return
        if path == DEFAULT_CHAT_STATUS_PATH:
            self._status()
            return
        if path == "/":
            self.send_response(302)
            self.send_header("Location", DEFAULT_CHAT_PATH)
            self.end_headers()
            return
        if path == "/chat" or path.startswith("/chat/"):
            self._serve_asset(path)
            return
        self._send_error("unknown path", status=404)

    def do_POST(self) -> None:
        if not self._require_loopback_origin():
            return
        path = urlparse(self.path).path
        if path == CHAT_SESSIONS_PATH:
            self._create_session()
            return
        prefix = f"{CHAT_SESSIONS_PATH}/"
        if path.startswith(prefix) and path.endswith("/turns"):
            session_id = path[len(prefix) : -len("/turns")].strip("/")
            self._session_turn(session_id)
            return
        parts = path.strip("/").split("/")
        if (
            len(parts) == 7
            and parts[:3] == ["api", "chat", "sessions"]
            and parts[4] == "turns"
            and parts[6] == "interrupt"
        ):
            self._interrupt_turn(parts[3], parts[5])
            return
        if path == CHAT_TODO_DRY_RUN_PATH:
            self._todo(apply=False)
            return
        if path == CHAT_TODO_APPLY_PATH:
            self._todo(apply=True)
            return
        self._send_error("unknown path", status=404)

    def do_DELETE(self) -> None:
        if not self._require_loopback_origin():
            return
        path = urlparse(self.path).path
        prefix = f"{CHAT_SESSIONS_PATH}/"
        if not path.startswith(prefix):
            self._send_error("unknown path", status=404)
            return
        session_id = path[len(prefix) :].strip("/")
        if not self.server.runtime_controller.close_session(session_id):
            self._send_error("chat session was not found", status=404)
            return
        self._send_json({"ok": True, "session_id": session_id, "closed": True})

    def log_message(self, format: str, *args: object) -> None:
        if self.server.verbose:
            super().log_message(format, *args)


def serve_chat(
    *,
    registry_path: Path,
    runtime_root_override: str | None,
    scan_roots: list[Path],
    limit: int,
    host: str,
    port: int,
    goal_id: str | None,
    codex_bin: str,
    startup_timeout_sec: float,
    idle_timeout_sec: float,
    hard_timeout_sec: float,
    assets_dir: Path | None,
    open_browser: bool,
    verbose: bool,
) -> None:
    if not is_loopback_host(host):
        raise ValueError("loopx chat requires a loopback --host such as 127.0.0.1")
    resolved_assets = (assets_dir or default_chat_assets_dir()).expanduser().resolve()
    if not (resolved_assets / "index.html").is_file():
        raise FileNotFoundError("LoopX Chat web assets are unavailable; reinstall LoopX or rebuild the chat bundle")
    server = ChatHTTPServer((host, port), ChatRequestHandler)
    server.registry_path = registry_path
    server.runtime_root_override = runtime_root_override
    server.scan_roots = scan_roots
    server.limit = limit
    server.selected_goal_id = goal_id
    server.codex_bin = codex_bin
    server.assets_dir = resolved_assets
    server.verbose = verbose
    registry = load_registry(registry_path)
    runtime_root = resolve_runtime_root(
        registry,
        runtime_root_override,
        registry_path=registry_path,
    )
    server.chat_store = ChatSessionStore(runtime_root)
    server.runtime_controller = ChatRuntimeController(
        store=server.chat_store,
        codex_bin=codex_bin,
        startup_timeout_sec=startup_timeout_sec,
        idle_timeout_sec=idle_timeout_sec,
        hard_timeout_sec=hard_timeout_sec,
    )
    url = f"http://{host}:{port}{DEFAULT_CHAT_PATH}"
    print(f"Serving LoopX Chat at {url}", flush=True)
    print("Agent boundary: Codex app-server, read-only sandbox, approval policy never", flush=True)
    print("Todo writes: preview-locked on loopback", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping LoopX Chat", flush=True)
    finally:
        server.server_close()
