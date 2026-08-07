from __future__ import annotations

from collections.abc import Collection


def _collection_size(value: object) -> int:
    if isinstance(value, Collection) and not isinstance(value, (str, bytes)):
        return len(value)
    return 0


def render_material_lifecycle_markdown(payload: dict[str, object]) -> str:
    if payload.get("skill_id") == "loopx-material":
        lines = [
            "# LoopX Material Project Skill",
            "",
            f"- status: `{payload.get('status')}`",
            f"- mode: `{payload.get('mode') or 'inspect'}`",
            f"- project_connected: `{payload.get('project_connected')}`",
            f"- managed: `{payload.get('managed')}`",
            f"- changed: `{payload.get('changed')}`",
        ]
        surface_items = payload.get("surfaces")
        for item in surface_items if isinstance(surface_items, list) else []:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('surface')}: `{item.get('status')}` at "
                    f"`{item.get('target')}`"
                )
        if payload.get("error"):
            lines.append(f"- error: `{payload.get('error')}`")
        return "\n".join([*lines, ""])
    capability = payload.get("capability")
    capability_id = (
        capability.get("capability_id")
        if isinstance(capability, dict)
        else "material_lifecycle"
    )
    return "\n".join(
        [
            "# Material Lifecycle",
            "",
            f"- status: `{payload.get('status')}`",
            f"- capability_id: `{capability_id}`",
            f"- contract_schemas: `{_collection_size(payload.get('contract_schemas'))}`",
            "",
        ]
    )
