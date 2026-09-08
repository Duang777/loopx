from __future__ import annotations

import pytest

from loopx.control_plane.todos.completion_validation_accountability import (
    require_accountable_completion_validation,
)
from loopx.control_plane.todos.completion_validation_projection import (
    pending_completion_validation_todo,
)
from loopx.feedback import validate_public_safe_text

LANE_AGENT = "kiro-cli"
OTHER_AGENT = "codex-main-control"


def _summary(*items: dict[str, object]) -> dict[str, object]:
    return {"items": list(items)}


def _gated(
    todo_id: str,
    *,
    claimed_by: str | None,
    status: str = "open",
) -> dict[str, object]:
    return {
        "todo_id": todo_id,
        "status": status,
        "claimed_by": claimed_by,
        "completion_validation_required": True,
    }


def test_lane_fence_ignores_unclaimed_validation_todo() -> None:
    """An unclaimed gated Todo owns no lane, so it must not fence another lane.

    The fence exists to stop an agent from claiming accountable evidence while
    its own controller-validated Todo is still open. A Todo nobody claimed has
    no owning lane, so it cannot be "its own" for any agent.
    """

    summary = _summary(_gated("todo_unclaimed", claimed_by=None))

    assert (
        pending_completion_validation_todo(
            summary,
            todo_id=None,
            agent_id=LANE_AGENT,
        )
        is None
    )


def test_lane_fence_ignores_other_lane_validation_todo() -> None:
    summary = _summary(_gated("todo_other_lane", claimed_by=OTHER_AGENT))

    assert (
        pending_completion_validation_todo(
            summary,
            todo_id=None,
            agent_id=LANE_AGENT,
        )
        is None
    )


def test_lane_fence_still_blocks_own_claimed_validation_todo() -> None:
    summary = _summary(_gated("todo_own_lane", claimed_by=LANE_AGENT))

    pending = pending_completion_validation_todo(
        summary,
        todo_id=None,
        agent_id=LANE_AGENT,
    )

    assert pending is not None
    assert pending["todo_id"] == "todo_own_lane"


def test_exact_todo_fence_blocks_regardless_of_claim() -> None:
    """Naming a Todo in the settlement binds it, so an unclaimed one still fences."""

    summary = _summary(_gated("todo_named", claimed_by=None))

    pending = pending_completion_validation_todo(
        summary,
        todo_id="todo_named",
        agent_id=LANE_AGENT,
    )

    assert pending is not None
    assert pending["todo_id"] == "todo_named"


def test_exact_todo_fence_releases_when_done() -> None:
    summary = _summary(_gated("todo_named", claimed_by=LANE_AGENT, status="done"))

    assert (
        pending_completion_validation_todo(
            summary,
            todo_id="todo_named",
            agent_id=LANE_AGENT,
        )
        is None
    )


def _state_with_unclaimed_gated_todo() -> str:
    return "\n".join(
        [
            "## Agent Todo",
            "",
            "- [ ] Fix the reported control-plane defect.",
            "  <!-- loopx:todo todo_id=todo_unclaimed status=open"
            " task_class=advancement_task validation_command=pytest -->",
            "",
        ]
    )


def test_accountable_refresh_is_not_fenced_by_unclaimed_gated_todo() -> None:
    require_accountable_completion_validation(
        _state_with_unclaimed_gated_todo(),
        todo_id=None,
        agent_id=LANE_AGENT,
    )


@pytest.mark.parametrize(
    "text",
    [
        "needs owner authorization before delivery",
        "the owner-authorized pull request is open",
        "Authorization remains with the human owner",
    ],
)
def test_governance_authorization_prose_is_public_safe(text: str) -> None:
    """The plain English word must not be mistaken for a credential header."""

    validate_public_safe_text("agent_vision.replan_trigger_summary", text)


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Bear" + "er abc123",
        "authorization=Bear" + "er abc123",
    ],
)
def test_authorization_header_is_still_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="private-looking value"):
        validate_public_safe_text("agent_vision.replan_trigger_summary", text)
