import assert from "node:assert/strict";
import test from "node:test";
import { projectDeliveryResponse } from "../../loopx/control_plane/work_items/delivery_history.ts";
import { evaluateTodoResumeConditions, TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION } from "../../loopx/control_plane/todos/resume_condition.ts";
import type { JsonObject } from "../../loopx/control_plane/effect_program.ts";

const run = { delivery_outcome: "outcome_gap", delivery_batch_scale: "implementation",
  delivery_turn_kind: "", todo_id: "todo_delivery", replan_obligation_id: "",
  outcome_followthrough_required: true,
  progress_observation: { schema_version: "typed_progress_observation_v0", result_class: "blocked",
    work_item_id: "todo_delivery", blocker_id: "blocker_dependency", evidence_ids: ["evidence_dependency"] } };
const waiting = { todo_id: "todo_delivery", role: "agent", status: "deferred",
  task_class: "advancement_task", claimed_by: "agent-a", resume_when: "todo_done:todo_dependency",
  resume_ready: false, resume_condition: { schema_version: "todo_resume_condition_v0",
    resume_when: "todo_done:todo_dependency", satisfied: false, kind: "todo_done",
    target_status: "open", target_task_class: "advancement_task", target_archive_state: "active" } };
const input = { run, todo: waiting, run_agent_id: "agent-a", agent_id: "agent-a" };

test("wait proof consumes the real resume evaluator for all four condition kinds", () => {
  const dependency = { todo_id: "todo_dependency", role: "agent", status: "open", task_class: "advancement_task" };
  for (const [resume, source, capabilities, valid] of [
    ["todo_done:todo_dependency", [dependency], [], true],
    ["todo_done:todo_dependency", [], [], false],
    ["monitor_changed:todo_dependency", [{ ...dependency, task_class: "continuous_monitor", material_change_generation: 0 }], [], true],
    ["monitor_changed:todo_dependency", [], [], false],
    ["capacity_available:network", [], [], true],
    ["capacity_available:network", [], null, false],
    ["pr_merged:example/project#1", [], [], true],
    ["pr_merged:#1", [], [], false],
  ] as const) {
    const todo = { ...waiting, resume_when: resume, resume_monitor_generation: 0 };
    const evaluated = evaluateTodoResumeConditions({ schema_version: TODO_RESUME_EVALUATION_REQUEST_SCHEMA_VERSION,
      items: [todo], source_items: source, rollout_events: [], available_capabilities: capabilities });
    const condition = (evaluated.conditions as JsonObject[])[0].condition;
    assert.equal(projectDeliveryResponse({ ...input, todo: { ...todo, resume_condition: condition } }).outcome_floor_applicable,
      !valid, resume + JSON.stringify(source));
  }
});

test("a bound blocked observation delegates a current legal wait to canonical planning", () => {
  const before = structuredClone(input);
  const result = projectDeliveryResponse(input);
  assert.equal(result.outcome_floor_applicable, false);
  assert.equal(result.outcome_followthrough, null);
  assert.equal(result.reason, "canonical_todo_wait");
  assert.deepEqual(input, before);
});

test("history alone, missing source, invalid wait, and other actors cannot exempt the floor", () => {
  for (const patch of [
    { todo: null }, { agent_id: "agent-b" }, { run_agent_id: "agent-b" },
    { todo: { ...waiting, todo_id: "todo_other" } },
    { todo: { ...waiting, claimed_by: "agent-b" } },
    { todo: { ...waiting, excluded_agents: ["agent-a"] } },
    { todo: { ...waiting, status: "done" } },
    { todo: { ...waiting, resume_ready: true } },
    { todo: { ...waiting, resume_condition: null } },
    { todo: { ...waiting, resume_when: "todo_done:todo_delivery", resume_condition: {
      ...waiting.resume_condition, resume_when: "todo_done:todo_delivery", target_todo_id: "todo_delivery" } } },
    { todo: { ...waiting, resume_condition: { ...waiting.resume_condition, target_status: null } } },
    { todo: { ...waiting, resume_condition: { ...waiting.resume_condition, target_task_class: "continuous_monitor" } } },
    { todo: { ...waiting, resume_condition: { ...waiting.resume_condition, invalid_state: "target_missing" } } },
    { todo: { ...waiting, resume_condition: { ...waiting.resume_condition, satisfied: true } } },
    { run: { ...run, progress_observation: null, delivery_turn_kind: "blocker_writeback" } },
    { run: { ...run, replan_obligation_id: "replan_other" } },
    { run: { ...run, progress_observation: { ...run.progress_observation, evidence_ids: [] } } },
  ]) assert.equal(projectDeliveryResponse({ ...input, ...patch }).outcome_floor_applicable, true, JSON.stringify(patch));
});

test("surface-only supervision and unknown remain distinct from durable work state", () => {
  const surface = projectDeliveryResponse({ ...input, run: { ...run, delivery_outcome: "surface_only" } });
  assert.equal(surface.outcome_floor_applicable, true);
  assert.ok(surface.outcome_followthrough);
  const unknown = projectDeliveryResponse({ ...input, run: { ...run, delivery_outcome: "unknown",
    outcome_followthrough_required: false, progress_observation: null } });
  assert.equal(unknown.outcome_floor_applicable, true);
  assert.equal(unknown.outcome_followthrough, null);
  assert.equal("resolved_todo_id" in unknown, false);
});
