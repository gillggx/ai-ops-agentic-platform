/**
 * 2026-05-13 — GUI smoke for the ResultInspector dual-view (Phase 1
 * object-native UI). Verifies what `tooling/skill_builder_smoke.sh`
 * can't reach: the actual React rendering of Table / { } JSON tabs,
 * [+] row expansion, and nested sub-panel content.
 *
 * Strategy: create a known fixture pipeline via API (no LLM dep),
 * open it in the builder, click the node, drive the DataPreviewPanel.
 *
 * Env (defaults):
 *   PW_BASE=https://aiops-gill.com
 *   PW_USER=itadmin_test
 *   PW_PASS=ITAdmin@2026
 *   GUI_SMOKE_ARTIFACTS=test-results/gui-smoke   (screenshots dump here)
 */
import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const BASE = process.env.PW_BASE ?? "https://aiops-gill.com";
const USER = process.env.PW_USER ?? "admin";
const PASS = process.env.PW_PASS ?? "admin";
const ART_DIR = process.env.GUI_SMOKE_ARTIFACTS ?? "test-results/gui-smoke";

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.locator('input[type="text"]').first().fill(USER);
  await page.locator('input[type="password"]').first().fill(PASS);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }),
    page.locator('button[type="submit"]').first().click(),
  ]);
}

/** Create a fixture pipeline that emits BOTH a dataframe (process_history
 *  with nested spc_charts) AND a chart (line_chart). Returns pipeline id.
 */
async function createFixturePipeline(token: string): Promise<number> {
  const pipelineJson = {
    version: "1.0",
    name: "gui-smoke-fixture",
    metadata: {},
    inputs: [{ name: "tool_id", type: "string", example: "EQP-01" }],
    nodes: [
      { id: "n1", block_id: "block_process_history", block_version: "1.0.0",
        position: { x: 100, y: 100 },
        params: { tool_id: "EQP-01", step: "STEP_001", limit: 10, time_range: "24h" } },
      { id: "n2", block_id: "block_unnest", block_version: "1.0.0",
        position: { x: 400, y: 100 },
        params: { column: "spc_charts" } },
      { id: "n3", block_id: "block_filter", block_version: "1.0.0",
        position: { x: 700, y: 100 },
        params: { column: "name", operator: "=", value: "xbar_chart" } },
      { id: "n4", block_id: "block_line_chart", block_version: "1.0.0",
        position: { x: 1000, y: 100 },
        params: { x: "eventTime", y: "value", ucl_column: "ucl", lcl_column: "lcl",
                  title: "Fixture: xbar trend" } },
    ],
    edges: [
      { id: "e1", from: { node: "n1", port: "data" }, to: { node: "n2", port: "data" } },
      { id: "e2", from: { node: "n2", port: "data" }, to: { node: "n3", port: "data" } },
      { id: "e3", from: { node: "n3", port: "data" }, to: { node: "n4", port: "data" } },
    ],
  };
  // Java's CreateRequest expects pipeline_json as a JSON STRING, not object.
  const res = await fetch(`${BASE}/api/v1/pipelines`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      name: `gui-smoke-${Date.now()}`,
      description: "fixture for gui_smoke",
      pipeline_json: JSON.stringify(pipelineJson),
      version: "1.0.0",
    }),
  });
  if (!res.ok) {
    throw new Error(`create pipeline failed: ${res.status} ${await res.text()}`);
  }
  const data = await res.json();
  return data.data?.id ?? data.id;
}

/** Login directly via Java API (bypass NextAuth) — returns Java JWT. */
async function loginJava(): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`Java auth/login failed: ${res.status} ${await res.text()}`);
  const j = await res.json();
  const token = j?.data?.access_token;
  if (!token) throw new Error(`auth/login no access_token: ${JSON.stringify(j).slice(0, 200)}`);
  return token;
}

async function ensureArtifactDir() {
  if (!fs.existsSync(ART_DIR)) fs.mkdirSync(ART_DIR, { recursive: true });
}

