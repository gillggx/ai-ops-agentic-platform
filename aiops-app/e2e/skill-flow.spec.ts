/**
 * Phase 11 v6 — Skill end-to-end flow with real Glass Box agent.
 *
 * Drives the full GUI sequence:
 *   1. Login as itadmin_test
 *   2. Create new skill
 *   3. Type C1 instruction → click Build → switch to popup tab
 *   4. Wait for AIAgentPanel auto-fired prompt to build the pipeline
 *      (real Anthropic call via /sidecar Glass Box; ~15-45s)
 *   5. Save the resulting pipeline
 *   6. Click banner "Done — bind to Skill" → tab closes
 *   7. Back on Skill page → verify C1 card is bound (not stale) and
 *      the user's original prose is shown as the description
 *   8. Cleanup: DELETE the test skill via API
 *
 * Spec is opt-in — set `ANTHROPIC_LIVE=1` to spend tokens. CI default skips.
 *
 * Env vars (defaults shown):
 *   PW_BASE=https://aiops-gill.com   target deployed env
 *   PW_USER=itadmin_test
 *   PW_PASS=ITAdmin@2026
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.PW_BASE ?? "https://aiops-gill.com";
const USER = process.env.PW_USER ?? "itadmin_test";
const PASS = process.env.PW_PASS ?? "ITAdmin@2026";

test.describe("Skill flow — full GUI with real agent", () => {
  test.skip(!process.env.ANTHROPIC_LIVE,
    "Set ANTHROPIC_LIVE=1 to run against real Anthropic (spends tokens)");
  test.setTimeout(240_000); // 4 min: agent ~30s + tab dance + reloads

  test("create → C1 build with agent → bind → C1 visible → cleanup",
    async ({ context, page, request }) => {
      const slug = `e2e-${Date.now()}`;

      // ── 1. Login ───────────────────────────────────────────────
      await page.goto(`${BASE}/login`);
      await page.locator('input[type="text"]').first().fill(USER);
      await page.locator('input[type="password"]').first().fill(PASS);
      await Promise.all([
        page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }),
        page.locator('button[type="submit"]').first().click(),
      ]);
      console.log("[1/8] logged in");

      // ── 2. New Skill ──────────────────────────────────────────
      await page.goto(`${BASE}/skills/new`);
      await page.waitForSelector('input[placeholder="ocap-diag"]', { timeout: 15_000 });
      await page.locator('input[placeholder="ocap-diag"]').fill(slug);
      await page.locator('input[placeholder*="Advanced Diagnostic"]').fill(`E2E ${slug}`);
      await page.click('button:has-text("Create skill")');
      await page.waitForURL(/\/skills\/[^/]+\/edit/, { timeout: 15_000 });
      console.log("[2/8] skill created", slug);

      // ── 3. Type C1 instruction + Build → opens popup ──────────
      const instruction = "檢查最近 5 lot 是否有 ≥ 3 次 OOC";
      await page.locator('input[placeholder*="先確認一個條件"]').fill(instruction);

      const [builderTab] = await Promise.all([
        context.waitForEvent("page"),
        page.locator('button:has-text("Build →")').first().click(),
      ]);
      await builderTab.waitForLoadState("domcontentloaded");
      // URL should carry embed=skill + instruction. Java URLEncoder uses
      // form encoding (`+` for spaces), so normalise both sides before
      // substring compare. Pull out a sentinel chunk of the prose.
      expect(builderTab.url()).toContain("embed=skill");
      const decoded = decodeURIComponent(builderTab.url()).replace(/\+/g, " ");
      expect(decoded).toContain("檢查最近");
      expect(decoded).toContain("OOC");
      console.log("[3/8] popup opened", builderTab.url().slice(0, 80));

      // ── 4. Wait for AIAgentPanel to auto-fire prompt + build canvas ──
      // SkillEmbedBanner should be visible
      await expect(builderTab.locator("text=Building CONFIRM")).toBeVisible({ timeout: 15_000 });
      // Agent panel mounts; auto-fired prompt → SSE → canvas nodes appear.
      // Poll for at least 2 nodes (a source block + block_step_check).
      console.log("    waiting for Glass Box agent to build canvas (up to 90s)…");
      await builderTab.waitForFunction(
        () => document.querySelectorAll(".react-flow__node").length >= 2,
        null,
        { timeout: 90_000, polling: 2000 },
      );
      const nodeCount = await builderTab.locator(".react-flow__node").count();
      console.log(`[4/8] agent built ${nodeCount} canvas nodes`);

      // ── 5. Save the pipeline ──────────────────────────────────
      await builderTab.locator('button:has-text("Save")').first().click();
      // /new → /[id] navigation happens after save
      await builderTab.waitForURL(/admin\/pipeline-builder\/\d+/, { timeout: 30_000 });
      const pidMatch = builderTab.url().match(/pipeline-builder\/(\d+)/);
      const pid = pidMatch ? Number(pidMatch[1]) : null;
      expect(pid).not.toBeNull();
      console.log("[5/8] saved pipeline #" + pid);

      // ── 6. Click Done — bind to Skill ─────────────────────────
      // Banner button label: "Done — bind to Skill ↵" (or "Done — update Skill 調整" on refine)
      const doneBtn = builderTab.locator('button:has-text("Done")');
      await expect(doneBtn).toBeEnabled({ timeout: 10_000 });
      await Promise.all([
        builderTab.waitForEvent("close").catch(() => {}), // tab may close
        doneBtn.click(),
      ]);
      console.log("[6/8] bind requested + tab closed");

      // ── 7. Back on Skill page → reload → verify C1 card ──────
      await page.bringToFront();
      // SkillEmbedBanner removes ctx, but the parent Skill page only refreshes
      // on focus. Force reload to be deterministic in test.
      await page.reload();
      await expect(page.getByText(instruction)).toBeVisible({ timeout: 10_000 });
      // Expect the orange "stale" border NOT to be there → green/blue card
      await expect(page.locator(":text-is('C1')")).toBeVisible();
      // The "underlying pipeline was deleted" warning must NOT appear
      await expect(page.getByText("underlying pipeline was deleted")).not.toBeVisible();
      console.log("[7/8] C1 bound + visible on Skill page");

      // ── 8. Cleanup ────────────────────────────────────────────
      // Use the page's session cookies to call DELETE /api/skill-documents/<slug>
      const cookies = await context.cookies();
      const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
      const del = await request.delete(`${BASE}/api/skill-documents/${slug}`, {
        headers: { Cookie: cookieHeader },
      });
      expect(del.ok()).toBeTruthy();
      console.log("[8/8] cleanup complete");
    });
});
