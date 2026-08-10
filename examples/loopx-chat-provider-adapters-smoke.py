#!/usr/bin/env python3
"""Offline smoke for Claude Code and direct-key Chat adapters."""

from __future__ import annotations

import json
import stat
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from loopx.chat_providers import ClaudeCodeAdapter, DirectModelAdapter  # noqa: E402


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json
import sys

tools_at = sys.argv.index("--tools")
assert sys.argv[tools_at + 1] == "Read,Glob,Grep", sys.argv
assert "Bash" not in sys.argv and "Edit" not in sys.argv and "Write" not in sys.argv, sys.argv

envelope = '<loopx-review-json>' + json.dumps({
    "schema_version": "loopx_chat_agent_response_v0",
    "message": "已确认。请完成两项操作。\n1. 更新 MR 描述\n2. 指定 reviewer",
    "proposals": [],
    "gate": None,
}) + '</loopx-review-json>'
print(json.dumps({"type": "system", "session_id": "11111111-1111-4111-8111-111111111111"}), flush=True)
print(json.dumps({"type": "stream_event", "event": {
    "type": "content_block_delta",
    "delta": {"type": "text_delta", "text": envelope},
}}), flush=True)
print(json.dumps({"type": "result", "result": envelope}), flush=True)
'''


class FakeDirectAdapter(DirectModelAdapter):
    def _post(self, url, body, headers):  # type: ignore[no-untyped-def]
        assert self.api_key not in json.dumps(body), body
        if self.provider == "anthropic":
            assert url.endswith("/v1/messages")
            assert headers["x-api-key"] == self.api_key
            return {"content": [{"type": "text", "text": "Anthropic 管家回答。"}]}
        assert url.endswith("/v1/responses")
        assert headers["authorization"] == f"Bearer {self.api_key}"
        return {"output_text": "OpenAI 管家回答。"}


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="loopx-chat-providers-") as raw_tmp:
        root = Path(raw_tmp)
        fake = root / "claude"
        fake.write_text(FAKE_CLAUDE, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        observed: list[tuple[str, dict[str, object]]] = []
        claude = ClaudeCodeAdapter.start(claude_bin=str(fake), work_dir=root)
        assert claude.capabilities()["tool_scope"] == "read_only"
        response = claude.start_turn("告诉我下一步", lambda kind, payload: observed.append((kind, payload)))
        assert response["message"].startswith("已确认"), response
        assert any(kind == "answer.delta" for kind, _ in observed), observed
        assert not any(kind == "assistant.delta" for kind, _ in observed), observed
        assert claude.upstream_thread_id == "11111111-1111-4111-8111-111111111111"

        for provider, expected in (("anthropic", "Anthropic 管家回答。"), ("openai", "OpenAI 管家回答。")):
            adapter = FakeDirectAdapter(
                provider=provider,
                model="fixture-model",
                api_key="private-fixture-key",
                work_dir=root,
            )
            assert "private-fixture-key" not in repr(adapter)
            events: list[tuple[str, dict[str, object]]] = []
            result = adapter.start_turn("下一步是什么", lambda kind, payload: events.append((kind, payload)))
            assert result["message"] == expected, result
            assert events[-1][0] == "answer.final", events

    print("loopx-chat-provider-adapters-smoke: ok")


if __name__ == "__main__":
    main()
