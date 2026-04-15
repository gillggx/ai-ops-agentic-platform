import { test, expect } from "@playwright/test";

test.describe("DataExplorer & Resizable Panel", () => {
  test("main content area and copilot panel are both visible", async ({ page }) => {
    await page.goto("/");
    // Main area (Panel with defaultSize=70)
    const main = page.locator("main");
    await expect(main).toBeVisible();
    // Copilot panel (textarea for input)
    const copilotInput = page.locator("textarea");
    await expect(copilotInput).toBeVisible();
  });

  test("resize handle is visible between panels", async ({ page }) => {
    await page.goto("/");
    // PanelResizeHandle renders with data-panel-resize-handle-id
    const handle = page.locator("[data-panel-resize-handle-id]");
    await expect(handle).toBeVisible();
  });

  test("copilot panel has console tab", async ({ page }) => {
    await page.goto("/");
    // Look for Console tab button
    const consoleTab = page.getByText("Console", { exact: false });
    await expect(consoleTab.first()).toBeVisible();
  });

  test("screenshot at current viewport", async ({ page }) => {
    await page.goto("/");
    await page.waitForTimeout(1000);
    const vp = page.viewportSize();
    await page.screenshot({
      path: `../screenshots/${vp?.width ?? "unknown"}x${vp?.height ?? "unknown"}.png`,
      fullPage: true,
    });
  });
});
