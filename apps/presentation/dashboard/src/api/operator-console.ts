import { createLoopXApiClient, ifNoneMatch } from "./generated/client";
import type { components } from "./generated/schema";

export type CapabilityList = components["schemas"]["CapabilityListResponse"];
export type Capability = components["schemas"]["CapabilityResponse"];
export type ConfigurationPatch = components["schemas"]["GoalConfigurationPatchRequest"];
export type ConfigurationPlan = components["schemas"]["ConfigurationPlanResponse"];
export type ControlSession = components["schemas"]["ControlSessionResponse"];
export type GoalList = components["schemas"]["GoalListResponse"];
export type GoalOverview = components["schemas"]["GoalOverviewResponse"];
export type GoalHistory = components["schemas"]["HistoryPageResponse"];
export type LeaseInspection = components["schemas"]["TaskLeaseInspectionResponse"];
export type OperatorStatus = components["schemas"]["OperatorStatusResponse"];
export type QuotaDecision = components["schemas"]["QuotaDecisionResponse"];
export type QuotaMutationPlan = components["schemas"]["QuotaMutationPlanResponse"];
export type TodoCompletionRequest = components["schemas"]["TodoCompletionRequest"];
export type TodoCompletionPlan = components["schemas"]["TodoCompletionPlanResponse"];
export type TodoList = components["schemas"]["TodoListResponse"];
export type TurnPlan = components["schemas"]["TurnPlanResponse"];
export type TurnPlanRequest = components["schemas"]["TurnPlanRequestBody"];
export type WriteContext = components["schemas"]["WriteContextRequest"];

export interface ObservedProjection<T> {
  etag: string | null;
  observedAt: number;
  payload: T;
  revision: string | null;
}

export class OperatorApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;

  constructor(input: {
    code: string;
    message: string;
    retryable?: boolean;
    status: number;
  }) {
    super(input.message);
    this.name = "OperatorApiError";
    this.code = input.code;
    this.retryable = input.retryable ?? false;
    this.status = input.status;
  }
}

type OpenApiResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

const generated = createLoopXApiClient();
const projectionCache = new Map<string, ObservedProjection<unknown>>();
let controlSessionId: string | null = null;

function detailFrom(error: unknown) {
  if (!error || typeof error !== "object") {
    return null;
  }
  const candidate = error as {
    error?: { code?: unknown; message?: unknown; retryable?: unknown };
  };
  if (!candidate.error || typeof candidate.error !== "object") {
    return null;
  }
  return candidate.error;
}

function apiError(error: unknown, response: Response): OperatorApiError {
  const detail = detailFrom(error);
  const code = typeof detail?.code === "string" ? detail.code : `http_${response.status}`;
  const message = typeof detail?.message === "string"
    ? detail.message
    : `LoopX API request failed with HTTP ${response.status}`;
  return new OperatorApiError({
    code,
    message,
    retryable: detail?.retryable === true,
    status: response.status,
  });
}

function unwrap<T>(result: OpenApiResult<T>): T {
  if (result.data !== undefined) {
    return result.data;
  }
  throw apiError(result.error, result.response);
}

function readHeaders(key: string): HeadersInit {
  return ifNoneMatch(projectionCache.get(key)?.etag);
}

function resolveProjection<T>(key: string, result: OpenApiResult<T>): ObservedProjection<T> {
  if (result.response.status === 304) {
    const cached = projectionCache.get(key) as ObservedProjection<T> | undefined;
    if (!cached) {
      throw new OperatorApiError({
        code: "etag_cache_miss",
        message: "The server returned 304 before this browser had a cached projection.",
        status: 304,
      });
    }
    const observed = { ...cached, observedAt: Date.now() };
    projectionCache.set(key, observed);
    return observed;
  }

  const payload = unwrap(result);
  const revision = payload && typeof payload === "object" && "revision" in payload
    ? String((payload as { revision: unknown }).revision ?? "") || null
    : null;
  const observed: ObservedProjection<T> = {
    etag: result.response.headers.get("etag"),
    observedAt: Date.now(),
    payload,
    revision,
  };
  projectionCache.set(key, observed);
  return observed;
}

function mutationHeaders() {
  if (!controlSessionId) {
    throw new OperatorApiError({
      code: "control_session_missing",
      message: "Create a control session before requesting an operator action.",
      status: 401,
    });
  }
  return { "X-LoopX-Control-Session": controlSessionId } as const;
}

export function createWriteContext(actor: string, expectedRevision: string | null): WriteContext {
  return {
    actor: actor.trim() || "local-operator",
    expected_revision: expectedRevision,
    idempotency_key: `dashboard-${crypto.randomUUID()}`,
  };
}

export function clearOperatorProjectionCache() {
  projectionCache.clear();
}

export function resetOperatorControlSession() {
  controlSessionId = null;
  generated.setControlSession(null);
  clearOperatorProjectionCache();
}

