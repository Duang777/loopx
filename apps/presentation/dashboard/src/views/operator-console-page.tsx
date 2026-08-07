import {
  Activity,
  ArrowRight,
  Bot,
  Braces,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  Command,
  Gauge,
  History,
  KeyRound,
  Layers3,
  ListChecks,
  LockKeyhole,
  RefreshCw,
  RotateCcw,
  Settings2,
  Shield,
  ShieldAlert,
  Sparkles,
  UserRound,
  Zap,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  type Capability,
  type ConfigurationPatch,
  type ConfigurationPlan,
  type QuotaMutationPlan,
  type TodoCompletionPlan,
  type TurnPlan,
  type TurnPlanRequest,
  OperatorApiError,
  operatorConsoleApi,
  resetOperatorControlSession,
} from "../api/operator-console";
import {
  ActionGate,
  ConsoleBadge,
  ConsolePanel,
  ErrorNotice,
  Field,
  Freshness,
  Metric,
  SuccessNotice,
  type ConsoleTone,
} from "../components/operator-console/operator-console-ui";
import { operatorRoute } from "../router";

type ActionTab = "configuration" | "todo" | "quota" | "turn";
type LeaseAction = "acquire" | "renew" | "release";

const visiblePollMs = 3_000;
const hiddenPollMs = 30_000;

