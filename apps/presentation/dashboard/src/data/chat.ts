import { z } from "zod";

import {
  todoApplyResultMatchesRequest,
  todoPreviewMatchesRequest,
  type TodoApplyResult,
  type TodoPreview,
} from "./chat-model";

export {
  agentBackendLabel,
  answerLocalStatusQuestion,
  buildGoalStudioNodes,
  chatFailureMessage,
  completedGoalReviews,
  pendingGoalReviews,
  proposalReviewState,
  sessionInvalidatedByPayload,
  selectChatGoal,
  stewardPrompts,
  turnReplaySafeByPayload,
  todoNoWriteReceiptFromPayload,
  todoNoWriteReceiptLabel,
  todoApplyResultMatchesRequest,
  todoPreviewMatchesRequest,
  todoReceiptLabel,
  todoReceiptOutcomeLabel,
  todoReceiptProjected,
} from "./chat-model";
export type {
  AgentResponse,
  ChatCapabilities,
  ChatGoal,
  ChatStatus,
  ChatTodo,
  GoalStudioNode,
  ProposalDecisionOutcome,
  ProposalReviewState,
  StewardPrompt,
  TodoNoWriteReceipt,
  TodoPreview,
  TodoProposal,
  TodoApplyResult,
  TodoWriteReceipt,
} from "./chat-model";

export const chatTodoSchema = z.object({
  todo_id: z.string().nullable(),
  role: z.string().nullable(),
  status: z.string(),
  priority: z.string().nullable(),
  text: z.string(),
  action_kind: z.string().nullable(),
  task_class: z.string().nullable(),
  claimed_by: z.string().nullable(),
  evidence: z.string().nullable(),
});

export const chatGoalSchema = z.object({
  goal_id: z.string(),
  title: z.string(),
  objective: z.string(),
  status: z.string(),
  waiting_on: z.string().nullable(),
  severity: z.string().nullable(),
  gate: z.string(),
  next_action: z.string(),
  top_todo: chatTodoSchema.nullable(),
  todos: z.array(chatTodoSchema),
  evidence: z.array(z.string()),
  quota: z.object({
    state: z.string().nullable(),
    spent_slots: z.number().nullable(),
    allowed_slots: z.number().nullable(),
    reason: z.string().nullable(),
  }),
});

export const chatStatusSchema = z.object({
  ok: z.boolean(),
  schema_version: z.literal("loopx_chat_status_v0"),
  selected_goal_id: z.string().nullable(),
  goal_count: z.number(),
  goals: z.array(chatGoalSchema),
});

export const chatCapabilitiesSchema = z.object({
  ok: z.literal(true),
  schema_version: z.enum(["loopx_chat_capabilities_v0", "loopx_chat_capabilities_v1"]),
  agent_backend: z.string(),
  sandbox: z.string(),
  approval_policy: z.string(),
  todo_write: z.string(),
  goal_id: z.string().nullable(),
  streaming: z.boolean().optional(),
  resume: z.boolean().optional(),
  interrupt: z.boolean().optional(),
  adapters: z.array(z.object({
    agent_id: z.string(),
    display_name: z.string(),
    adapter_kind: z.string(),
    available: z.boolean(),
    streaming: z.boolean(),
    resume: z.boolean(),
    interrupt: z.boolean(),
  })).optional(),
});

export const todoProposalSchema = z.object({
  kind: z.literal("todo"),
  text: z.string(),
  priority: z.enum(["P0", "P1", "P2"]),
  rationale: z.string(),
});

export const agentResponseSchema = z.object({
  schema_version: z.literal("loopx_chat_agent_response_v0"),
  message: z.string(),
  proposals: z.array(todoProposalSchema),
  gate: z
    .object({
      kind: z.string(),
      summary: z.string(),
      next_action: z.string(),
    })
    .nullable(),
});

export const chatSessionCloseSchema = z.object({
  closed: z.literal(true),
  ok: z.literal(true),
  session_id: z.string().min(1),
});

export const todoPreviewSchema = z.object({
  dry_run: z.literal(true),
  ok: z.literal(true),
  preview_id: z.string().min(1),
  todo: z.object({
    goal_id: z.string().min(1),
    text: z.string(),
    todo_id: z.string().optional(),
  }),
});

export const todoWriteReceiptSchema = z.object({
  schema_version: z.literal("loopx_chat_todo_receipt_v0"),
  receipt_id: z.string().min(1),
  preview_id: z.string().min(1),
  goal_id: z.string().min(1),
  todo_id: z.string().min(1),
  status: z.literal("applied"),
  outcome: z.enum(["todo_added", "todo_already_exists"]),
  already_exists: z.boolean(),
  preview_revision: z.string().nullable(),
});

