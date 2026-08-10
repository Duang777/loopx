// @ts-expect-error The smoke compiler intentionally runs without @types/node.
import { readFileSync } from "node:fs";

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

function includes(source: string, snippet: string, label: string) {
  assert(source.includes(snippet), `missing ${label}: ${snippet}`);
}

function excludes(source: string, snippet: string, label: string) {
  assert(!source.includes(snippet), `unexpected ${label}: ${snippet}`);
}

function sourceBetween(source: string, start: string, end: string, label: string) {
  const startIndex = source.indexOf(start);
  assert(startIndex >= 0, `missing ${label} start: ${start}`);
  const endIndex = source.indexOf(end, startIndex);
  assert(endIndex >= 0, `missing ${label} end: ${end}`);
  return source.slice(startIndex, endIndex);
}

const routerSource = readFileSync("src/router.tsx", "utf8");
const dashboardSource = readFileSync("src/views/dashboard-page.tsx", "utf8");
const stylesSource = readFileSync("src/styles.css", "utf8");
const readmeSource = readFileSync("README.md", "utf8");
const contractSource = readFileSync("../../../docs/status-data-contract.md", "utf8");
const packageSource = readFileSync("package.json", "utf8");
const viteSource = readFileSync("vite.config.ts", "utf8");
const dashboardDevSource = readFileSync("../../../scripts/dashboard-dev.sh", "utf8");
const exampleSource = readFileSync("../../../examples/status.example.json", "utf8");
const designSource = readFileSync("design.md", "utf8");

includes(routerSource, 'view: z.enum(["ops", "share"]).optional()', "optional view search param");
includes(routerSource, 'todoGoalId: z.string().optional().default("all")', "todo project search param");
includes(routerSource, 'todoQuery: z.string().optional().default("")', "todo query search param");
includes(routerSource, 'todoRole: z.enum(["all", "user", "agent"]).optional().default("all")', "todo role search param");
includes(routerSource, 'todoStatus: z.enum(["all", "open", "done", "blocked", "deferred"]).optional().default("all")', "todo status search param");
excludes(routerSource, 'view: z.enum(["ops", "share"]).optional().default("share")', "share default route mode");

