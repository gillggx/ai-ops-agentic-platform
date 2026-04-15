# AIOps Platform — UI/UX Design Guidelines

**Version:** 1.0
**Date:** 2026-04-16
**Author:** Gill + Claude
**Status:** Active

---

## 1. Core Principle: Content First, Chrome Minimal

使用者的核心任務是**看數據、做決策**。所有 UI chrome（sidebar、panel、toolbar）都是輔助，不應搶佔主要內容的空間。

### 1.1 Golden Rule

> **重點畫面吃滿畫面。** 左右側面板都可收合，讓使用者在需要時獲得最大的內容區域。

---

## 2. Layout Architecture

### 2.1 三欄結構

```
┌────────────────────────────────────────────────────────────┐
│ Topbar (48px, sticky)                                      │
├──┬───────────────────────────────────────────────┬──┬──────┤
│  │                                               │  │      │
│S │            Main Content                       │T │ AI   │
│I │            (flex: 1)                          │O │Copilot│
│D │                                               │G │(380px)│
│E │                                               │G │      │
│B │                                               │L │      │
│A │                                               │E │      │
│R │                                               │  │      │
├──┴───────────────────────────────────────────────┴──┴──────┤
```

| 區域 | 寬度 | 可收合 | 收合後 |
|------|------|--------|--------|
| Left Sidebar (Nav) | 48px collapsed / 200px expanded | Yes | 48px (icon-only) |
| Main Content | `flex: 1` (吃滿剩餘空間) | No | — |
| Copilot Toggle Strip | 28px | — | 永遠可見 |
| AI Copilot Panel | 380px (min 280, max 50vw) | Yes | 隱藏，只剩 toggle strip |

### 2.2 頁面內左側面板

部分頁面有自己的左側列表（Alarm Center、Dashboard）。這些面板必須遵守：

| 頁面 | 面板寬度 | 可收合 | 收合後 |
|------|---------|--------|--------|
| Dashboard (設備清單) | 220px | Yes (◀ 按鈕) | 48px (icon-only) |
| Alarm Center (告警列表) | 220px | 建議加 | — |

**規範：** 頁面內左側面板寬度統一 **220px**，與 Dashboard 對齊。

### 2.3 Copilot Panel 行為

- 預設展開（380px）
- 點擊 toggle strip (▶) 收合，只剩 28px 垂直文字 "AI Copilot"
- 點擊 toggle strip (◀) 展開
- `resize: horizontal` + `direction: rtl` 允許使用者從左邊拖拽調整寬度
- 約束：min 280px, max 50vw

---

## 3. Fluid Typography (流體字型)

### 3.1 Design Tokens

定義在 `aiops-app/src/app/globals.css` 的 `:root`：

```css
:root {
  /* Font sizes — clamp(min, preferred, max) */
  --fs-xs: clamp(0.625rem, 0.575rem + 0.2vw, 0.75rem);     /* ~10-12px */
  --fs-sm: clamp(0.75rem, 0.7rem + 0.25vw, 0.875rem);      /* ~12-14px */
  --fs-md: clamp(0.8125rem, 0.76rem + 0.25vw, 0.9375rem);  /* ~13-15px */
  --fs-lg: clamp(0.875rem, 0.82rem + 0.3vw, 1.0625rem);    /* ~14-17px */
  --fs-xl: clamp(1rem, 0.92rem + 0.4vw, 1.25rem);          /* ~16-20px */

  /* Spacing */
  --sp-xs: clamp(0.25rem, 0.2rem + 0.2vw, 0.375rem);       /* ~4-6px */
  --sp-sm: clamp(0.375rem, 0.3rem + 0.35vw, 0.625rem);     /* ~6-10px */
  --sp-md: clamp(0.5rem, 0.42rem + 0.5vw, 0.75rem);        /* ~8-12px */
  --sp-lg: clamp(0.75rem, 0.62rem + 0.65vw, 1rem);         /* ~12-16px */
  --sp-xl: clamp(1rem, 0.82rem + 0.9vw, 1.5rem);           /* ~16-24px */

  /* Border radius */
  --radius-sm: clamp(3px, 0.15rem + 0.1vw, 5px);
  --radius-md: clamp(4px, 0.2rem + 0.15vw, 8px);
}
```

### 3.2 Usage Rules

| 用途 | Token | 範例 |
|------|-------|------|
| 表格數據、次要標籤 | `--fs-xs` | Alarm list metadata, table headers |
| 正文、按鈕文字 | `--fs-sm` | Card content, button labels, nav items |
| 段落文字 | `--fs-md` | Alarm detail body text |
| 小標題 | `--fs-lg` | Section headers, panel titles |
| 大標題 | `--fs-xl` | Page titles, Topbar brand |

### 3.3 Inline Style 用法

