"""Behavior-preserving presentation helpers for shared benchmark contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .parity import render_codex_app_parity_posthoc_check_markdown


def render_benchmark_artifact_path_filter_markdown(
    payload: dict[str, object],
) -> str:
    artifact_policy = (
        payload.get("artifact_policy")
        if isinstance(payload.get("artifact_policy"), dict)
        else {}
    )
    lines = [
        "# Benchmark Artifact Path Filter",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Adapter policy: `{artifact_policy.get('adapter_kind')}`",
        f"- Allowed to read: `{payload.get('allowed_to_read_count')}`",
        f"- Blocked: `{payload.get('blocked_count')}`",
        f"- Full paths recorded: `{payload.get('path_recorded')}`",
    ]
    allowed = payload.get("allowed_artifact_basenames")
    if isinstance(allowed, list) and allowed:
        lines.append("- Allowed basenames: " + ", ".join(f"`{item}`" for item in allowed))
    blocked = payload.get("blocked_reasons")
    if isinstance(blocked, dict) and blocked:
        reasons = ", ".join(f"`{key}`={value}" for key, value in blocked.items())
        lines.append("- Blocked reasons: " + reasons)
    return "\n".join(lines) + "\n"


def render_benchmark_candidate_source_boundary_markdown(
    payload: dict[str, object],
) -> str:
    lines = [
        "# Benchmark Candidate Source Boundary",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Clean: `{payload.get('clean')}`",
        f"- Allowed: `{payload.get('allowed_source_count')}`",
        f"- Blocked: `{payload.get('blocked_source_count')}`",
        f"- Paths recorded: `{payload.get('path_recorded')}`",
    ]
    blocked = payload.get("blocked_reasons")
    if isinstance(blocked, dict) and blocked:
        reasons = ", ".join(f"`{key}`={value}" for key, value in blocked.items())
        lines.append("- Blocked reasons: " + reasons)
    if payload.get("next_action"):
        lines.append(f"- Next action: {payload.get('next_action')}")
    return "\n".join(lines) + "\n"


def render_benchmark_parity_check_markdown(payload: dict[str, object]) -> str:
    return render_codex_app_parity_posthoc_check_markdown(
        cast(
            Mapping[str, Any],
            payload["codex_app_parity_posthoc_check"],
        )
    )
