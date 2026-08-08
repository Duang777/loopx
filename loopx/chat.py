from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .todos import add_goal_todo


CHAT_AGENT_RESPONSE_SCHEMA_VERSION = "loopx_chat_agent_response_v0"
CHAT_TODO_PREVIEW_SCHEMA_VERSION = "loopx_chat_todo_preview_v0"
CHAT_TODO_RECEIPT_SCHEMA_VERSION = "loopx_chat_todo_receipt_v0"
CHAT_TODO_NO_WRITE_RECEIPT_SCHEMA_VERSION = "loopx_chat_todo_no_write_receipt_v0"
CHAT_REVIEW_OPEN_TAG = "<loopx-review-json>"
CHAT_REVIEW_CLOSE_TAG = "</loopx-review-json>"
CHAT_TODO_ACTION_KIND = "loopx_chat_proposal"

_ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?<![A-Za-z0-9])(?:/(?:Users|home|private|tmp|var)/[^\s`'\"<>]+|[A-Za-z]:[\\/][^\s`'\"<>]+)"
)


class TodoReviewPreviewConflict(ValueError):
    def __init__(self, message: str, *, receipt: dict[str, Any]) -> None:
        super().__init__(message)
        self.receipt = receipt


def _stable_digest(payload: dict[str, Any], *, length: int = 24) -> str:
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:length]


def redact_local_paths(text: str, *, protected_paths: Iterable[Path | str] = ()) -> str:
    redacted = str(text or "")
    replacements: list[tuple[str, str]] = []
    for index, value in enumerate(protected_paths):
        raw = str(value).rstrip("/")
        if raw:
            replacements.append((raw, "[project]" if index == 0 else "[local-path]"))

    def replace_absolute_path(match: re.Match[str]) -> str:
        matched = match.group(0)
        candidate = matched.rstrip(".,;:!?)]}")
        suffix = matched[len(candidate) :]
        for raw, label in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
            if candidate == raw or candidate.startswith(f"{raw}/") or candidate.startswith(f"{raw}\\"):
                return f"{label}{suffix}"
        return f"[local-path]{suffix}"

    redacted = _ABSOLUTE_LOCAL_PATH.sub(replace_absolute_path, redacted)
    for raw, label in sorted(replacements, key=lambda item: len(item[0]), reverse=True):
        redacted = redacted.replace(raw, label)
    return redacted


def _compact_line(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit].strip()


def _normalize_proposals(value: Any, *, protected_paths: Iterable[Path | str]) -> list[dict[str, str]]:
    proposals: list[dict[str, str]] = []
    if not isinstance(value, list):
        return proposals
    for raw in value[:5]:
        if not isinstance(raw, dict) or raw.get("kind") != "todo":
            continue
        text = _compact_line(redact_local_paths(str(raw.get("text") or ""), protected_paths=protected_paths), limit=400)
        if not text:
            continue
        priority = str(raw.get("priority") or "P1").upper()
        if priority not in {"P0", "P1", "P2"}:
            priority = "P1"
        rationale = _compact_line(
            redact_local_paths(str(raw.get("rationale") or ""), protected_paths=protected_paths),
            limit=500,
        )
        proposals.append(
            {
                "kind": "todo",
                "text": text,
                "priority": priority,
                "rationale": rationale,
            }
        )
    return proposals


def _normalize_gate(value: Any, *, protected_paths: Iterable[Path | str]) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind = _compact_line(value.get("kind"), limit=80)
    summary = _compact_line(
        redact_local_paths(str(value.get("summary") or ""), protected_paths=protected_paths),
        limit=500,
    )
    next_action = _compact_line(
        redact_local_paths(str(value.get("next_action") or ""), protected_paths=protected_paths),
        limit=500,
    )
    if not kind and not summary:
        return None
    return {
        "kind": kind or "host_gate",
        "summary": summary,
        "next_action": next_action,
    }


def parse_agent_response(
    raw_text: str,
    *,
    protected_paths: Iterable[Path | str] = (),
) -> dict[str, Any]:
    protected = tuple(protected_paths)
    start = raw_text.rfind(CHAT_REVIEW_OPEN_TAG)
    end = raw_text.rfind(CHAT_REVIEW_CLOSE_TAG)
    if start >= 0 and end > start:
        body = raw_text[start + len(CHAT_REVIEW_OPEN_TAG) : end].strip()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            message = redact_local_paths(str(payload.get("message") or ""), protected_paths=protected).strip()
            return {
                "schema_version": CHAT_AGENT_RESPONSE_SCHEMA_VERSION,
                "message": message,
                "proposals": _normalize_proposals(payload.get("proposals"), protected_paths=protected),
                "gate": _normalize_gate(payload.get("gate"), protected_paths=protected),
            }
    return {
        "schema_version": CHAT_AGENT_RESPONSE_SCHEMA_VERSION,
        "message": redact_local_paths(raw_text, protected_paths=protected).strip(),
        "proposals": [],
        "gate": None,
    }


