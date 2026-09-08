import type { JsonObject } from "../effect_program.ts";
import { EffectRuntimeRequestError } from "../effect_runtime_errors.ts";
import {
  requireBoolean,
  requireInteger,
  requireJsonObject,
  requireNonEmptyString,
  requireStringArray,
  requireStringLiteral,
} from "../runtime_decode.ts";
import { normalizeRegisteredTodoAgents, normalizeTodoAgent } from "./todo_agents.ts";

export const COORDINATION_TODO_TERMINAL_DECISION_REQUEST_SCHEMA =
  "loopx_coordination_todo_terminal_decision_request_v0";
export const COORDINATION_TODO_TERMINAL_DECISION_RESULT_SCHEMA =
  "loopx_coordination_todo_terminal_decision_result_v0";

const COMMANDS = ["complete", "supersede"] as const;
const HANDOFF_MODES = ["legacy", "soft_claim", "hard_lease"] as const;
const OUTCOMES = ["approve", "reject", "cancel"] as const;
const AUTHORITY_ACTIONS = ["complete", "reassign", "supersede", "update"] as const;

type TerminalCommand = typeof COMMANDS[number];
type HandoffMode = typeof HANDOFF_MODES[number];
type DecisionOutcome = typeof OUTCOMES[number];

interface DecisionScope extends JsonObject {
  readonly kind: string;
  readonly granularity: string;
  readonly scope_key: string;
}

interface TodoFact extends JsonObject {
  readonly todo_id: string;
  readonly status: string;
  readonly role: "user" | "agent";
  readonly task_class: string | null;
  readonly claimed_by: string | null;
  readonly excluded_agents: readonly string[];
  readonly bound_agent: string | null;
  readonly blocks_agent: string | null;
  readonly decision_scope: DecisionScope | null;
  readonly required_decision_scopes: readonly DecisionScope[];
  readonly unblocks_todo_id: string | null;
}

interface LeaseFact extends JsonObject {
  readonly present: boolean;
  readonly active: boolean;
  readonly status: string | null;
  readonly owner: string | null;
  readonly idempotency_key: string | null;
  readonly version: number;
  readonly lease_epoch: number;
  readonly write_scopes: readonly string[];
  readonly acquire_ttl_seconds: number | null;
}

interface LifecycleGrant extends JsonObject {
  readonly agent_id: string;
  readonly actions: readonly string[];
  readonly requires_reason: boolean;
}

interface TerminalDecisionRequest {
  readonly command: TerminalCommand;
  readonly handoff_mode: HandoffMode;
  readonly registered_agents: readonly string[];
  readonly lifecycle_grants: readonly LifecycleGrant[];
  readonly todo: TodoFact;
  readonly decision_target: TodoFact | null;
  readonly lease: LeaseFact | null;
  readonly actor_agent_id: string | null;
  readonly authority_action: string;
  readonly authority_reason: string | null;
  readonly decision_outcome: DecisionOutcome | null;
  readonly lease_idempotency_key: string | null;
  readonly lease_expected_version: number | null;
  readonly allow_user_gate_auto_acquire: boolean;
}

export interface CoordinationTodoTerminalDecisionResult extends JsonObject {
  readonly schema_version: typeof COORDINATION_TODO_TERMINAL_DECISION_RESULT_SCHEMA;
  readonly outcome: "apply" | "no_change" | "conflict" | "rejected";
  readonly code: string;
  readonly authority_mode: string | null;
  readonly ownership_gate: "not_required" | "require_holder" | "delegated_override";
  readonly lease_fence: "not_required" | "required" | "auto_acquire" | "delegated_override";
  readonly idempotent: boolean;
  readonly next_todo_status: "done" | null;
  readonly next_lease: LeaseFact | null;
}

function optionalString(value: unknown, label: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value !== "string") {
    throw new EffectRuntimeRequestError(`${label} must be a string or null`);
  }
  return value;
}

function optionalAgent(value: unknown, label: string): string | null {
  const candidate = optionalString(value, label);
  return candidate === null ? null : normalizeTodoAgent(candidate, label);
}

function optionalNonNegativeInteger(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null;
  const candidate = requireInteger(value, label);
  if (candidate < 0) {
    throw new EffectRuntimeRequestError(`${label} must be a non-negative integer or null`);
  }
  return candidate;
}