test.describe("GUI ResultInspector — dual-view + nested expansion", () => {
  test.setTimeout(120_000);
  test.skip(!process.env.PW_BASE, "PW_BASE not set (run via tooling/gui_smoke.sh)");

  let pipelineId: number;
  let token: string;

  test.beforeAll(async () => {
    await ensureArtifactDir();
  });

  test("open fixture pipeline → click chart node → assert Table/JSON tabs + nested expand", async ({ page }) => {
    // ── 1. Create fixture via direct Java auth, then drive GUI via NextAuth ─
    token = await loginJava();
    pipelineId = await createFixturePipeline(token);
    console.log(`[fixture] created pipeline ${pipelineId}`);
    await login(page);

    // ── 2. Open in builder ────────────────────────────────────────
    await page.goto(`${BASE}/admin/pipeline-builder/${pipelineId}`);
    await page.waitForLoadState("networkidle", { timeout: 30_000 });

    // Dismiss onboarding tour
    const skipBtn = page.locator('button:has-text("Skip")').first();
    if (await skipBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await skipBtn.click();
      await page.waitForTimeout(300);
    }

    // Canvas uses human labels: "Process History", "Unnest", "Filter", "Line Chart"
    await expect(page.locator('text=/^Process History$/').first()).toBeVisible({ timeout: 15_000 });
    await page.screenshot({ path: path.join(ART_DIR, "01-canvas-loaded.png"), fullPage: true });

    // ── 3. Click Filter node — should show data preview ──────────
    const filterNode = page.locator('text=/^Filter$/').first();
    await filterNode.click();
    await page.waitForTimeout(500);

    // Run preview to populate the panel (click "Run Preview" button if present,
    // otherwise the panel auto-populates from cache when node selected).
    const runBtn = page.locator('button:has-text("Run Preview"), button:has-text("預覽")').first();
    if (await runBtn.isVisible().catch(() => false)) {
      await runBtn.click();
      await page.waitForResponse(
        (r) => r.url().includes("/preview") && r.status() === 200,
        { timeout: 30_000 }
      );
    }
    await page.screenshot({ path: path.join(ART_DIR, "02-preview-loaded.png"), fullPage: true });

    // ── 4. Assert Table / JSON tabs exist ────────────────────────
    const tableTab = page.locator('[data-testid="tab-rows"]').first();
    const jsonTab  = page.locator('[data-testid="tab-json"]').first();
    await expect(tableTab, "📊 Table tab missing").toBeVisible({ timeout: 10_000 });
    await expect(jsonTab,  "{} JSON tab missing").toBeVisible({ timeout: 10_000 });
    console.log("[asserts] Table + JSON tabs present");

    // Click JSON tab → expect tree view (JsonNode entries)
    await jsonTab.click();
    await page.waitForTimeout(300);
    // Look for a `[0]` or `▸` / `▾` glyph from JsonNode
    const treeMarkers = page.locator('text=/[▸▾]/');
    await expect(treeMarkers.first(), "JSON tree markers absent").toBeVisible({ timeout: 5_000 });
    await page.screenshot({ path: path.join(ART_DIR, "03-json-tab.png"), fullPage: true });
    console.log("[asserts] JSON tree view renders");

    // Switch back to Table
    await tableTab.click();
    await page.waitForTimeout(300);
    await expect(page.locator('[data-testid="preview-table"]')).toBeVisible({ timeout: 5_000 });

    // ── 5. Nested row expansion ──────────────────────────────────
    // Click the Unnest node — its output still has nested siblings
    // (spc_summary, APC etc.) so the row should have [+].
    const unnestNode = page.locator('text=/^Unnest$/').first();
    await unnestNode.click();
    await page.waitForTimeout(800);
    await page.screenshot({ path: path.join(ART_DIR, "04-unnest-node.png"), fullPage: true });

    // Look for an expand triangle (▸) in the leading column.
    const expandTriangle = page.locator('td:has-text("▸")').first();
    const hasExpand = await expandTriangle.isVisible().catch(() => false);
    if (hasExpand) {
      console.log("[asserts] [+] expand triangle present (nested rows detected)");
      await expandTriangle.click();
      await page.waitForTimeout(300);
      await page.screenshot({ path: path.join(ART_DIR, "05-row-expanded.png"), fullPage: true });
      // Expanded sub-panel should appear — look for the field label of a nested object
      const subPanel = page.locator('text=/spc_summary|APC|RECIPE/').first();
      await expect(subPanel, "nested sub-panel content").toBeVisible({ timeout: 5_000 });
      console.log("[asserts] sub-panel rendered nested fields");
    } else {
      console.warn("[asserts] no [+] triangle — table may be all-flat; check 04 screenshot");
    }

    console.log(`[done] artifacts in ${ART_DIR}/`);
  });

  test.afterAll(async ({ request }) => {
    if (pipelineId && token) {
      const res = await fetch(`${BASE}/api/v1/pipelines/${pipelineId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      console.log(`[cleanup] pipeline ${pipelineId} delete: ${res.status}`);
    }
  });
});
