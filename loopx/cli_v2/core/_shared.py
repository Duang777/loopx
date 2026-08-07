from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping

from loopx.application import WriteContext
from loopx.cli_contract import to_json_value

from ..registrar import CommandOutcome


def success(
    *,
    operation: str,
    result: object,
    title: str,
    extra: Mapping[str, object] | None = None,
    ok: bool = True,
) -> CommandOutcome:
    payload: dict[str, object] = {
        "title": title,
        "ok": ok,
        "schema_version": "loopx_cli_v2_result_v1",
        "application_operation": operation,
        "result": to_json_value(result),
    }
    if extra:
        payload.update(extra)
    return CommandOutcome(payload, exit_code=0 if ok else 1)


def pending_migration(*, command: str, reason: str) -> CommandOutcome:
    return CommandOutcome(
        {
            "title": "LoopX CLI v2",
            "ok": False,
            "schema_version": "loopx_cli_v2_result_v1",
            "error": {
                "code": "cli_v2_pending_migration",
                "message": reason,
                "details": {"command": command},
                "retryable": False,
            },
        },
        exit_code=2,
    )


def require_text(args: argparse.Namespace, name: str, option: str) -> str:
    value = str(getattr(args, name, None) or "").strip()
    if not value:
        raise ValueError(f"{option} is required")
    return value


def write_context(
    *,
    actor: str,
    operation: str,
    expected_revision: str | None,
    material: object,
) -> WriteContext:
    digest = hashlib.sha256(
        json.dumps(
            to_json_value(material),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return WriteContext(
        actor=actor,
        idempotency_key=f"cli-v2:{operation}:{digest}",
        expected_revision=expected_revision,
    )
