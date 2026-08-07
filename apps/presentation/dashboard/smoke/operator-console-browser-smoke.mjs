#!/usr/bin/env node

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  cleanupBrowserSmoke,
  launchBrowser,
  loadPlaywright,
} from "../../../../examples/dashboard-browser-smoke-support.mjs";

const dashboardDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.LOOPX_OPERATOR_CONSOLE_SMOKE_PORT ?? "5213");
const baseUrl = `http://127.0.0.1:${port}`;
const controlSessionToken = "fixture-control-session-must-stay-opaque";
const goalId = "operator-console-fixture";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function startDashboardServer() {
  const viteBin = resolve(dashboardDir, "node_modules/vite/bin/vite.js");
  if (!existsSync(viteBin)) {
    throw new Error(`Vite package not installed: ${viteBin}`);
  }
  const nodeBin = [
    process.env.LOOPX_NODE_BIN,
    "/opt/homebrew/bin/node",
    "/usr/local/bin/node",
    process.execPath,
  ].find((candidate) => candidate && existsSync(candidate));
  return spawn(nodeBin, [viteBin, "--host", "127.0.0.1", "--port", String(port), "--strictPort"], {
    cwd: dashboardDir,
    env: {
      ...process.env,
      PATH: ["/opt/homebrew/bin", "/usr/local/bin", process.env.PATH].filter(Boolean).join(":"),
    },
    stdio: "ignore",
  });
}

