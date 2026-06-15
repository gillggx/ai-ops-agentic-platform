import { test, expect, Page } from "@playwright/test";

/**
 * Interactive-brief GUI flow (2026-06-15).
 *
 * Drives the design-intent BRIEF card the way a user would — typing a build
 * prompt, waiting for the brief, resolving each decision (option click or 其它
 * free-text), and asserting the build AUTO-STARTS once every decision is
 * resolved (no manual "開始建" button). This is the GUI-level self-verification
 * the interactive-brief spec requires: stable data-testid hooks make the card
 * driveable headlessly.
 *
 * Requires the backend running with ENABLE_INTERACTIVE_BRIEF=1 (the brief only
 * renders in brief mode). Targets the app at playwright.config baseURL.
 *
 * NOTE: build prompts hit a live LLM (haiku for the brief, then the builder),
 * so timeouts are generous and assertions tolerate LLM variability (we assert
 * the FLOW reaches each milestone, not exact node contents).
 */

const BASE = process.env.PW_BASE ?? "https://aiops-gill.com";
const USER = process.env.PW_USER ?? "admin";
const PASS = process.env.PW_PASS ?? "admin";
const CARD = '[data-testid="design-intent-card"]';
const SUBMITTED = '[data-testid="brief-submitted"]';

/** LOOP GUARD (2026-06-15): after the resume fires, a correct bypass proceeds to
 *  build; a broken bypass re-emits the brief → infinite ask. Wait past a full
 *  re-classify + completeness cycle and assert NO new brief card appeared. */
async function assertNoReAsk(page: Page, cardsBefore: number) {
  await page.waitForTimeout(90_000);
  expect(await page.locator(CARD).count()).toBe(cardsBefore);
}

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  // Already-authenticated sessions skip straight past /login.
  if (!page.url().includes("/login")) return;
  await page.locator('input[type="text"]').first().fill(USER);
  await page.locator('input[type="password"]').first().fill(PASS);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }),
    page.locator('button[type="submit"]').first().click(),
  ]);
}

async function openChatAndSend(page: Page, prompt: string) {
  await login(page);
  await page.goto(`${BASE}/`);
  const input = page.locator("textarea").first();
  await expect(input).toBeVisible({ timeout: 15_000 });
  await input.click();
  await input.fill(prompt);
  await input.press("Enter");
}

async function resolveAllDecisions(page: Page) {
  // Each decision container is [data-testid="decision-<dim>"]. Resolve every
  // one: prefer a concrete option; if only 其它 is reasonable, type free text.
  const decisions = page.locator('[data-testid^="decision-"]').filter({
    has: page.locator('input[type="radio"]'),
  });
  const count = await decisions.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const dec = decisions.nth(i);
    // Prefer ANY concrete (non-其它) option — incl. the degenerate single
    // 「開始建立」. Only fall back to 其它 free-text when no concrete option.
    const nonOther = dec.locator('input[type="radio"]:not([data-testid$="-opt-__other__"])');
    if ((await nonOther.count()) > 0) {
      await nonOther.first().check();
    } else {
      await dec.locator('[data-testid$="-opt-__other__"]').first().check();
      const otherInput = dec.locator('[data-testid$="-other-input"]');
      await expect(otherInput).toBeVisible();
      await otherInput.fill("依預設處理即可");
    }
  }
}

test.describe("interactive brief", () => {
  test("clear prompt → degenerate brief → click start decision → auto-build", async ({ page }) => {
    test.setTimeout(480_000);
    await openChatAndSend(page, "EQP-01 STEP_001 過去 7 天的 xbar 趨勢圖");

    // Brief card must appear (always-align gate).
    await expect(page.locator(CARD).last()).toBeVisible({ timeout: 260_000 });

    // Resolve every decision (degenerate = single 「開始建立」). Auto-submit
    // fires synchronously — no manual button — surfacing the submitted marker.
    const cardsBefore = await page.locator(CARD).count();
    await resolveAllDecisions(page);
    await expect(page.locator(SUBMITTED).last()).toBeVisible({ timeout: 15_000 });
    await assertNoReAsk(page, cardsBefore);  // no infinite re-ask loop
  });

  test("ambiguous prompt → multi-decision (incl 其它) → resolve all → auto-build", async ({ page }) => {
    test.setTimeout(480_000);
    await openChatAndSend(page, "各機台過去 7 天的 OOC 排名");

    await expect(page.locator(CARD).last()).toBeVisible({ timeout: 260_000 });
    const cardsBefore = await page.locator(CARD).count();
    await resolveAllDecisions(page);
    // Resolving every decision (option pick or 其它 free-text) auto-fires the
    // build with no manual button — synchronous submitted marker.
    await expect(page.locator(SUBMITTED).last()).toBeVisible({ timeout: 15_000 });
    await assertNoReAsk(page, cardsBefore);  // no infinite re-ask loop
  });
});
