"""Markdown presentation for public-safe Decision Context status packets."""

from __future__ import annotations

from collections.abc import Collection


def _collection_size(value: object) -> int:
    if isinstance(value, Collection) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0


def render_decision_context_markdown(payload: dict[str, object]) -> str:
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "decision_context"
    )
    return "\n".join(
        [
            "# Decision Context",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- packet_schemas: `{_collection_size(payload.get('packet_schemas'))}`",
            f"- source_schemas: `{_collection_size(payload.get('source_schemas'))}`",
            f"- source_count: `{payload.get('source_count', 0)}`",
            "",
        ]
    )
