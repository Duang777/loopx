"""Current canonical waits constrain historical supervision, not vice versa."""
from copy import deepcopy

from loopx.control_plane.handoff.delivery_contract import handoff_delivery_contract
from loopx.control_plane.testing.quota_fixtures import quota_status_payload, quota_todo_item, quota_todo_summary
from loopx.control_plane.work_items.delivery_history import project_delivery_response
from loopx.control_plane.work_items.work_lane_context import build_work_lane_context_contract
from loopx.quota import build_quota_should_run, quota_with_handoff_outcome_floor
from loopx.status import project_post_handoff_history


PROFILE = {"outcome_floor": {"outcome_markers": ["outcome"], "surface_only_hints": ["surface"]}}


def blocked_run():
    return {"agent_id": "agent-a", "todo_id": "todo_delivery", "delivery_outcome": "outcome_gap",
        "delivery_batch_scale": "implementation", "progress_observation": {
            "schema_version": "typed_progress_observation_v0", "result_class": "blocked",
            "work_item_id": "todo_delivery", "blocker_id": "blocker_dependency", "evidence_ids": ["evidence_dependency"]}}


def waiting_todo():
    return quota_todo_item(todo_id="todo_delivery", title="Wait for the dependency", status="deferred",
        claimed_by="agent-a", resume_when="todo_done:todo_dependency", resume_ready=False,
        resume_condition={"schema_version": "todo_resume_condition_v0", "resume_when": "todo_done:todo_dependency",
                          "satisfied": False, "kind": "todo_done", "target_status": "open",
                          "target_task_class": "advancement_task", "target_archive_state": "active"})


def dependency_todo():
    return quota_todo_item(todo_id="todo_dependency", title="Complete prerequisite", claimed_by="agent-b")


def test_status_compaction_preserves_binding_and_all_consumers_defer_to_current_wait():
    readiness = project_post_handoff_history([blocked_run()] * 3, PROFILE)
    summary = quota_todo_summary([waiting_todo(), dependency_todo()], claim_scope_agent_id="agent-a")
    asset = {"execution_profile": PROFILE, "agent_todos": summary}
    item = {"handoff_readiness": readiness, "agent_todos": summary, "project_asset": asset}
    assert project_delivery_response(readiness["post_handoff_latest_run"], summary)["reason"] == "canonical_todo_wait"
    quota = {"state": "eligible", "reason": "fixture"}
    assert quota_with_handoff_outcome_floor(quota, waiting_on="codex", project_asset=asset,
        handoff_readiness=readiness) == quota
    assert handoff_delivery_contract(item) is None
    for state in ("paused", "operator_gate", "blocked_health", "throttled", "waiting"):
        hard = {"state": state, "reason": "existing gate"}
        assert quota_with_handoff_outcome_floor(hard, waiting_on="codex", project_asset=asset,
            handoff_readiness=readiness) == hard
    small = {**item, "handoff_readiness": {**readiness, "post_handoff_small_scale_streak": 3}}
    assert handoff_delivery_contract(small)["mode"] == "expand_after_repeated_small_delivery"
    extra = quota_todo_item(todo_id="todo_alternative", title="Implement independent work", claimed_by="agent-a")
    with_work = quota_todo_summary([waiting_todo(), dependency_todo(), extra], claim_scope_agent_id="agent-a")
    lane = build_work_lane_context_contract(item, agent_todo_summary=with_work)
    assert lane["must_attempt_work"] is True
    assert lane["obligation"] == "advance_one_bounded_segment"
    assert "outcome_followthrough" not in lane


def test_surface_supervision_remains_and_invalid_wait_does_not_clear_floor():
    summary = quota_todo_summary([waiting_todo()], claim_scope_agent_id="agent-a")
    asset = {"execution_profile": PROFILE, "agent_todos": summary}
    for run in ({"delivery_outcome": "surface_only"}, {"delivery_outcome": "outcome_gap"}):
        readiness = project_post_handoff_history([run] * 3, PROFILE)
        assert quota_with_handoff_outcome_floor({"state": "eligible"}, waiting_on="codex",
            project_asset=asset, handoff_readiness=readiness)["state"] == "focus_wait"
        assert handoff_delivery_contract({"handoff_readiness": readiness, "project_asset": asset}) is not None


def test_unknown_refreshes_do_not_close_canonical_work_or_mutate_sources():
    rows = [quota_todo_item(todo_id="todo_active", title="Implement remaining work", claimed_by="agent-a")]
    payload = quota_status_payload(goal_id="delivery-response", status="ready", agent_todo_items=rows,
        claim_scope_agent_id="agent-a", recommended_action="Advance remaining work", latest_runs=[],
        coordination={"registered_agents": ["agent-a"]})
    before = deepcopy(payload)
    baseline = build_quota_should_run(payload, goal_id="delivery-response", agent_id="agent-a")
    payload["run_history"]["goals"][0]["latest_runs"] = [
        {"agent_id": "agent-a", "classification": "state_refreshed"} for _ in range(50)]
    actual = build_quota_should_run(payload, goal_id="delivery-response", agent_id="agent-a")
    assert actual["work_lane_contract"]["must_attempt_work"] is True
    assert actual["work_lane_contract"] == baseline["work_lane_contract"]
    assert payload["attention_queue"] == before["attention_queue"]
