from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loopx.chat_server import (
    CHAT_GOAL_CONTEXTS_PATH,
    CHAT_LARK_APPS_PATH,
    CHAT_LARK_CHATS_PATH,
    CHAT_LARK_CONNECTIONS_PATH,
    build_goal_repository_contexts,
)


def test_lark_management_uses_dedicated_local_api_routes() -> None:
    assert CHAT_GOAL_CONTEXTS_PATH == "/api/chat/goals/contexts"
    assert CHAT_LARK_APPS_PATH == "/api/chat/lark/apps"
    assert CHAT_LARK_CHATS_PATH == "/api/chat/lark/chats"
    assert CHAT_LARK_CONNECTIONS_PATH == "/api/chat/lark/connections"


def test_goal_repository_context_is_credential_free_and_path_free(tmp_path: Path) -> None:
    project = tmp_path / "private" / "loopx"
    project.mkdir(parents=True)
    calls: list[list[str]] = []

    def git_runner(args: list[str]) -> dict[str, Any]:
        calls.append(args)
        if args[-3:] == ["config", "--get", "remote.origin.url"]:
            return {"returncode": 0, "stdout": "git@github.com:loopx-ai/loopx.git\n"}
        if args[-2:] == ["branch", "--show-current"]:
            return {"returncode": 0, "stdout": "codex/lark-goal-topic-binding\n"}
        return {"returncode": 1, "stdout": ""}

    rows = build_goal_repository_contexts(
        registry={"goals": [{"id": "goal-alpha", "repo": str(project)}]},
        git_runner=git_runner,
    )

    assert rows == [
        {
            "goal_id": "goal-alpha",
            "repository": {
                "branch": "codex/lark-goal-topic-binding",
                "identity": "git:github.com/loopx-ai/loopx",
                "label": "loopx-ai/loopx",
                "read_only": True,
            },
        }
    ]
    encoded = json.dumps(rows)
    assert str(tmp_path) not in encoded
    assert "git@" not in encoded
    assert calls
