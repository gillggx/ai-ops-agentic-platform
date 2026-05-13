/**
 * 2026-05-13 — Stable harness skill flow.
 *
 * Differs from skill-flow.spec.ts by using a PERMANENT harness skill
 * (slug='harness-spc-ooc') instead of creating + deleting a fresh skill
 * each run. Per-test it RESETS confirm_check.pipeline_id=null (stale
 * state matching the user's real complaint) then drives Build through
 * the GUI same-tab flow.
 *
 * The harness skill is seeded once via SQL (see migration / setup notes).
 * It survives between runs so we have a fixed URL + state to inspect.
 *
 * Env (defaults):
 *   PW_BASE=https://aiops-gill.com
 *   PW_USER=admin  PW_PASS=admin
 *   HARNESS_SLUG=harness-spc-ooc
 *   INSTRUCTION="<full prompt>"  — overrides skill's existing C1 description
 *
 * Run via:
 *   tooling/harness_smoke.sh  (or direct npx playwright test)
 */
import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.PW_BASE ?? "https://aiops-gill.com";
const USER = process.env.PW_USER ?? "admin";
const PASS = process.env.PW_PASS ?? "admin";
const SLUG = process.env.HARNESS_SLUG ?? "harness-spc-ooc";
const INSTRUCTION = process.env.INSTRUCTION ??
  "檢查機台最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts";

async function loginJava(): Promise<string> {
  const res = await fetch(`${BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`auth/login failed: ${res.status}`);
  const j = await res.json();
  return j?.data?.access_token ?? "";
}

async function resetHarness(token: string) {
  // Reset confirm_check.pipeline_id=null + description to the user's prompt
  // so each test starts from "stale C1" state — same as the user's GUI complaint.
  // 2026-05-13: include trigger_payload sample. AgentBuilderPanel reads this
  // on embed=skill, forwards to /api/agent/build → sidecar dry-run uses
  // production-shape inputs → inspect catches runtime-only issues at build
  // time → reflect_plan has something to repair.
  const cc = {
    description: INSTRUCTION,
    ai_summary: "",
    pipeline_id: null,
    must_pass: true,
    trigger_payload: {
      equipment_id: "EQP-01",
      lot_id: "LOT-0001",
      step_id: "STEP_005",
      chamber_id: "CH-1",
      spc_chart: "xbar_chart",
      severity: "high",
    },
  };
  const res = await fetch(`${BASE}/api/v1/skill-documents/${SLUG}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ confirm_check: JSON.stringify(cc) }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`reset harness failed: ${res.status} ${body.slice(0, 200)}`);
  }
}

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.locator('input[type="text"]').first().fill(USER);
  await page.locator('input[type="password"]').first().fill(PASS);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }),
    page.locator('button[type="submit"]').first().click(),
  ]);
}

