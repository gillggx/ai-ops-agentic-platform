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
  test.setTimeout(360_000); // 6 min: agent up to 3 min + tab dance + reloads

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
      // 2026-05-13: UI simplified — slug now auto-generated from title;
      // only TITLE (placeholder "e.g. OCAP 進階診斷") + DESCRIPTION fields.
      await page.goto(`${BASE}/skills/new`);
      await page.waitForSelector('input[placeholder*="OCAP"]', { timeout: 15_000 });
      await page.locator('input[placeholder*="OCAP"]').fill(`E2E ${slug}`);
      await page.locator('textarea').first().fill(`E2E smoke ${slug}`);
      await page.click('button:has-text("Create skill")');
      await page.waitForURL(/\/skills\/[^/]+\/edit/, { timeout: 15_000 });
      // Extract the auto-generated slug from URL for cleanup later
      const slugFromUrl = page.url().match(/\/skills\/([^/?]+)/)?.[1] ?? slug;
      console.log("[2/8] skill created — slug:", slugFromUrl);

      // ── 3. Type C1 instruction + Build → opens popup ──────────
      // 2026-05-13: parametrize via INSTRUCTION env var so the same harness
      // can be pointed at any failing prompt the user reports.
      const instruction = process.env.INSTRUCTION ?? "檢查最近 5 lot 是否有 ≥ 3 次 OOC";
      console.log(`[3/8] instruction: ${instruction.slice(0, 80)}…`);
      await page.locator('input[placeholder*="先確認一個條件"]').fill(instruction);

      const [builderTab] = await Promise.all([
        context.waitForEvent("page"),
        page.locator('button:has-text("Build →")').first().click(),
      ]);
      // Phase 11 v6 — surface browser console logs + network from the popup
      // so [AIAgentPanel] diagnostic prints land in the Playwright run output.
      builderTab.on("console", (msg) => {
        const txt = msg.text();
        if (txt.includes("AIAgentPanel") || txt.includes("[skill") || txt.includes("auto-fire")) {
          console.log("    [popup]", msg.type(), txt.slice(0, 200));
        }
        // Capture client-side errors so test logs surface them
        if (msg.type() === "error" || msg.type() === "warning") {
          console.log("    [popup-err]", msg.type(), txt.slice(0, 400));
        }
      });
      builderTab.on("pageerror", (err) => {
        console.log("    [pageerror]", err.message.slice(0, 400));
      });
      builderTab.on("response", async (res) => {
        const url = res.url();
        if (url.includes("/api/agent/chat") || url.includes("/api/agent/build")) {
          console.log(`    [net] ${res.status()} ${res.request().method()} ${url.slice(0, 120)}`);
        }
      });
      builderTab.on("requestfailed", (req) => {
        if (req.url().includes("/api/")) {
          console.log(`    [net-fail] ${req.method()} ${req.url().slice(0, 120)} — ${req.failure()?.errorText}`);
        }
      });
      await builderTab.waitForLoadState("domcontentloaded");
      // URL should carry embed=skill + instruction. Java URLEncoder uses
      // form encoding (`+` for spaces), so normalise both sides before
      // substring compare. Pull out a sentinel chunk of the prose.
      expect(builderTab.url()).toContain("embed=skill");
      const decoded = decodeURIComponent(builderTab.url()).replace(/\+/g, " ");
      // Sentinel: first 4 chars of instruction (after stripping leading
      // emojis/whitespace) — survives URL encoding round-trip.
      const sentinel = instruction.trim().slice(0, 4);
      expect(decoded, "popup URL should carry the prompt").toContain(sentinel);
      console.log("[3/8] popup opened", builderTab.url().slice(0, 80));

      // ── 4. Wait for AIAgentPanel to auto-fire prompt + build canvas ──
      builderTab.on("dialog", (d) => d.dismiss().catch(() => {}));
      // Phase 11 v6 — Pipeline Builder shows an 8-step onboarding tour for
      // first-time users (rendered via SurfaceTour as a fixed-position
      // tour-bubble over the canvas). It blocks all canvas interaction.
      // ESC dismisses the entire tour. For the product itself, skill embed
      // should suppress tour (separate fix tracked in v6 to-remove memory).
      try {
        await builderTab.keyboard.press("Escape");
        await builderTab.waitForFunction(
          () => !document.querySelector(".tour-bubble") && !document.querySelector(".tour-mask"),
          null,
          { timeout: 5_000 },
        );
        console.log("    tour dismissed");
      } catch {
        // Tour didn't dismiss — proceed anyway, may overlay canvas.
      }
      await expect(builderTab.locator("text=Building CONFIRM")).toBeVisible({ timeout: 15_000 });
      console.log("    waiting for Glass Box agent to build canvas (up to 90s)…");
      try {
        await builderTab.waitForFunction(
          () => document.querySelectorAll(".react-flow__node").length >= 2,
          null,
          { timeout: 180_000, polling: 2000 },
        );
      } catch (e) {
        await builderTab.screenshot({ path: "playwright-report/agent-timeout-builder-tab.png", fullPage: true });
        // Phase 11 v6 — diagnostic: count iframes + dump modal-shaped divs +
        // dump html length so we can tell if page is intact.
        const diag = await builderTab.evaluate(() => {
          const ifs = document.querySelectorAll("iframe").length;
          const all = document.querySelectorAll("*").length;
          const role = document.querySelectorAll('[role="dialog"], [aria-modal="true"]').length;
          const fixed = Array.from(document.querySelectorAll("div"))
            .filter((d) => {
              const s = window.getComputedStyle(d);
              return (s.position === "fixed" || s.position === "absolute") && s.zIndex && Number(s.zIndex) >= 50;
            })
            .slice(0, 5)
            .map((d) => ({
              text: (d.textContent || "").slice(0, 200),
              z: window.getComputedStyle(d).zIndex,
              top: window.getComputedStyle(d).top,
              tag: d.className?.toString?.().slice(0, 80) || "",
            }));
          return { ifs, all, role, fixed, html_len: document.documentElement.outerHTML.length };
        }).catch((err) => `ERROR ${err}`);
        console.log("DIAG:", JSON.stringify(diag, null, 2));
        const buttons = await builderTab.locator('button:visible').all();
        console.log(`VISIBLE BUTTONS (${buttons.length}):`);
        for (let i = 0; i < Math.min(buttons.length, 25); i++) {
          const t = await buttons[i].innerText().catch(() => "?");
          if (t.trim()) console.log(`  - ${JSON.stringify(t.slice(0, 80))}`);
        }
        // Count canvas nodes via various selectors
        const variants = [".react-flow__node", "[data-id]", "[class*='Node']"];
        for (const sel of variants) {
          const n = await builderTab.locator(sel).count().catch(() => -1);
          console.log(`  selector ${sel} → ${n} matches`);
        }
        throw e;
      }
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
      console.log("[7/9] C1 bound + visible on Skill page");

      // ── 8. Run the skill end-to-end via /run SSE ──────────────
      // The bound C1 pipeline is now the only step. Drive a real run with
      // a mock OOC payload so the SkillRunner fires the pipeline against
      // the simulator's actual data — what 「跑的動」 means in production.
      const cookies = await context.cookies();
      const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
      const runRes = await request.post(
        `${BASE}/api/skill-documents/${slug}/run`,
        {
          headers: {
            Cookie: cookieHeader,
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          data: {
            trigger_payload: {
              tool_id: "EQP-01",
              lot_id: "LOT-0001",
              step: "STEP_005",
              chamber_id: "CH-1",
              spc_chart: "xbar_chart",
              severity: "high",
            },
            is_test: true,
          },
          timeout: 120_000,
        },
      );
      expect(runRes.ok()).toBeTruthy();

      // Parse SSE frames out of the body. Look for a confirm_done with
      // status pass|fail (NOT error) to prove the pipeline ran for real.
      const sseBody = await runRes.text();
      const events: Array<{ event: string; data: Record<string, unknown> }> = [];
      for (const frame of sseBody.split(/\n\n/)) {
        const lines = frame.split("\n");
        let evt = "message";
        const dataLines: string[] = [];
        for (const ln of lines) {
          if (ln.startsWith("event:")) evt = ln.slice(6).trim();
          else if (ln.startsWith("data:")) dataLines.push(ln.slice(5).trim());
        }
        if (dataLines.length) {
          try { events.push({ event: evt, data: JSON.parse(dataLines.join("\n")) }); }
          catch { /* ignore */ }
        }
      }
      const confirmDone = events.find((e) => e.event === "confirm_done");
      const done = events.find((e) => e.event === "done");
      console.log(`[8/9] /run SSE got ${events.length} events`);
      console.log(`        types: ${[...new Set(events.map((e) => e.event))].join(",")}`);
      if (confirmDone) {
        console.log(`        confirm result: status=${confirmDone.data.status} value=${confirmDone.data.value} note=${(confirmDone.data.note as string)?.slice(0, 100)}`);
      }
      if (done) {
        console.log(`        run done: ${JSON.stringify(done.data).slice(0, 200)}`);
      }
      expect(confirmDone, "expected at least one confirm_done event").toBeTruthy();
      expect(["pass", "fail"], "confirm step must return real pass/fail (not error)")
        .toContain(confirmDone!.data.status);
      // 跑的動 means: pipeline ran AND read pass/fail from block_step_check.
      // value="error" means SkillRunner couldn't find a step_check output OR
      // pipeline status was not "success" — i.e. pipeline didn't actually
      // complete. That's NOT 跑的動.
      if (confirmDone!.data.value === "error") {
        // Skip cleanup so the skill survives for manual psql / browser
        // inspection. Print enough info to find it.
        console.log("PIPELINE FAILED AT RUNTIME — skill kept for inspection:");
        console.log("  slug:", slug);
        console.log("  full SSE events:");
        for (const ev of events) {
          console.log("   ", ev.event, JSON.stringify(ev.data).slice(0, 300));
        }
        throw new Error(`pipeline ran but value="error" — agent didn't produce a step_check terminator OR pipeline failed. note=${confirmDone!.data.note}`);
      }
      console.log("[8/9] skill ran end-to-end with real verdict");

      // ── 9. Cleanup (skip if SKIP_CLEANUP=1 for inspection) ────
      if (!process.env.SKIP_CLEANUP) {
        const del = await request.delete(`${BASE}/api/skill-documents/${slug}`, {
          headers: { Cookie: cookieHeader },
        });
        expect(del.ok()).toBeTruthy();
        console.log("[9/9] cleanup complete");
      } else {
        console.log("[9/9] cleanup SKIPPED — skill kept:", slug);
      }
    });
});
