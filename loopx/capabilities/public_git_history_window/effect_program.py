from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from ...control_plane.effect_program import EffectRequest

PUBLIC_GIT_HISTORY_WINDOW_DECISION_SCHEMA_VERSION = (
    "public_git_history_window_decision_v0"
)
PUBLIC_GIT_HISTORY_WINDOW_RECEIPT_SCHEMA_VERSION = (
    "public_git_history_window_receipt_v0"
)


class PublicRepositoryAction(StrEnum):
    COMMIT = "commit"
    AMEND = "amend"
    REBASE = "rebase"
    CHERRY_PICK = "cherry_pick"
    REVERT = "revert"
    MERGE_COMMIT = "merge_commit"
    PUSH = "push"
    PR_MERGE = "pr_merge"
    AUTO_MERGE_ENABLE = "auto_merge_enable"
    TAG = "tag"
    RELEASE = "release"
    PR_CREATE = "pr_create"
    PR_COMMENT = "pr_comment"
    PR_REVIEW = "pr_review"
    PR_METADATA = "pr_metadata"
    REQUEST_REVIEWER = "request_reviewer"
    LABEL = "label"


PUBLIC_GIT_HISTORY_ACTIONS = frozenset(
    {
        PublicRepositoryAction.COMMIT,
        PublicRepositoryAction.AMEND,
        PublicRepositoryAction.REBASE,
        PublicRepositoryAction.CHERRY_PICK,
        PublicRepositoryAction.REVERT,
        PublicRepositoryAction.MERGE_COMMIT,
        PublicRepositoryAction.PUSH,
        PublicRepositoryAction.PR_MERGE,
        PublicRepositoryAction.AUTO_MERGE_ENABLE,
        PublicRepositoryAction.TAG,
        PublicRepositoryAction.RELEASE,
    }
)
PUBLIC_GIT_PUBLICATION_ACTIONS = frozenset(
    {
        PublicRepositoryAction.PUSH,
        PublicRepositoryAction.PR_MERGE,
        PublicRepositoryAction.TAG,
        PublicRepositoryAction.RELEASE,
    }
)


def is_public_git_history_action(action: PublicRepositoryAction | str) -> bool:
    try:
        normalized = PublicRepositoryAction(str(action))
    except ValueError:
        return False
    return normalized in PUBLIC_GIT_HISTORY_ACTIONS


def _aware_datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a UTC offset")
    return parsed


def _clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


def _window_contains(local: datetime, window: Mapping[str, Any]) -> bool:
    start = _clock(str(window["start"]))
    end = _clock(str(window["end"]))
    current = local.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _window_resume_at(local: datetime, window: Mapping[str, Any]) -> datetime:
    start = _clock(str(window["start"]))
    end = _clock(str(window["end"]))
    current = local.timetz().replace(tzinfo=None)
    resume_date: date
    if start < end:
        resume_date = local.date()
    elif current >= start:
        resume_date = local.date() + timedelta(days=1)
    else:
        resume_date = local.date()
    return datetime.combine(resume_date, end, tzinfo=local.tzinfo)


def _blocked_window(
    observed_at: datetime,
    policy: Mapping[str, Any],
) -> tuple[Mapping[str, Any], datetime] | None:
    local = observed_at.astimezone(ZoneInfo(str(policy["timezone"])))
    for window in policy.get("blocked_windows") or []:
        if isinstance(window, Mapping) and _window_contains(local, window):
            return window, _window_resume_at(local, window)
    return None


