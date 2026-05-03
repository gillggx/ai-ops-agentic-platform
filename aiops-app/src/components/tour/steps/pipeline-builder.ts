import type { TourStep } from "../types";

/** Pipeline Builder onboarding (8 steps).
 *
 * Selectors target classes already present in BuilderLayout / BlockLibrary /
 * AIAgentPanel / canvas. Add a `data-tour-id="..."` attribute next to any
 * fragile selector if a class rename breaks targeting.
 */
export const PIPELINE_BUILDER_STEPS: TourStep[] = [
  {
    title: "歡迎使用 AIOps Pipeline Builder",
    body: "這是一個資料管線編輯器。我們會用 60 秒帶你走過 6 個重點功能。隨時可按 ESC 或 Skip 略過；之後可隨時點左下角 ? 重看。",
    target: null,
    placement: "center",
  },
  {
    title: "① Block Library — 從這裡加入元件",
    body: "左側面板有 4 種 blocks：資料源、處理、圖表、邏輯。新增的 18 種 chart blocks（Histogram / Pareto / Wafer Heatmap…）都在「圖表」分類下，跟 Filter / Join 一樣可拖入 canvas。",
    target: '[data-tour-id="pb-library"]',
    placement: "right",
  },
  {
    title: "② AI Agent — 自然語言建 Pipeline",
    body: "右側 AI Agent 接收自然語言需求，自動規劃並串接 nodes。例如輸入「分析 EQP-05 各站點 OOC rate」，Agent 會建立 Source → Filter → Groupby → Pareto chart 的完整管線。",
    target: '[data-tour-id="pb-agent-panel"]',
    placement: "left",
  },
  {
    title: "③ 連接 Nodes",
    body: "Node 右側的 ● 是輸出 port，左側是輸入 port。從輸出拖到輸入即可串接。資料流從左到右，邊上的數字代表 row count。",
    target: '[data-tour-id="pb-canvas"]',
    placement: "top",
  },
  {
    title: "④ Inspector + StyleAdjuster",
    body: "選取一個 chart node，右側會出現 Inspector 可改 chart type、palette、線粗、顏色。每張 chart 卡片右上的 ✦ 按鈕也可獨立調整樣式。",
    target: '[data-tour-id="pb-inspector"]',
    placement: "left",
  },
  {
    title: "⑤ ⌘K 快速找東西",
    body: "在任何頁面按 ⌘K（Windows 是 Ctrl+K），跨 surface 搜尋 pipeline / alarm / equipment / 當下 canvas 上的 nodes — 一鍵跳轉。",
    target: null,
    placement: "center",
  },
  {
    title: "⑥ Run Full → 看 Results",
    body: "右上 Run Full 執行整條 pipeline。執行完按 Results，可在多張 charts 之間切換瀏覽（也可用 ← / → 鍵）。",
    target: '[data-tour-id="pb-run-full"]',
    placement: "bottom",
  },
  {
    title: "完成！",
    body: "隨時可點左下角 ? 按鈕重新觀看本導覽。Pipeline 列表（左上 ☰ List）可切換 pipelines。祝順利。",
    target: ".tour-help",
    placement: "right",
  },
];