includes(
  dashboardSource,
  'const defaultGlobalStatusUrl = import.meta.env.DEV ? "/status.json" : "http://127.0.0.1:8766/status.json";',
  "environment-aware default status URL",
);
includes(viteSource, '"/status.json"', "status service Vite proxy");
includes(packageSource, '"dev": "bash ../../../scripts/dashboard-dev.sh"', "complete dashboard dev launcher");
includes(dashboardDevSource, "serve-status", "dashboard launcher status service");
includes(dashboardDevSource, "loopx.cli chat", "dashboard launcher Chat service");
includes(dashboardDevSource, "sys.version_info < (3, 11)", "dashboard launcher Python version guard");
includes(dashboardDevSource, "wait_for_service", "dashboard launcher readiness gate");
assert(
  dashboardDevSource.indexOf('wait_for_service "status"')
    < dashboardDevSource.lastIndexOf("npm run dev:web"),
  "dashboard launcher should wait for status before Vite",
);
includes(dashboardSource, 'return view === "ops" ? "ops" : undefined;', "canonical URL omits non-ops view");
includes(dashboardSource, 'if (search.view !== "ops" && source.kind === "example") {', "non-ops loads global status source once");
includes(
  dashboardSource,
  '[exampleModeRequested, search.statusUrl, search.view, source.kind, source.label]',
  "status URL change reload effect",
);
includes(dashboardSource, 'void loadFromUrl(defaultGlobalStatusUrl);', "home loads global status source");
includes(dashboardSource, 'data-testid="personal-goal-home"', "personal Goal home test id");
includes(dashboardSource, 'data-testid="personal-manager-summary"', "personal manager summary test id");
includes(dashboardSource, 'data-testid="personal-needs-you"', "needs-you section test id");
includes(dashboardSource, 'data-testid="personal-goal-list"', "personal Goal list test id");
includes(dashboardSource, 'data-testid="personal-goal-row"', "personal Goal row test id");
includes(dashboardSource, 'data-testid="personal-manager-home"', "manager Chat home test id");
includes(dashboardSource, 'data-testid="personal-manager-quick-action"', "manager quick action test id");
includes(dashboardSource, 'data-testid="personal-manager-thread"', "manager thread test id");
includes(dashboardSource, 'data-testid="personal-manager-composer"', "manager composer test id");
includes(dashboardSource, 'data-testid="personal-manager-send"', "manager send test id");
includes(dashboardSource, 'data-testid="personal-goal-summary"', "Goal projection timeline test id");
includes(dashboardSource, 'data-testid="personal-agent-trigger"', "Agent selector trigger test id");
includes(dashboardSource, 'data-testid="personal-agent-menu"', "Agent selector menu test id");
includes(dashboardSource, 'data-testid="personal-agent-option"', "discovered Agent option test id");
includes(dashboardSource, 'data-testid="personal-agent-plan-card"', "Agent Todo plan card test id");
includes(dashboardSource, 'data-testid="personal-run-evidence-card"', "run evidence card test id");
includes(dashboardSource, 'data-testid="personal-running-details-trigger"', "running details trigger test id");
includes(dashboardSource, 'data-testid="personal-running-details"', "running details dialog test id");
includes(dashboardSource, "buildPersonalHomeModel(payload, rows)", "dynamic personal projection wiring");
includes(dashboardSource, "run_history.goals", "Goal projection source");
includes(dashboardSource, "attention_queue.items", "todo projection source");
includes(dashboardSource, ".filter((todo) => !todo.done)", "open user todo filtering");
includes(dashboardSource, "Number(right.blocking) - Number(left.blocking)", "blocking Goal ordering");
includes(dashboardSource, "allUserTodos.slice(0, 5)", "needs-you row limit");
includes(dashboardSource, 'if (state === "已完成")', "completed Goals hidden from active list");
includes(dashboardSource, 'if (personalGoalNeedsRepair(payload, row)) {', "goal-specific repair state precedence");
includes(dashboardSource, 'if (["user_or_controller", "controller"].includes(row.waitingOn) || hasOpenUserTodo) {', "waiting-on-user state");
includes(dashboardSource, 'if (row.waitingOn === "external_evidence") {', "external condition state");
includes(dashboardSource, 'if (quotaStateForShare(row) === "eligible" || hasOpenAgentTodo) {', "agent progress state");
includes(dashboardSource, "cleanShareText(value)", "personal text redaction");
includes(dashboardSource, "function personalProjectionSentence(", "machine-to-human status translation");
includes(dashboardSource, "刷新 LoopX 状态，确认当前进度仍然有效", "refresh-state user-facing translation");
includes(dashboardSource, "Todo 状态已经更新，正在确认下一步", "Todo event user-facing translation");
includes(dashboardSource, "function answerPersonalManagerQuestion(", "deterministic manager answer router");
includes(dashboardSource, '["现在", "下一步", "我该", "该做什么"]', "next-action manager routing");
includes(dashboardSource, '["等我", "阻塞", "需要我"]', "waiting-on-user manager routing");
includes(dashboardSource, '["Agent", "agent", "推进", "在做"]', "agent activity manager routing");
includes(dashboardSource, '["状态", "异常", "修复", "健康"]', "health manager routing");
assert(
  dashboardSource.indexOf('["Agent", "agent", "推进", "在做"]')
    < dashboardSource.indexOf('["现在", "下一步", "我该", "该做什么"]'),
  "agent activity routing should precede the overlapping next-action intent",
);
includes(dashboardSource, "当前管家支持三类问题", "unknown manager query guidance");
includes(dashboardSource, "Agent 正在推进当前 Goal", "progress sentence final fallback");
includes(dashboardSource, "row.queueItem?.recommended_action", "queue recommendation progress fallback");
includes(dashboardSource, "row.latestRun?.recommended_action", "latest run recommendation progress fallback");
includes(dashboardSource, "function personalOpsHref(goalId?: string)", "safe ops link builder");
includes(dashboardSource, 'params.set("view", "ops")', "ops view search link");
includes(dashboardSource, 'params.set("goalId", goalId)', "ops Goal selection link");
includes(dashboardSource, "LoopX 管家", "manager Chat title");
includes(dashboardSource, "需要你", "needs-you heading");
includes(dashboardSource, "问问 Goals，或交代一个任务…", "manager composer placeholder");
includes(dashboardSource, 'aria-label={selectedGoal ? `${selectedGoal.title} 的 Goal Chat 输入区`', "Goal context on composer form");
includes(dashboardSource, 'aria-label={`切换当前 Agent：${selectedAgent.label}`}', "composer Agent selector label");
includes(dashboardSource, "我现在该做什么？", "manager next action quick prompt");
includes(dashboardSource, "哪些 Goal 在等我？", "manager waiting quick prompt");
includes(dashboardSource, "Agent 在做什么？", "manager activity quick prompt");
includes(dashboardSource, 'agentId: "status-only"', "deterministic status-only Agent option");
includes(dashboardSource, 'managerQuickPrompts.includes(question)', "fixed quick questions use deterministic projection");
includes(dashboardSource, '"LoopX 状态投影 · 仅查状态"', "status-only answer attribution");
includes(dashboardSource, '"仅查状态"', "deterministic answer author attribution");
includes(dashboardSource, 'selectedGoal ? "goal" : "manager"', "manager and Goal Chat session isolation");
includes(dashboardSource, "fetchChatHistory({", "durable local Chat history hydration");
includes(dashboardSource, 'const channelId = selectedGoal ? `goal.${selectedGoal.goalId}` : "manager";', "manager history channel selection");
includes(dashboardSource, 'const anchorGoalId = selectedGoal?.goalId ?? model.goals[0]?.goalId ?? "";', "manager session project anchor");
includes(dashboardSource, "const sessionGoalId = latest?.goal_id ?? anchorGoalId;", "restored manager session project binding");
includes(dashboardSource, "if (latest && !latest.resumable)", "local history survives upstream resume failure");
excludes(dashboardSource, 'if (!selectedGoal || selectedAgent.agentId === "status-only"', "selected Goal guard hiding manager history");
includes(dashboardSource, '`${selectedRoute.label} 管家 · 跨 Goal 只读`', "global manager source label");
includes(dashboardSource, 'createChatSession(', "Agent Goal Chat session creation");
includes(dashboardSource, "sendChatTurnStreaming(sessionId, question", "streaming Agent Goal Chat turn");
includes(dashboardSource, "interruptChatTurn", "interruptible Agent Goal Chat turn");
includes(dashboardSource, 'error.payload.error_code === "resume_failed"', "Agent resume failure route");
includes(dashboardSource, "LoopX 状态服务未连接", "missing status service guidance");
includes(dashboardSource, "previewTodo(card.goalId, card.proposal.text)", "Todo dry-run preview");
includes(dashboardSource, "applyTodo(card.goalId, card.proposal.text, card.previewId)", "Todo preview-locked apply");
includes(dashboardSource, 'state: "rejected" | "cancelled"', "zero-write reject and cancel decisions");
includes(dashboardSource, "todoNoWriteReceiptFromPayload(error.payload)", "stale preview no-write receipt");
includes(dashboardSource, 'data-testid="personal-proposal-card"', "compact Todo candidate card");
includes(dashboardSource, "personalAgentLabel(selectedGoal.agentId)", "durable Todo owner attribution");
includes(dashboardSource, "`${goal.title} · ${goal.state} · ${goal.agentSentence}`", "human Goal titles in manager answers");
includes(dashboardSource, "`${selectedAgent.label} · ${selectedGoal.state}", "Goal interaction summary subtitle");
includes(dashboardSource, 'agent.label === "Codex" && agent.available', "Codex available default");
includes(dashboardSource, "selectedAgents[contextId] ?? defaultAgentId", "Codex-first per-Chat Agent default");
excludes(dashboardSource, "selectedAgents[contextId] ?? goalAgentId", "Goal owner overriding the Chat default Agent");
includes(dashboardSource, "fetchChatCapabilities()", "runtime Agent endpoint discovery");
includes(dashboardSource, "capabilities.adapters ?? []", "runtime Adapter capability wiring");
includes(dashboardSource, 'statusLabel: agent.available ? "可用" : "需要配置"', "unavailable endpoint guidance");
includes(dashboardSource, "selectAvailableChatAgent(", "stale Agent selection fallback");
includes(dashboardSource, "/codex/i.test(agent.agentId) && agent.status.variant !== \"danger\"", "Goal Codex preference");
includes(dashboardSource, 'personalAgentSelectionStorageKey = "loopx.personal-agent-selection.v1"', "per-Chat Agent persistence key");
includes(dashboardSource, 'useState<Record<string, string>>(readPersonalAgentSelections)', "persisted Agent selection initialization");
includes(dashboardSource, 'mobilePanel === "goals" && "mobile-goals-visible"', "mobile Goal-list mode");
includes(dashboardSource, 'className="personal-agent-menu-backdrop"', "mobile Agent picker backdrop");
includes(dashboardSource, 'agentMenuRef.current?.querySelector<HTMLElement>', "Agent menu focus handoff");
includes(dashboardSource, 'detailsCloseRef.current?.focus()', "running-details focus handoff");
includes(dashboardSource, 'aria-label="关闭运行详情" autoFocus', "running-details deterministic initial focus");
includes(dashboardSource, "data-source-todo-id={selectedGoal.needsYouTodoId ?? undefined}", "user-action Todo lineage");
includes(dashboardSource, "data-source-agent-id={selectedGoal.agentId}", "Agent execution lineage");
includes(stylesSource, ".personal-workspace.mobile-goals-visible .personal-chat-pane", "mobile one-panel behavior");
includes(stylesSource, "bottom: 0.75rem", "mobile Agent bottom sheet positioning");
includes(stylesSource, ".personal-manager-quick-actions button,", "mobile quick-action touch target");
includes(dashboardSource, "稍后", "user decision defer response");
includes(dashboardSource, "personalDecisionPrimaryLabel(selectedGoal)", "user decision scoped response");
includes(dashboardSource, "打开完整控制台", "advanced operator fallback");
includes(dashboardSource, 'selectedGoal.state === "需修复" ? "查看原因" : "Goal 进度"', "abnormal running-details emphasis");
includes(dashboardSource, "计划进度", "Goal Agent-Todo progress label");
includes(dashboardSource, "来自 {goalAgentTodos.length} 项 Agent Todo", "Goal Todo source label");
includes(dashboardSource, "function personalRunEvidence(", "Goal run-evidence projection");
includes(dashboardSource, "Goal 状态、Todo 与注册信息已验证", "machine validation summary translation");
includes(dashboardSource, "<PersonalGoalHome", "default personal home rendering");
excludes(dashboardSource, "<ShareEvidenceView", "retired showcase home rendering");
includes(designSource, "## Agent Discovery And Selection", "design Agent discovery contract");
includes(designSource, "## LoopX Projection Mapping", "design projection mapping");
includes(designSource, "## Business Object Contract", "design business object contract");
includes(designSource, "## Acceptance Criteria", "design acceptance criteria");
includes(dashboardSource, '<h1 className="text-2xl font-semibold">Goal 控制台</h1>', "ops workbench fallback");
includes(dashboardSource, 'data-testid="operator-mental-model-panel"', "operator mental model panel test id");
includes(dashboardSource, "操作者概览", "operator mental model title");
includes(dashboardSource, "首屏把控制面状态整理成五个需要关注的问题。", "operator mental model helper");
includes(dashboardSource, "下一步", "operator mental model next step label");
includes(dashboardSource, "需要你判断", "operator mental model judgment label");
includes(dashboardSource, "是否可继续", "operator mental model continue label");
includes(dashboardSource, 'data-testid="project-todo-explorer"', "project todo explorer test id");
includes(dashboardSource, 'data-testid="project-todo-search-input"', "project todo search input test id");
includes(dashboardSource, 'data-testid="project-todo-id"', "project todo id rendering");
includes(dashboardSource, "todoExplorerProjectOptions", "project todo auto project options");
includes(dashboardSource, "selectedTodoGoalId", "project todo selected project prop");
includes(dashboardSource, "claimed_by=", "project todo claimed owner metadata");
includes(dashboardSource, "action=", "project todo action metadata");
includes(dashboardSource, "source={item.source}", "project todo source metadata");
includes(dashboardSource, "latest_event_kind", "project todo historical event metadata");
includes(dashboardSource, "todoIndex={payload.todo_index}", "project todo index wiring");
includes(dashboardSource, 'data-testid="agent-management-panel"', "agent management panel test id");
includes(dashboardSource, 'data-testid="agent-management-row"', "agent management row test id");
includes(dashboardSource, 'data-testid="agent-management-copy-command"', "agent management copy command test id");
includes(dashboardSource, 'data-testid="agent-management-handoff-note"', "agent management handoff note test id");
includes(dashboardSource, 'data-testid="agent-management-workspace-ref"', "agent management workspace hint test id");
includes(dashboardSource, 'data-testid="agent-management-stale-claim-hint"', "agent management stale claim hint test id");
includes(dashboardSource, "buildAgentManagementRows", "agent management projection builder");
includes(dashboardSource, "agentManagementProjection={payload.agent_management_projection}", "agent management live projection wiring");
includes(dashboardSource, "agent_id", "agent management agent id metadata");
includes(exampleSource, '"todo_index"', "example todo index projection");
includes(exampleSource, '"source": "live_loopx_status_public_slice"', "example live LoopX status source");
includes(exampleSource, '"public_safe_export": true', "example public-safe export marker");
includes(exampleSource, '"agent_id": "codex-main-control"', "example main-control agent row");
includes(exampleSource, '"agent_id": "codex-product-capability"', "example product-capability agent row");
includes(exampleSource, '"agent_id": "codex-side-bypass"', "example side-bypass agent row");
includes(exampleSource, '"agent_id": "codex-value-explorer"', "example value-explorer agent row");
includes(exampleSource, '"todo_id": "todo_2bf560b48a0c"', "example real main-control todo id");
includes(exampleSource, '"todo_id": "todo_584f55f8f3b4"', "example real value-explorer todo id");
includes(exampleSource, '"claimed_by": "codex-value-explorer"', "example claimed agent row");
includes(exampleSource, '"stale_claim_hint": {', "example live stale claim hint projection");
excludes(exampleSource, "todo_example_", "synthetic todo rows in bundled example");
excludes(exampleSource, "experiment-controller-goal", "legacy synthetic goal in bundled example");
excludes(exampleSource, "department-", "private department label in bundled example");
excludes(exampleSource, "/Users/", "local absolute path in bundled example");
excludes(exampleSource, "/private/", "private temp path in bundled example");
excludes(dashboardSource, "raw internal slot constraints", "raw internal constraint copy");
includes(contractSource, "todo_id", "status contract todo id metadata");
includes(readFileSync("src/data/goal-channel-frontstage.ts", "utf8"), "generated_at: z.string().optional().nullable()", "goal channel generated_at optional live status compatibility");
includes(packageSource, '"smoke:home-route"', "home route smoke script");
includes(packageSource, '"smoke:home-browser"', "home browser smoke script");
includes(packageSource, '"smoke:demo-readiness"', "demo readiness smoke script");
includes(readmeSource, "npm run smoke:home-browser", "README home browser smoke command");
includes(readmeSource, "npm run smoke:demo-readiness", "README demo readiness smoke command");
includes(readmeSource, "--skip-browser", "README demo readiness CI skip-browser command");
includes(readmeSource, "Fresh Clone Public Preview", "README fresh-clone preview section");
includes(readmeSource, "npm ci", "README fresh-clone npm dependency install");
includes(readmeSource, "examples/status.example.json", "README bundled public status fixture");
includes(readmeSource, "without `view=share`", "README home smoke canonical route expectation");

