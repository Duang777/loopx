import { useEffect, useMemo, useState } from "react";
import { Bot, Send } from "lucide-react";

import {
  applyTypedAction,
  cancelTypedAction,
  ChatApiError,
  listTypedActions,
  previewTypedAction,
  transitionTypedAction,
  type TypedActionProposal,
} from "../../data/chat";

import { ChannelHeader } from "./channel-header";
import { ChannelTimeline } from "./channel-timeline";
import { ContextDrawer } from "./context-drawer";
import { GoalSidebar } from "./goal-sidebar";
import { GoalTasksView } from "./goal-tasks-view";
import type {
  PersonalWorkspaceCallbacks,
  WorkspaceAgentOption,
  WorkspaceActionPreview,
  WorkspaceActionPreviewRequest,
  WorkspaceChannel,
  WorkspaceDrawerSelection,
  WorkspaceGoalTab,
  WorkspaceModel,
  WorkspaceTimelineItem,
} from "./personal-workspace-model";
import { goalTitleFor } from "./personal-workspace-model";
import { WorkspaceShell } from "./workspace-shell";
import "./personal-workspace.css";

function defaultTimeline(model: WorkspaceModel, selectedGoalId: string | null): WorkspaceTimelineItem[] {
  const items: WorkspaceTimelineItem[] = [];
  if (selectedGoalId === null) {
    model.userTodos.slice(0, 4).forEach((attention) => items.push({
      attention: { ...attention, goalTitle: attention.goalTitle ?? goalTitleFor(model, attention.goalId) },
      id: `attention:${attention.todoId}`,
      kind: "attention",
    }));
    model.goals.filter((goal) => goal.state === "推进中").slice(0, 4).forEach((goal) => items.push({
      id: `run:${goal.goalId}`,
      kind: "run",
      run: {
        agentId: goal.agentId,
        agentLabel: goal.agentLabel ?? goal.agentId,
        completedSteps: goal.agentTodos.filter((todo) => todo.done).length,
        goalId: goal.goalId,
        goalTitle: goal.title,
        latestActivity: goal.agentSentence,
        runId: `goal:${goal.goalId}`,
        status: "running",
        title: goal.nextSentence,
        totalSteps: goal.agentTodos.length || 1,
      },
    }));
    return items;
  }
  const goal = model.goals.find((candidate) => candidate.goalId === selectedGoalId);
  if (!goal) return items;
  if (goal.needsYou) {
    items.push({
      attention: {
        blocking: goal.needsYouBlocking ?? false,
        goalId: goal.goalId,
        goalTitle: goal.title,
        text: goal.needsYou,
        todoId: `${goal.goalId}:attention`,
      },
      id: `attention:${goal.goalId}`,
      kind: "attention",
    });
  }
  items.push({
    id: `run:${goal.goalId}`,
    kind: "run",
    run: {
      agentId: goal.agentId,
      agentLabel: goal.agentLabel ?? goal.agentId,
      completedSteps: goal.agentTodos.filter((todo) => todo.done).length,
      goalId: goal.goalId,
      goalTitle: goal.title,
      latestActivity: goal.agentSentence,
      runId: `goal:${goal.goalId}`,
      status: goal.state === "推进中" ? "running" : goal.state === "需修复" ? "failed" : "waiting",
      title: goal.nextSentence,
      totalSteps: goal.agentTodos.length || 1,
    },
  });
  const activeRun = model.timeline?.find((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> =>
    item.kind === "run" && item.run.goalId === goal.goalId && Boolean(item.run.sessionId));
  goal.agentTodos.filter((todo) => todo.taskClass === "continuous_monitor").forEach((todo) => items.push({
    id: `schedule:${goal.goalId}:${todo.todoId}`,
    kind: "schedule",
    schedule: {
      agentId: goal.agentId,
      executionHistory: activeRun ? [{
        label: activeRun.run.latestActivity || activeRun.run.title,
        runId: activeRun.run.runId,
        status: activeRun.run.status === "waiting" || activeRun.run.status === "queued" ? "running" : activeRun.run.status,
        timestamp: goal.latestActivity || "最近活动",
      }] : [],
      goalId: goal.goalId,
      label: todo.text,
      schedule: todo.evidence ?? "由 LoopX continuous_monitor Todo 驱动",
      scheduleId: todo.todoId,
      scheduleKind: "monitor",
      sessionId: activeRun?.run.sessionId,
      status: todo.done || todo.status === "paused" ? "paused" : "active",
      stopCondition: "Goal 完成或 owner 停止",
      target: todo.text,
      timezone: "Asia/Shanghai",
    },
  }));
  const heartbeatProposal = model.timeline?.find((item): item is Extract<WorkspaceTimelineItem, { kind: "proposal" }> =>
    item.kind === "proposal" && item.proposal.actionKind === "heartbeat.bind" && item.proposal.goalId === goal.goalId);
  if (heartbeatProposal) {
    const field = (label: string) => heartbeatProposal.proposal.fields.find((item) => item.label === label)?.value;
    items.push({
      id: `schedule:${goal.goalId}:heartbeat`,
      kind: "schedule",
      schedule: {
        agentId: goal.agentId,
        executionHistory: [],
        goalId: goal.goalId,
        label: `推进 ${goal.title}`,
        nextRunAt: "等待宿主调度确认",
        notificationRule: field("notification policy") ?? "仅在需要你时通知",
        schedule: field("cadence") ?? "由 heartbeat-prompt 生命周期驱动",
        scheduleId: `${goal.goalId}:heartbeat`,
        scheduleKind: "heartbeat",
        status: heartbeatProposal.proposal.status === "applied" ? "active" : "draft",
        stopCondition: field("stop condition") ?? "Goal 完成或 owner 停止",
        timezone: field("timezone") ?? "Asia/Shanghai",
      },
    });
  }
  return items;
}

function proposalStatus(status: TypedActionProposal["status"]): WorkspaceActionPreview["status"] {
  if (status === "preview_ready") return "ready";
  if (status === "cancelled") return "draft";
  if (status === "failed") return "error";
  return status;
}

function proposalFields(parameters: Record<string, unknown>) {
  return Object.entries(parameters).slice(0, 8).map(([label, value]) => ({
    label: label.replaceAll("_", " "),
    value: Array.isArray(value) ? value.join(" · ") : typeof value === "object" && value !== null
      ? JSON.stringify(value)
      : String(value ?? "—"),
  }));
}

function workspaceProposal(proposal: TypedActionProposal): WorkspaceActionPreview {
  return {
    actionKind: proposal.action_kind,
    fields: proposalFields(proposal.normalized_parameters),
    goalId: typeof proposal.normalized_parameters.goal_id === "string" ? proposal.normalized_parameters.goal_id : undefined,
    impact: proposal.permission_classification === "protected"
      ? "该操作需要通过受保护的 LoopX 写入服务完成。"
      : "确认后会调用规范 LoopX 服务写入状态。",
    previewId: proposal.proposal_id,
    gate: proposal.gate ? {
      kind: String(proposal.gate.kind ?? "protected_action"),
      nextAction: typeof proposal.gate.next_action === "string" ? proposal.gate.next_action : undefined,
      summary: String(proposal.gate.summary ?? "需要宿主确认"),
    } : undefined,
    primaryLabel: proposal.action_kind === "goal.create" ? "创建并启动" : "确认并应用",
    status: proposalStatus(proposal.status),
    title: proposal.summary,
  };
}

function compactGoalSlug(value: string) {
  const ascii = value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 42);
  return ascii || `goal-${Date.now().toString(36)}`;
}

