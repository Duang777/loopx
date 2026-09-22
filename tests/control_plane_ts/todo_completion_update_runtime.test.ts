import assert from "node:assert/strict";
import test from "node:test";
import {terminalLifecycleLocalCoordinationTodo, updateLocalCoordinationTodo} from "../../loopx/control_plane/coordination/local_authority_runtime.ts";
import {executeCoordinationTodoUpdate} from "../../loopx/control_plane/coordination/todo_update.ts";
import type {AuthorityStore} from "../../loopx/control_plane/coordination/authority_store.ts";

for (const version of [0, 1, 2]) {
  test(`update v${version} cannot silently ignore completion payload`, async () => {
    let opened = false;
    const result = await updateLocalCoordinationTodo({schema_version: `loopx_local_coordination_todo_update_request_v${version}`,
      completion: {}}, {createStore: () => {opened = true; throw new Error("must not open provider");}});
    assert.equal(result.status, "failed");
    assert.match(String(result.reason), /completion payload requires request v3/);
    assert.equal(opened, false);
  });
}
test("completion v3 requires an explicit effect envelope", async () => {
  const result = await updateLocalCoordinationTodo({schema_version: "loopx_local_coordination_todo_update_request_v3"});
  assert.equal(result.status, "failed");
  assert.match(String(result.reason), /requires its completion payload/);
});
test("malformed completion facts fail before any provider read", async () => {
  const store = new Proxy({} as AuthorityStore, {get: () => {throw new Error("invalid intent reached provider");}});
  for (const completion of [{validation_receipt: []}, {unknown_field: true}, {source_provider_revision: 1}]) {
    const result = await executeCoordinationTodoUpdate(store, {goal_id: "g", todo_id: "todo_a", expected_role: "user",
      actor_agent_id: "agent-a", registered_agents: ["agent-a"], operation_id: "op", patch: {}, clear_fields: [],
      planning_intent: {status: "done"}, completion, dry_run: false, now: new Date()});
    assert.equal(result.reason_code, "invalid_coordination_todo_update");
  }
});

for (const version of [0, 1]) {
  for (const field of ["review_basis", "validation_source_provider_revision", "validation_declaration_sha256"]) {
    test(`terminal v${version} rejects ${field} instead of dropping its obligation`, async () => {
      let opened = false;
      const result = await terminalLifecycleLocalCoordinationTodo({
        schema_version: `loopx_local_coordination_todo_terminal_lifecycle_request_v${version}`, [field]: null,
      }, {createStore: () => {opened = true; throw new Error("must not open provider");}});
      assert.equal(result.status, "failed");
      assert.match(String(result.reason), /source binding requires request v2/);
      assert.equal(opened, false);
    });
  }
}