function decisionScope(value: unknown, label: string): DecisionScope | null {
  if (value === null || value === undefined) return null;
  const scope = requireJsonObject(value, label);
  return {
    kind: requireNonEmptyString(scope.kind, `${label}.kind`),
    granularity: requireNonEmptyString(scope.granularity, `${label}.granularity`),
    scope_key: requireNonEmptyString(scope.scope_key, `${label}.scope_key`),
    ...(typeof scope.schema_version === "string"
      ? { schema_version: scope.schema_version }
      : {}),
    ...(typeof scope.decision_id === "string"
      ? { decision_id: scope.decision_id }
      : {}),
  };
}

function decisionScopes(value: unknown, label: string): DecisionScope[] {
  if (!Array.isArray(value)) {
    throw new EffectRuntimeRequestError(`${label} must be an array`);
  }
  return value.map((scope, index) => decisionScope(scope, `${label}[${index}]`)!);
}

function todoFact(value: unknown, label: string): TodoFact {
  const todo = requireJsonObject(value, label);
  const role = requireStringLiteral(todo.role, ["user", "agent"] as const, `${label}.role`);
  return {
    todo_id: requireNonEmptyString(todo.todo_id, `${label}.todo_id`),
    status: requireNonEmptyString(todo.status, `${label}.status`),
    role,
    task_class: optionalString(todo.task_class, `${label}.task_class`),
    claimed_by: optionalAgent(todo.claimed_by, `${label}.claimed_by`),
    excluded_agents: normalizeRegisteredTodoAgents(
      requireStringArray(todo.excluded_agents ?? [], `${label}.excluded_agents`),
    ),
    bound_agent: optionalAgent(todo.bound_agent, `${label}.bound_agent`),
    blocks_agent: optionalAgent(todo.blocks_agent, `${label}.blocks_agent`),
    decision_scope: decisionScope(todo.decision_scope, `${label}.decision_scope`),
    required_decision_scopes: decisionScopes(
      todo.required_decision_scopes ?? [],
      `${label}.required_decision_scopes`,
    ),
    unblocks_todo_id: optionalString(todo.unblocks_todo_id, `${label}.unblocks_todo_id`),
  };
}

function leaseFact(value: unknown): LeaseFact | null {
  if (value === null || value === undefined) return null;
  const lease = requireJsonObject(value, "lease");
  const version = optionalNonNegativeInteger(lease.version, "lease.version");
  const epoch = optionalNonNegativeInteger(lease.lease_epoch, "lease.lease_epoch");
  if (version === null || epoch === null) {
    throw new EffectRuntimeRequestError("lease version and lease_epoch are required");
  }
  return {
    present: requireBoolean(lease.present, "lease.present"),
    active: requireBoolean(lease.active, "lease.active"),
    status: optionalString(lease.status, "lease.status"),
    owner: optionalAgent(lease.owner, "lease.owner"),
    idempotency_key: optionalString(lease.idempotency_key, "lease.idempotency_key"),
    version,
    lease_epoch: epoch,
    write_scopes: requireStringArray(lease.write_scopes ?? [], "lease.write_scopes"),
    acquire_ttl_seconds: optionalNonNegativeInteger(
      lease.acquire_ttl_seconds,
      "lease.acquire_ttl_seconds",
    ),
  };
}

function lifecycleGrants(
  value: unknown,
  registeredAgents: readonly string[],
): LifecycleGrant[] {
  if (!Array.isArray(value)) {
    throw new EffectRuntimeRequestError("lifecycle_grants must be an array");
  }
  const seen = new Set<string>();
  return value.map((raw, index) => {
    const grant = requireJsonObject(raw, `lifecycle_grants[${index}]`);
    const agentId = normalizeTodoAgent(grant.agent_id, `lifecycle_grants[${index}].agent_id`);
    if (!registeredAgents.includes(agentId)) {
      throw new EffectRuntimeRequestError(
        `todo lifecycle authority agent_id='${agentId}' must already be registered`,
      );
    }
    if (seen.has(agentId)) {
      throw new EffectRuntimeRequestError(`duplicate todo lifecycle authority grant for '${agentId}'`);
    }
    seen.add(agentId);
    const actions = requireStringArray(grant.actions, `lifecycle_grants[${index}].actions`)
      .map((action) => action.trim().toLowerCase());
    if (actions.length === 0 || actions.some((action) =>
      !AUTHORITY_ACTIONS.some((candidate) => candidate === action))) {
      throw new EffectRuntimeRequestError(
        "todo lifecycle authority actions must contain supported actions",
      );
    }
    return {
      agent_id: agentId,
      actions: [...new Set(actions)],
      requires_reason: requireBoolean(
        grant.requires_reason,
        `lifecycle_grants[${index}].requires_reason`,
      ),
    };
  });
}