def _normalize_todo_text(text: str) -> str:
    normalized = _compact_line(text, limit=400)
    if not normalized:
        raise ValueError("todo text is required")
    if _ABSOLUTE_LOCAL_PATH.search(normalized):
        raise ValueError("todo text must not contain a local absolute path")
    return normalized


def _todo_revision(payload: dict[str, Any]) -> str | None:
    correctness = payload.get("local_state_write_correctness")
    if not isinstance(correctness, dict):
        return None
    intent = correctness.get("write_intent")
    if not isinstance(intent, dict):
        return None
    expected = intent.get("expected_revision")
    if not isinstance(expected, dict):
        return None
    value = expected.get("value")
    return str(value) if value else None


def _compact_todo_payload(payload: dict[str, Any], *, applied: bool) -> dict[str, Any]:
    todo = {
        "goal_id": str(payload.get("goal_id") or ""),
        "todo_id": str(payload.get("todo_id") or ""),
        "text": str(payload.get("todo") or ""),
        "status": str(payload.get("status") or "open"),
        "task_class": str(payload.get("task_class") or "advancement_task"),
        "action_kind": str(payload.get("action_kind") or CHAT_TODO_ACTION_KIND),
    }
    return {
        "ok": bool(payload.get("ok")),
        "schema_version": CHAT_TODO_PREVIEW_SCHEMA_VERSION,
        "dry_run": not applied,
        "applied": applied,
        "added": bool(payload.get("added")),
        "already_exists": bool(payload.get("already_exists")),
        "todo": todo,
    }


def _todo_preview_fingerprint(payload: dict[str, Any]) -> str:
    compact = _compact_todo_payload(payload, applied=False)
    return _stable_digest(
        {
            "schema_version": CHAT_TODO_PREVIEW_SCHEMA_VERSION,
            "todo": compact["todo"],
            "added": compact["added"],
            "already_exists": compact["already_exists"],
            "expected_revision": _todo_revision(payload),
        }
    )


def _todo_write_receipt(
    *,
    preview_id: str,
    preview_payload: dict[str, Any],
    applied_payload: dict[str, Any],
) -> dict[str, Any]:
    compact = _compact_todo_payload(applied_payload, applied=True)
    todo = compact["todo"]
    outcome = "todo_already_exists" if compact["already_exists"] else "todo_added"
    receipt = {
        "schema_version": CHAT_TODO_RECEIPT_SCHEMA_VERSION,
        "preview_id": preview_id,
        "goal_id": todo["goal_id"],
        "todo_id": todo["todo_id"],
        "status": "applied",
        "outcome": outcome,
        "already_exists": compact["already_exists"],
        "preview_revision": _todo_revision(preview_payload),
    }
    receipt["receipt_id"] = _stable_digest(receipt)
    return receipt


def _todo_no_write_receipt(
    *,
    goal_id: str,
    current_preview: dict[str, Any],
) -> dict[str, Any]:
    receipt = {
        "schema_version": CHAT_TODO_NO_WRITE_RECEIPT_SCHEMA_VERSION,
        "goal_id": goal_id,
        "status": "not_applied",
        "outcome": "preview_stale",
        "write_attempted": False,
        "current_preview_id": _todo_preview_fingerprint(current_preview),
        "state_revision": _todo_revision(current_preview),
    }
    receipt["receipt_id"] = _stable_digest(receipt)
    return receipt


def _add_review_todo(
    *,
    registry_path: Path,
    goal_id: str,
    text: str,
    dry_run: bool,
) -> dict[str, Any]:
    return add_goal_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        role="agent",
        text=_normalize_todo_text(text),
        task_class="advancement_task",
        action_kind=CHAT_TODO_ACTION_KIND,
        dry_run=dry_run,
    )


def build_todo_review_preview(
    *,
    registry_path: Path,
    goal_id: str,
    text: str,
) -> dict[str, Any]:
    payload = _add_review_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        text=text,
        dry_run=True,
    )
    compact = _compact_todo_payload(payload, applied=False)
    compact["preview_id"] = _todo_preview_fingerprint(payload)
    return compact


def apply_todo_review_preview(
    *,
    registry_path: Path,
    goal_id: str,
    text: str,
    preview_id: str,
) -> dict[str, Any]:
    current_preview = _add_review_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        text=text,
        dry_run=True,
    )
    if not preview_id or preview_id != _todo_preview_fingerprint(current_preview):
        raise TodoReviewPreviewConflict(
            "stale todo preview; preview the proposal again before applying",
            receipt=_todo_no_write_receipt(
                goal_id=goal_id,
                current_preview=current_preview,
            ),
        )
    applied = _add_review_todo(
        registry_path=registry_path,
        goal_id=goal_id,
        text=text,
        dry_run=False,
    )
    compact = _compact_todo_payload(applied, applied=True)
    compact["receipt"] = _todo_write_receipt(
        preview_id=preview_id,
        preview_payload=current_preview,
        applied_payload=applied,
    )
    return compact
