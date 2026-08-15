import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (name) => readFileSync(new URL(name, import.meta.url), "utf8");
const model = source("./personal-workspace-model.ts");
const drawer = source("./context-drawer.tsx");
const header = source("./channel-header.tsx");
const page = source("./personal-workspace-page.tsx");
const timeline = source("./channel-timeline.tsx");
const larkSettings = source("./lark-settings-page.tsx");
const styles = source("./personal-workspace.css");
const dashboard = source("../../views/dashboard-page.tsx");
const tasks = source("./goal-tasks-view.tsx");

assert.match(model, /kind: "todo"/, "Todo has its own drawer selection");
for (const field of ["dependencies", "nextTransition", "ownerLabel", "todoId", "taskClass"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Todo exposes ${field}`);
}
assert.match(drawer, /actionKind: "todo\.update"/, "Todo mutations use typed previews");
for (const operation of ["reassign", "block", "defer"]) {
  assert.match(drawer, new RegExp(`operation:\\s*"${operation}"`), `Todo supports ${operation}`);
}
assert.match(drawer, /previewTodoTransition\(selection\.item, "complete"/, "Todo complete is the primary drawer action");
assert.match(drawer, /actionKind: "todo\.create"/, "Todo successor uses the canonical create action");

for (const field of ["evidence", "explanation"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Decision exposes ${field}`);
}
for (const decision of ["reject", "defer"]) {
  assert.match(drawer, new RegExp(`resolution:\\s*"${decision}"`), `Decision previews ${decision}`);
}
assert.match(drawer, /previewDecision\(selection\.item, "approve"/, "Decision approval uses a typed preview");

for (const callback of ["onRetryResumeRun", "onStartNewRunSession", "onCloseRunSession"]) {
  assert.match(model, new RegExp(`${callback}\\??:`), `Run exposes ${callback}`);
  assert.match(drawer, new RegExp(`callbacks\\.${callback}`), `Run menu calls ${callback}`);
}
assert.match(drawer, /resume_failed/, "Run recovery presents resume failure explicitly");
assert.match(drawer, /personal-run-more/, "Run secondary actions live in a compact menu");
assert.match(page, /item\.run\.runId === selection\.item\.runId/, "Run drawer refresh keeps the selected run identity");
assert.match(model, /todoId\??:/, "An execution Run keeps its Task identity");
assert.match(tasks, /查看 Session/, "A running Task exposes a visible execution Session link");
assert.match(drawer, />查看运行记录</, "Run details expose an explicit run-record entry");
assert.doesNotMatch(drawer, /agentLabel\} · \{selection\.item\.status\}/, "Run details do not expose raw status codes in the heading");
assert.match(page, /activeSessionRun/, "Opening a Session preserves the selected run in Goal state");
assert.match(page, /personal-session-record/, "Goal chat visibly identifies the loaded Session record");
assert.doesNotMatch(header, /personal-goal-tabs/, "Goal Tasks and Files no longer compete with the main timeline in the header");
for (const view of ["Goal 动态", "Tasks", "Files"]) {
  assert.match(drawer, new RegExp(`>${view}<`), `Goal detail exposes ${view}`);
}
assert.match(model, /onOpenGoalView\??:/, "Goal detail can switch the center workspace view");
for (const label of ["执行中", "已安排", "等待条件", "可继续"]) {
  assert.match(model + drawer + page, new RegExp(label), `Session and Run status language includes ${label}`);
}
assert.match(dashboard, /actionKind:\s*"run\.correct"/, "Run correction uses the scoped typed action");
assert.doesNotMatch(
  dashboard,
  /onCorrectRun:[\s\S]{0,240}sendManagerQuestion/,
  "Run correction does not fall back to the read-only manager Chat",
);
assert.match(page, /function isExecutionIntent/, "Execution routing is centralized in one intent classifier");
for (const phrase of ["用 bytedcli codebase 解决一下，push 一下", "帮我修复 MR 3960 的冲突，跑测试，然后 push"]) {
  assert.match(page, new RegExp(JSON.stringify(phrase).slice(1, -1)), `Execution routing keeps a regression example for: ${phrase}`);
}
assert.match(timeline, /待你确认/, "Historical gated proposals are grouped into a compact summary");
assert.match(timeline, /gatedItems\.length/, "The compact Gate summary exposes the pending count");
assert.match(page, /Boolean\(item\.run\.sessionId\)/, "Running count requires a discovered execution Session");
assert.match(page, /Boolean\(item\.run\.canInterrupt\)/, "Running count requires an active interruptible turn");
assert.match(page, /accept="image\/png,image\/jpeg,image\/webp,image\/gif"/, "Composer accepts bounded image types");
assert.match(page, /maxImageAttachmentCount = 4/, "Composer limits image count");
assert.match(page, /maxImageAttachmentBytes = 5 \* 1024 \* 1024/, "Composer limits image size");
assert.match(timeline, /personal-message-images/, "Sent images remain visible in the conversation");
assert.match(dashboard, /attachments: route\?\.attachments/, "Image attachments enter the selected Agent Session");

