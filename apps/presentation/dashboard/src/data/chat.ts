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
  schema_version: z.literal("loopx_chat_capabilities_v0"),
  agent_backend: z.string(),
  sandbox: z.string(),
  approval_policy: z.string(),
  todo_write: z.string(),
  goal_id: z.string().nullable(),
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

export async function createChatSession(goalId: string) {
  return requestJson<{ goal_id: string; ok: true; session_id: string }>("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ goal_id: goalId }),
  });
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
