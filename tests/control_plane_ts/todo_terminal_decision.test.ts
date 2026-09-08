import assert from "node:assert/strict";
import test from "node:test";

import {
  COORDINATION_TODO_TERMINAL_DECISION_REQUEST_SCHEMA,
  evaluateCoordinationTodoTerminalDecision,
} from "../../loopx/control_plane/coordination/todo_terminal_decision.ts";

function request(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: COORDINATION_TODO_TERMINAL_DECISION_REQUEST_SCHEMA,
    command: "complete",
    handoff_mode: "legacy",
    registered_agents: ["agent-a", "agent-b"],
    lifecycle_grants: [],
    todo: {
      todo_id: "todo_target",
      status: "open",
      role: "agent",
      task_class: "advancement_task",
      claimed_by: "agent-a",
      excluded_agents: [],
      bound_agent: null,
      blocks_agent: null,
      decision_scope: null,
      required_decision_scopes: [],
      unblocks_todo_id: null,
    },
    decision_target: null,
    lease: null,
    actor_agent_id: "agent-a",
    authority_action: "complete",
    authority_reason: null,
    decision_outcome: null,
    lease_idempotency_key: null,
    lease_expected_version: null,
    allow_user_gate_auto_acquire: false,
    ...overrides,
  };
}

test("terminal decision owns complete and supersede authority", () => {
  for (const command of ["complete", "supersede"]) {
    const decided = evaluateCoordinationTodoTerminalDecision(request({
      command,
      authority_action: command,
    }));
    assert.equal(decided.outcome, "apply");
    assert.equal(decided.code, "terminal_transition");
    assert.equal(decided.authority_mode, "registered_peer_actor");
    assert.equal(decided.next_todo_status, "done");
  }
});

test("terminal authority rejects missing, unknown, excluded, bound, and foreign actors", () => {
  const cases: Array<[Record<string, unknown>, string]> = [
    [{ actor_agent_id: null }, "actor_required"],
    [{ actor_agent_id: "agent-c" }, "actor_not_registered"],
    [{ todo: { ...request().todo as object, excluded_agents: ["agent-a"] } }, "actor_excluded"],
    [{ todo: { ...request().todo as object, role: "user", claimed_by: null,
      bound_agent: "agent-b" } }, "bound_agent_mismatch"],
    [{ actor_agent_id: "agent-b" }, "claim_owner_mismatch"],
  ];
  for (const [overrides, code] of cases) {
    const decided = evaluateCoordinationTodoTerminalDecision(request(overrides));
    assert.equal(decided.outcome, "rejected");
    assert.equal(decided.code, code);
  }
});

test("delegated terminal authority is explicit and reason-bound", () => {
  const base = {
    actor_agent_id: "agent-b",
    lifecycle_grants: [{
      agent_id: "agent-b",
      actions: ["complete"],
      requires_reason: true,
    }],
  };
  assert.equal(evaluateCoordinationTodoTerminalDecision(request(base)).code,
    "delegation_reason_required");
  const accepted = evaluateCoordinationTodoTerminalDecision(request({
    ...base,
    authority_reason: "recover abandoned owner",
  }));
  assert.equal(accepted.outcome, "apply");
  assert.equal(accepted.authority_mode, "delegated_orchestration_override");

  const wrongAction = evaluateCoordinationTodoTerminalDecision(request({
    ...base,
    authority_action: "supersede",
    authority_reason: "recover abandoned owner",
  }));
  assert.equal(wrongAction.code, "delegation_action_not_granted");
});

test("exact linked user gate decision scope does not invent Agent authority", () => {
  const scope = {kind: "direction", granularity: "action", scope_key: "release"};
  const gate = {
    todo_id: "todo_gate",
    status: "open",
    role: "user",
    task_class: "user_gate",
    claimed_by: null,
    excluded_agents: [],
    bound_agent: null,
    blocks_agent: "agent-a",
    decision_scope: scope,
    required_decision_scopes: [],
    unblocks_todo_id: "todo_target",
  };
  const target = {
    ...request().todo as object,
    todo_id: "todo_target",
    required_decision_scopes: [scope],
  };
  const accepted = evaluateCoordinationTodoTerminalDecision(request({
    todo: gate,
    decision_target: target,
    actor_agent_id: null,
    decision_outcome: "approve",
  }));
  assert.equal(accepted.outcome, "apply");
  assert.equal(accepted.authority_mode, "exact_user_gate_decision_scope_override");

  const mismatch = evaluateCoordinationTodoTerminalDecision(request({
    todo: gate,
    decision_target: { ...target, required_decision_scopes: [] },
    actor_agent_id: null,
    decision_outcome: "approve",
  }));
  assert.equal(mismatch.code, "actor_required");
});

test("hard-lease terminal transition releases the exact owned generation", () => {
  const lease = {
    present: true,
    active: true,
    status: "active",
    owner: "agent-a",
    idempotency_key: "lease-a",
    version: 3,
    lease_epoch: 7,
    write_scopes: ["docs/**"],
    acquire_ttl_seconds: 600,
  };
  const missingFence = evaluateCoordinationTodoTerminalDecision(request({
    handoff_mode: "hard_lease",
    lease,
  }));
  assert.equal(missingFence.code, "lease_fence_required");
  const stale = evaluateCoordinationTodoTerminalDecision(request({
    handoff_mode: "hard_lease",
    lease,
    lease_idempotency_key: "lease-a",
    lease_expected_version: 2,
  }));
  assert.equal(stale.outcome, "conflict");
  assert.equal(stale.code, "version_mismatch");
  const accepted = evaluateCoordinationTodoTerminalDecision(request({
    handoff_mode: "hard_lease",
    lease,
    lease_idempotency_key: "lease-a",
    lease_expected_version: 3,
  }));
  assert.equal(accepted.outcome, "apply");
  assert.equal(accepted.lease_fence, "required");
  assert.equal(accepted.next_lease?.status, "released");
  assert.equal(accepted.next_lease?.version, 3);
  assert.equal(accepted.next_lease?.lease_epoch, 7);
});

test("hard-lease divergence and terminal replay fail closed in the established order", () => {
  const divergent = evaluateCoordinationTodoTerminalDecision(request({
    handoff_mode: "hard_lease",
    lease: {
      present: true,
      active: true,
      status: "active",
      owner: "agent-b",
      idempotency_key: "lease-b",
      version: 1,
      lease_epoch: 1,
      write_scopes: [],
      acquire_ttl_seconds: 600,
    },
  }));
  assert.equal(divergent.code, "handoff_mode_lease_claim_divergence");

  const replayed = evaluateCoordinationTodoTerminalDecision(request({
    todo: { ...request().todo as object, status: "done" },
    handoff_mode: "hard_lease",
  }));
  assert.equal(replayed.outcome, "no_change");
  assert.equal(replayed.code, "terminal_replay");
  assert.equal(replayed.idempotent, true);
});
