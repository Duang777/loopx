import type { JsonObject } from "../effect_program.ts";
import type { AuthorityStore } from "./authority_store.ts";
import {
  AuthorityStoreProtocolError,
  canonicalAuthorityObject,
  canonicalAuthoritySha256,
  requireAuthorityStoreId,
} from "./authority_store_codec.ts";
import {
  COORDINATION_PROJECTION_MUTATION_RECEIPT_SCHEMA,
  commitCoordinationProjectionMutation,
  indexCoordinationProjection,
  validateCoordinationTodoReadModel,
} from "./coordination_projection.ts";

export const COORDINATION_TODO_CLAIM_RESULT_SCHEMA =
  "loopx_coordination_todo_claim_result_v0";

export interface CoordinationTodoClaimInput {
  readonly goal_id: string;
  readonly todo_id: string;
  readonly claimed_by: string;
  readonly actor_agent_id: string | null;
  readonly expected_role: string | null;
  readonly registered_agents: readonly string[];
  readonly operation_id: string;
  readonly dry_run: boolean;
  readonly now: Date;
}

export type CoordinationTodoClaimResult = JsonObject & {
  readonly schema_version: typeof COORDINATION_TODO_CLAIM_RESULT_SCHEMA;
};

function normalizeAgent(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new AuthorityStoreProtocolError(`${label} must be a public-safe agent id`);
  }
  const candidate = value.trim().toLowerCase().replaceAll(" ", "-");
  if (!/^[a-z][a-z0-9_.:@-]{0,79}$/u.test(candidate)) {
    throw new AuthorityStoreProtocolError(`${label} must be a public-safe agent id`);
  }
  return candidate;
}

function normalizeRegisteredAgents(value: readonly string[]): string[] {
  const normalized = value.map((agent, index) =>
    normalizeAgent(agent, `registered_agents[${index}]`)
  );
  if (normalized.length === 0 || new Set(normalized).size !== normalized.length) {
    throw new AuthorityStoreProtocolError(
      "registered_agents must contain unique public-safe agent ids",
    );
  }
  return normalized;
}

function failure(code: string, reason: string, detail: JsonObject = {}): CoordinationTodoClaimResult {
  return {
    schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
    status: "failed",
    reason_code: code,
    reason,
    ...detail,
  };
}

function claimAuthority(
  todo: JsonObject,
  input: CoordinationTodoClaimInput,
): { owner: string; actor: string | null; mode: string } | CoordinationTodoClaimResult {
  const registered = normalizeRegisteredAgents(input.registered_agents);
  const owner = normalizeAgent(input.claimed_by, "claimed_by");
  const actor = input.actor_agent_id === null
    ? null
    : normalizeAgent(input.actor_agent_id, "actor_agent_id");
  if (!registered.includes(owner)) {
    return failure("actor_not_registered", "claimed_by is not registered for this goal", {
      claimed_by: owner,
    });
  }
  if (actor !== null && !registered.includes(actor)) {
    return failure("actor_not_registered", "actor_agent_id is not registered for this goal", {
      actor_agent_id: actor,
    });
  }
  if (registered.length > 1 && actor === null) {
    return failure("actor_required", "multi-agent Todo claim requires actor_agent_id");
  }
  if (actor !== null && actor !== owner) {
    return failure(
      "claim_actor_mismatch",
      "Todo claim requires claimed_by to match actor_agent_id",
      { actor_agent_id: actor, claimed_by: owner },
    );
  }
  if (todo.role !== "agent") {
    return failure("todo_not_agent", "claimed_by is only valid for agent Todos");
  }
  if (input.expected_role !== null && input.expected_role !== todo.role) {
    return failure("todo_role_mismatch", "Todo does not have the requested role", {
      requested_role: input.expected_role,
      todo_role: todo.role,
    });
  }
  if (todo.status !== "open") {
    return failure("todo_not_open", "Todo claim requires status=open", {
      todo_status: todo.status,
    });
  }
  if (typeof todo.removed_continuation_policy === "string" &&
      todo.removed_continuation_policy.length > 0) {
    return failure(
      "removed_continuation_policy",
      "Todo uses a removed continuation policy and must be repaired before claiming",
    );
  }
  const excluded = Array.isArray(todo.excluded_agents) ? todo.excluded_agents : [];
  if (excluded.includes(owner)) {
    return failure("actor_excluded", "claiming agent is excluded from this Todo", {
      actor_agent_id: owner,
    });
  }
  const existing = typeof todo.claimed_by === "string" && todo.claimed_by.length > 0
    ? normalizeAgent(todo.claimed_by, "todo.claimed_by")
    : null;
  if (existing !== null && existing !== owner) {
    return failure("claim_owner_mismatch", "Todo is already claimed by another agent", {
      claim_owner: existing,
    });
  }
  return {
    owner,
    actor,
    mode: registered.length <= 1 ? "single_agent_compatibility" : "registered_peer_actor",
  };
}

