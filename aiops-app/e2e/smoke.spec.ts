import { test, expect } from "@playwright/test";

test.describe("Smoke tests", () => {
  test("app loads and sidebar is visible", async ({ page }) => {
    await page.goto("/");
    // Sidebar nav should be present
    await expect(page.locator("nav")).toBeVisible();
    // Topbar should be present
    await expect(page.getByText("AIOps")).toBeVisible();
  });

  test("copilot panel is visible", async ({ page }) => {
    await page.goto("/");
    // Copilot input area should be present
    await expect(page.locator("textarea")).toBeVisible();
  });

  test("sidebar collapse/expand works", async ({ page }) => {
    await page.goto("/");
    // Find collapse toggle
    const toggle = page.locator("button", { hasText: /[▶◀]/ }).first();
    await expect(toggle).toBeVisible();
    // Click to expand
    await toggle.click();
    // Should show nav labels (e.g. "Dashboard")
    await expect(page.getByText("Dashboard")).toBeVisible();
    // Click to collapse
    await toggle.click();
    // Wait a bit for transition
    await page.waitForTimeout(300);
  });

  test("navigation links work", async ({ page }) => {
    await page.goto("/");
    // Expand sidebar first
    const toggle = page.locator("button", { hasText: /[▶◀]/ }).first();
    await toggle.click();
    // Click on Alarm Center
    await page.getByText("Alarm Center").click();
    await expect(page).toHaveURL(/\/alarms/);
  });
});
