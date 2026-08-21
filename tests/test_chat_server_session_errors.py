from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from loopx.chat_agent import CodexChatAgentError
from loopx.chat_server import ChatRequestHandler


class _SessionStore:
    def load_session(self, session_id: str) -> dict[str, Any]:
        assert session_id == "session-resume-failed"
        return {
            "goal_id": "goal-alpha",
            "status": "resume_failed",
            "channel_id": "goal.goal-alpha",
        }


class _FailingRuntimeController:
    def submit_turn(self, **_kwargs: Any) -> None:
        raise CodexChatAgentError(
            "The previous Agent conversation could not be restored.",
            error_code="resume_failed",
            gate={
                "kind": "host_tool_gate",
                "summary": "Agent Session restore was rejected.",
                "next_action": "Choose a Session recovery action.",
            },
        )


def test_session_turn_preserves_resume_failure_contract() -> None:
    responses: list[dict[str, Any]] = []

    class Handler(ChatRequestHandler):
        def _read_json(self) -> dict[str, Any]:
            return {
                "message": "continue",
                "client_turn_id": "turn-resume-failed",
            }

        def _registry_and_goal(self, goal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
            assert goal_id == "goal-alpha"
            return {}, {"id": goal_id}

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
            responses.append(
                {
                    "message": message,
                    "status": status,
                    "gate": gate,
                    "error_code": error_code,
                    "session_invalidated": session_invalidated,
                    "turn_replay_safe": turn_replay_safe,
                    "todo_receipt": todo_receipt,
                }
            )

    handler = object.__new__(Handler)
    handler.server = SimpleNamespace(
        chat_store=_SessionStore(),
        runtime_controller=_FailingRuntimeController(),
    )

    handler._session_turn("session-resume-failed")

    assert responses == [
        {
            "message": "The previous Agent conversation could not be restored.",
            "status": 424,
            "gate": {
                "kind": "host_tool_gate",
                "summary": "Agent Session restore was rejected.",
                "next_action": "Choose a Session recovery action.",
            },
            "error_code": "resume_failed",
            "session_invalidated": True,
            "turn_replay_safe": True,
            "todo_receipt": None,
        }
    ]