function goalTitleFromMessage(message: string) {
  const quoted = message.match(/[「“"]([^」”"]{2,80})[」”"]/u)?.[1];
  if (quoted) return quoted.trim();
  return message
    .replace(/^(请|帮我|我想|给我|创建|新建|设置)+/u, "")
    .replace(/(一个|新的)?\s*(goal|目标)/giu, "")
    .replace(/[，。！？].*$/u, "")
    .trim()
    .slice(0, 80) || "新的个人 Goal";
}

function cadenceFromMessage(message: string) {
  const minutes = message.match(/每\s*(\d{1,3})\s*分钟/u)?.[1];
  if (minutes) return `${minutes}m`;
  const hours = message.match(/每\s*(\d{1,2})\s*小时/u)?.[1];
  if (hours) return `${hours}h`;
  if (/每小时/u.test(message)) return "1h";
  if (/每天|每日|早上|上午/u.test(message)) return "1d";
  return "1d";
}

function stopConditionFromMessage(message: string) {
  if (/(mr|pr).{0,8}(合并|merge)/iu.test(message)) return "pr_merged";
  if (/发布完成|上线完成/u.test(message)) return "release_complete";
  return "goal_complete";
}

function mentionedAgent(message: string, agents: WorkspaceAgentOption[]) {
  const normalized = message.toLowerCase();
  return agents.find((agent) =>
    normalized.includes(agent.agentId.toLowerCase()) || normalized.includes(agent.label.toLowerCase()));
}

function todoTextFromMessage(message: string) {
  const quoted = message.match(/[「“"]([^」”"]{2,200})[」”"]/u)?.[1];
  if (quoted) return quoted.trim();
  return message
    .replace(/^(请|帮我|给我|新增|新建|创建|添加|加上|加一个|记一个)+/u, "")
    .replace(/\s*(todo|待办|任务)\s*/giu, " ")
    .replace(/[，,]\s*(并且|然后|再)?\s*(交给|分配给|让).+$/u, "")
    .replace(/\s*(交给|分配给|让)\s+.+$/u, "")
    .trim()
    .slice(0, 400) || "推进当前 Goal 的下一项工作";
}

export function PersonalWorkspacePage({
  agents = [{ agentId: "codex", available: true, capability: "代码与项目执行", label: "Codex" }],
  callbacks = {},
  model,
  ownerLabel,
  selectedAgentId: controlledAgentId,
  selectedGoalId: controlledGoalId,
}: {
  agents?: WorkspaceAgentOption[];
  callbacks?: PersonalWorkspaceCallbacks;
  model: WorkspaceModel;
  ownerLabel?: string;
  selectedAgentId?: string;
  selectedGoalId?: string | null;
}) {
  const [localGoalId, setLocalGoalId] = useState<string | null>(controlledGoalId ?? null);
  const [localAgentId, setLocalAgentId] = useState(controlledAgentId ?? agents.find((agent) => agent.available)?.agentId ?? "codex");
  const [selection, setSelection] = useState<WorkspaceDrawerSelection | null>(null);
  const [proposals, setProposals] = useState<Record<string, WorkspaceActionPreview>>({});
  const [selectedChannel, setSelectedChannel] = useState<WorkspaceChannel>("manager");
  const [selectedGoalTab, setSelectedGoalTab] = useState<WorkspaceGoalTab>("chat");
  const [composer, setComposer] = useState("");
  const [sending, setSending] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [pwTheme, setPwTheme] = useState<"brutal" | "paper">(() => {
    try {
      return window.localStorage.getItem("loopx-personal-workspace-theme") === "brutal" ? "brutal" : "paper";
    } catch {
      return "paper";
    }
  });
  function togglePwTheme() {
    setPwTheme((current) => {
      const next = current === "brutal" ? "paper" : "brutal";
      try {
        window.localStorage.setItem("loopx-personal-workspace-theme", next);
      } catch {
        // Private-mode storage failures should not block the visual toggle.
      }
      return next;
    });
  }
  const selectedGoalId = controlledGoalId === undefined ? localGoalId : controlledGoalId;
  const selectedAgentId = controlledAgentId ?? localAgentId;
  const selectedGoal = model.goals.find((goal) => goal.goalId === selectedGoalId) ?? null;
  const managerProjectionId = selectedGoalId ?? (selectedChannel === "manager" ? null : "__manager_channel__");
  const items = useMemo(() => {
    const heartbeatSchedules: WorkspaceTimelineItem[] = Object.values(proposals)
      .filter((proposal) => proposal.actionKind === "heartbeat.bind" && proposal.goalId)
      .map((proposal) => ({
        id: `schedule:${proposal.goalId}:heartbeat`,
        kind: "schedule" as const,
        schedule: {
          agentId: selectedAgentId,
          executionHistory: [],
          goalId: proposal.goalId!,
          label: proposal.title,
          nextRunAt: proposal.status === "applied" ? "等待下次宿主唤醒" : "等待宿主确认",
          notificationRule: "仅在需要你时通知",
          schedule: proposal.fields.find((field) => field.label === "cadence")?.value ?? "由 heartbeat-prompt 生命周期驱动",
          scheduleId: `${proposal.goalId}:heartbeat`,
          scheduleKind: "heartbeat" as const,
          status: proposal.status === "applied" ? "active" as const : "draft" as const,
          stopCondition: proposal.fields.find((field) => field.label === "stop condition")?.value ?? "Goal 完成或 owner 停止",
          timezone: proposal.fields.find((field) => field.label === "timezone")?.value ?? "Asia/Shanghai",
        },
      }));
    const merged: WorkspaceTimelineItem[] = [
      ...defaultTimeline(model, managerProjectionId === "__manager_channel__" ? null : managerProjectionId),
      ...(model.timeline ?? []),
      ...heartbeatSchedules,
      ...Object.values(proposals).map((proposal) => ({ id: `proposal:${proposal.previewId}`, kind: "proposal" as const, proposal })),
    ];
    const projected = [...new Map(merged.map((item) => [item.id, item])).values()];
    return projected.filter((item) => {
      if (!selectedGoalId) return true;
      if (item.kind === "message") return true;
      if (item.kind === "proposal") return !item.proposal.goalId || item.proposal.goalId === selectedGoalId;
      if (item.kind === "attention") return item.attention.goalId === selectedGoalId;
      if (item.kind === "run") return item.run.goalId === selectedGoalId;
      if (item.kind === "schedule") return item.schedule.goalId === selectedGoalId;
      return item.output.goalId === selectedGoalId;
    }).filter((item) => {
      if (selectedGoalId || selectedChannel === "manager") return true;
      if (selectedChannel === "attention") return item.kind === "attention";
      if (selectedChannel === "running") return item.kind === "run";
      return item.kind === "output";
    });
  }, [managerProjectionId, model, proposals, selectedAgentId, selectedChannel, selectedGoalId]);
  const drawerSelection = useMemo<WorkspaceDrawerSelection | null>(() => {
    if (selection?.kind !== "run") return selection;
    const currentRun = items.find((item): item is Extract<WorkspaceTimelineItem, { kind: "run" }> =>
      item.kind === "run" && item.run.runId === selection.item.runId
    );
    return currentRun ? { item: currentRun.run, kind: "run" } : selection;
  }, [items, selection]);

  useEffect(() => {
    if (!mobileSidebarOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMobileSidebarOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mobileSidebarOpen]);

  useEffect(() => {
    let cancelled = false;
    void listTypedActions(selectedGoalId ? { goalId: selectedGoalId } : { contextKind: "manager" })
      .then((stored) => {
        if (cancelled) return;
        const restored = Object.fromEntries(stored
          .filter((proposal) => proposal.status !== "cancelled")
          .map((proposal) => {
            const projected = workspaceProposal(proposal);
            return [projected.previewId, projected];
          }));
        setProposals((current) => ({ ...current, ...restored }));
      })
      .catch(() => {
        // The workspace remains usable when the optional local proposal store is unavailable.
      });
    return () => { cancelled = true; };
  }, [selectedGoalId]);

  async function createPreview(request: WorkspaceActionPreviewRequest) {
    let local: WorkspaceActionPreview;
    try {
      local = callbacks.onPreviewAction
        ? await callbacks.onPreviewAction(request)
        : workspaceProposal(await previewTypedAction(request));
    } catch (error) {
      if (!(error instanceof ChatApiError) || error.payload.error_code !== "action_preview_gate") throw error;
      const rawGate = error.payload.gate && typeof error.payload.gate === "object"
        ? error.payload.gate as Record<string, unknown>
        : {};
      const rawCandidates = Array.isArray(rawGate.candidates) ? rawGate.candidates : [];
      const workspaceCandidates = rawCandidates.flatMap((candidate) => {
        if (!candidate || typeof candidate !== "object") return [];
        const item = candidate as Record<string, unknown>;
        return typeof item.workspace_ref === "string" && typeof item.label === "string"
          ? [{ label: item.label, workspaceRef: item.workspace_ref }]
          : [];
      });
      const gateKind = String(rawGate.kind ?? "workspace_selection_required");
      const requiresAgentBinding = gateKind === "agent_binding_required"
        || gateKind === "agent_identity_selection_required";
      local = {
        actionKind: request.actionKind,
        fields: workspaceCandidates.map((candidate) => ({ label: candidate.label, value: candidate.workspaceRef })),
        gate: {
          kind: gateKind,
          nextAction: typeof rawGate.next_action === "string" ? rawGate.next_action : undefined,
          summary: String(rawGate.summary ?? "请选择 Goal 所属工作区。"),
        },
        impact: requiresAgentBinding
          ? "先完成 Agent 身份绑定，再重新生成原操作预览；当前没有写入 Goal。"
          : "选择工作区后会重新生成结构化预览，选择本身不会写入状态。",
        previewId: `workspace-choice-${Date.now().toString(36)}`,
        sourceRequest: request,
        status: "gated",
        title: requiresAgentBinding ? "先绑定 Agent" : "选择 Goal 工作区",
        workspaceCandidates,
      };
    }
    setProposals((current) => ({ ...current, [local.previewId]: local }));
    setSelection({ item: local, kind: "proposal" });
    return local;
  }

  async function requestGoalCreate() {
    const delegated = await callbacks.onRequestGoalCreate?.();
    if (delegated) {
      setProposals((current) => ({ ...current, [delegated.previewId]: delegated }));
      setSelection({ item: delegated, kind: "proposal" });
      return;
    }
    const timestamp = Date.now().toString(36);
    await createPreview({
      actionKind: "goal.create",
      context: { kind: "manager", goal_id: null },
      idempotencyKey: `workspace-goal-${timestamp}`,
      normalizedParameters: {
        agent_id: selectedAgentId,
        goal_id: `new-goal-${timestamp}`,
        heartbeat: { cadence: "daily", enabled: false, timezone: "Asia/Shanghai" },
        initial_todos: ["确认目标边界与完成条件", "推进首个可验证结果", "汇总证据并确认完成"],
        objective: "定义并推进一个新的个人 Goal",
        permission: "workspace_write_on_confirmation",
        stop_condition: "goal_complete_or_owner_pause",
        title: "新的个人 Goal",
        workspace_ref: model.goals[0]?.goalId ?? "current",
      },
      summary: "创建并绑定一个新的个人 Goal",
    });
  }

  async function requestSchedule(kind: "heartbeat" | "monitor", goalId: string | null, intent = "") {
    const delegated = await callbacks.onRequestScheduleConfig?.(kind, goalId);
    if (delegated) {
      setProposals((current) => ({ ...current, [delegated.previewId]: delegated }));
      setSelection({ item: delegated, kind: "proposal" });
      return;
    }
    if (!goalId) {
      setComposer(kind === "heartbeat" ? "为哪个 Goal 设置 Heartbeat？" : "为哪个 Goal 添加定时检查？");
      return;
    }
    const timestamp = Date.now().toString(36);
    await createPreview({
      actionKind: kind === "heartbeat" ? "heartbeat.bind" : "monitor.create",
      context: { kind: "schedule", goal_id: goalId },
      idempotencyKey: `workspace-${kind}-${goalId}-${timestamp}`,
      normalizedParameters: kind === "heartbeat" ? {
        agent_id: selectedAgentId,
        cadence: cadenceFromMessage(intent),
        goal_id: goalId,
        stop_condition: stopConditionFromMessage(intent),
        timezone: "Asia/Shanghai",
      } : {
        agent_id: selectedAgentId,
        cadence: cadenceFromMessage(intent),
        goal_id: goalId,
        stop_condition: stopConditionFromMessage(intent),
        target: "检查当前 Goal 的阻塞、进度与新产出",
        target_key: `goal-${goalId}`,
        timezone: "Asia/Shanghai",
      },
      summary: kind === "heartbeat" ? "为当前 Goal 设置每日 Heartbeat" : "为当前 Goal 创建每日定时检查",
    });
  }

  const drawerCallbacks: PersonalWorkspaceCallbacks = {
    ...callbacks,
    onOpenOutput: (output) => {
      if (output.goalId !== selectedGoalId) selectGoal(output.goalId);
      setSelectedGoalTab("files");
      callbacks.onOpenOutput?.(output);
    },
    onApplyProposal: async (proposal) => {
      setProposals((current) => ({ ...current, [proposal.previewId]: { ...proposal, status: "applying" } }));
      setSelection({ item: { ...proposal, status: "applying" }, kind: "proposal" });
      try {
        if (callbacks.onApplyProposal) {
          await callbacks.onApplyProposal(proposal);
          const applied = { ...proposal, status: "applied" as const };
          setProposals((current) => ({ ...current, [proposal.previewId]: applied }));
          setSelection({ item: applied, kind: "proposal" });
          return;
        }
        const result = await applyTypedAction(proposal.previewId);
        const applied = workspaceProposal(result.proposal);
        setProposals((current) => ({ ...current, [proposal.previewId]: applied }));
        setSelection({ item: applied, kind: "proposal" });
        if (applied.actionKind === "goal.create" && applied.goalId) {
          callbacks.onRefresh?.();
          selectGoal(applied.goalId);
        }
      } catch (error) {
        if (error instanceof ChatApiError && error.payload.error_code === "protected_action") {
          const rawGate = error.payload.gate;
          const gate = rawGate && typeof rawGate === "object" ? rawGate as Record<string, unknown> : {};
          const gated = {
            ...proposal,
            gate: {
              kind: String(gate.kind ?? "protected_action"),
              nextAction: typeof gate.next_action === "string" ? gate.next_action : undefined,
              summary: String(gate.summary ?? error.message),
            },
            status: "gated" as const,
          };
          setProposals((current) => ({ ...current, [proposal.previewId]: gated }));
          setSelection({ item: gated, kind: "proposal" });
          if (proposal.actionKind === "goal.create" && proposal.goalId) {
            callbacks.onRefresh?.();
            selectGoal(proposal.goalId);
          }
          return;
        }
        const stale = error instanceof Error && /stale|状态.*变化|conflict/i.test(error.message);
        const failed = { ...proposal, status: (stale ? "stale" : "error") as "stale" | "error" };
        setProposals((current) => ({ ...current, [proposal.previewId]: failed }));
        setSelection({ item: failed, kind: "proposal" });
      }
    },
    onCancelProposal: async (proposal) => {
      callbacks.onCancelProposal?.(proposal);
      if (!callbacks.onCancelProposal) await cancelTypedAction(proposal.previewId);
      setProposals((current) => {
        const next = { ...current };
        delete next[proposal.previewId];
        return next;
      });
      setSelection(null);
    },
    onTransitionProposal: async (proposal, transition) => {
      const transitioned = workspaceProposal(await transitionTypedAction(proposal.previewId, transition));
      setProposals((current) => {
        const next = { ...current };
        if (transition === "regenerate") delete next[proposal.previewId];
        next[transitioned.previewId] = transitioned;
        return next;
      });
      setSelection({ item: transitioned, kind: "proposal" });
    },
    onSelectWorkspaceCandidate: async (proposal, workspaceRef) => {
      if (!proposal.sourceRequest) return;
      setProposals((current) => {
        const next = { ...current };
        delete next[proposal.previewId];
        return next;
      });
      await createPreview({
        ...proposal.sourceRequest,
        idempotencyKey: `${proposal.sourceRequest.idempotencyKey}-${workspaceRef}`,
        normalizedParameters: { ...proposal.sourceRequest.normalizedParameters, workspace_ref: workspaceRef },
      });
    },
    onPreviewAction: createPreview,
    onRequestScheduleConfig: (kind, goalId) => void requestSchedule(kind, goalId),
    onUpdateSchedule: async (schedule, operation) => {
      const timestamp = Date.now().toString(36);
      const heartbeat = schedule.scheduleKind === "heartbeat";
      await createPreview({
        actionKind: heartbeat ? "heartbeat.bind" : "monitor.update",
        context: { kind: "schedule", goal_id: schedule.goalId },
        idempotencyKey: `workspace-monitor-${schedule.scheduleId}-${operation}-${timestamp}`,
        normalizedParameters: {
          agent_id: schedule.agentId ?? selectedAgentId,
          ...(operation === "edit" ? { cadence: "2h", ...(heartbeat ? { timezone: schedule.timezone ?? "Asia/Shanghai" } : {}) } : {}),
          goal_id: schedule.goalId,
          operation,
          ...(!heartbeat && operation === "run_now" && schedule.sessionId ? { session_id: schedule.sessionId } : {}),
          ...(!heartbeat ? { todo_id: schedule.scheduleId } : {}),
        },
        summary: operation === "pause" ? `暂停自动运行：${schedule.label}`
          : operation === "resume" ? `恢复自动运行：${schedule.label}`
            : operation === "run_now" ? `立即运行：${schedule.label}`
              : operation === "stop" ? `停止自动运行：${schedule.label}`
                : `编辑自动运行生命周期：${schedule.label}`,
      });
    },
  };

  function selectGoal(goalId: string | null) {
    setLocalGoalId(goalId);
    if (goalId === null) setSelectedChannel("manager");
    setSelection(null);
    setSelectedGoalTab("chat");
    setMobileSidebarOpen(false);
    callbacks.onSelectGoal?.(goalId);
  }

  function selectChannel(channel: WorkspaceChannel) {
    setLocalGoalId(null);
    setSelectedChannel(channel);
    setSelection(null);
    setMobileSidebarOpen(false);
    callbacks.onSelectGoal?.(null);
    callbacks.onSelectChannel?.(channel);
  }

  function selectAgent(agentId: string) {
    setLocalAgentId(agentId);
    callbacks.onSelectAgent?.(agentId);
  }

  async function sendMessage() {
    const message = composer.trim();
    if (!message || sending) return;
    setComposer("");
    setSending(true);
    try {
      if (!selectedGoalId && /(创建|新建|设置).{0,8}(goal|目标)/iu.test(message)) {
        const title = goalTitleFromMessage(message);
        const goalId = compactGoalSlug(title);
        await createPreview({
          actionKind: "goal.create",
          context: { kind: "manager", goal_id: null, natural_language: message },
          idempotencyKey: `workspace-goal-intent-${goalId}-${Date.now().toString(36)}`,
          normalizedParameters: {
            agent_id: selectedAgentId,
            goal_id: goalId,
            heartbeat: {
              cadence: cadenceFromMessage(message),
              enabled: /(heartbeat|心跳|每天推进|持续推进)/iu.test(message),
              timezone: "Asia/Shanghai",
            },
            initial_todos: ["确认目标边界与完成条件", "推进首个可验证结果", "汇总证据并确认完成"],
            objective: message,
            permission: /只读|read.?only/iu.test(message) ? "read_only" : "workspace_write_on_confirmation",
            stop_condition: stopConditionFromMessage(message),
            title,
            workspace_ref: model.goals[0]?.goalId ?? "current",
          },
          summary: `创建 Goal：${title}`,
        });
        return;
      }
      if (selectedGoalId && /(heartbeat|心跳|每天推进|持续推进)/iu.test(message)) {
        await requestSchedule("heartbeat", selectedGoalId, message);
        return;
      }
      if (selectedGoalId && /(定时|监控|监测|每.{0,8}(分钟|小时|天)|持续观察)/u.test(message)) {
        await requestSchedule("monitor", selectedGoalId, message);
        return;
      }
      const requestedAgent = mentionedAgent(message, agents);
      if (selectedGoalId && requestedAgent && /((让|交给).{0,20}(管理|负责|接管).{0,8}(goal|目标)|(绑定).{0,12}(goal|目标)|(goal|目标).{0,12}(交给|绑定|负责|接管))/iu.test(message)) {
        await createPreview({
          actionKind: "agent.bind",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-agent-bind-${selectedGoalId}-${requestedAgent.agentId}-${Date.now().toString(36)}`,
          normalizedParameters: { agent_id: requestedAgent.agentId, goal_id: selectedGoalId },
          summary: `将 ${requestedAgent.label} 绑定到 ${selectedGoal?.title ?? selectedGoalId}`,
        });
        return;
      }
      if (selectedGoalId && /(创建|新建|新增|添加|加一个|记一个).{0,16}(todo|待办|任务)|(todo|待办|任务).{0,12}(创建|新建|新增|添加)/iu.test(message)) {
        await createPreview({
          actionKind: "todo.create",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-todo-create-${selectedGoalId}-${Date.now().toString(36)}`,
          normalizedParameters: {
            ...(requestedAgent ? { endpoint_id: requestedAgent.agentId } : {}),
            goal_id: selectedGoalId,
            text: todoTextFromMessage(message),
          },
          summary: `创建 Todo：${todoTextFromMessage(message)}`,
        });
        return;
      }
      const matchedTodo = selectedGoal?.agentTodos.find((todo) =>
        message.includes(todo.todoId) || message.includes(todo.text));
      const todoOperation = /完成|做完|关闭/u.test(message) ? "complete"
        : /阻塞|卡住/u.test(message) ? "block"
          : /暂缓|稍后|推迟/u.test(message) ? "defer"
            : requestedAgent && /交给|分配给|改派/u.test(message) ? "reassign"
              : null;
      if (selectedGoalId && matchedTodo && todoOperation) {
        await createPreview({
          actionKind: "todo.update",
          context: { kind: "todo", goal_id: selectedGoalId, todo_id: matchedTodo.todoId, natural_language: message },
          idempotencyKey: `workspace-todo-update-${matchedTodo.todoId}-${todoOperation}-${Date.now().toString(36)}`,
          normalizedParameters: {
            ...(todoOperation === "reassign" && requestedAgent ? { endpoint_id: requestedAgent.agentId } : {}),
            ...(todoOperation === "block" ? { note: message } : {}),
            ...(todoOperation === "defer" ? { resume_when: "owner_resume" } : {}),
            goal_id: selectedGoalId,
            operation: todoOperation,
            todo_id: matchedTodo.todoId,
          },
          summary: `更新 Todo：${matchedTodo.text}`,
        });
        return;
      }
      if (selectedGoalId && /(请|现在|开始|批准|执行).{0,8}(发布|上线|合并|部署|删除|付款)/u.test(message)) {
        await createPreview({
          actionKind: "goal.update",
          context: { kind: "goal", goal_id: selectedGoalId, natural_language: message },
          idempotencyKey: `workspace-protected-${selectedGoalId}-${Date.now().toString(36)}`,
          normalizedParameters: { goal_id: selectedGoalId, status: "operator_gate_requested" },
          summary: `请求受保护操作：${message.slice(0, 160)}`,
        });
        return;
      }
      await callbacks.onSendMessage?.(message, selectedAgentId, selectedGoalId);
    } catch (error) {
      setComposer(message);
      throw error;
    } finally {
      setSending(false);
    }
  }

  return (
    <WorkspaceShell
      drawer={drawerSelection ? <ContextDrawer agents={agents} callbacks={drawerCallbacks} onClose={() => setSelection(null)} selection={drawerSelection} /> : null}
      drawerOpen={drawerSelection !== null}
      mobileSidebarOpen={mobileSidebarOpen}
      onCloseMobileSidebar={() => setMobileSidebarOpen(false)}
      theme={pwTheme}
      main={(
        <div className="personal-channel">
          <ChannelHeader
            agents={agents}
            mobileNavigationOpen={mobileSidebarOpen}
            onRefresh={callbacks.onRefresh}
            onOpenNavigation={() => setMobileSidebarOpen(true)}
            onSelectAgent={selectAgent}
            onSelectGoalTab={setSelectedGoalTab}
            selectedAgentId={selectedAgentId}
            selectedGoal={selectedGoal}
            selectedGoalTab={selectedGoalTab}
          />
          <div className="personal-channel-scroll">
            {!selectedGoal ? (
              <section className="personal-manager-greeting">
                <span><Bot size={20} /></span>
                <div><strong>你好，我是 LoopX 管家</strong><p>你有 {model.openUserTodoCount} 项需要处理，其中 {model.blockingTodoCount} 项正在阻塞 Agent。</p></div>
              </section>
            ) : null}
            {selectedGoal && selectedGoalTab === "tasks" ? (
              <GoalTasksView goal={selectedGoal} items={items} onQuickComplete={(todo) => void createPreview({
                actionKind: "todo.update",
                context: { goal_id: todo.goalId, kind: "todo", todo_id: todo.todoId },
                idempotencyKey: `workspace-todo-${todo.todoId}-complete-${Date.now().toString(36)}`,
                normalizedParameters: { goal_id: todo.goalId, operation: "complete", todo_id: todo.todoId },
                summary: `标记完成：${todo.text}`,
              })} onSelect={setSelection} userTodos={model.userTodos} />
            ) : selectedGoal && selectedGoalTab === "files" ? (
              <section className="personal-object-list"><header><strong>Files & Outputs</strong><span>{items.filter((item) => item.kind === "output").length}</span></header>{items.filter((item): item is Extract<WorkspaceTimelineItem, { kind: "output" }> => item.kind === "output").map((item) => <button key={item.id} onClick={() => setSelection({ item: item.output, kind: "output" })} type="button"><span>↗</span><strong>{item.output.title}</strong><small>{item.output.createdAt ?? "最近产出"}</small></button>)}</section>
            ) : <ChannelTimeline items={items} onSelect={setSelection} selectedGoal={selectedGoal} />}
          </div>
          <div className="personal-composer-wrap">
            <div className="personal-quick-prompts">
              <button onClick={() => setComposer("我现在该做什么？")} type="button">我现在该做什么？</button>
              <button onClick={() => setComposer("总结今天的进展")} type="button">总结今天进展</button>
              <button onClick={() => void requestSchedule("monitor", selectedGoalId)} type="button">创建定时检查</button>
            </div>
            <div className="personal-channel-composer">
              <span><Bot size={17} />{agents.find((agent) => agent.agentId === selectedAgentId)?.label ?? selectedAgentId}</span>
              <textarea
                aria-label="向 LoopX 发送消息"
                onChange={(event) => setComposer(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void sendMessage();
                  }
                }}
                placeholder={selectedGoal ? `询问或纠偏 ${selectedGoal.title}…` : "问问 LoopX 管家，或描述一个新 Goal…"}
                rows={1}
                value={composer}
              />
              <button aria-label="发送" disabled={!composer.trim() || sending} onClick={() => void sendMessage()} type="button"><Send size={18} /></button>
            </div>
          </div>
        </div>
      )}
      sidebar={(
        <GoalSidebar
          activeRunCount={model.goals.filter((goal) => goal.state === "推进中").length}
          attentionCount={model.openUserTodoCount}
          goals={model.goals}
          onRequestGoalCreate={() => void requestGoalCreate()}
          onOpenSettings={() => {
            const agent = agents.find((candidate) => candidate.agentId === selectedAgentId) ?? agents[0];
            if (agent) setSelection({ item: agent, kind: "agent" });
          }}
          onSelectChannel={selectChannel}
          onSelectGoal={selectGoal}
          onToggleTheme={togglePwTheme}
          ownerLabel={ownerLabel}
          recentOutputCount={(model.timeline ?? []).filter((item) => item.kind === "output").length}
          selectedChannel={selectedChannel}
          selectedGoalId={selectedGoalId}
          theme={pwTheme}
        />
      )}
    />
  );
}
