/**
 * render.mjs (result-vision, 2026-07-13) — headless 成品截圖。
 * 用法：node render.mjs <payload.json> <out.png>
 * payload: {kind:"chart", spec:{__dsl chart_spec}} 或 {kind:"table", columns, rows, title}
 * 依賴：playwright（借 aiops-app/node_modules，見旁邊的 node_modules symlink）
 * ＋ chromium binary（npx playwright install chromium --with-deps）。
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const [payloadPath, outPath] = process.argv.slice(2);
if (!payloadPath || !outPath) {
  console.error("usage: node render.mjs <payload.json> <out.png>");
  process.exit(2);
}
const payload = JSON.parse(readFileSync(payloadPath, "utf8"));
const here = dirname(fileURLToPath(import.meta.url));
const bundle = readFileSync(join(here, "bundle.js"), "utf8");

const browser = await chromium.launch({ args: ["--no-sandbox", "--disable-dev-shm-usage"] });
try {
  const page = await browser.newPage({ viewport: { width: 940, height: 520 } });
  await page.setContent(
    `<!doctype html><html><body style="margin:0;background:#fff"><div id="root"></div></body></html>`,
    { waitUntil: "domcontentloaded" },
  );
  await page.addScriptTag({ content: bundle });
  const status = await page.evaluate((p) => window.__renderResult(p), payload);
  if (status !== "ok") {
    console.error(`render failed: ${status}`);
    process.exit(3);
  }
  await page.waitForTimeout(150);
  await page.locator("#root").screenshot({ path: outPath });
  console.log("ok");
} finally {
  await browser.close();
}