def _receipt_id(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def _policy_fingerprint(policy: Mapping[str, Any]) -> str:
    public_contract = {
        "schema_version": policy.get("schema_version"),
        "enabled": policy.get("enabled") is True,
        "timezone": policy.get("timezone"),
        "blocked_windows": policy.get("blocked_windows") or [],
        "public_repositories_only": policy.get("public_repositories_only")
        is not False,
        "collaboration_writes_allowed": policy.get(
            "collaboration_writes_allowed"
        )
        is True,
    }
    return _receipt_id(public_contract)


def build_public_git_history_effect_request(
    *,
    effect_id: str,
    goal_id: str,
    action: PublicRepositoryAction | str,
    repository_visibility: str,
    repository_identity: str,
    observed_at: datetime | str,
    outgoing_commits: Sequence[Mapping[str, Any]] = (),
    outgoing_commits_verified: bool = False,
    source: str = "agent_or_host",
) -> EffectRequest:
    effect_id = str(effect_id or "").strip()
    if not effect_id:
        raise ValueError("effect_id must be present")
    normalized_action = PublicRepositoryAction(str(action))
    visibility = str(repository_visibility or "").strip().lower()
    if visibility not in {"public", "private", "unknown"}:
        raise ValueError("repository_visibility must be public, private, or unknown")
    identity = str(repository_identity or "").strip()
    if not identity:
        raise ValueError("repository_identity must be present")
    observed = _aware_datetime(observed_at, label="observed_at")
    return EffectRequest(
        kind=f"public_repository.{normalized_action.value}",
        source=source,
        goal_id=goal_id,
        capabilities=("public_git_history_window",),
        context={
            "effect_id": effect_id,
            "action": normalized_action.value,
            "repository_visibility": visibility,
            "repository_identity": identity,
            "observed_at": observed.isoformat(),
            "outgoing_commits": [dict(item) for item in outgoing_commits],
            "outgoing_commits_verified": outgoing_commits_verified is True,
        },
    )


def _decision(
    *,
    request: EffectRequest,
    action: PublicRepositoryAction,
    disposition: str,
    reason_code: str,
    observed_at: datetime,
    policy: Mapping[str, Any],
    defer_until: datetime | None = None,
    blocked_window_id: str | None = None,
    violating_commits: Sequence[Mapping[str, Any]] = (),
    required_guards: Sequence[str] = (),
    required_action: str | None = None,
) -> dict[str, Any]:
    receipt_core: dict[str, Any] = {
        "schema_version": PUBLIC_GIT_HISTORY_WINDOW_RECEIPT_SCHEMA_VERSION,
        "effect_id": str(request.context.get("effect_id") or ""),
        "goal_id": request.goal_id,
        "action": action.value,
        "disposition": disposition,
        "reason_code": reason_code,
        "observed_at": observed_at.isoformat(),
        "repository_identity": str(
            request.context.get("repository_identity") or ""
        ),
        "policy_fingerprint": _policy_fingerprint(policy),
    }
    if defer_until is not None:
        receipt_core["defer_until"] = defer_until.isoformat()
    if blocked_window_id:
        receipt_core["blocked_window_id"] = blocked_window_id
    receipt = dict(receipt_core)
    receipt["receipt_id"] = _receipt_id(receipt_core)
    payload: dict[str, Any] = {
        "ok": disposition == "allow",
        "schema_version": PUBLIC_GIT_HISTORY_WINDOW_DECISION_SCHEMA_VERSION,
        "goal_id": request.goal_id,
        "effect_id": receipt_core["effect_id"],
        "action": action.value,
        "history_write": action in PUBLIC_GIT_HISTORY_ACTIONS,
        "collaboration_write": action not in PUBLIC_GIT_HISTORY_ACTIONS,
        "disposition": disposition,
        "reason_code": reason_code,
        "repository_visibility": request.context.get("repository_visibility"),
        "observed_at": observed_at.isoformat(),
        "policy": {
            "schema_version": policy.get("schema_version"),
            "enabled": policy.get("enabled") is True,
            "public_repositories_only": policy.get("public_repositories_only")
            is not False,
            "collaboration_writes_allowed": policy.get(
                "collaboration_writes_allowed"
            )
            is True,
            "fingerprint": receipt_core["policy_fingerprint"],
        },
        "required_guards": list(required_guards),
        "receipt": receipt,
    }
    if defer_until is not None:
        payload["defer_until"] = defer_until.isoformat()
    if blocked_window_id:
        payload["blocked_window_id"] = blocked_window_id
    if violating_commits:
        payload["violating_commits"] = [dict(item) for item in violating_commits]
    if required_action:
        payload["required_action"] = required_action
    return payload


def _violating_outgoing_commits(
    commits: object,
    *,
    policy: Mapping[str, Any],
) -> list[dict[str, str]]:
    if commits is None:
        return []
    if not isinstance(commits, Sequence) or isinstance(commits, (str, bytes)):
        raise TypeError("outgoing_commits must be a list")
    violating: list[dict[str, str]] = []
    for index, raw in enumerate(commits):
        if not isinstance(raw, Mapping):
            raise TypeError(f"outgoing_commits[{index}] must be an object")
        sha = str(raw.get("sha") or "").strip()
        if not sha:
            raise ValueError(f"outgoing_commits[{index}].sha must be present")
        for field in ("author_at", "committer_at"):
            timestamp = _aware_datetime(
                raw.get(field), label=f"outgoing_commits[{index}].{field}"
            )
            blocked = _blocked_window(timestamp, policy)
            if blocked is not None:
                window, _resume = blocked
                violating.append(
                    {
                        "sha": sha,
                        "field": field,
                        "timestamp": timestamp.isoformat(),
                        "blocked_window_id": str(window["window_id"]),
                    }
                )
    return violating


def evaluate_public_git_history_effect(
    request: EffectRequest,
    *,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    action = PublicRepositoryAction(str(request.context.get("action") or ""))
    observed_at = _aware_datetime(
        request.context.get("observed_at"), label="request observed_at"
    )

    if action not in PUBLIC_GIT_HISTORY_ACTIONS:
        guards = (
            ("head_already_remote", "no_implicit_push")
            if action is PublicRepositoryAction.PR_CREATE
            else ()
        )
        return _decision(
            request=request,
            action=action,
            disposition="allow",
            reason_code="collaboration_write_outside_capability",
            observed_at=observed_at,
            policy=policy,
            required_guards=guards,
        )
    if policy.get("enabled") is not True:
        return _decision(
            request=request,
            action=action,
            disposition="allow",
            reason_code="capability_disabled",
            observed_at=observed_at,
            policy=policy,
        )

    visibility = str(request.context.get("repository_visibility") or "unknown")
    if policy.get("public_repositories_only") is not False:
        if visibility == "private":
            return _decision(
                request=request,
                action=action,
                disposition="allow",
                reason_code="private_repository_outside_policy",
                observed_at=observed_at,
                policy=policy,
            )
        if visibility != "public":
            return _decision(
                request=request,
                action=action,
                disposition="reject",
                reason_code="repository_visibility_unknown",
                observed_at=observed_at,
                policy=policy,
                required_action="resolve repository visibility before history write",
            )

    if action is PublicRepositoryAction.AUTO_MERGE_ENABLE:
        return _decision(
            request=request,
            action=action,
            disposition="reject",
            reason_code="execution_time_not_rechecked",
            observed_at=observed_at,
            policy=policy,
            required_action=(
                "keep auto-merge disabled and evaluate pr_merge at execution time"
            ),
        )

    violations = _violating_outgoing_commits(
        request.context.get("outgoing_commits"),
        policy=policy,
    )
    if violations:
        return _decision(
            request=request,
            action=action,
            disposition="reject",
            reason_code="outgoing_commit_timestamp_in_blocked_window",
            observed_at=observed_at,
            policy=policy,
            violating_commits=violations,
            required_action="recreate the unpublished commit outside the blocked window",
        )

    blocked = _blocked_window(observed_at, policy)
    if blocked is not None:
        window, resume = blocked
        return _decision(
            request=request,
            action=action,
            disposition="defer",
            reason_code="blocked_window_active",
            observed_at=observed_at,
            policy=policy,
            defer_until=resume,
            blocked_window_id=str(window["window_id"]),
            required_action="preserve local work and retry this exact effect after defer_until",
        )

    if (
        action in PUBLIC_GIT_PUBLICATION_ACTIONS
        and request.context.get("outgoing_commits_verified") is not True
    ):
        return _decision(
            request=request,
            action=action,
            disposition="reject",
            reason_code="outgoing_commit_inventory_unverified",
            observed_at=observed_at,
            policy=policy,
            required_action=(
                "compare against the target remote ref and provide the complete "
                "newly outgoing commit inventory"
            ),
        )

    return _decision(
        request=request,
        action=action,
        disposition="allow",
        reason_code="outside_blocked_window",
        observed_at=observed_at,
        policy=policy,
    )