```tsx
// React inline style 中使用 CSS variable
<span style={{ fontSize: "var(--fs-sm)", padding: "var(--sp-md)" }}>
  Content
</span>
```

### 3.4 不適用的場景

- **Plotly 圖表**：Plotly 用自己的 layout.font.size，不受 CSS variables 影響
- **第三方元件**：不強制改寫第三方 library 的內部樣式

---

## 4. Responsive Targets

### 4.1 支援的解析度

| 名稱 | 寬度 | 說明 |
|------|------|------|
| Desktop (1920) | 1920×1080 | 主要開發目標 |
| Laptop (1366) | 1366×768 | 14 吋筆電，需確保不破版 |

### 4.2 斷點策略

目前不使用 media queries 斷點。用 `clamp()` 做連續縮放：
- 1366px 時 `--fs-sm` ≈ 12px, `--sp-md` ≈ 8px
- 1920px 時 `--fs-sm` ≈ 14px, `--sp-md` ≈ 12px

### 4.3 Playwright E2E 驗證

每次 UI 改動後，用兩個 viewport project 驗證：
```bash
cd aiops-app && npm run e2e
# Runs: desktop-1920 (1920×1080) + laptop-1366 (1366×768)
```

---

## 5. Component Patterns

### 5.1 Sidebar Lists (Alarm, Equipment)

```
寬度: 220px (fixed)
每個 item:
  padding: 6px 10px
  title: fontSize 11px, fontWeight 600, max 2 lines (line-clamp)
  metadata: fontSize 10px, color #aaa
  selected: background #e6f7ff, left border 3px #1890ff
```

### 5.2 Admin Tables (Auto-Patrols, Diagnostic Rules, Skills)

```
Table:
  wrapper: overflowX: auto (允許小螢幕水平捲動)
  table: minWidth 700-800px (防止欄位壓縮)
  
Action buttons:
  container: display flex, gap 4px, flexWrap nowrap
  button: whiteSpace nowrap, padding 4px 10px, fontSize 12px
```

### 5.3 Collapsible Panels

所有可收合的面板必須：
1. 有明確的收合/展開 toggle (▶/◀ 或 icon)
2. 收合動畫 < 200ms (`transition: width 0.2s`)
3. 收合後仍顯示最小辨識資訊（icon 或垂直文字）
4. 預設狀態：根據頁面的主要操作決定

| 面板 | 預設 | 理由 |
|------|------|------|
| Nav Sidebar | 收合 | 不需要頻繁切換頁面 |
| Dashboard Equipment | 展開 | 選機台是主要操作 |
| Alarm List | 展開 | 瀏覽告警是主要操作 |
| AI Copilot | 展開 | 對話是核心功能 |

### 5.4 ChartExplorer

```
Chart type selector: [Line] [Scatter] [Histogram] [Box Plot] [Heatmap*]
  * Heatmap 只在有 grouped data 或 compute_results.matrix 時顯示

Time Range toggle: 只在 Line/Scatter 模式顯示
  開啟: Plotly rangeslider (thickness 0.08)

Group filter: dropdown (一次一個 group)
  + Chart button: 疊加更多 group 的獨立圖表
```

---

## 6. Color Palette

| 用途 | Color | Hex |
|------|-------|-----|
| Primary (brand, links) | Blue | #2b6cb0 |
| Success | Green | #38a169 |
| Warning | Orange | #dd6b20 |
| Error / OOC | Red | #e53e3e |
| Info | Purple | #6366f1 |
| Text primary | Dark | #1a202c |
| Text secondary | Gray | #718096 |
| Text muted | Light gray | #a0aec0 |
| Border | Separator | #e2e8f0 |
| Background page | Off-white | #f7f8fc |
| Background card | White | #ffffff |
| Selected row | Light blue | #e6f7ff |
| SPC line | Green | #48bb78 |
| UCL/LCL | Orange dash | #ed8936 |

---

## 7. Anti-patterns (避免)

| 問題 | 為什麼不好 | 正確做法 |
|------|-----------|---------|
| 硬編碼 `fontSize: 13` | 14 吋筆電上太小/太大 | 用 `var(--fs-sm)` |
| 百分比寬度的側邊欄 (`width: 35%`) | 大螢幕上浪費空間 | 用固定寬度 `220px` + 可收合 |
| Action buttons 不加 `nowrap` | 窄欄位時按鈕垂直堆疊 | `display: flex` + `flexWrap: nowrap` |
| Table 沒有 `overflowX: auto` wrapper | 窄螢幕表格被壓扁 | 加 wrapper + `minWidth` |
| 用 `react-resizable-panels` v4 | API 不穩定，Panel 會 collapse | 用 CSS `resize` + collapsible toggle |
| 不可收合的面板 | 14 吋筆電上被壓縮 | 所有面板可收合，內容區吃滿 |

---

*此文件是 AIOps Platform UI/UX 的 living document，隨功能迭代持續更新。*