function decodeRequest(value: unknown): TerminalDecisionRequest {
  const request = requireJsonObject(value, "Todo terminal decision request");
  requireStringLiteral(
    request.schema_version,
    [COORDINATION_TODO_TERMINAL_DECISION_REQUEST_SCHEMA] as const,
    "schema_version",
  );
  const registeredAgents = normalizeRegisteredTodoAgents(
    requireStringArray(request.registered_agents, "registered_agents"),
  );
  const outcome = optionalString(request.decision_outcome, "decision_outcome");
  return {
    command: requireStringLiteral(request.command, COMMANDS, "command"),
    handoff_mode: requireStringLiteral(request.handoff_mode, HANDOFF_MODES, "handoff_mode"),
    registered_agents: registeredAgents,
    lifecycle_grants: lifecycleGrants(request.lifecycle_grants ?? [], registeredAgents),
    todo: todoFact(request.todo, "todo"),
    decision_target: request.decision_target === null || request.decision_target === undefined
      ? null
      : todoFact(request.decision_target, "decision_target"),
    lease: leaseFact(request.lease),
    actor_agent_id: optionalAgent(request.actor_agent_id, "actor_agent_id"),
    authority_action: requireStringLiteral(
      request.authority_action,
      AUTHORITY_ACTIONS,
      "authority_action",
    ),
    authority_reason: optionalString(request.authority_reason, "authority_reason"),
    decision_outcome: outcome === null
      ? null
      : requireStringLiteral(outcome, OUTCOMES, "decision_outcome"),
    lease_idempotency_key: optionalString(
      request.lease_idempotency_key,
      "lease_idempotency_key",
    ),
    lease_expected_version: optionalNonNegativeInteger(
      request.lease_expected_version,
      "lease_expected_version",
    ),
    allow_user_gate_auto_acquire: requireBoolean(
      request.allow_user_gate_auto_acquire,
      "allow_user_gate_auto_acquire",
    ),
  };
}

function scopeKey(scope: DecisionScope): string {
  return `${scope.kind}\u0000${scope.granularity}\u0000${scope.scope_key}`;
}

function exactUserGateOverride(request: TerminalDecisionRequest): boolean {
  const { todo, decision_target: target } = request;
  return request.command === "complete" && target !== null && todo.role === "user" &&
    todo.task_class === "user_gate" && request.decision_outcome !== null &&
    todo.decision_scope !== null && todo.unblocks_todo_id === target.todo_id &&
    target.required_decision_scopes.some((scope) =>
      scopeKey(scope) === scopeKey(todo.decision_scope!));
}

function result(
  outcome: CoordinationTodoTerminalDecisionResult["outcome"],
  code: string,
  options: Partial<Pick<CoordinationTodoTerminalDecisionResult,
    "authority_mode" | "ownership_gate" | "lease_fence" | "idempotent" |
    "next_todo_status" | "next_lease">> = {},
): CoordinationTodoTerminalDecisionResult {
  return {
    schema_version: COORDINATION_TODO_TERMINAL_DECISION_RESULT_SCHEMA,
    outcome,
    code,
    authority_mode: options.authority_mode ?? null,
    ownership_gate: options.ownership_gate ?? "not_required",
    lease_fence: options.lease_fence ?? "not_required",
    idempotent: options.idempotent ?? false,
    next_todo_status: options.next_todo_status ?? null,
    next_lease: options.next_lease ?? null,
  };
}

function authority(request: TerminalDecisionRequest):
  | { mode: string; ownershipGate: CoordinationTodoTerminalDecisionResult["ownership_gate"] }
  | CoordinationTodoTerminalDecisionResult {
  const { todo, actor_agent_id: actor, registered_agents: registered } = request;
  if (registered.length <= 1) {
    if (actor !== null && registered.length > 0 && !registered.includes(actor)) {
      return result("rejected", "actor_not_registered");
    }
    return { mode: "single_agent_compatibility", ownershipGate: "not_required" };
  }
  if (exactUserGateOverride(request)) {
    return { mode: "exact_user_gate_decision_scope_override", ownershipGate: "not_required" };
  }
  if (actor === null) return result("rejected", "actor_required");
  if (!registered.includes(actor)) return result("rejected", "actor_not_registered");
  if (todo.excluded_agents.includes(actor)) return result("rejected", "actor_excluded");
  const boundAgent = todo.bound_agent ?? (todo.role === "user" ? todo.blocks_agent : null);
  if (boundAgent !== null && boundAgent !== actor) {
    return result("rejected", "bound_agent_mismatch");
  }
  if (todo.claimed_by !== null && todo.claimed_by !== actor) {
    const grant = request.lifecycle_grants.find((candidate) => candidate.agent_id === actor);
    if (grant === undefined) return result("rejected", "claim_owner_mismatch");
    if (!grant.actions.includes(request.authority_action)) {
      return result("rejected", "delegation_action_not_granted");
    }
    if (grant.requires_reason && !String(request.authority_reason ?? "").trim()) {
      return result("rejected", "delegation_reason_required");
    }
    return { mode: "delegated_orchestration_override", ownershipGate: "not_required" };
  }
  return { mode: "registered_peer_actor", ownershipGate: "not_required" };
}

