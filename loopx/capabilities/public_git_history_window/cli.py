from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ...registry import read_json, registry_goals
from .effect_program import (
    PublicRepositoryAction,
    build_public_git_history_effect_request,
    evaluate_public_git_history_effect,
)
from .policy import (
    load_public_git_history_window_config,
    public_git_history_window_goal_policy,
)

PrintPayload = Callable[
    [dict[str, object], str, Callable[[dict[str, object]], str]],
    None,
]
FormatSelector = Callable[..., str]
AddFormat = Callable[[argparse.ArgumentParser], None]


def register_public_git_history_window_commands(
    subparsers: argparse._SubParsersAction,
    add_subcommand_format: AddFormat,
) -> None:
    parser = subparsers.add_parser(
        "public-git-history-window",
        help="Evaluate goal-scoped time windows before public Git history writes.",
    )
    commands = parser.add_subparsers(
        dest="public_git_history_window_command",
        required=True,
    )
    evaluate = commands.add_parser(
        "evaluate",
        help="Return an allow, defer, or reject receipt for one repository effect.",
    )
    add_subcommand_format(evaluate)
    evaluate.add_argument("--goal-id", required=True)
    evaluate.add_argument("--effect-id", required=True)
    evaluate.add_argument(
        "--action",
        choices=[action.value for action in PublicRepositoryAction],
        required=True,
    )
    evaluate.add_argument(
        "--repository-visibility",
        choices=["public", "private", "unknown"],
        default="unknown",
    )
    evaluate.add_argument("--repository-identity", required=True)
    evaluate.add_argument(
        "--observed-at",
        help="Offset-aware ISO timestamp. Defaults to the host's current local time.",
    )
    evaluate.add_argument(
        "--outgoing-commits-json",
        type=Path,
        help=(
            "JSON list of newly outgoing commits with sha, author_at, and "
            "committer_at. Required for push, PR merge, tag, and release; use an "
            "empty list only after comparing the target remote ref."
        ),
    )


def _goal(registry_path: Path, goal_id: str) -> dict[str, Any]:
    payload = read_json(registry_path)
    goal = next(
        (item for item in registry_goals(payload) if str(item.get("id")) == goal_id),
        None,
    )
    if goal is None:
        raise ValueError(f"goal id not found in registry: {goal_id}")
    return goal


def _outgoing_commits(path: Path | None) -> list[Mapping[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("outgoing commits JSON is unavailable") from exc
    if not isinstance(payload, list) or not all(
        isinstance(item, Mapping) for item in payload
    ):
        raise ValueError("outgoing commits JSON must be a list of objects")
    return payload


def render_public_git_history_window_markdown(
    payload: dict[str, object],
) -> str:
    lines = [
        "# Public Git History Window",
        "",
        f"- ok: `{str(payload.get('ok')).lower()}`",
        f"- goal_id: `{payload.get('goal_id')}`",
        f"- action: `{payload.get('action')}`",
        f"- disposition: `{payload.get('disposition') or payload.get('status')}`",
        f"- reason_code: `{payload.get('reason_code')}`",
    ]
    if payload.get("defer_until"):
        lines.append(f"- defer_until: `{payload.get('defer_until')}`")
    if payload.get("required_action"):
        lines.append(f"- required_action: {payload.get('required_action')}")
    receipt = payload.get("receipt")
    if isinstance(receipt, Mapping):
        lines.append(f"- receipt_id: `{receipt.get('receipt_id')}`")
    if payload.get("error"):
        lines.append(f"- error: {payload.get('error')}")
    return "\n".join(lines).rstrip() + "\n"


def handle_public_git_history_window_command(
    args: argparse.Namespace,
    *,
    registry_path: Path,
    output_format: FormatSelector,
    print_payload: PrintPayload,
) -> int | None:
    if args.command != "public-git-history-window":
        return None
    try:
        if args.public_git_history_window_command != "evaluate":
            raise ValueError("public-git-history-window requires evaluate")
        goal = _goal(registry_path, str(args.goal_id))
        goal_policy = public_git_history_window_goal_policy(goal)
        if not goal_policy["enabled"]:
            policy = {
                "schema_version": goal_policy["schema_version"],
                "enabled": False,
                "public_repositories_only": True,
                "collaboration_writes_allowed": True,
                "blocked_windows": [],
            }
        else:
            config_path = str(goal_policy.get("config_path") or "")
            if not config_path:
                raise ValueError(
                    "enabled public Git history window has no config pointer"
                )
            policy = load_public_git_history_window_config(
                project=Path(str(goal.get("repo") or "")),
                config_path=config_path,
            )
        request = build_public_git_history_effect_request(
            effect_id=str(args.effect_id),
            goal_id=str(args.goal_id),
            action=str(args.action),
            repository_visibility=str(args.repository_visibility),
            repository_identity=str(args.repository_identity),
            observed_at=(
                str(args.observed_at)
                if args.observed_at
                else datetime.now().astimezone().isoformat()
            ),
            outgoing_commits=_outgoing_commits(args.outgoing_commits_json),
            outgoing_commits_verified=args.outgoing_commits_json is not None,
        )
        payload = evaluate_public_git_history_effect(request, policy=policy)
    except (OSError, TypeError, ValueError) as exc:
        payload = {
            "ok": False,
            "schema_version": "public_git_history_window_error_v0",
            "goal_id": str(args.goal_id),
            "status": "error",
            "error": str(exc),
        }
    print_payload(
        payload,
        output_format(args),
        render_public_git_history_window_markdown,
    )
    if payload.get("disposition") == "allow":
        return 0
    return 3 if payload.get("disposition") in {"defer", "reject"} else 1
