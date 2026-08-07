// @ts-expect-error The standalone smoke intentionally compiles without @types/node.
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

const routerSource = readFileSync("src/router.tsx", "utf8");
const pageSource = readFileSync("src/views/operator-console-page.tsx", "utf8");
const apiSource = readFileSync("src/api/operator-console.ts", "utf8");
const generatedClientSource = readFileSync("src/api/generated/client.ts", "utf8");
const uiSource = readFileSync("src/components/operator-console/operator-console-ui.tsx", "utf8");
const stylesSource = readFileSync("src/styles.css", "utf8");

includes(routerSource, 'path: "/operator"', "operator side route");
includes(routerSource, "lazyRouteComponent", "operator route code splitting");
includes(routerSource, 'import("./views/operator-console-page")', "operator lazy module");
excludes(routerSource, 'import { OperatorConsolePage } from "./views/operator-console-page"', "eager operator page import");
includes(routerSource, 'path: "/frontstage"', "preserved public frontstage route");
includes(routerSource, 'path: "/"', "preserved dashboard home route");

includes(apiSource, 'from "./generated/client"', "official generated client usage");
includes(apiSource, "ifNoneMatch", "conditional projection reads");
includes(apiSource, "result.response.status === 304", "304 cache reuse");
includes(apiSource, "projectionCache", "per-resource ETag cache");
includes(apiSource, "resetOperatorControlSession", "server restart session recovery");
includes(apiSource, 'generated.setControlSession(null)', "invalid session clearing");
includes(generatedClientSource, "openapi-fetch", "official openapi-fetch generator output");

includes(pageSource, "visiblePollMs = 3_000", "visible conditional polling cadence");
includes(pageSource, "hiddenPollMs = 30_000", "hidden-page polling slowdown");
includes(pageSource, "refetchIntervalInBackground: true", "explicit hidden-page polling policy");
includes(uiSource, 'data-testid="operator-freshness"', "freshness readout");
includes(pageSource, "manualRefresh", "manual refresh action");
includes(pageSource, "const goalRefetches = selectedGoalId", "empty-goal refresh guard");
includes(pageSource, "Rebuild control session", "invalid control session recovery UI");
excludes(pageSource, "control_session_id.slice", "control session token projection");

includes(pageSource, "describe_capabilities()", "capability-driven action copy");
includes(pageSource, "capabilityMap", "capability lookup");
includes(pageSource, "canWrite", "operator plus capability gate");
includes(pageSource, "Confirm takeover", "explicit takeover confirmation");
includes(pageSource, "Read-only profile", "server profile presentation");
includes(pageSource, "Acquire operator", "viewer-to-operator control");
includes(pageSource, "Release role", "operator release control");

includes(pageSource, "Preview configuration", "configuration preview");
includes(pageSource, "Apply reviewed plan", "configuration apply");
includes(pageSource, "Preview completion", "todo completion preview");
includes(pageSource, "Apply completion", "todo completion apply");
includes(pageSource, "Preview spend", "quota spend preview");
includes(pageSource, "Apply quota spend", "quota spend apply");
includes(pageSource, "Acquire lease", "lease action");
includes(pageSource, "Compute turn plan", "viewer-readable turn planning");
includes(pageSource, "requiresOperator={false}", "read-only turn capability gate");
includes(pageSource, "Turn execution stays CUI-only", "CUI execution boundary");
excludes(apiSource, '"/api/v1/goals/{goal_id}/turns/run', "browser turn execution endpoint");
excludes(pageSource, "run_once", "run-once browser affordance");
excludes(pageSource, "shell command", "arbitrary shell command affordance");

includes(stylesSource, ".operator-console", "isolated operator visual system");
includes(stylesSource, ".operator-workspace", "operator cockpit layout");
includes(stylesSource, "@media (max-width: 900px)", "tablet operator layout");
includes(stylesSource, "@media (max-width: 640px)", "mobile operator layout");

console.log("operator-console-route-smoke ok");