export const todoApplyResultSchema = z.object({
  applied: z.literal(true),
  ok: z.literal(true),
  receipt: todoWriteReceiptSchema,
  todo: z.object({
    text: z.string(),
    todo_id: z.string(),
  }),
});

export const storedDecisionHistoryItemSchema = z
  .object({
    id: z.string().min(1),
    outcome: z.enum(["approved", "rejected", "cancelled"]),
    projectionVerified: z.boolean().nullable(),
    proposal: todoProposalSchema,
    receipt: todoWriteReceiptSchema.nullable(),
  })
  .superRefine((item, context) => {
    if (item.outcome === "approved" && !item.receipt) {
      context.addIssue({
        code: "custom",
        message: "approved decision history requires a Todo receipt",
        path: ["receipt"],
      });
    }
    if (item.outcome !== "approved" && item.receipt) {
      context.addIssue({
        code: "custom",
        message: "zero-write decision history must not include a Todo receipt",
        path: ["receipt"],
      });
    }
  });

export const storedDecisionHistorySchema = z.object({
  schema_version: z.literal("loopx_chat_decision_history_v0"),
  goal_id: z.string().min(1),
  decisions: z.array(storedDecisionHistoryItemSchema).max(24),
});

export type StoredDecisionHistoryItem = z.infer<typeof storedDecisionHistoryItemSchema>;

export class ChatApiError extends Error {
  payload: Record<string, unknown>;

  constructor(message: string, payload: Record<string, unknown>) {
    super(message);
    this.payload = payload;
  }
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    cache: "no-store",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const payload = (await response.json()) as Record<string, unknown>;
  if (!response.ok) {
    throw new ChatApiError(String(payload.error || `HTTP ${response.status}`), payload);
  }
  return payload as T;
}

export async function fetchChatStatus() {
  return chatStatusSchema.parse(await requestJson<unknown>("/status.json"));
}

export async function fetchChatCapabilities() {
  return chatCapabilitiesSchema.parse(await requestJson<unknown>("/api/chat/capabilities"));
}

export async function createChatSession(
  goalId: string,
  agentId = "codex",
  mode: "resume_latest" | "new" = "resume_latest",
  contextKind: "goal" | "manager" = "goal",
) {
  return requestJson<{
    agent_id: string;
    goal_id: string;
    ok: true;
    resumed: boolean;
    session_id: string;
  }>("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ goal_id: goalId, agent_id: agentId, mode, context_kind: contextKind }),
  });
}

export type ChatStreamEvent = {
  event_id: string;
  sequence: number;
  kind: string;
  created_at: string;
  payload: Record<string, unknown>;
};

export type ChatSessionSnapshot = {
  ok: true;
  schema_version: "loopx_chat_store_v1";
  session: {
    session_id: string;
    goal_id: string;
    agent_id: string;
    adapter_kind: string;
    channel_id?: string;
    status: string;
    active_turn_id: string | null;
    last_error_code: string | null;
    created_at: string;
    updated_at: string;
    last_activity_at: string;
    resumable: boolean;
  };
  messages: Array<{
    message_id: string;
    turn_id: string | null;
    role: string;
    text: string;
    created_at: string;
  }>;
  active_turn: Record<string, unknown> | null;
};

export async function fetchChatSession(sessionId: string) {
  return requestJson<ChatSessionSnapshot>(`/api/chat/sessions/${sessionId}`);
}