for (const field of ["agentId", "todoId", "runId", "safePreview"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Output exposes ${field}`);
}
assert.match(model, /onExportOutput\??:/, "Output exposes export callback");
assert.match(drawer, /personal-safe-preview/, "Output drawer renders a safe preview");

for (const field of ["timezone", "nextRunAt", "previousRunAt", "notificationRule", "stopCondition", "executionHistory"]) {
  assert.match(model, new RegExp(`${field}\\??:`), `Schedule exposes ${field}`);
}
assert.match(drawer, /personal-execution-history/, "Schedule drawer renders execution history");
assert.match(page, /const heartbeat = schedule\.scheduleKind === "heartbeat"/, "Schedule distinguishes heartbeat lifecycle type");
assert.match(page, /actionKind: heartbeat \? "heartbeat\.bind" : "monitor\.update"/, "Schedule previews preserve heartbeat lifecycle type");

assert.match(drawer, /event\.key === "Tab"/, "Drawer traps keyboard focus");
assert.doesNotMatch(timeline, /<div aria-live="polite" className="personal-channel-timeline">/, "The full timeline is not a live region");
assert.match(timeline, /className="personal-live-region"/, "Timeline has a dedicated live region");
assert.match(drawer, /aria-label=\{`输入纠偏信息：Goal/, "Correction label includes its scoped context");
assert.match(styles, /env\(safe-area-inset-bottom\)/, "Mobile composers respect the safe area");
assert.match(styles, /\.personal-mobile-back/, "Mobile drawer exposes a context back affordance");

assert.match(model, /repository\??:\s*WorkspaceRepositoryContext/, "Goal exposes one repository context");
assert.match(drawer, /Repository/, "Goal settings display the repository");
assert.match(drawer, /Read only/, "Repository is visibly read-only");
assert.doesNotMatch(drawer, /Add repository/, "Goal settings do not imply repository binding controls");

for (const lane of ["needs_you", "running", "observing", "scheduled", "history"]) {
  assert.match(model, new RegExp(`"${lane}"`), `Manager home models the ${lane} lane`);
}
assert.match(model, /function workspaceHomeLaneForGoal/, "Manager lane projection is centralized and testable");
assert.match(model, /goal\.state === "推进中" \|\| goal\.state === "需修复"/, "Agent-owned repair work stays in the running lane");
for (const label of ["需要你", "执行中", "观察中", "已安排", "历史"]) {
  assert.match(page, new RegExp(label), `Manager home renders ${label}`);
}
assert.match(page, /personal-home-board/, "Manager home uses the four-lane workspace board");
assert.match(page, /<details className="personal-home-history"/, "Completed work is collapsed into history");
assert.doesNotMatch(page, />接下来</, "The ambiguous 接下来 lane is not rendered");
assert.match(page, /managerNeedsYouCount[\s\S]*workspaceHomeLaneForGoal\(goal\) === "needs_you"/, "Manager greeting derives attention from the same lane projection");
assert.match(page, /你有 \{managerNeedsYouCount\} 项需要处理/, "Manager greeting shows the projected needs-you count");
assert.match(page, /managerBlockingCount[\s\S]*goal\.needsYouBlocking \|\| goal\.state === "等你"/, "Manager blocking count includes projected user waits without a parsed Todo");
assert.match(page, /其中 \{managerBlockingCount\} 项正在阻塞 Agent/, "Manager greeting shows the projected blocking count");
assert.match(dashboard, /function personalGoalState[\s\S]*hasOpenUserTodo[\s\S]*if \(\["user_or_controller", "controller"\][\s\S]*if \(personalGoalNeedsRepair/, "User gates outrank agent-owned health repair in Goal state projection");
assert.match(drawer, />进入 Goal</, "Applied Goal creation offers an explicit navigation action");

assert.match(page, /notificationSettingsOpen\s*\?\s*\(/, "Notification settings replace the center workspace");
assert.match(page, /<LarkSettingsPage/, "Pure configuration mode renders the Lark management page");
assert.match(larkSettings, /Lark Apps/, "Lark management exposes reusable Apps");
assert.match(larkSettings, /Connections/, "Lark management exposes Goal Topic connections");
for (const label of ["Connect Lark App", "Group chat", "Bind to Goal", "Create Goal topic automatically", "Topic reply"]) {
  assert.match(larkSettings, new RegExp(label), `Connect flow contains ${label}`);
}
assert.match(larkSettings, /One Lark App · many Goals · one topic per Goal/, "Connection cardinality is explicit");
assert.match(larkSettings, /connectLarkGoalTopic\([^)]*execute:\s*false/s, "Connect flow previews before execution");
assert.match(larkSettings, /connectLarkGoalTopic\([^)]*execute:\s*true/s, "Connect flow performs the approved external write");
assert.match(larkSettings, /Register another Lark App/, "App chooser exposes Feishu registration");
assert.match(larkSettings, /startLarkAppSetup/, "Registration starts through the local setup API");
assert.match(larkSettings, /fetchLarkAppSetup/, "Registration polls the local setup session");
assert.match(larkSettings, /window\.open\(/, "Registration opens the provider flow from a user gesture");
assert.match(larkSettings, /window\.open\(window\.location\.href,\s*"_blank"\)/, "Registration never leaves a blank waiting tab");
assert.match(larkSettings, /setAppRef\(snapshot\.app_ref\)/, "Completed registration selects the new App");

console.log("personal workspace drawer contract smoke passed");
