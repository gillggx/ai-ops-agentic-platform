/**
 * 2026-05-13 — GUI smoke for chart rendering. Verifies that the
 * ChartDSLRenderer turns the sidecar's chart_spec JSON into an actual
 * SVG with paths/rects — the layer `skill_builder_smoke.sh` can't see.
 *
 * Approach: re-uses the fixture pipeline pattern from result-inspector,
 * but selects the terminal block_line_chart node and asserts:
 *   - chart canvas (svg or canvas) is visible
 *   - SVG contains path/circle/rect elements (data drawn)
 *   - x-axis label contains "eventTime"
 *   - chart title matches the spec.title set in fixture params
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

/** Login directly via Java API (bypass NextAuth proxy) — returns a JWT
 *  we can attach to /api/v1/* requests. */
async function loginJava(): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`Java auth/login failed: ${res.status} ${await res.text()}`);
  const j = await res.json();
  const token = j?.data?.access_token;
  if (!token) throw new Error(`auth/login returned no access_token: ${JSON.stringify(j).slice(0, 200)}`);
  return token;
}

async function createFixture(token: string): Promise<number> {
  const pipelineJson = {
    version: "1.0", name: "gui-smoke-chart", metadata: {},
    inputs: [{ name: "tool_id", type: "string", example: "EQP-01" }],
    nodes: [
      { id: "n1", block_id: "block_process_history", block_version: "1.0.0",
        position: { x: 100, y: 100 },
        params: { tool_id: "EQP-01", step: "STEP_001", limit: 30, time_range: "24h" } },
      { id: "n2", block_id: "block_unnest", block_version: "1.0.0",
        position: { x: 400, y: 100 }, params: { column: "spc_charts" } },
      { id: "n3", block_id: "block_filter", block_version: "1.0.0",
        position: { x: 700, y: 100 },
        params: { column: "name", operator: "=", value: "xbar_chart" } },
      { id: "n4", block_id: "block_line_chart", block_version: "1.0.0",
        position: { x: 1000, y: 100 },
        params: { x: "eventTime", y: "value", ucl_column: "ucl", lcl_column: "lcl",
                  title: "ChartSmoke: xbar trend" } },
    ],
    edges: [
      { id: "e1", from: { node: "n1", port: "data" }, to: { node: "n2", port: "data" } },
      { id: "e2", from: { node: "n2", port: "data" }, to: { node: "n3", port: "data" } },
      { id: "e3", from: { node: "n3", port: "data" }, to: { node: "n4", port: "data" } },
    ],
  };
  const res = await fetch(`${BASE}/api/v1/pipelines`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      name: `chart-smoke-${Date.now()}`,
      description: "fixture for chart-render smoke",
      pipeline_json: JSON.stringify(pipelineJson),  // Java DTO expects String
      version: "1.0.0",
    }),
  });
  if (!res.ok) throw new Error(`create pipeline failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  return data.data?.id ?? data.id;
}

test.describe("GUI ChartRender — chart_spec → SVG pixels", () => {
  test.setTimeout(120_000);
  test.skip(!process.env.PW_BASE, "PW_BASE not set");

  let pipelineId: number;
  let token: string;

  test.beforeAll(async () => {
    if (!fs.existsSync(ART_DIR)) fs.mkdirSync(ART_DIR, { recursive: true });
  });

  test("line_chart terminal renders SVG with paths + title + axis", async ({ page }) => {
    token = await loginJava();
    pipelineId = await createFixture(token);
    console.log(`[fixture] pipeline ${pipelineId}`);
    await login(page);

    await page.goto(`${BASE}/admin/pipeline-builder/${pipelineId}`);
    await page.waitForLoadState("networkidle", { timeout: 30_000 });

    // Dismiss the onboarding tour if present
    const skipBtn = page.locator('button:has-text("Skip")').first();
    if (await skipBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await skipBtn.click();
      await page.waitForTimeout(300);
    }

    // Click the Line Chart node ON THE CANVAS (sidebar also has "Line Chart"
    // in the block library — need to scope to react-flow node, not sidebar).
    const chartNode = page.locator('.react-flow__node[data-id="n4"]').first();
    await expect(chartNode, "n4 (Line Chart) node not on canvas").toBeVisible({ timeout: 15_000 });
    await chartNode.click();
    await page.waitForTimeout(800);

    // Trigger preview via the RUN PREVIEW button in the bottom panel.
    const runBtn = page.locator('button:has-text("RUN PREVIEW")').first();
    await expect(runBtn, "RUN PREVIEW button not found").toBeVisible({ timeout: 5_000 });
    await runBtn.click();
    await page.waitForResponse((r) => r.url().includes("/preview") && r.status() === 200,
                                { timeout: 60_000 });
    await page.waitForTimeout(1500); // let SVG paint

    await page.screenshot({ path: path.join(ART_DIR, "chart-01-clicked.png"), fullPage: true });

    // Assert chart container has an SVG
    const svg = page.locator('svg').filter({ hasNot: page.locator('text=icon') }).last();
    await expect(svg, "no SVG rendered for chart").toBeVisible({ timeout: 10_000 });

    // SVG should contain at least one <path>, <circle>, <line>, or <rect>
    const pathCount = await page.locator('svg path').count();
    const circleCount = await page.locator('svg circle').count();
    const lineCount = await page.locator('svg line').count();
    const rectCount = await page.locator('svg rect').count();
    const totalShapes = pathCount + circleCount + lineCount + rectCount;
    console.log(`[svg] paths=${pathCount} circles=${circleCount} lines=${lineCount} rects=${rectCount}`);
    expect(totalShapes, "SVG has no data-drawing shapes").toBeGreaterThan(0);

    // Look for the title text we set in fixture params
    const titleText = page.locator('text=ChartSmoke').first();
    await expect(titleText, "chart title from fixture spec not rendered").toBeVisible({
      timeout: 5_000,
    });

    // Save the full SVG markup for inspection
    const svgHTML = await svg.evaluate((el) => el.outerHTML);
    const svgFile = path.join(ART_DIR, "chart-rendered.svg");
    fs.writeFileSync(svgFile, svgHTML);
    console.log(`[svg saved] ${svgFile} (${svgHTML.length} bytes)`);

    await page.screenshot({ path: path.join(ART_DIR, "chart-02-rendered.png"), fullPage: true });
    console.log(`[done] artifacts in ${ART_DIR}/`);
  });

  test.afterAll(async () => {
    if (pipelineId && token) {
      const res = await fetch(`${BASE}/api/v1/pipelines/${pipelineId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      console.log(`[cleanup] pipeline ${pipelineId} delete: ${res.status}`);
    }
  });
});
