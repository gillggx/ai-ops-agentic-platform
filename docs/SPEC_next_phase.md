# Spec: Next Phase — Skill Pipeline 存儲 + Resizable UI + 進階 Explorer

**Version:** 2.0
**Date:** 2026-04-16 (updated)
**Author:** Gill + Claude
**Status:** Implemented

---

## 1. Skill Pipeline 存儲（「儲存為 My Skill」）

### 1.1 目標
使用者在 Copilot 完成一次成功的 pipeline 查詢後，可以一鍵「儲存為 My Skill」，保存 Stage 3~6 的 params + code。

### 1.2 存儲內容

```yaml
Skill:
  name: "使用者命名"
  source: "pipeline"
  binding_type: "none"  # My Skill
  pipeline_config:
    data_retrieval:
      mcp: "get_process_info"
      params: {step: "STEP_007"}
    data_transform:
      code: "..." # 自動生成的 transform Python code
    compute:
      code: "..." # 自動生成的 compute Python code
      type: "linear_regression"
    presentation:
      data_source: "processed_data"
      chart_type: "scatter"
  input_schema:
    - {key: "step", type: "string", required: true}
  output_schema:
    - {key: "regression_results", type: "table"}
```

### 1.3 執行
下次 Copilot 遇到匹配的問題 → `execute_skill` → 系統直接跑 pipeline（不需要 LLM 重新規劃）。

### 1.4 升級路徑
My Skill → 綁 Event → Auto-Patrol（自動巡檢）
My Skill → 綁 Alarm → Diagnostic Rule（告警診斷）

---

## 2. Resizable Panel（拖拽調整寬度）

### 2.1 需求
- Copilot 側邊欄 360px 固定太窄
- 14 吋筆電上 DataExplorer 被壓縮

### 2.2 方案
使用 `react-resizable-panels` library（輕量，~10KB）：

```tsx
<PanelGroup direction="horizontal">
  <Panel defaultSize={70}>
    {/* Main content / DataExplorer */}
  </Panel>
  <PanelResizeHandle />
  <Panel defaultSize={30} minSize={20} maxSize={50}>
    {/* AI Copilot */}
  </Panel>
</PanelGroup>
```

### 2.3 影響
- AppShell.tsx 改用 PanelGroup
- 需要 `npm install react-resizable-panels`

---

## 3. 進階 Explorer 功能

### 3.1 Histogram / Distribution View
目前 Explorer 只有 line/scatter/bar。新增：
- Histogram tab — 顯示值的分佈
- Box plot — 顯示 Q1/Q2/Q3 + outliers
- 適用 TC20（常態分佈 + sigma 標記）

### 3.2 Correlation Matrix
多參數之間的相關性熱力圖：
- 使用者選 3~5 個參數
- 自動計算 Pearson correlation
- 熱力圖顯示

### 3.3 Time-window Slider
- X 軸下方加一個 range slider
- 使用者可以拖拽選擇時間範圍
- 圖表即時更新（前端計算，不呼叫 API）

---

## 4. Playwright E2E 測試

### 4.1 目的
確保 UI 在不同解析度下正常運作。

### 4.2 測試腳本
```typescript
test("DataExplorer renders on 1920x1080", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/");
  // ... trigger TC01
  await expect(page.locator(".data-explorer")).toBeVisible();
  await page.screenshot({ path: "screenshots/1920.png", fullPage: true });
});

test("DataExplorer renders on 1366x768", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  // ...
});
```

### 4.3 CI 整合
GitHub Actions deploy workflow → run Playwright → upload screenshots as artifacts。

---

## 5. rem/clamp 流體化（全站）

### 5.1 目標
將 px 單位改為 rem/clamp，讓 padding/font-size 在不同 viewport 自動縮放。

### 5.2 規範
```css
/* Before */
font-size: 13px;
padding: 12px 16px;

/* After */
font-size: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);
padding: clamp(0.5rem, 0.4rem + 0.5vw, 0.75rem) clamp(0.75rem, 0.6rem + 0.75vw, 1rem);
```

### 5.3 影響
全站所有元件。建議用 CSS variables：
```css
:root {
  --fs-xs: clamp(0.65rem, 0.6rem + 0.2vw, 0.75rem);
  --fs-sm: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);
  --fs-md: clamp(0.875rem, 0.8rem + 0.3vw, 1rem);
  --sp-xs: clamp(0.25rem, 0.2rem + 0.25vw, 0.5rem);
  --sp-sm: clamp(0.5rem, 0.4rem + 0.5vw, 0.75rem);
  --sp-md: clamp(0.75rem, 0.6rem + 0.75vw, 1rem);
}
```

---

## 6. Implementation Status (2026-04-16)

| Priority | 項目 | 狀態 | 實作摘要 |
|----------|------|------|---------|
| P1 | Skill Pipeline 存儲 | ✅ Done | `pipeline_config` DB column + `POST /from-pipeline` API + SkillExecutorService pipeline branch + PipelineConsole "Save as Skill" button |
| P1 | Resizable Panel | ✅ Done | CSS `resize: horizontal` + collapsible Copilot toggle strip (28px) |
| P2 | Explorer Histogram/Distribution | ✅ Done | ChartExplorer: Line/Scatter/Histogram/Box Plot selector + sigma bands (1-4σ) |
| P2 | Playwright E2E | ✅ Done | `e2e/playwright.config.ts` + smoke.spec.ts + data-explorer.spec.ts (1920/1366 viewports) |
| P3 | Correlation Matrix | ✅ Done | Heatmap chart type (auto-detect compute_results.matrix or client-side Pearson) |
| P3 | Time-window Slider | ✅ Done | Plotly rangeslider toggle for Line/Scatter modes |
| P3 | rem/clamp 流體化 | ✅ Done | CSS design tokens in globals.css + applied to 6 components |

### Additional fixes during deployment:
- Alarm Center left panel: 35% → 220px compact sidebar (aligned with Dashboard)
- Admin tables (Auto-Patrols, Diagnostic Rules): action buttons `flex nowrap` + scrollable wrapper
- Copilot panel: collapsible toggle strip instead of `react-resizable-panels` (v4 API broken)

### UI/UX Guidelines
See [SPEC_ui_guidelines.md](SPEC_ui_guidelines.md) for the consolidated design system.

---

*All 7 items implemented and deployed 2026-04-16.*
