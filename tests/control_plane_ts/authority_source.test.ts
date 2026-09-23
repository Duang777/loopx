import assert from "node:assert/strict";
import {createHash} from "node:crypto";
import {mkdtemp, rm, writeFile} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import test from "node:test";
import {registryAuthoritySourceCheck} from "../../loopx/control_plane/coordination/authority_source.ts";
import {
  claimLocalCoordinationTodo, createLocalCoordinationTodo, updateLocalCoordinationTodo,
  terminalLifecycleLocalCoordinationTodo, pollLocalCoordinationMonitor,
} from "../../loopx/control_plane/coordination/local_authority_runtime.ts";

test("registry witness captures primitive values across awaited request mutation", async t => {
  const root = await mkdtemp(join(tmpdir(), "loopx-source-wire-"));
  t.after(() => rm(root, {recursive: true, force: true}));
  const path = join(root, "registry.json"), body = "original registration";
  await writeFile(path, body);
  const source = {path, sha256: createHash("sha256").update(body).digest("hex")};
  const check = registryAuthoritySourceCheck({registry_source: source}, true);
  const conflictingReview = registryAuthoritySourceCheck({registry_source: source}, true, "0".repeat(64));
  source.path = join(root, "missing.json"); source.sha256 = "0".repeat(64);
  assert.equal(await check(), true, "mutable decoded input cannot redirect the witness");
  assert.equal(await conflictingReview(), false);
  await writeFile(path, "revoked");
  assert.equal(await check(), false);
  await rm(path);
  assert.equal(await check(), false);
});

const wires = [
  {invoke: createLocalCoordinationTodo, prefix: "loopx_local_coordination_todo_create_request",
    legacy: [0], current: 1, currentFields: {},
    legacyReason: /registry_source|admission and revision fields/u},
  {invoke: claimLocalCoordinationTodo, prefix: "loopx_local_coordination_todo_claim_request",
    legacy: [0], current: 1, currentFields: {},
    legacyReason: /registry_source|admission and revision fields/u},
  {invoke: terminalLifecycleLocalCoordinationTodo, prefix: "loopx_local_coordination_todo_terminal_lifecycle_request",
    legacy: [0, 1, 2], current: 3, currentFields: {command: "supersede",
      operation_identity: {kind: "explicit", operation_id: "source-wire"},
      requested_completion_turn_key: null},
    legacyReason: /schema mismatch; regenerate with the current runtime/u},
  {invoke: updateLocalCoordinationTodo, prefix: "loopx_local_coordination_todo_update_request",
    legacy: [0, 1], current: 2, currentFields: {},
    legacyReason: /registry_source|admission and revision fields/u},
  {invoke: pollLocalCoordinationMonitor, prefix: "loopx_coordination_monitor_poll_request",
    legacy: [0, 1], current: 2, currentFields: {},
    legacyReason: /registry_source|admission and revision fields/u},
];
for (const wire of wires) test(`${wire.prefix}: source obligation cannot silently cross wire versions`, async () => {
  for (const version of wire.legacy) for (const source of [null, {path: "/unused", sha256: "0".repeat(64)}]) {
    const result = await wire.invoke({schema_version: `${wire.prefix}_v${version}`, registry_source: source});
    assert.equal(result.status, "failed");
    assert.match(String(result.reason), wire.legacyReason);
  }
  for (const source of [undefined, {}, {path: "relative", sha256: "0".repeat(64)}, {path: "/unused", sha256: "invalid"}]) {
    const result = await wire.invoke({schema_version: `${wire.prefix}_v${wire.current}`, registry_source: source,
      lifecycle_grants: [], ...wire.currentFields});
    assert.equal(result.status, "failed");
    assert.match(String(result.reason), /registry_source/u);
  }
});