export async function acceptChatTurn(sessionId: string, message: string, clientTurnId: string) {
  return requestJson<{
    ok: true;
    session_id: string;
    turn_id: string;
    created: boolean;
    status: string;
    events_url: string;
  }>(`/api/chat/sessions/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({ message, client_turn_id: clientTurnId }),
  });
}

function parseSseBlock(block: string): ChatStreamEvent | null {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    const parsed = JSON.parse(data) as Partial<ChatStreamEvent>;
    if (!parsed.kind || !parsed.payload || typeof parsed.payload !== "object") return null;
    return {
      event_id: String(parsed.event_id ?? ""),
      sequence: Number(parsed.sequence ?? 0),
      kind: String(parsed.kind),
      created_at: String(parsed.created_at ?? ""),
      payload: parsed.payload as Record<string, unknown>,
    };
  } catch {
    return null;
  }
}

export async function streamChatTurn(
  eventsUrl: string,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
) {
  let cursor = "";
  let attempts = 0;
  let terminal = false;
  while (!terminal && attempts < 4) {
    const url = new URL(eventsUrl, window.location.origin);
    if (cursor) url.searchParams.set("after", cursor);
    try {
      const response = await fetch(url, {
        cache: "no-store",
        headers: { Accept: "text/event-stream" },
        signal,
      });
      if (!response.ok || !response.body) {
        throw new ChatApiError(`SSE HTTP ${response.status}`, { status: response.status });
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
        let boundary = buffer.indexOf("\n\n");
        while (boundary >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const event = parseSseBlock(block);
          if (event) {
            if (event.event_id) cursor = event.event_id;
            onEvent(event);
            terminal = ["turn.completed", "turn.interrupted", "turn.failed"].includes(event.kind);
          }
          boundary = buffer.indexOf("\n\n");
        }
        if (done || terminal) break;
      }
      attempts = terminal ? attempts : attempts + 1;
    } catch (error) {
      if (signal?.aborted) throw error;
      attempts += 1;
      if (attempts >= 4) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 250 * 2 ** (attempts - 1)));
    }
  }
  if (!terminal) {
    throw new ChatApiError("Agent 事件流连接已断开。", { reconnect_attempts: attempts });
  }
}

export async function interruptChatTurn(sessionId: string, turnId: string) {
  return requestJson<{ ok: true; session_id: string; turn_id: string; status: string }>(
    `/api/chat/sessions/${sessionId}/turns/${turnId}/interrupt`,
    { method: "POST", body: "{}" },
  );
}

export async function sendChatTurnStreaming(
  sessionId: string,
  message: string,
  options: {
    clientTurnId?: string;
    onDelta?: (text: string) => void;
    onPhase?: (phase: string, turnId: string) => void;
    signal?: AbortSignal;
  } = {},
) {
  const accepted = await acceptChatTurn(
    sessionId,
    message,
    options.clientTurnId ?? crypto.randomUUID(),
  );
  let finalResponse: unknown = null;
  const outcome: { failure: Record<string, unknown> | null } = { failure: null };
  await streamChatTurn(
    accepted.events_url,
    (event) => {
      options.onPhase?.(event.kind, accepted.turn_id);
      if (event.kind === "assistant.delta") {
        options.onDelta?.(String(event.payload.text ?? ""));
      }
      if (event.kind === "turn.completed") {
        finalResponse = event.payload.response;
      }
      if (event.kind === "turn.failed") {
        outcome.failure = event.payload;
      }
    },
    options.signal,
  );
  if (outcome.failure) {
    throw new ChatApiError(
      String(outcome.failure.message || "Agent 回合失败。"),
      outcome.failure,
    );
  }
  return {
    response: agentResponseSchema.parse(finalResponse),
    sessionId,
    turnId: accepted.turn_id,
  };
}

export async function sendChatTurn(sessionId: string, message: string) {
  const payload = await requestJson<{ response: unknown }>(`/api/chat/sessions/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
  return agentResponseSchema.parse(payload.response);
}

export async function closeChatSession(sessionId: string) {
  const result = chatSessionCloseSchema.parse(
    await requestJson<unknown>(`/api/chat/sessions/${sessionId}`, {
      keepalive: true,
      method: "DELETE",
    }),
  );
  if (result.session_id !== sessionId) {
    throw new ChatApiError("Agent 会话关闭回执与本次请求不一致。", {
      session_id: result.session_id,
    });
  }
  return result;
}

export async function previewTodo(goalId: string, text: string) {
  const preview = todoPreviewSchema.parse(
    await requestJson<unknown>("/api/chat/todo/dry-run", {
      method: "POST",
      body: JSON.stringify({ goal_id: goalId, text }),
    }),
  );
  if (!todoPreviewMatchesRequest(preview, { goalId, text })) {
    throw new ChatApiError("Todo 写入预览与本次请求不一致，已停止进入批准状态。", {
      preview,
    });
  }
  return preview;
}

export async function applyTodo(goalId: string, text: string, previewId: string) {
  const result = todoApplyResultSchema.parse(
    await requestJson<TodoApplyResult>("/api/chat/todo/apply", {
      method: "POST",
      body: JSON.stringify({ goal_id: goalId, text, preview_id: previewId }),
    }),
  );
  if (!todoApplyResultMatchesRequest(result, { goalId, previewId, text })) {
    throw new ChatApiError("Todo 写入回执与本次批准不一致，界面已停止更新。", {
      receipt: result.receipt,
      todo: result.todo,
    });
  }
  return result;
}

export function parseCompletedDecisionHistory(raw: string | null, goalId: string) {
  if (!raw) return [];
  try {
    const parsed = storedDecisionHistorySchema.safeParse(JSON.parse(raw));
    if (!parsed.success || parsed.data.goal_id !== goalId) return [];
    return parsed.data.decisions;
  } catch {
    return [];
  }
}

export function serializeCompletedDecisionHistory(
  goalId: string,
  decisions: StoredDecisionHistoryItem[],
) {
  return JSON.stringify(
    storedDecisionHistorySchema.parse({
      schema_version: "loopx_chat_decision_history_v0",
      goal_id: goalId,
      decisions: decisions.slice(0, 24),
    }),
  );
}