for (const [source, sourceLabel] of [
  [readmeSource, "dashboard README"],
  [contractSource, "status data contract"],
] as const) {
  includes(source, "control-plane home", `${sourceLabel} canonical home`);
  includes(source, "?view=ops", `${sourceLabel} ops fallback`);
  includes(source, "view=share", `${sourceLabel} legacy share compatibility`);
}

includes(contractSource, "translate raw machine fields", "status contract translation expectation");
includes(contractSource, "single_surface", "status contract raw machine token example");

const personalGoalStateSource = sourceBetween(
  dashboardSource,
  "function personalGoalState(",
  "function personalAgentSentence(",
  "personal Goal state projection",
);
excludes(personalGoalStateSource, "!payload.ok", "global payload failure in per-Goal repair state");
excludes(personalGoalStateSource, "!payload.contract.ok", "global contract failure in per-Goal repair state");
excludes(personalGoalStateSource, "!payload.global_registry.ok", "global registry failure in per-Goal repair state");
includes(personalGoalStateSource, "personalGoalNeedsRepair(payload, row)", "goal-specific repair attribution");

const personalManagerSource = sourceBetween(
  dashboardSource,
  "type PersonalManagerMessage",
  "function ShareEvidenceView(",
  "personal manager implementation",
);
for (const forbiddenApi of [
  "fetch(",
  "WebSocket",
  "EventSource",
  "sessionStorage",
  "clipboard",
]) {
  excludes(personalManagerSource, forbiddenApi, `manager network or persistence API ${forbiddenApi}`);
}
includes(personalManagerSource, 'event.key === "Escape"', "manager Escape close");
includes(personalManagerSource, 'event.currentTarget === event.target', "manager backdrop close boundary");
includes(personalManagerSource, 'aria-live="polite"', "manager polite live thread");
includes(personalManagerSource, "if (!question)", "manager blank input guard");

console.log("home-route smoke ok");
