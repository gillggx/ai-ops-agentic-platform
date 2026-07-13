// E2E: user 案例（多機台 trend, x=時間排序, 顏色分機台）+ ChatOps 新介面驗收
import { chromium } from "playwright";
const BASE = process.env.AIOPS_BASE ?? "https://aiops-gill.com";
const OUT = process.env.REG_OUT ?? "/tmp/aiops-regression";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 860 } });
const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await page.fill('input[type="text"]', "admin");
await page.fill('input[type="password"]', "admin");
await page.click('button[type="submit"]');
await page.waitForURL((u) => !u.pathname.includes("login"), { timeout: 20000 });
await page.goto(`${BASE}/chatops`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
const skip = page.locator('button:has-text("Skip")');
if (await skip.count()) { await skip.first().click(); await page.waitForTimeout(400); }
log("logged in, chatops loaded");

// rail assertions: 最近運作 section exists
const railOk = await page.locator('text=最近運作').count();
log(`rail 最近運作 section: ${railOk > 0 ? "PASS" : "FAIL"}`);
// console collapsed strip exists (CONSOLE vertical)
const consoleStrip = await page.locator('text=CONSOLE').count();
log(`console collapsed strip: ${consoleStrip > 0 ? "PASS" : "FAIL"}`);
await page.screenshot({ path: `${OUT}/qa_p2_idle.png` });

// send build request (user's case)
const input = page.locator('textarea, input[placeholder*="輸入"]').last();
await input.fill("用 EQP-06 過去 7 天的資料畫 xbar 值 vs r 值的散點圖，要含迴歸線與 R² 標註");
await page.keyboard.press("Enter");
log("build request sent, waiting for plan card…");

// wait for plan confirm button
const confirmBtn = page.locator('button:has-text("確認，開始建構"), button:has-text("開始建構"), button:has-text("確認してビルド開始")').first();
await confirmBtn.waitFor({ timeout: 180000 });
await page.screenshot({ path: `${OUT}/qa_p2_plan.png` });
await confirmBtn.click();
log("plan confirmed — building…");

// during build: capture console panel expanded + topbar pill + 建構中 header
await page.waitForTimeout(9000);
const pill = await page.locator('text=agent 執行中').count();
const buildingHdr = await page.locator('text=背景執行，斷線照跑').count();
const consoleOpen = await page.locator('button:has-text("收合")').count();
log(`topbar pill: ${pill > 0 ? "PASS" : "FAIL"} / 建構中 header: ${buildingHdr > 0 ? "PASS" : "FAIL"} / console expanded: ${consoleOpen > 0 ? "PASS" : "FAIL"}`);
await page.screenshot({ path: `${OUT}/qa_p2_building.png` });

// wait for done or failure (up to 8 min)
const done = page.locator('text=/建構完成 — \\d+ nodes/').first();
const failed = page.locator('text=建構未完成').first();
const result = await Promise.race([
  done.waitFor({ timeout: 480000 }).then(() => "done"),
  failed.waitFor({ timeout: 480000 }).then(() => "failed"),
]).catch(() => "timeout");
log(`build result: ${result}`);
await page.waitForTimeout(2500);
await page.screenshot({ path: `${OUT}/qa_p2_result.png`, fullPage: false });

if (result === "done") {
  const footer = await page.locator('text=/已自動存入草稿（\\d+\\/10）/').count();
  log(`draft footer: ${footer > 0 ? "PASS" : "FAIL"}`);
  const chart = await page.locator("svg path").count();
  log(`chart svg paths on page: ${chart}`);
  // scroll chat to bottom & screenshot chart area
  await page.screenshot({ path: `${OUT}/qa_p2_done_full.png` });
}

// auto-collapse check: wait 10s after done → console should collapse (not pinned)
await page.waitForTimeout(11000);
const stripAfter = await page.locator('text=CONSOLE').count();
log(`console auto-collapsed after run: ${stripAfter > 0 ? "PASS" : "FAIL (still open or pinned)"}`);
await page.screenshot({ path: `${OUT}/qa_p2_after.png` });

await browser.close();
log("DONE");