function leaseIsActiveForOwner(lease: JsonObject | undefined, owner: string, now: Date): boolean {
  if (lease === undefined || lease.status !== "active" ||
      typeof lease.owner !== "string" || typeof lease.expires_at !== "string") return false;
  let leaseOwner: string;
  try {
    leaseOwner = normalizeAgent(lease.owner, "lease.owner");
  } catch {
    return false;
  }
  if (leaseOwner !== owner) return false;
  const expiresAt = new Date(lease.expires_at);
  return !Number.isNaN(expiresAt.valueOf()) && expiresAt.valueOf() > now.valueOf();
}

/**
 * Claim one Todo against the canonical provider head.
 *
 * The transaction is store-neutral: file, NoKV, and PostgreSQL adapters share
 * the same semantic decision, complete-record replacement, CAS, and receipt.
 * No caller-supplied projection is accepted.
 */
export async function executeCoordinationTodoClaim(
  store: AuthorityStore,
  rawInput: CoordinationTodoClaimInput,
): Promise<CoordinationTodoClaimResult> {
  let input: CoordinationTodoClaimInput;
  try {
    input = {
      ...rawInput,
      goal_id: requireAuthorityStoreId(rawInput.goal_id, "goal id"),
      todo_id: requireAuthorityStoreId(rawInput.todo_id, "todo id"),
      operation_id: requireAuthorityStoreId(rawInput.operation_id, "operation id"),
    };
    if (!(input.now instanceof Date) || Number.isNaN(input.now.valueOf())) {
      throw new AuthorityStoreProtocolError("now must be a valid Date");
    }
  } catch (error) {
    return failure(
      "invalid_coordination_todo_claim",
      error instanceof Error ? error.message : "invalid Todo claim",
    );
  }

  const head = await store.loadAuthority();
  if (head.status !== "loaded") {
    return {
      schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
      ...head,
    } as CoordinationTodoClaimResult;
  }

  let projection: ReturnType<typeof indexCoordinationProjection>;
  try {
    projection = indexCoordinationProjection(head.head, input.goal_id);
    validateCoordinationTodoReadModel(head.head, input.goal_id);
  } catch (error) {
    return failure(
      "invalid_coordination_projection",
      error instanceof Error ? error.message : "invalid coordination projection",
    );
  }
  const todo = projection.todos.get(input.todo_id);
  if (todo === undefined) {
    return failure("todo_not_found", "Todo is missing from the canonical provider head", {
      todo_id: input.todo_id,
    });
  }

  let authority: ReturnType<typeof claimAuthority>;
  try {
    authority = claimAuthority(todo, input);
  } catch (error) {
    return failure(
      "invalid_coordination_todo_claim",
      error instanceof Error ? error.message : "invalid Todo claim",
    );
  }
  if (typeof authority.owner !== "string") return authority as CoordinationTodoClaimResult;

  const handoffMode = typeof head.head.handoff_mode === "string"
    ? head.head.handoff_mode
    : "legacy";
  if (!["legacy", "soft_claim", "hard_lease"].includes(handoffMode)) {
    return failure("invalid_handoff_mode", "canonical projection has an invalid handoff mode");
  }
  if (handoffMode === "hard_lease" &&
      !leaseIsActiveForOwner(projection.leases.get(input.todo_id), authority.owner, input.now)) {
    return failure(
      "handoff_mode_requires_lease",
      "hard_lease Todo claim requires an active canonical lease held by the claiming agent",
      { todo_id: input.todo_id, actor_agent_id: authority.owner },
    );
  }

  const mutationAuthority = {
    schema_version: "todo_mutation_authority_v0",
    command: "claim",
    mode: authority.mode,
    actor_agent_id: authority.actor,
    todo_id: input.todo_id,
    registered_agent_count: input.registered_agents.length,
    ...(authority.mode === "registered_peer_actor"
      ? { claim_owner: typeof todo.claimed_by === "string" ? todo.claimed_by : null }
      : {}),
  };
  const updatedAt = input.now.toISOString().replace(/\.\d{3}Z$/u, "Z");
  const nextTodo = canonicalAuthorityObject({
    ...todo,
    claimed_by: authority.owner,
    updated_at: updatedAt,
  }, "claimed Todo");
  if (todo.claimed_by === authority.owner) {
    const receipt = await store.readReceipt(input.operation_id);
    if (receipt.status === "found") {
      const expectedMutationSha = canonicalAuthoritySha256([
        { kind: "todo_upsert", todo: nextTodo },
      ]);
      const exact = receipt.receipts.length === 1 &&
        receipt.receipts[0]?.schema_version ===
          COORDINATION_PROJECTION_MUTATION_RECEIPT_SCHEMA &&
        receipt.receipts[0]?.operation_id === input.operation_id &&
        receipt.receipts[0]?.goal_id === input.goal_id &&
        receipt.receipts[0]?.mutation_sha256 === expectedMutationSha;
      return exact
        ? {
          schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
          status: "replayed",
          changed: false,
          todo_id: input.todo_id,
          claimed_by: authority.owner,
          provider_revision: receipt.provider_revision,
          cursor: receipt.cursor,
          handoff_mode: handoffMode,
          mutation_authority: mutationAuthority,
        }
        : failure(
          "coordination_operation_identity_mismatch",
          "operation id already names a different coordination mutation",
        );
    }
    if (receipt.status !== "missing") {
      return {
        schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
        ...receipt,
      } as CoordinationTodoClaimResult;
    }
    return {
      schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
      status: "no_change",
      changed: false,
      todo_id: input.todo_id,
      claimed_by: authority.owner,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      handoff_mode: handoffMode,
      mutation_authority: mutationAuthority,
    };
  }

  if (input.dry_run) {
    return {
      schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
      status: "planned",
      changed: true,
      dry_run: true,
      todo_id: input.todo_id,
      claimed_by: authority.owner,
      provider_revision: head.provider_revision,
      cursor: head.cursor,
      handoff_mode: handoffMode,
      updated_at: updatedAt,
      mutation_authority: mutationAuthority,
    };
  }

  const committed = await commitCoordinationProjectionMutation(store, {
    goal_id: input.goal_id,
    operation_id: input.operation_id,
    expected_provider_revision: head.provider_revision,
    mutations: [{ kind: "todo_upsert", todo: nextTodo }],
  });
  const changed = ["applied", "recovered", "replayed"].includes(committed.status);
  return {
    schema_version: COORDINATION_TODO_CLAIM_RESULT_SCHEMA,
    ...committed,
    changed,
    todo_id: input.todo_id,
    claimed_by: authority.owner,
    handoff_mode: handoffMode,
    updated_at: changed ? updatedAt : null,
    mutation_authority: mutationAuthority,
  };
}