export const operatorConsoleApi = {
  async createControlSession(): Promise<ControlSession> {
    const result = await generated.client.POST("/api/v1/control-sessions", {
      body: {},
    });
    const session = unwrap(result);
    controlSessionId = session.control_session_id;
    generated.setControlSession(controlSessionId);
    return session;
  },

  async operatorStatus(): Promise<OperatorStatus> {
    return unwrap(await generated.client.GET("/api/v1/operator"));
  },

  async setOperatorRole(action: "acquire" | "release" | "takeover"): Promise<OperatorStatus> {
    const path = action === "acquire"
      ? "/api/v1/operator/acquire"
      : action === "release"
        ? "/api/v1/operator/release"
        : "/api/v1/operator/takeover";
    return unwrap(await generated.client.POST(path, {
      body: { confirmed: true },
      headers: mutationHeaders(),
      params: { header: mutationHeaders() },
    }));
  },

  async capabilities(): Promise<ObservedProjection<CapabilityList>> {
    const key = "capabilities";
    return resolveProjection(key, await generated.client.GET("/api/v1/capabilities", {
      headers: readHeaders(key),
    }));
  },

  async goals(): Promise<ObservedProjection<GoalList>> {
    const key = "goals";
    return resolveProjection(key, await generated.client.GET("/api/v1/goals", {
      headers: readHeaders(key),
    }));
  },

  async overview(goalId: string): Promise<ObservedProjection<GoalOverview>> {
    const key = `overview:${goalId}`;
    return resolveProjection(key, await generated.client.GET("/api/v1/goals/{goal_id}/overview", {
      headers: readHeaders(key),
      params: { path: { goal_id: goalId } },
    }));
  },

  async todos(goalId: string): Promise<ObservedProjection<TodoList>> {
    const key = `todos:${goalId}`;
    return resolveProjection(key, await generated.client.GET("/api/v1/goals/{goal_id}/todos", {
      headers: readHeaders(key),
      params: { path: { goal_id: goalId } },
    }));
  },

  async quota(goalId: string): Promise<ObservedProjection<QuotaDecision>> {
    const key = `quota:${goalId}`;
    return resolveProjection(key, await generated.client.GET("/api/v1/goals/{goal_id}/quota/should-run", {
      headers: readHeaders(key),
      params: { path: { goal_id: goalId } },
    }));
  },

  async history(goalId: string): Promise<ObservedProjection<GoalHistory>> {
    const key = `history:${goalId}`;
    return resolveProjection(key, await generated.client.GET("/api/v1/goals/{goal_id}/history", {
      headers: readHeaders(key),
      params: {
        path: { goal_id: goalId },
        query: { page_size: 8 },
      },
    }));
  },

  async lease(goalId: string, todoId: string): Promise<ObservedProjection<LeaseInspection>> {
    const key = `lease:${goalId}:${todoId}`;
    return resolveProjection(key, await generated.client.GET("/api/v1/goals/{goal_id}/leases/{todo_id}", {
      headers: readHeaders(key),
      params: { path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async previewConfiguration(goalId: string, patch: ConfigurationPatch): Promise<ConfigurationPlan> {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/configuration/preview", {
      body: { patch },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId } },
    }));
  },

  async applyConfiguration(goalId: string, patch: ConfigurationPatch, plan: ConfigurationPlan, actor: string) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/configuration/apply", {
      body: {
        patch,
        plan_hash: plan.plan_hash,
        write_context: createWriteContext(actor, plan.revision),
      },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId } },
    }));
  },

  async claimTodo(goalId: string, todoId: string, actor: string, revision: string) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/todos/{todo_id}/claim", {
      body: { write_context: createWriteContext(actor, revision) },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async previewTodoCompletion(
    goalId: string,
    todoId: string,
    actor: string,
    completion: TodoCompletionRequest,
  ): Promise<TodoCompletionPlan> {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/todos/{todo_id}/complete/preview", {
      body: { actor, completion },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async applyTodoCompletion(goalId: string, todoId: string, actor: string, plan: TodoCompletionPlan) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/todos/{todo_id}/complete/apply", {
      body: {
        plan,
        write_context: createWriteContext(actor, plan.revision),
      },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async acquireLease(goalId: string, todoId: string, actor: string, expectedRevision: string | null) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/leases/{todo_id}/acquire", {
      body: {
        ttl_seconds: 900,
        write_context: createWriteContext(actor, expectedRevision),
        write_scopes: ["todo"],
      },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async renewLease(goalId: string, todoId: string, actor: string, expectedRevision: string) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/leases/{todo_id}/renew", {
      body: {
        ttl_seconds: 900,
        write_context: createWriteContext(actor, expectedRevision),
      },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async releaseLease(goalId: string, todoId: string, actor: string, expectedRevision: string) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/leases/{todo_id}/release", {
      body: { write_context: createWriteContext(actor, expectedRevision) },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId, todo_id: todoId } },
    }));
  },

  async previewQuotaSpend(goalId: string, slots: number, actor: string): Promise<QuotaMutationPlan> {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/quota/spend/preview", {
      body: { agent_id: actor, slots, source: "visible-goal" },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId } },
    }));
  },

  async applyQuotaSpend(goalId: string, plan: QuotaMutationPlan, actor: string) {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/quota/spend/apply", {
      body: {
        plan,
        write_context: createWriteContext(actor, plan.revision),
      },
      headers: mutationHeaders(),
      params: { header: mutationHeaders(), path: { goal_id: goalId } },
    }));
  },

  async planTurn(goalId: string, request: TurnPlanRequest): Promise<TurnPlan> {
    return unwrap(await generated.client.POST("/api/v1/goals/{goal_id}/turns/plan", {
      body: request,
      params: { path: { goal_id: goalId } },
    }));
  },
};