function useDocumentVisibility() {
  const [hidden, setHidden] = useState(() => document.hidden);
  useEffect(() => {
    const update = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return hidden;
}

function compact(value: unknown) {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function dateTime(value: string | null | undefined) {
  if (!value) {
    return "Not recorded";
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function statusTone(value: string | null | undefined): ConsoleTone {
  const normalized = (value ?? "").toLowerCase();
  if (/ready|eligible|active|complete|success|clear|operator/.test(normalized)) {
    return "positive";
  }
  if (/blocked|error|failed|denied|conflict|throttle/.test(normalized)) {
    return "danger";
  }
  if (/wait|warning|attention|stale|viewer/.test(normalized)) {
    return "warning";
  }
  return "neutral";
}

function capabilityReason(capability: Capability | undefined) {
  return capability?.unavailable_reason?.message ?? null;
}

function retryQuery(count: number, error: unknown) {
  if (error instanceof OperatorApiError && error.status < 500) {
    return false;
  }
  return count < 1;
}

function defaultConfigurationPatch(quotaCompute: number, quotaWindowHours: number): ConfigurationPatch {
  return {
    clear_allowed_domains: false,
    clear_boundary_authority: false,
    clear_explore_harness_profile: false,
    clear_issue_fix_reviewer_notification_config: false,
    clear_lark_event_inbox_config: false,
    clear_registered_agents: false,
    clear_reward_memory_config: false,
    clear_supervisor: false,
    clear_waiting_on: false,
    clear_write_scope: false,
    quota_compute: quotaCompute,
    quota_window_hours: quotaWindowHours,
    replace_write_scope: false,
  };
}

function PlanHash({ value }: { value: string }) {
  return <code className="operator-plan-hash">{value}</code>;
}

export function OperatorConsolePage() {
  const hidden = useDocumentVisibility();
  const pollInterval = hidden ? hiddenPollMs : visiblePollMs;
  const queryClient = useQueryClient();
  const search = operatorRoute.useSearch();
  const navigate = operatorRoute.useNavigate();
  const [now, setNow] = useState(Date.now());
  const [actor, setActor] = useState(() => sessionStorage.getItem("loopx.operator.actor") ?? "local-operator");
  const [actionTab, setActionTab] = useState<ActionTab>("configuration");
  const [selectedTodoId, setSelectedTodoId] = useState("");
  const [takeoverConfirmed, setTakeoverConfirmed] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [quotaCompute, setQuotaCompute] = useState(1);
  const [quotaWindowHours, setQuotaWindowHours] = useState(24);
  const [configurationPlan, setConfigurationPlan] = useState<ConfigurationPlan | null>(null);
  const [completionNote, setCompletionNote] = useState("");
  const [successorTodo, setSuccessorTodo] = useState("");
  const [completionPlan, setCompletionPlan] = useState<TodoCompletionPlan | null>(null);
  const [quotaSlots, setQuotaSlots] = useState(1);
  const [quotaPlan, setQuotaPlan] = useState<QuotaMutationPlan | null>(null);
  const [turnHost, setTurnHost] = useState<TurnPlanRequest["host"]>("codex-cli");
  const [executionMode, setExecutionMode] = useState<TurnPlanRequest["execution_mode"]>("interactive-visible");
  const [turnPlan, setTurnPlan] = useState<TurnPlan | null>(null);
  const [recoveringSession, setRecoveringSession] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    sessionStorage.setItem("loopx.operator.actor", actor);
  }, [actor]);

  const sessionQuery = useQuery({
    queryKey: ["operator-console", "session"],
    queryFn: () => operatorConsoleApi.createControlSession(),
    retry: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  const operatorQuery = useQuery({
    queryKey: ["operator-console", "operator"],
    queryFn: () => operatorConsoleApi.operatorStatus(),
    enabled: Boolean(sessionQuery.data),
    refetchInterval: pollInterval,
    refetchIntervalInBackground: true,
    retry: retryQuery,
    staleTime: 2_000,
  });

  const capabilitiesQuery = useQuery({
    queryKey: ["operator-console", "capabilities"],
    queryFn: () => operatorConsoleApi.capabilities(),
    refetchInterval: pollInterval,
    refetchIntervalInBackground: true,
    retry: retryQuery,
    staleTime: 2_000,
  });

  const goalsQuery = useQuery({
    queryKey: ["operator-console", "goals"],
    queryFn: () => operatorConsoleApi.goals(),
    refetchInterval: pollInterval,
    refetchIntervalInBackground: true,
    retry: retryQuery,
    staleTime: 2_000,
  });

  const goals = goalsQuery.data?.payload.goals ?? [];
  const selectedGoalId = search.goalId || goals[0]?.goal_id || "";

  useEffect(() => {
    if (!search.goalId && goals[0]?.goal_id) {
      void navigate({
        replace: true,
        search: (previous) => ({ ...previous, goalId: goals[0].goal_id }),
      });
    }
  }, [goals, navigate, search.goalId]);

  const goalQueryOptions = {
    enabled: Boolean(selectedGoalId),
    refetchInterval: pollInterval,
    refetchIntervalInBackground: true,
    retry: retryQuery,
    staleTime: 2_000,
  } as const;

  const overviewQuery = useQuery({
    queryKey: ["operator-console", "goal", selectedGoalId, "overview"],
    queryFn: () => operatorConsoleApi.overview(selectedGoalId),
    ...goalQueryOptions,
  });

  const todosQuery = useQuery({
    queryKey: ["operator-console", "goal", selectedGoalId, "todos"],
    queryFn: () => operatorConsoleApi.todos(selectedGoalId),
    ...goalQueryOptions,
  });

  const quotaQuery = useQuery({
    queryKey: ["operator-console", "goal", selectedGoalId, "quota"],
    queryFn: () => operatorConsoleApi.quota(selectedGoalId),
    ...goalQueryOptions,
  });

  const historyQuery = useQuery({
    queryKey: ["operator-console", "goal", selectedGoalId, "history"],
    queryFn: () => operatorConsoleApi.history(selectedGoalId),
    ...goalQueryOptions,
  });

  const todos = todosQuery.data?.payload.items ?? [];

  useEffect(() => {
    if (todos.length === 0) {
      setSelectedTodoId("");
      return;
    }
    if (!todos.some((item) => item.todo_id === selectedTodoId)) {
      setSelectedTodoId(todos.find((item) => item.status === "open")?.todo_id ?? todos[0].todo_id);
    }
  }, [selectedTodoId, todos]);

  useEffect(() => {
    setConfigurationPlan(null);
    setCompletionPlan(null);
    setQuotaPlan(null);
    setTurnPlan(null);
    setSuccessMessage(null);
  }, [selectedGoalId]);

  const leaseQuery = useQuery({
    queryKey: ["operator-console", "goal", selectedGoalId, "lease", selectedTodoId],
    queryFn: () => operatorConsoleApi.lease(selectedGoalId, selectedTodoId),
    enabled: Boolean(selectedGoalId && selectedTodoId),
    refetchInterval: pollInterval,
    refetchIntervalInBackground: true,
    retry: retryQuery,
    staleTime: 2_000,
  });

  const capabilityMap = useMemo(
    () => new Map((capabilitiesQuery.data?.payload.capabilities ?? []).map((capability) => [capability.capability_id, capability])),
    [capabilitiesQuery.data],
  );
  const operatorStatus = operatorQuery.data ?? sessionQuery.data;
  const isOperator = operatorStatus?.role === "operator";
  const selectedTodo = todos.find((item) => item.todo_id === selectedTodoId) ?? null;

  const capability = (id: string) => capabilityMap.get(id);
  const canWrite = (id: string) => Boolean(isOperator && capability(id)?.available);
  const canRead = (id: string) => Boolean(capability(id)?.available);

  const refreshGoalState = async () => {
    if (!selectedGoalId) {
      return;
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["operator-console", "goals"] }),
      queryClient.invalidateQueries({ queryKey: ["operator-console", "operator"] }),
      queryClient.invalidateQueries({ queryKey: ["operator-console", "goal", selectedGoalId] }),
    ]);
  };

  const manualRefresh = async () => {
    setSuccessMessage(null);
    const baseRefetches = [
      capabilitiesQuery.refetch(),
      goalsQuery.refetch(),
      operatorQuery.refetch(),
    ];
    const goalRefetches = selectedGoalId
      ? [overviewQuery.refetch(), todosQuery.refetch(), quotaQuery.refetch(), historyQuery.refetch()]
      : [];
    const leaseRefetches = selectedGoalId && selectedTodoId ? [leaseQuery.refetch()] : [];
    await Promise.all([...baseRefetches, ...goalRefetches, ...leaseRefetches]);
  };

  const rebuildControlSession = async () => {
    setRecoveringSession(true);
    setSuccessMessage(null);
    resetOperatorControlSession();
    try {
      const session = await operatorConsoleApi.createControlSession();
      queryClient.setQueryData(["operator-console", "session"], session);
      queryClient.removeQueries({ queryKey: ["operator-console", "operator"], exact: true });
      await queryClient.invalidateQueries({ queryKey: ["operator-console", "operator"] });
      setSuccessMessage("Control session rebuilt as a viewer. Reacquire operator authority if needed.");
    } finally {
      setRecoveringSession(false);
    }
  };

  const roleMutation = useMutation({
    mutationFn: (action: "acquire" | "release" | "takeover") => operatorConsoleApi.setOperatorRole(action),
    onSuccess: async (status, action) => {
      queryClient.setQueryData(["operator-console", "operator"], status);
      setTakeoverConfirmed(false);
      setSuccessMessage(action === "release" ? "Operator role released; this session is a viewer." : "Operator authority is active for this control session.");
      await capabilitiesQuery.refetch();
    },
  });

  const configurationPatch = useMemo(
    () => defaultConfigurationPatch(quotaCompute, quotaWindowHours),
    [quotaCompute, quotaWindowHours],
  );

  const configurationPreviewMutation = useMutation({
    mutationFn: () => operatorConsoleApi.previewConfiguration(selectedGoalId, configurationPatch),
    onSuccess: (plan) => {
      setConfigurationPlan(plan);
      setSuccessMessage("Configuration preview is ready. Review effects and warnings before apply.");
    },
  });

  const configurationApplyMutation = useMutation({
    mutationFn: () => operatorConsoleApi.applyConfiguration(selectedGoalId, configurationPatch, configurationPlan!, actor),
    onSuccess: async () => {
      setConfigurationPlan(null);
      setSuccessMessage("Configuration applied with revision and idempotency checks.");
      await refreshGoalState();
    },
  });

  const claimMutation = useMutation({
    mutationFn: () => operatorConsoleApi.claimTodo(selectedGoalId, selectedTodoId, actor, todosQuery.data!.payload.revision),
    onSuccess: async () => {
      setSuccessMessage(`Todo ${selectedTodoId} claimed by ${actor}.`);
      await refreshGoalState();
    },
  });

  const completionPreviewMutation = useMutation({
    mutationFn: () => operatorConsoleApi.previewTodoCompletion(selectedGoalId, selectedTodoId, actor, {
      clear_claim: true,
      next_agent_todo: successorTodo.trim() || null,
      no_followup: !successorTodo.trim(),
      note: completionNote.trim() || null,
      self_merged: false,
    }),
    onSuccess: (plan) => {
      setCompletionPlan(plan);
      setSuccessMessage("Completion preview is ready. Confirm its successor effects before apply.");
    },
  });

  const completionApplyMutation = useMutation({
    mutationFn: () => operatorConsoleApi.applyTodoCompletion(selectedGoalId, selectedTodoId, actor, completionPlan!),
    onSuccess: async () => {
      setCompletionPlan(null);
      setCompletionNote("");
      setSuccessorTodo("");
      setSuccessMessage(`Todo ${selectedTodoId} completed.`);
      await refreshGoalState();
    },
  });

  const leaseMutation = useMutation({
    mutationFn: (action: LeaseAction) => {
      const lease = leaseQuery.data?.payload.lease;
      if (action === "acquire") {
        return operatorConsoleApi.acquireLease(selectedGoalId, selectedTodoId, actor, lease?.revision ?? null);
      }
      if (!lease) {
        throw new Error("No lease is available for this action.");
      }
      return action === "renew"
        ? operatorConsoleApi.renewLease(selectedGoalId, selectedTodoId, actor, lease.revision)
        : operatorConsoleApi.releaseLease(selectedGoalId, selectedTodoId, actor, lease.revision);
    },
    onSuccess: async (_, action) => {
      setSuccessMessage(`Lease ${action} completed for ${selectedTodoId}.`);
      await refreshGoalState();
    },
  });

  const quotaPreviewMutation = useMutation({
    mutationFn: () => operatorConsoleApi.previewQuotaSpend(selectedGoalId, quotaSlots, actor),
    onSuccess: (plan) => {
      setQuotaPlan(plan);
      setSuccessMessage("Quota spend preview is ready. Review the budget delta before apply.");
    },
  });

  const quotaApplyMutation = useMutation({
    mutationFn: () => operatorConsoleApi.applyQuotaSpend(selectedGoalId, quotaPlan!, actor),
    onSuccess: async () => {
      setQuotaPlan(null);
      setSuccessMessage(`${quotaSlots} quota slot${quotaSlots === 1 ? "" : "s"} recorded.`);
      await refreshGoalState();
    },
  });

  const turnPlanMutation = useMutation({
    mutationFn: () => operatorConsoleApi.planTurn(selectedGoalId, {
      agent_id: actor.trim() || "local-operator",
      execution_mode: executionMode,
      host: turnHost,
      turn_instance_id: `dashboard-plan-${crypto.randomUUID()}`,
    }),
    onSuccess: (plan) => {
      setTurnPlan(plan);
      setSuccessMessage("Turn plan computed. The browser will not execute it.");
    },
  });

  const mutationErrors = [
    roleMutation.error,
    configurationPreviewMutation.error,
    configurationApplyMutation.error,
    claimMutation.error,
    completionPreviewMutation.error,
    completionApplyMutation.error,
    leaseMutation.error,
    quotaPreviewMutation.error,
    quotaApplyMutation.error,
    turnPlanMutation.error,
  ];
  const requestErrors = [
    sessionQuery.error,
    capabilitiesQuery.error,
    goalsQuery.error,
    operatorQuery.error,
    overviewQuery.error,
    todosQuery.error,
    quotaQuery.error,
    historyQuery.error,
    leaseQuery.error,
  ];
  const visibleError = mutationErrors.find(Boolean) ?? requestErrors.find(Boolean) ?? null;
  const needsSessionRecovery = visibleError instanceof OperatorApiError
    && (visibleError.status === 401 || visibleError.code.includes("control_session"));
  const lastUpdated = Math.max(
    capabilitiesQuery.dataUpdatedAt,
    goalsQuery.dataUpdatedAt,
    operatorQuery.dataUpdatedAt,
    overviewQuery.dataUpdatedAt,
    todosQuery.dataUpdatedAt,
    quotaQuery.dataUpdatedAt,
    historyQuery.dataUpdatedAt,
  );
  const stale = lastUpdated === 0 || now - lastUpdated > (hidden ? hiddenPollMs * 2.5 : visiblePollMs * 3.5);
  const quota = quotaQuery.data?.payload;
  const overview = overviewQuery.data?.payload;
  const history = historyQuery.data?.payload.items ?? [];
  const openTodos = todos.filter((item) => item.status === "open").length;
  const activeLease = leaseQuery.data?.payload.lease?.active ? leaseQuery.data.payload.lease : null;
  const busy = roleMutation.isPending
    || configurationPreviewMutation.isPending
    || configurationApplyMutation.isPending
    || claimMutation.isPending
    || completionPreviewMutation.isPending
    || completionApplyMutation.isPending
    || leaseMutation.isPending
    || quotaPreviewMutation.isPending
    || quotaApplyMutation.isPending
    || turnPlanMutation.isPending;

  const actionTabs: Array<{ id: ActionTab; label: string; icon: typeof Settings2; capabilityId: string }> = [
    { id: "configuration", label: "Configure", icon: Settings2, capabilityId: "goal.configuration.preview" },
    { id: "todo", label: "Todo & lease", icon: ListChecks, capabilityId: "goal.todos.claim" },
    { id: "quota", label: "Quota", icon: Gauge, capabilityId: "goal.quota.spend.preview" },
    { id: "turn", label: "Turn plan", icon: Command, capabilityId: "goal.turn.plan" },
  ];

  return (
    <main className="operator-console" data-testid="operator-console-route">
      <header className="operator-topbar">
        <a className="operator-brand" href="/operator" aria-label="LoopX Operator Console">
          <span className="operator-brand__mark"><Layers3 aria-hidden="true" size={19} /></span>
          <span><strong>LoopX</strong><small>Operator Console</small></span>
        </a>
        <nav aria-label="Dashboard surfaces">
          <a href="/">Dashboard</a>
          <a href="/frontstage">Showcase</a>
          <a aria-current="page" href="/operator">Operator</a>
        </nav>
        <div className="operator-topbar__actions">
          <Freshness hidden={hidden} lastUpdated={lastUpdated} stale={stale} />
          <button
            aria-label="Refresh operator projections"
            className="operator-icon-button"
            disabled={busy}
            onClick={() => void manualRefresh()}
            type="button"
          >
            <RefreshCw aria-hidden="true" className={busy ? "operator-spin" : ""} size={16} />
          </button>
        </div>
      </header>

      <section className="operator-command-bar" data-testid="operator-authority-bar">
        <div className="operator-command-bar__intro">
          <ConsoleBadge tone={operatorStatus?.role === "operator" ? "positive" : "warning"}>
            <CircleDot aria-hidden="true" size={11} /> {operatorStatus?.role ?? "connecting"}
          </ConsoleBadge>
          <div>
            <span>Authority session</span>
            <strong>{operatorStatus?.profile === "local_operator" ? "Local operator profile" : "Read-only profile"}</strong>
          </div>
        </div>
        <div className="operator-command-bar__signals">
          <span><Shield size={14} /> Profile <strong>{operatorStatus?.profile ?? "loading"}</strong></span>
          <span><KeyRound size={14} /> Slot <strong>{operatorStatus?.operator_slot_occupied ? "occupied" : "available"}</strong></span>
          <span><Activity size={14} /> Session <strong>{sessionQuery.data ? "active" : "creating…"}</strong></span>
        </div>
        <div className="operator-command-bar__controls">
          {operatorStatus?.role === "operator" ? (
            <button className="operator-button operator-button--ghost" disabled={roleMutation.isPending} onClick={() => roleMutation.mutate("release")} type="button">
              <RotateCcw size={14} /> Release role
            </button>
          ) : operatorStatus?.can_acquire ? (
            <button className="operator-button operator-button--primary" disabled={roleMutation.isPending} onClick={() => roleMutation.mutate("acquire")} type="button">
              <Shield size={14} /> Acquire operator
            </button>
          ) : operatorStatus?.can_takeover ? (
            <div className="operator-takeover">
              <label><input checked={takeoverConfirmed} onChange={(event) => setTakeoverConfirmed(event.target.checked)} type="checkbox" /> Confirm takeover</label>
              <button className="operator-button operator-button--danger" disabled={!takeoverConfirmed || roleMutation.isPending} onClick={() => roleMutation.mutate("takeover")} type="button">
                <ShieldAlert size={14} /> Take over
              </button>
            </div>
          ) : (
            <ConsoleBadge>{operatorStatus?.profile === "read_only" ? "Writes disabled by profile" : "Viewer session"}</ConsoleBadge>
          )}
        </div>
      </section>

      {(successMessage || visibleError) && (
        <div className="operator-feedback">
          {successMessage && <SuccessNotice>{successMessage}</SuccessNotice>}
          <ErrorNotice error={visibleError} />
          {needsSessionRecovery && (
            <button className="operator-button operator-button--ghost" disabled={recoveringSession} onClick={() => void rebuildControlSession()} type="button">
              <RefreshCw className={recoveringSession ? "operator-spin" : ""} size={14} /> Rebuild control session
            </button>
          )}
        </div>
      )}

      <div className="operator-workspace">
        <aside className="operator-goal-rail" data-testid="operator-goal-list">
          <div className="operator-section-title">
            <div><p className="operator-eyebrow">Registry</p><h2>Goals</h2></div>
            <ConsoleBadge tone="info">{goals.length}</ConsoleBadge>
          </div>
          <div className="operator-goal-list">
            {goals.map((goal) => {
              const selected = goal.goal_id === selectedGoalId;
              return (
                <button
                  className={selected ? "operator-goal operator-goal--selected" : "operator-goal"}
                  data-testid={`operator-goal-${goal.goal_id}`}
                  key={goal.goal_id}
                  onClick={() => void navigate({ search: (previous) => ({ ...previous, goalId: goal.goal_id }) })}
                  type="button"
                >
                  <span className="operator-goal__icon"><Bot size={16} /></span>
                  <span className="operator-goal__copy">
                    <strong>{goal.goal_id}</strong>
                    <small>{goal.domain ?? "No domain"}</small>
                  </span>
                  <ChevronRight size={15} />
                  <ConsoleBadge tone={statusTone(goal.status)}>{goal.status ?? "unknown"}</ConsoleBadge>
                </button>
              );
            })}
            {!goalsQuery.isLoading && goals.length === 0 && <p className="operator-empty">No goals are registered.</p>}
          </div>
          <div className="operator-rail-note">
            <LockKeyhole size={15} />
            <p><strong>Browser boundary</strong><span>Projection reads are safe by default. Every mutation requires this tab’s explicit operator session.</span></p>
          </div>
        </aside>

        <section className="operator-goal-workspace" data-testid="operator-goal-workspace">
          <div className="operator-goal-header">
            <div>
              <p className="operator-eyebrow">Goal workspace</p>
              <h1>{selectedGoalId || "Select a goal"}</h1>
              <div className="operator-goal-meta">
                <ConsoleBadge tone={statusTone(overview?.status)}>{overview?.status ?? "loading"}</ConsoleBadge>
                <span>{overview?.domain ?? "No domain"}</span>
                <span>rev {overview?.revision?.slice(0, 12) ?? "—"}</span>
              </div>
            </div>
            <div className="operator-goal-header__route">
              <span>Route</span>
              <strong>{overview?.route_status ?? "loading"}</strong>
              <small>{overview?.routed_to_source_registry ? "source registry" : "local registry"}</small>
            </div>
          </div>

          <div className="operator-metric-grid">
            <Metric detail={quota?.reason ?? "No quota reason"} label="Run decision" tone={statusTone(quota?.decision)} value={quota?.should_run ? "Should run" : quota?.decision ?? "—"} />
            <Metric detail={quota?.recommended_action ?? "No recommended action"} label="Next action" tone={quota?.action_required ? "warning" : "neutral"} value={quota?.effective_action ?? "Observe"} />
            <Metric detail={`${todos.length} projected total`} label="Open todos" tone={openTodos > 0 ? "info" : "positive"} value={openTodos} />
            <Metric detail={`${quota?.budget.spent_slots ?? 0} spent`} label="Quota slots" tone={quota?.state === "eligible" ? "positive" : "warning"} value={`${quota?.budget.allowed_slots ?? "—"}`} />
          </div>

          <div className="operator-content-grid">
            <ConsolePanel className="operator-todos-panel" description="Claims, completion status, and successor lineage from the typed todo projection." eyebrow="Work queue" title="Todos">
              <div className="operator-todo-list" data-testid="operator-todo-list">
                {todos.map((todo) => (
                  <button
                    className={todo.todo_id === selectedTodoId ? "operator-todo operator-todo--selected" : "operator-todo"}
                    key={todo.todo_id}
                    onClick={() => {
                      setSelectedTodoId(todo.todo_id);
                      setActionTab("todo");
                      setCompletionPlan(null);
                    }}
                    type="button"
                  >
                    <span className="operator-todo__state">{todo.status === "done" ? <Check size={14} /> : <CircleDot size={14} />}</span>
                    <span className="operator-todo__copy">
                      <strong>{todo.text ?? todo.todo_id}</strong>
                      <small>{todo.todo_id} · {todo.task_class ?? "unclassified"}</small>
                    </span>
                    <span className="operator-todo__owner">{todo.claimed_by ?? "unclaimed"}</span>
                    <ConsoleBadge tone={statusTone(todo.status)}>{todo.status}</ConsoleBadge>
                  </button>
                ))}
                {!todosQuery.isLoading && todos.length === 0 && <p className="operator-empty">No todos in this projection.</p>}
              </div>
            </ConsolePanel>

            <ConsolePanel className="operator-history-panel" description="Compact public-safe run evidence; raw logs and trajectories remain outside the browser." eyebrow="Evidence" title="Recent history">
              <div className="operator-history-list" data-testid="operator-history-list">
                {history.map((entry) => (
                  <article className="operator-history-item" key={entry.run_id}>
                    <span className="operator-history-item__rail" />
                    <div>
                      <span>{dateTime(entry.generated_at)}</span>
                      <strong>{entry.classification}</strong>
                      <small>{entry.delivery_outcome ?? entry.progress_scope ?? "No outcome projected"}</small>
                    </div>
                    <ConsoleBadge tone={entry.artifacts_verified ? "positive" : "neutral"}>
                      {entry.artifacts_verified ? "verified" : "compact"}
                    </ConsoleBadge>
                  </article>
                ))}
                {!historyQuery.isLoading && history.length === 0 && <p className="operator-empty">No run history is available.</p>}
              </div>
            </ConsolePanel>
          </div>
        </section>

        <aside className="operator-action-panel" data-testid="operator-action-panel">
          <div className="operator-section-title">
            <div><p className="operator-eyebrow">Controlled changes</p><h2>Action panel</h2></div>
            <ConsoleBadge tone={isOperator ? "positive" : "warning"}>{isOperator ? "armed" : "viewer"}</ConsoleBadge>
          </div>
          <Field hint="Written into idempotent write context; not a shell identity." label="Actor">
            <div className="operator-input-with-icon"><UserRound size={14} /><input aria-label="Operator actor" onChange={(event) => setActor(event.target.value)} value={actor} /></div>
          </Field>

          <div className="operator-action-tabs" role="tablist">
            {actionTabs.map((tab) => {
              const Icon = tab.icon;
              const tabCapability = capability(tab.capabilityId);
              return (
                <button
                  aria-selected={actionTab === tab.id}
                  className={actionTab === tab.id ? "operator-action-tab operator-action-tab--selected" : "operator-action-tab"}
                  data-available={tabCapability?.available ?? false}
                  key={tab.id}
                  onClick={() => setActionTab(tab.id)}
                  role="tab"
                  type="button"
                >
                  <Icon size={14} /> {tab.label}
                  <span className={tabCapability?.available ? "operator-cap-dot operator-cap-dot--ready" : "operator-cap-dot"} />
                </button>
              );
            })}
          </div>

          {actionTab === "configuration" && (
            <div className="operator-action-body" role="tabpanel">
              <ActionGate available={Boolean(capability("goal.configuration.preview")?.available)} isOperator={Boolean(isOperator)} reason={capabilityReason(capability("goal.configuration.preview"))} />
              <div className="operator-form-grid">
                <Field label="Quota compute">
                  <input aria-label="Quota compute" min={0.1} onChange={(event) => { setQuotaCompute(Number(event.target.value)); setConfigurationPlan(null); }} step={0.1} type="number" value={quotaCompute} />
                </Field>
                <Field label="Window hours">
                  <input aria-label="Quota window hours" min={1} onChange={(event) => { setQuotaWindowHours(Number(event.target.value)); setConfigurationPlan(null); }} type="number" value={quotaWindowHours} />
                </Field>
              </div>
              <button className="operator-button operator-button--primary operator-button--wide" disabled={!canWrite("goal.configuration.preview") || configurationPreviewMutation.isPending} onClick={() => configurationPreviewMutation.mutate()} type="button">
                <Sparkles size={14} /> Preview configuration
              </button>
              {configurationPlan && (
                <div className="operator-preview" data-testid="operator-configuration-preview">
                  <div className="operator-preview__header"><span>Preview</span><ConsoleBadge tone={configurationPlan.can_apply ? "positive" : "danger"}>{configurationPlan.can_apply ? "can apply" : "blocked"}</ConsoleBadge></div>
                  {configurationPlan.effects.map((effect) => (
                    <div className="operator-effect" key={effect.field}><strong>{effect.field}</strong><span>{compact(effect.before)} <ArrowRight size={12} /> {compact(effect.after)}</span></div>
                  ))}
                  {configurationPlan.warnings.map((warning) => <p className="operator-warning" key={warning}>{warning}</p>)}
                  <PlanHash value={configurationPlan.plan_hash} />
                  <button className="operator-button operator-button--apply operator-button--wide" disabled={!configurationPlan.can_apply || !canWrite("goal.configuration.apply") || configurationApplyMutation.isPending} onClick={() => configurationApplyMutation.mutate()} type="button">
                    <Check size={14} /> Apply reviewed plan
                  </button>
                </div>
              )}
            </div>
          )}

          {actionTab === "todo" && (
            <div className="operator-action-body" role="tabpanel">
              <ActionGate available={Boolean(capability("goal.todos.claim")?.available)} isOperator={Boolean(isOperator)} reason={capabilityReason(capability("goal.todos.claim"))} />
              <Field label="Selected todo">
                <select aria-label="Selected todo" onChange={(event) => { setSelectedTodoId(event.target.value); setCompletionPlan(null); }} value={selectedTodoId}>
                  {todos.map((todo) => <option key={todo.todo_id} value={todo.todo_id}>{todo.todo_id}</option>)}
                </select>
              </Field>
              {selectedTodo && (
                <div className="operator-selected-todo">
                  <strong>{selectedTodo.text ?? selectedTodo.todo_id}</strong>
                  <span>{selectedTodo.claimed_by ? `claimed by ${selectedTodo.claimed_by}` : "unclaimed"}</span>
                </div>
              )}
              <div className="operator-button-row">
                <button className="operator-button operator-button--ghost" disabled={!selectedTodo || !canWrite("goal.todos.claim") || claimMutation.isPending} onClick={() => claimMutation.mutate()} type="button"><UserRound size={14} /> Claim</button>
                {!activeLease ? (
                  <button className="operator-button operator-button--ghost" disabled={!selectedTodo || !canWrite("goal.lease.acquire") || leaseMutation.isPending} onClick={() => leaseMutation.mutate("acquire")} type="button"><KeyRound size={14} /> Acquire lease</button>
                ) : (
                  <>
                    <button className="operator-button operator-button--ghost" disabled={!canWrite("goal.lease.renew") || leaseMutation.isPending} onClick={() => leaseMutation.mutate("renew")} type="button"><Clock3 size={14} /> Renew</button>
                    <button className="operator-button operator-button--danger" disabled={!canWrite("goal.lease.release") || leaseMutation.isPending} onClick={() => leaseMutation.mutate("release")} type="button"><RotateCcw size={14} /> Release</button>
                  </>
                )}
              </div>
              <div className="operator-lease-readout">
                <span>Lease</span><strong>{activeLease ? `${activeLease.owner} · ${activeLease.status}` : "none active"}</strong>
                {activeLease?.expires_at && <small>expires {dateTime(activeLease.expires_at)}</small>}
              </div>
              <Field label="Completion note">
                <textarea aria-label="Completion note" onChange={(event) => { setCompletionNote(event.target.value); setCompletionPlan(null); }} placeholder="Public-safe outcome summary" rows={2} value={completionNote} />
              </Field>
              <Field hint="Leave empty to preview an explicit no-followup completion." label="Next agent todo">
                <input aria-label="Next agent todo" onChange={(event) => { setSuccessorTodo(event.target.value); setCompletionPlan(null); }} placeholder="Optional bounded successor" value={successorTodo} />
              </Field>
              <button className="operator-button operator-button--primary operator-button--wide" disabled={!selectedTodo || !canWrite("goal.todos.complete.preview") || completionPreviewMutation.isPending} onClick={() => completionPreviewMutation.mutate()} type="button"><Sparkles size={14} /> Preview completion</button>
              {completionPlan && (
                <div className="operator-preview" data-testid="operator-completion-preview">
                  <div className="operator-preview__header"><span>Completion preview</span><ConsoleBadge tone={completionPlan.can_apply ? "positive" : "danger"}>{completionPlan.can_apply ? "can apply" : "blocked"}</ConsoleBadge></div>
                  <div className="operator-effect"><strong>Todo</strong><span>{completionPlan.todo_id}</span></div>
                  <div className="operator-effect"><strong>Successors</strong><span>{completionPlan.successor_todo_ids.length || "none"}</span></div>
                  <PlanHash value={completionPlan.plan_hash} />
                  <button className="operator-button operator-button--apply operator-button--wide" disabled={!completionPlan.can_apply || !canWrite("goal.todos.complete.apply") || completionApplyMutation.isPending} onClick={() => completionApplyMutation.mutate()} type="button"><Check size={14} /> Apply completion</button>
                </div>
              )}
            </div>
          )}

          {actionTab === "quota" && (
            <div className="operator-action-body" role="tabpanel">
              <ActionGate available={Boolean(capability("goal.quota.spend.preview")?.available)} isOperator={Boolean(isOperator)} reason={capabilityReason(capability("goal.quota.spend.preview"))} />
              <div className="operator-budget-readout">
                <span><strong>{quota?.budget.spent_slots ?? 0}</strong> spent</span>
                <div><i style={{ width: `${Math.min(100, ((quota?.budget.spent_slots ?? 0) / Math.max(1, quota?.budget.allowed_slots ?? 1)) * 100)}%` }} /></div>
                <span><strong>{quota?.budget.allowed_slots ?? 0}</strong> allowed</span>
              </div>
              <Field hint="Recorded as visible-goal spend for the actor above." label="Slots to spend">
                <input aria-label="Quota slots to spend" min={1} onChange={(event) => { setQuotaSlots(Number(event.target.value)); setQuotaPlan(null); }} type="number" value={quotaSlots} />
              </Field>
              <button className="operator-button operator-button--primary operator-button--wide" disabled={!canWrite("goal.quota.spend.preview") || quotaPreviewMutation.isPending} onClick={() => quotaPreviewMutation.mutate()} type="button"><Sparkles size={14} /> Preview spend</button>
              {quotaPlan && (
                <div className="operator-preview" data-testid="operator-quota-preview">
                  <div className="operator-preview__header"><span>Budget delta</span><ConsoleBadge tone={quotaPlan.would_throttle ? "warning" : "positive"}>{quotaPlan.would_throttle ? "would throttle" : "within budget"}</ConsoleBadge></div>
                  <div className="operator-effect"><strong>Spent slots</strong><span>{quotaPlan.before.spent_slots} <ArrowRight size={12} /> {quotaPlan.after?.spent_slots ?? "—"}</span></div>
                  <div className="operator-effect"><strong>Reason</strong><span>{quotaPlan.reason ?? "validated spend"}</span></div>
                  <PlanHash value={quotaPlan.plan_hash} />
                  <button className="operator-button operator-button--apply operator-button--wide" disabled={!quotaPlan.can_apply || !canWrite("goal.quota.spend.apply") || quotaApplyMutation.isPending} onClick={() => quotaApplyMutation.mutate()} type="button"><Zap size={14} /> Apply quota spend</button>
                </div>
              )}
            </div>
          )}

          {actionTab === "turn" && (
            <div className="operator-action-body" role="tabpanel">
              <ActionGate available={Boolean(capability("goal.turn.plan")?.available)} isOperator={Boolean(isOperator)} reason={capabilityReason(capability("goal.turn.plan"))} requiresOperator={false} />
              <div className="operator-cui-boundary">
                <Command size={16} />
                <p><strong>Planning only</strong><span>Turn execution stays CUI-only. This console has no arbitrary command or run-once control.</span></p>
              </div>
              <Field label="Host">
                <select aria-label="Turn host" onChange={(event) => setTurnHost(event.target.value as TurnPlanRequest["host"])} value={turnHost}>
                  <option value="codex-cli">Codex CLI</option>
                  <option value="claude-code">Claude Code</option>
                  <option value="generic-cli">Generic CLI</option>
                </select>
              </Field>
              <Field label="Execution mode">
                <select aria-label="Turn execution mode" onChange={(event) => setExecutionMode(event.target.value as TurnPlanRequest["execution_mode"])} value={executionMode}>
                  <option value="interactive-visible">Interactive visible</option>
                  <option value="isolated-headless">Isolated headless</option>
                </select>
              </Field>
              <button className="operator-button operator-button--primary operator-button--wide" disabled={!canRead("goal.turn.plan") || turnPlanMutation.isPending} onClick={() => turnPlanMutation.mutate()} type="button"><Braces size={14} /> Compute turn plan</button>
              {turnPlan && (
                <div className="operator-preview" data-testid="operator-turn-preview">
                  <div className="operator-preview__header"><span>Turn envelope</span><ConsoleBadge tone={turnPlan.can_run ? "positive" : "warning"}>{turnPlan.can_run ? "runnable in CUI" : "blocked"}</ConsoleBadge></div>
                  <div className="operator-effect"><strong>Route</strong><span>{turnPlan.route}</span></div>
                  <div className="operator-effect"><strong>Selected todo</strong><span>{turnPlan.selected_todo_id ?? "none"}</span></div>
                  {turnPlan.unavailable_reasons.map((reason) => <p className="operator-warning" key={reason}>{reason}</p>)}
                  <PlanHash value={turnPlan.plan_hash} />
                </div>
              )}
            </div>
          )}

          <div className="operator-capability-footer">
            <span><CircleDot size={12} /> {capabilitiesQuery.data?.payload.capabilities.filter((item) => item.available).length ?? 0} capabilities ready</span>
            <small>Actions mirror describe_capabilities()</small>
          </div>
        </aside>
      </div>
    </main>
  );
}