test.describe("Harness flow — stable skill, repeated builds", () => {
  test.setTimeout(360_000);
  test.skip(!process.env.ANTHROPIC_LIVE,
    "Set ANTHROPIC_LIVE=1 to spend tokens against the harness");

  test("build → save → bind → run, asserting chart + verdict signals", async ({ page }) => {
    // ── 1. Reset harness to stale state ──────────────────────────
    const token = await loginJava();
    await resetHarness(token);
    console.log(`[1/7] harness ${SLUG} reset (pipeline_id=null, desc=${INSTRUCTION.slice(0, 50)}…)`);

    // ── 2. Login + navigate to harness skill ─────────────────────
    await login(page);
    await page.goto(`${BASE}/skills/${SLUG}/edit`);
    await expect(page.getByText(INSTRUCTION)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("underlying pipeline was deleted")).toBeVisible({ timeout: 5_000 });
    console.log("[2/7] harness skill loaded, C1 shows stale warning as expected");

    // ── 3. Click Build → same-tab nav ────────────────────────────
    await Promise.all([
      page.waitForURL(/\/admin\/pipeline-builder\//, { timeout: 30_000 }),
      page.locator('button:has-text("Build →")').first().click(),
    ]);
    const builder = page;
    await builder.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});
    console.log(`[3/7] popup ${builder.url().slice(0, 80)}`);

    // ── 4. Dismiss tour, click 開始建 to dispatch plan ──────────
    try {
      await builder.keyboard.press("Escape");
      await builder.waitForFunction(
        () => !document.querySelector(".tour-bubble") && !document.querySelector(".tour-mask"),
        null, { timeout: 5_000 },
      );
    } catch { /* ok */ }

    await expect(builder.locator("text=Building CONFIRM")).toBeVisible({ timeout: 60_000 });
    const confirmBtn = builder.locator(
      'button:has-text("開始建"), button:has-text("Confirm Build"), button:has-text("開始建構")'
    ).first();
    await expect(confirmBtn).toBeVisible({ timeout: 30_000 });
    await confirmBtn.click();
    console.log("[4/7] 開始建 clicked, waiting for canvas…");

    await builder.waitForFunction(
      () => document.querySelectorAll(".react-flow__node").length >= 2,
      null, { timeout: 180_000, polling: 2000 },
    );
    // 2026-05-13: wait for the agent's "✓ <summary>" line in the chat
    // panel — that's the signal that the SSE "done" event was processed,
    // which means the done handler has replaced canvas with sidecar's
    // final_pipeline. Without this we save mid-reflect, missing edges /
    // post-reflect param changes that arrive later.
    await builder.locator('text=/^✓ /').first().waitFor({ timeout: 300_000 });
    // Extra 1s for React Flow to settle on the laid-out positions.
    await builder.waitForTimeout(1_000);
    const nodeCount = await builder.locator(".react-flow__node").count();
    console.log(`[5/7] canvas has ${nodeCount} nodes (build done)`);

    // ── 6. Save → wait for /[id] URL → Done ──────────────────────
    await builder.locator('button:has-text("Save")').first().click();
    await builder.waitForURL(/admin\/pipeline-builder\/\d+/, { timeout: 120_000 });
    const pid = Number(builder.url().match(/pipeline-builder\/(\d+)/)?.[1]);
    expect(pid).toBeGreaterThan(0);
    console.log(`[6/7] saved pipeline #${pid}`);

    await expect(builder.locator('button:has-text("Done")')).toBeEnabled({ timeout: 10_000 });
    await Promise.all([
      page.waitForURL(new RegExp(`/skills/${SLUG}/edit`), { timeout: 30_000 }),
      builder.locator('button:has-text("Done")').first().click(),
    ]);
    console.log("[7/7] bound + back to skill page");
    await page.reload();
    await expect(page.getByText("underlying pipeline was deleted")).not.toBeVisible({ timeout: 5_000 });

    // ── 7. Run skill end-to-end + assert signals ─────────────────
    const cookies = await page.context().cookies();
    const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    const runRes = await fetch(`${BASE}/api/skill-documents/${SLUG}/run`, {
      method: "POST",
      headers: { Cookie: cookieHeader, "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        trigger_payload: {
          equipment_id: "EQP-01", lot_id: "LOT-0001", step_id: "STEP_005",
          chamber_id: "CH-1", spc_chart: "xbar_chart", severity: "high",
        },
        is_test: true,
      }),
    });
    expect(runRes.ok).toBeTruthy();

    const sseBody = await runRes.text();
    const events: Array<{ event: string; data: Record<string, unknown> }> = [];
    for (const frame of sseBody.split(/\n\n/)) {
      let evt = "message"; const dataLines: string[] = [];
      for (const ln of frame.split("\n")) {
        if (ln.startsWith("event:")) evt = ln.slice(6).trim();
        else if (ln.startsWith("data:")) dataLines.push(ln.slice(5).trim());
      }
      if (dataLines.length) {
        try { events.push({ event: evt, data: JSON.parse(dataLines.join("\n")) }); } catch {}
      }
    }
    const confirmDone = events.find((e) => e.event === "confirm_done");
    expect(confirmDone, "expected confirm_done event").toBeTruthy();
    const verdict = confirmDone!.data;
    console.log(`[run] confirm verdict: status=${verdict.status} value=${verdict.value} note=${(verdict.note as string)?.slice(0, 80)}`);

    // ── Signal 1: verdict value is numeric, not "error" ──
    expect(verdict.value, `verdict value should be numeric/bool, got: ${verdict.value}`)
      .not.toBe("error");
    expect(verdict.value).not.toBeNull();
    if (typeof verdict.note === "string") {
      expect(verdict.note).not.toContain("not numeric");
      expect(verdict.note).not.toContain("error");
    }

    // ── Signal 2: pipeline preview → chart distinct_x >= 3 ──
    // Reload pipeline from DB then preview every terminal to inspect chart blocks.
    const pipeRes = await fetch(`${BASE}/api/v1/pipelines/${pid}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const pipeJ = await pipeRes.json();
    const pj = pipeJ?.data?.pipelineJson ?? pipeJ?.data?.pipeline_json;
    expect(pj, "pipeline_json should be loadable").toBeTruthy();
    const pipelineJson = typeof pj === "string" ? JSON.parse(pj) : pj;
    const srcs = new Set((pipelineJson.edges || []).map((e: { from: { node: string } }) => e.from.node));
    const terminals = (pipelineJson.nodes || [])
      .map((n: { id: string }) => n.id).filter((id: string) => !srcs.has(id));
    console.log(`[run] terminals: ${terminals.join(", ")}`);

    let chartChecks = 0; let chartFails = 0;
    for (const tid of terminals) {
      const previewRes = await fetch(`${BASE}/api/agent/pipeline/preview`, {
        method: "POST",
        headers: { Cookie: cookieHeader, "Content-Type": "application/json" },
        body: JSON.stringify({ pipeline_json: pipelineJson, node_id: tid, sample_size: 200 }),
      });
      if (!previewRes.ok) continue;
      const pv = await previewRes.json();
      const nodeResults = pv?.all_node_results ?? {};
      for (const [nid, nr] of Object.entries<{ status?: string; preview?: Record<string, unknown> }>(nodeResults)) {
        if (nr?.status !== "success") continue;
        const preview = nr.preview ?? {};
        for (const portBlob of Object.values<unknown>(preview)) {
          if (!portBlob || typeof portBlob !== "object") continue;
          // Non-facet: { snapshot: { type, data } }
          const snap = (portBlob as { snapshot?: { type?: string; data?: unknown[] } }).snapshot;
          if (snap?.type && Array.isArray(snap.data)) {
            const distinctX = new Set(snap.data.map((d: { eventTime?: unknown }) => d?.eventTime ?? null)).size;
            chartChecks++;
            if (distinctX < 3) {
              console.log(`  ✗ chart ${nid}.${snap.type}: ${distinctX} distinct eventTime (single-point bug)`);
              chartFails++;
            } else {
              console.log(`  ✓ chart ${nid}.${snap.type}: ${snap.data.length} pts, ${distinctX} distinct eventTime`);
            }
          }
          // Facet list
          const blob = portBlob as { type?: string; sample?: Array<{ type?: string; data?: unknown[] }> };
          if (blob.type === "list" && Array.isArray(blob.sample)) {
            for (let i = 0; i < blob.sample.length; i++) {
              const panel = blob.sample[i];
              if (!Array.isArray(panel?.data)) continue;
              const distinctX = new Set(panel.data.map((d: { eventTime?: unknown }) => d?.eventTime ?? null)).size;
              chartChecks++;
              if (distinctX < 3) {
                console.log(`  ✗ chart ${nid} facet panel ${i}: ${distinctX} distinct (single-point bug)`);
                chartFails++;
              } else {
                console.log(`  ✓ chart ${nid} facet panel ${i}: ${panel.data.length} pts, ${distinctX} distinct`);
              }
            }
          }
        }
      }
    }
    if (chartChecks > 0) {
      expect(chartFails, `expected 0 single-point charts; got ${chartFails}/${chartChecks}`).toBe(0);
    }
  });
});
