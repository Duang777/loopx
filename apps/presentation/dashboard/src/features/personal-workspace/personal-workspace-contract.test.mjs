import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (name) => readFileSync(new URL(name, import.meta.url), "utf8");
const model = source("./personal-workspace-model.ts");
const drawer = source("./context-drawer.tsx");
const page = source("./personal-workspace-page.tsx");
const timeline = source("./channel-timeline.tsx");
const larkSettings = source("./lark-settings-page.tsx");
const styles = source("./personal-workspace.css");

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

console.log("personal workspace drawer contract smoke passed");