function ownerEligible(request: TerminalDecisionRequest, owner: string | null): boolean {
  const todo = request.todo;
  return todo.status === "open" && owner !== null &&
    request.registered_agents.includes(owner) && !todo.excluded_agents.includes(owner) &&
    (todo.claimed_by === null || todo.claimed_by === owner);
}

function terminalFence(
  request: TerminalDecisionRequest,
  authorityMode: string,
): CoordinationTodoTerminalDecisionResult {
  const lease = request.lease;
  const timeActive = lease !== null && lease.present && lease.active;
  const effective = timeActive && ownerEligible(request, lease.owner);
  const explicitFence = request.lease_idempotency_key !== null ||
    request.lease_expected_version !== null;
  const delegated = authorityMode === "delegated_orchestration_override";
  const autoAcquire = request.handoff_mode === "hard_lease" && !delegated &&
    request.allow_user_gate_auto_acquire && request.todo.role === "user" &&
    request.todo.task_class === "user_gate";
  if (autoAcquire && !effective && !timeActive) {
    if (!ownerEligible(request, request.actor_agent_id)) {
      return result("rejected", "handoff_mode_requires_lease", {
        authority_mode: authorityMode,
        lease_fence: "auto_acquire",
      });
    }
    const version = (lease?.present ? lease.version : 0) + 1;
    const epoch = (lease?.lease_epoch ?? 0) + 1;
    return result("apply", "terminal_transition", {
      authority_mode: authorityMode,
      lease_fence: "auto_acquire",
      next_todo_status: "done",
      next_lease: {
        present: true,
        active: false,
        status: "released",
        owner: request.actor_agent_id,
        idempotency_key: request.lease_idempotency_key ?? `auto-${request.todo.todo_id}`,
        version,
        lease_epoch: epoch,
        write_scopes: [],
        acquire_ttl_seconds: 2700,
      },
    });
  }
  if (!effective) {
    if (request.handoff_mode === "hard_lease" && !delegated) {
      return result("rejected", timeActive
        ? "handoff_mode_lease_claim_divergence"
        : "handoff_mode_requires_lease", {
        authority_mode: authorityMode,
        lease_fence: "required",
      });
    }
    if (explicitFence) {
      return result("rejected", "lease_not_active", { authority_mode: authorityMode });
    }
    return result("apply", "terminal_transition", {
      authority_mode: authorityMode,
      lease_fence: delegated && request.handoff_mode === "hard_lease"
        ? "delegated_override"
        : "not_required",
      next_todo_status: "done",
    });
  }
  if (request.lease_idempotency_key === null) {
    return result("rejected", "lease_fence_required", {
      authority_mode: authorityMode,
      lease_fence: "required",
    });
  }
  if (lease!.owner !== request.actor_agent_id ||
      lease!.idempotency_key !== request.lease_idempotency_key) {
    return result("rejected", "lease_cas_mismatch", {
      authority_mode: authorityMode,
      lease_fence: "required",
    });
  }
  if (request.lease_expected_version === null) {
    return result("rejected", "version_required", {
      authority_mode: authorityMode,
      lease_fence: "required",
    });
  }
  if (lease!.version !== request.lease_expected_version) {
    return result("conflict", "version_mismatch", {
      authority_mode: authorityMode,
      lease_fence: "required",
    });
  }
  return result("apply", "terminal_transition", {
    authority_mode: authorityMode,
    lease_fence: "required",
    next_todo_status: "done",
    next_lease: { ...lease!, active: false, status: "released" },
  });
}

/** One semantic owner for complete/supersede authority and the terminal lease fence. */
export function evaluateCoordinationTodoTerminalDecision(
  value: unknown,
): CoordinationTodoTerminalDecisionResult {
  const request = decodeRequest(value);
  const authorityResult = authority(request);
  if ("outcome" in authorityResult) return authorityResult;
  if (request.todo.status === "done") {
    return result("no_change", "terminal_replay", {
      authority_mode: authorityResult.mode,
      ownership_gate: authorityResult.ownershipGate,
      idempotent: true,
    });
  }
  return terminalFence(request, authorityResult.mode);
}