async function waitForDashboard() {
  const deadline = Date.now() + 20_000;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(baseUrl);
      if (response.ok) {
        return;
      }
      lastError = new Error(`HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolveTimeout) => setTimeout(resolveTimeout, 200));
  }
  throw lastError ?? new Error(`Timed out waiting for ${baseUrl}`);
}

function correctness() {
  return {
    atomic_revision_check: true,
    idempotent_retry: true,
    status: "core_enforced",
  };
}

function capabilities() {
  const read = [
    "application.list_goals",
    "application.describe_capabilities",
    "goal.overview",
    "goal.todos.list",
    "goal.lease.inspect",
    "goal.quota.should_run",
    "goal.history.list",
    "goal.turn.plan",
  ];
  const write = [
    "goal.configuration.preview",
    "goal.configuration.apply",
    "goal.todos.claim",
    "goal.todos.complete.preview",
    "goal.todos.complete.apply",
    "goal.lease.acquire",
    "goal.lease.renew",
    "goal.lease.release",
    "goal.quota.spend.preview",
    "goal.quota.spend.apply",
  ];
  return {
    profile: "local_operator",
    capabilities: [
      ...read.map((capability_id) => ({
        available: true,
        capability_id,
        kind: "read",
        requires_preview: false,
        scope: capability_id.startsWith("application.") ? "application" : "goal",
        supports_preview: capability_id === "goal.turn.plan",
        unavailable_reason: null,
      })),
      ...write.map((capability_id) => ({
        available: true,
        capability_id,
        kind: "write",
        requires_preview: capability_id.endsWith(".apply"),
        scope: "goal",
        supports_preview: capability_id.includes("configuration") || capability_id.includes("complete") || capability_id.includes("quota"),
        unavailable_reason: null,
      })),
      {
        available: false,
        capability_id: "goal.turn.run_once",
        kind: "execute",
        requires_preview: true,
        scope: "goal",
        supports_preview: true,
        unavailable_reason: {
          code: "cui_only",
          details: {},
          message: "Turn execution remains CUI-only.",
        },
      },
    ],
  };
}

function fixtureApiHandler() {
  let operatorRole = false;
  let sessionGeneration = 0;
  let revisionGeneration = 1;
  let conditionalRequestCount = 0;
  let mutationHeaderCount = 0;
  let failNextOperatorStatus = false;

  const state = {
    failNextOperatorStatus() {
      failNextOperatorStatus = true;
    },
    get conditionalRequestCount() {
      return conditionalRequestCount;
    },
    get mutationHeaderCount() {
      return mutationHeaderCount;
    },
  };

  async function fulfillJson(route, payload, { etag = null, status = 200 } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (etag) {
      headers.ETag = etag;
    }
    await route.fulfill({ body: JSON.stringify(payload), headers, status });
  }

  async function handle(route) {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const headers = request.headers();

    const isMutation = method !== "GET" && path !== "/api/v1/control-sessions" && !path.endsWith("/turns/plan");
    if (isMutation && headers["x-loopx-control-session"]) {
      mutationHeaderCount += 1;
    }

    if (method === "POST" && path === "/api/v1/control-sessions") {
      sessionGeneration += 1;
      operatorRole = false;
      await fulfillJson(route, {
        can_acquire: true,
        can_takeover: false,
        control_session_id: `${controlSessionToken}-${sessionGeneration}`,
        operator_slot_occupied: false,
        profile: "local_operator",
        role: "viewer",
      }, { status: 201 });
      return;
    }

    if (method === "GET" && path === "/api/v1/operator") {
      if (failNextOperatorStatus) {
        failNextOperatorStatus = false;
        await fulfillJson(route, {
          error: {
            code: "invalid_control_session",
            details: {},
            message: "Control session no longer exists after server restart.",
            retryable: false,
          },
        }, { status: 401 });
        return;
      }
      await fulfillJson(route, {
        can_acquire: !operatorRole,
        can_takeover: false,
        changed: false,
        operator_slot_occupied: operatorRole,
        profile: "local_operator",
        role: operatorRole ? "operator" : "viewer",
      });
      return;
    }

    if (method === "POST" && path === "/api/v1/operator/acquire") {
      operatorRole = true;
      await fulfillJson(route, {
        can_acquire: false,
        can_takeover: false,
        changed: true,
        operator_slot_occupied: true,
        profile: "local_operator",
        role: "operator",
      });
      return;
    }

    if (method === "POST" && path === "/api/v1/operator/release") {
      operatorRole = false;
      await fulfillJson(route, {
        can_acquire: true,
        can_takeover: false,
        changed: true,
        operator_slot_occupied: false,
        profile: "local_operator",
        role: "viewer",
      });
      return;
    }

    const etag = `"operator-fixture-${path}-${revisionGeneration}"`;
    if (method === "GET" && headers["if-none-match"] === etag) {
      conditionalRequestCount += 1;
      await route.fulfill({ headers: { ETag: etag }, status: 304 });
      return;
    }

    if (method === "GET" && path === "/api/v1/capabilities") {
      await fulfillJson(route, capabilities(), { etag });
      return;
    }
    if (method === "GET" && path === "/api/v1/goals") {
      await fulfillJson(route, {
        generated_at: "2026-08-07T09:00:00Z",
        goals: [
          {
            domain: "application-server",
            generated_at: "2026-08-07T09:00:00Z",
            goal_id: goalId,
            revision: "sha256:fixture-goal-1",
            status: "active_delivery",
          },
          {
            domain: "release-readiness",
            generated_at: "2026-08-07T08:58:00Z",
            goal_id: "operator-console-secondary",
            revision: "sha256:fixture-goal-2",
            status: "waiting_on_owner",
          },
        ],
        revision: `sha256:goals-${revisionGeneration}`,
      }, { etag });
      return;
    }
    if (method === "GET" && path === `/api/v1/goals/${goalId}/overview`) {
      await fulfillJson(route, {
        adapter_kind: "native",
        adapter_status: "ready",
        attention_status: "action",
        domain: "application-server",
        generated_at: "2026-08-07T09:00:00Z",
        goal_id: goalId,
        revision: `sha256:overview-${revisionGeneration}`,
        route_status: "canonical",
        routed_to_source_registry: true,
        status: "active_delivery",
      }, { etag });
      return;
    }
    if (method === "GET" && path === `/api/v1/goals/${goalId}/todos`) {
      await fulfillJson(route, {
        generated_at: "2026-08-07T09:00:00Z",
        goal_id: goalId,
        items: [
          {
            action_kind: "implementation",
            blocks_agent: null,
            claimed_by: null,
            role: "agent",
            status: "open",
            successor_todo_ids: [],
            task_class: "advancement_task",
            text: "Finish the typed Operator Console and preserve the public frontstage.",
            todo_id: "todo_operator_console",
            updated_at: "2026-08-07T08:59:00Z",
          },
          {
            action_kind: "owner_review",
            blocks_agent: "codex",
            claimed_by: "owner",
            role: "user",
            status: "open",
            successor_todo_ids: [],
            task_class: "user_gate",
            text: "Review the first visible Operator Console viewport.",
            todo_id: "todo_owner_first_screen",
            updated_at: "2026-08-07T08:58:00Z",
          },
        ],
        revision: `sha256:todos-${revisionGeneration}`,
      }, { etag });
      return;
    }
    if (method === "GET" && path === `/api/v1/goals/${goalId}/quota/should-run`) {
      await fulfillJson(route, {
        action_required: true,
        agent_id: "codex",
        budget: { allowed_slots: 24, compute: 1, slot_minutes: 60, spent_slots: 7, window_hours: 24 },
        decision: "eligible",
        delivery_allowed: true,
        effective_action: "implement_operator_console",
        envelope_verified: true,
        envelope_within_budget: true,
        generated_at: "2026-08-07T09:00:00Z",
        goal_id: goalId,
        must_attempt: true,
        open_count: 2,
        quiet_noop_allowed: false,
        reason: "Open advancement work remains within the bounded quota envelope.",
        recommended_action: "Complete implementation, then request owner first-screen review.",
        revision: `sha256:quota-${revisionGeneration}`,
        route_status: "canonical",
        selected_todo_id: "todo_operator_console",
        should_run: true,
        state: "eligible",
      }, { etag });
      return;
    }
    if (method === "GET" && path === `/api/v1/goals/${goalId}/history`) {
      await fulfillJson(route, {
        generated_at: "2026-08-07T09:00:00Z",
        goal_id: goalId,
        items: [
          {
            agent_id: "codex",
            artifacts_verified: true,
            classification: "typed_http_surface_complete",
            delivery_outcome: "primary_goal_outcome",
            generated_at: "2026-08-07T08:55:00Z",
            json_available: true,
            markdown_available: true,
            progress_scope: "application_server_v1",
            run_id: "run-operator-console-001",
          },
          {
            agent_id: "codex-peer",
            artifacts_verified: true,
            classification: "official_client_chain_verified",
            delivery_outcome: "validation",
            generated_at: "2026-08-07T08:40:00Z",
            json_available: true,
            markdown_available: false,
            progress_scope: "generated_client",
            run_id: "run-operator-console-000",
          },
        ],
        next_page_token: null,
        revision: `sha256:history-${revisionGeneration}`,
        total_count: 2,
      }, { etag });
      return;
    }
    if (method === "GET" && path === `/api/v1/goals/${goalId}/leases/todo_operator_console`) {
      await fulfillJson(route, {
        active: false,
        constraint_reason: null,
        generated_at: "2026-08-07T09:00:00Z",
        goal_id: goalId,
        lease: null,
        todo_id: "todo_operator_console",
      }, { etag });
      return;
    }

    if (method === "POST" && path === `/api/v1/goals/${goalId}/configuration/preview`) {
      await fulfillJson(route, {
        can_apply: true,
        changed: true,
        correctness: correctness(),
        effects: [
          { after: 2, before: 1, field: "quota_compute" },
          { after: 36, before: 24, field: "quota_window_hours" },
        ],
        generated_at: "2026-08-07T09:01:00Z",
        goal_id: goalId,
        plan_hash: "sha256:configuration-plan-fixture",
        revision: `sha256:overview-${revisionGeneration}`,
        warnings: ["Quota changes affect future admission decisions only."],
      });
      return;
    }
    if (method === "POST" && path === `/api/v1/goals/${goalId}/configuration/apply`) {
      revisionGeneration += 1;
      await fulfillJson(route, {
        changed: true,
        correctness: correctness(),
        generated_at: "2026-08-07T09:02:00Z",
        global_sync_verified: true,
        goal_id: goalId,
        plan_hash: "sha256:configuration-plan-fixture",
        previous_revision: "sha256:overview-1",
        revision: `sha256:overview-${revisionGeneration}`,
        written: true,
      });
      return;
    }
    if (method === "POST" && path.endsWith("/turns/plan")) {
      await fulfillJson(route, {
        agent_id: "local-operator",
        can_run: true,
        canonical_route_status: "canonical",
        commit_coordinator_available: true,
        core_contract_valid: true,
        execution_authorized: true,
        executor_available: true,
        generated_at: "2026-08-07T09:03:00Z",
        goal_id: goalId,
        plan_hash: "sha256:turn-plan-fixture",
        revision: `sha256:turn-${revisionGeneration}`,
        route: "source_registry",
        routed_to_source_registry: true,
        selected_todo_id: "todo_operator_console",
        turn_key: "fixture-turn-key",
        unavailable_reasons: [],
        would_invoke_host: true,
      });
      return;
    }

    await fulfillJson(route, {
      error: {
        code: "fixture_route_missing",
        details: { method, path },
        message: `No fixture response for ${method} ${path}`,
        retryable: false,
      },
    }, { status: 404 });
  }

  return { handle, state };
}

async function assertNoHorizontalOverflow(page, label) {
  const report = await page.evaluate(() => ({
    scrollWidth: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
    viewportWidth: window.innerWidth,
  }));
  assert(report.scrollWidth <= report.viewportWidth + 2, `${label} horizontal overflow: ${JSON.stringify(report)}`);
}

async function main() {
  const { chromium } = loadPlaywright();
  const server = startDashboardServer();
  let browser;
  try {
    await waitForDashboard();
    browser = await launchBrowser(chromium);
    const fixture = fixtureApiHandler();
    const page = await browser.newPage({ viewport: { height: 980, width: 1440 } });
    const pageErrors = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/api/v1/**", fixture.handle);
    await page.goto(`${baseUrl}/operator?goalId=${goalId}`, { waitUntil: "networkidle" });
    await page.getByTestId("operator-console-route").waitFor();
    await page.getByRole("button", { name: "Acquire operator" }).waitFor();

    let bodyText = await page.locator("body").innerText();
    for (const expected of [
      "LoopX",
      "Operator Console",
      "Authority session",
      "Local operator profile",
      "Finish the typed Operator Console",
      "Recent history",
      "3s conditional polling",
    ]) {
      assert(bodyText.includes(expected), `missing first-screen browser text: ${expected}`);
    }
    assert(bodyText.toLowerCase().includes("viewer"), "default viewer role is not visible");
    assert(!bodyText.includes(controlSessionToken), "control session token leaked into the visible console");
    assert(await page.getByRole("button", { name: "Acquire operator" }).isEnabled(), "default viewer cannot acquire operator");

    await page.getByRole("button", { name: "Acquire operator" }).click();
    await page.getByText("Operator authority is active for this control session.").waitFor();
    await page.getByLabel("Quota compute").fill("2");
    await page.getByLabel("Quota window hours").fill("36");
    await page.getByRole("button", { name: "Preview configuration" }).click();
    await page.getByTestId("operator-configuration-preview").waitFor();
    bodyText = await page.getByTestId("operator-configuration-preview").innerText();
    assert(bodyText.includes("quota_compute"), "configuration preview did not show field effects");
    assert(bodyText.includes("Quota changes affect future admission decisions only."), "configuration warning missing");
    await page.getByRole("button", { name: "Apply reviewed plan" }).click();
    await page.getByText("Configuration applied with revision and idempotency checks.").waitFor();
    assert(fixture.state.mutationHeaderCount >= 3, "generated client did not attach the opaque control session header to mutations");

    await page.getByRole("tab", { name: /Turn plan/ }).click();
    await page.getByText("Turn execution stays CUI-only.", { exact: false }).waitFor();
    assert((await page.getByText("Read capability is ready; operator authority is not required.").count()) === 1, "turn plan did not present its viewer-readable gate");
    await page.getByRole("button", { name: "Compute turn plan" }).click();
    await page.getByTestId("operator-turn-preview").waitFor();
    bodyText = await page.locator("body").innerText();
    assert(!bodyText.includes("Run once"), "browser exposed a run-once affordance");
    assert(!bodyText.includes("Execute command"), "browser exposed an arbitrary command affordance");

    await page.waitForTimeout(3_400);
    assert(fixture.state.conditionalRequestCount > 0, "polling did not issue If-None-Match conditional reads");

    fixture.state.failNextOperatorStatus();
    await page.getByRole("button", { name: "Refresh operator projections" }).click();
    await page.getByRole("button", { name: "Rebuild control session" }).waitFor();
    await page.getByRole("button", { name: "Rebuild control session" }).click();
    await page.getByText("Control session rebuilt as a viewer.", { exact: false }).waitFor();
    await page.getByRole("button", { name: "Acquire operator" }).waitFor();

    await assertNoHorizontalOverflow(page, "desktop operator console");
    await page.screenshot({
      animations: "disabled",
      fullPage: true,
      path: "/tmp/loopx-operator-console-browser-smoke.png",
    });

    const mobile = await browser.newPage({ viewport: { height: 844, width: 390 } });
    await mobile.route("**/api/v1/**", fixture.handle);
    await mobile.goto(`${baseUrl}/operator?goalId=${goalId}`, { waitUntil: "networkidle" });
    await mobile.getByTestId("operator-console-route").waitFor();
    await assertNoHorizontalOverflow(mobile, "mobile operator console");
    assert(pageErrors.length === 0, `operator console page errors: ${pageErrors.join(" | ")}`);

    console.log("operator-console-browser-smoke ok");
  } finally {
    await cleanupBrowserSmoke({ browser, fixturePaths: [], server });
  }
}

await main();
