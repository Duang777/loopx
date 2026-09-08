#!/usr/bin/env node
// Exercise replacement surfaces and old bookmarks through the real browser router.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { dirname, resolve, extname } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dashboard = resolve(root, "apps/presentation/dashboard");
const require = createRequire(resolve(dashboard, "package.json"));
const { chromium } = require("playwright");
const exportSite = process.env.LOOPX_PUBLIC_SITE_DIR ?? "/tmp/loopx-frontstage-share-bundle-smoke/site";
const output = resolve(root, "output/playwright/home-navigation");
await mkdir(output, { recursive: true });
const child = spawn(process.execPath, [resolve(dashboard, "node_modules/vite/bin/vite.js"), "--host", "127.0.0.1", "--port", "5197", "--strictPort"], { cwd: dashboard, stdio: "pipe" });
let logs = "";
child.stdout.on("data", (v) => { logs += v; });
child.stderr.on("data", (v) => { logs += v; });
const staticServer = createServer(async (req, res) => {
  const path = new URL(req.url, "http://localhost").pathname;
  if (!path.startsWith("/loopx/")) { res.writeHead(404).end(); return; }
  const file = resolve(exportSite, path.slice(7) + (path.endsWith("/") ? "index.html" : ""));
  if (!file.startsWith(resolve(exportSite) + "/")) { res.writeHead(403).end(); return; }
  try {
    const body = await readFile(file);
    res.setHeader("Content-Type", ({ ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml" })[extname(file)] ?? "application/octet-stream");
    res.end(body);
  } catch { res.writeHead(404).end(); }
});
await new Promise((done) => staticServer.listen(0, "127.0.0.1", done));
const publicOrigin = `http://127.0.0.1:${staticServer.address().port}`;
async function assertAnchorInView(page, id) {
  await page.waitForFunction((id) => {
    const section = document.getElementById(id);
    if (!section) return false;
    const top = section.getBoundingClientRect().top;
    const heading = section.querySelector("h2")?.getBoundingClientRect();
    return top >= -2 && top < 80 && heading && heading.top >= 0 && heading.bottom < innerHeight;
  }, id, { timeout: 4000 });
}

let browser;
try {
  for (let i = 0; ; i++) {
    try { if ((await fetch("http://127.0.0.1:5197/")).ok) break; } catch {}
    if (i > 100 || child.exitCode !== null) throw new Error(`Vite did not start: ${logs}`);
    await new Promise((done) => setTimeout(done, 200));
  }
  browser = await chromium.launch({ headless: true });
  // A shared fragment URL must land on its section without any test-driven
  // scroll or focus. Use cold pages and delayed JS to cover pre-React parsing.
  for (const reducedMotion of ["no-preference", "reduce"]) {
    for (const width of [1440, 390]) {
      const entryContext = await browser.newContext({ reducedMotion, viewport: { width, height: 900 } });
      const entry = await entryContext.newPage();
      const entryErrors = [];
      entry.on("pageerror", (error) => entryErrors.push(error.message));
      await entry.route("**/site-assets/*.js", async (route) => {
        await new Promise((done) => setTimeout(done, 250));
        await route.continue();
      });
      for (const lang of ["en", "zh"]) {
        await entry.goto("about:blank");
        await entry.goto(`${publicOrigin}/loopx/?lang=${lang}#explore`);
        await assertAnchorInView(entry, "explore");
        await entry.reload();
        await assertAnchorInView(entry, "explore");
      }
      for (const fragment of ["learn", "%65xplore"]) {
        await entry.goto(`${publicOrigin}/loopx/?lang=zh#${fragment}`);
        await assertAnchorInView(entry, decodeURIComponent(fragment));
      }
      for (const fragment of ["", "missing-section", "%zz"]) {
        await entry.goto("about:blank");
        await entry.goto(`${publicOrigin}/loopx/?lang=zh#${fragment}`);
        await entry.locator("#explore").waitFor();
        assert.equal(await entry.evaluate(() => scrollY), 0, "missing fragments must preserve normal page entry");
      }
      assert.deepEqual(entryErrors, [], "fragment entry must not raise runtime errors");
      await entryContext.close();
    }
  }
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.route((url) => url.pathname === "/status.example.json", async (route) => route.fulfill({ contentType: "application/json", body: await readFile(resolve(root, "examples/status.example.json"), "utf8") }));
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const privateRequests = [];
  await page.route((url) => url.pathname === "/private-status.json", (route) => { privateRequests.push(route.request().url()); return route.abort(); });
  // Resolve the public destination to the actual exported case directory in this test.
  await page.route("https://huangruiteng.github.io/loopx/**", (route) => {
    return route.fulfill({ status: 200, contentType: "text/html", body: "<h1>Public destination</h1>" });
  });
  for (const route of ["/frontstage?statusUrl=/private-status.json", "/frontstage?mode=showcase&statusUrl=https://example.com/private-status.json"]) {
    await page.goto(`http://127.0.0.1:5197${route}`);
    await page.waitForURL("https://huangruiteng.github.io/loopx/docs/showcases/index.en.html");
  }
  for (const route of ["/frontstage?mode=developer", "/frontstage/developer"]) {
    await page.goto(`http://127.0.0.1:5197${route}`);
    await page.waitForURL("**/developers/projections");
    await page.locator('[data-testid="frontstage-developer-cockpit"]').waitFor();
  }
  for (const route of ["/frontstage?mode=ops&", "/deprecated/frontstage/ops?"]) {
    await page.goto(`http://127.0.0.1:5197${route}goalId=demo&statusUrl=https://example.com/private-status.json`);
    await page.getByRole("alert").filter({ hasText: "relative or loopback" }).waitFor();
    await page.goto(`http://127.0.0.1:5197${route}goalId=demo&statusUrl=/status.example.json`);
    await page.waitForURL((url) => url.pathname === "/" && url.searchParams.get("goalId") === "demo" && url.searchParams.get("statusUrl") === "/status.example.json");
    await page.locator(".personal-workspace-shell").waitFor();
  }
  assert.deepEqual(privateRequests, [], "retired/public URLs must not read rejected status sources");
  for (const [route, target] of [
    ["frontstage/?mode=ops&statusUrl=/private-status.json", "/loopx/docs/showcases/index.en.html"],
    ["frontstage/developer/", "/loopx/developers/projections/"],
  ]) {
    await page.goto(`${publicOrigin}/loopx/${route}`);
    await page.waitForURL(`${publicOrigin}${target}`);
  }
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const lang of ["en", "zh"]) {
      await page.goto(`${publicOrigin}/loopx/?lang=${lang}`);
      await page.locator("#explore").waitFor();
      assert.equal(await page.locator("html").getAttribute("lang"), lang === "zh" ? "zh-CN" : "en");
      assert.equal(await page.locator('a[href*="deprecated"], a[href*="frontstage/"]').count(), 0);
      const expected = ["docs/guides/personal-workspace-user-guide/", `benchmarks/swe-marathon/${lang === "zh" ? "?lang=zh" : ""}`, "benchmarks/deepswe/behavior-discovery/", `docs/showcases/index${lang === "en" ? ".en" : ""}.html`];
      assert.deepEqual(await page.locator("#explore .resource-card").evaluateAll((links) => links.map((a) => a.getAttribute("href"))), expected.map((path) => `/loopx/${path}`));
      if (width === 390) {
        await page.getByRole("button", { name: "Open navigation" }).click();
        await page.locator('.mobile-nav a[href="#explore"]').click();
        assert.equal(await page.locator(".mobile-nav").count(), 0);
      } else {
        await page.screenshot({ path: resolve(output, `home-${lang}-desktop.png`) });
        await page.locator('.desktop-nav a[href="#explore"]').click();
      }
      await assertAnchorInView(page, "explore");
      await page.locator("#explore .resource-card").first().focus();
      assert.ok(await page.locator("#explore .resource-card").first().evaluate((a) => a === document.activeElement));
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "horizontal overflow");
      await page.screenshot({ path: resolve(output, `explore-${lang}-${width}.png`) });
      // Follow the actual research and case links; the guide is built by MkDocs later.
      for (let i = process.env.LOOPX_PUBLIC_SITE_DIR ? 0 : 1; i < expected.length; i++) {
        await page.goto(`${publicOrigin}/loopx/${expected[i]}`);
        await page.locator("h1").first().waitFor();
      }
    }
  }
  assert.deepEqual(errors, [], "browser runtime errors");
  console.log("public navigation and Frontstage migration browser smoke: ok");
} finally {
  await browser?.close();
  child.kill("SIGTERM");
  staticServer.closeAllConnections();
  await new Promise((done) => staticServer.close(done));
}
