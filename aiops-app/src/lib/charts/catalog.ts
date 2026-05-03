/**
 * Chart Catalog — single source of truth for /help/charts (grid + detail
 * pages). Every chart has:
 *
 *   - id           = ChartType enum member (matches backend block_id stem)
 *   - blockId      = "block_<id>" name in pb_blocks (used to fetch
 *                    description / params from /api/pipeline-builder/blocks)
 *   - group        = filter category (Primitive / EDA / SPC / Diagnostic / Wafer)
 *   - title / hint = catalog card display
 *   - examples     = ≥ 1 named mock-data factories (Detail page renders a
 *                    dropdown switcher)
 *   - llmPrompts   = 1-2 example natural-language prompts a user can paste
 *                    into AIAgentPanel to build this chart via the agent
 *
 * Source for `group / title / hint` matches the existing /dev/charts page so
 * we keep visual consistency. block-description metadata (用途 / 何時用 /
 * 參數) is fetched live from the API; this file only carries what the API
 * doesn't have (LLM prompts, example labels, advanced flag).
 */

import type { ChartType } from "@/components/pipeline-builder/charts";
import type { ChartSpec } from "@/components/pipeline-builder/charts";
import {
  lineSpec, barSpec, scatterSpec,
  boxPlotSpec, splomSpec, histogramSpec,
  xbarRSpec, imrSpec, ewmaCusumSpec,
  paretoSpec, variabilityGaugeSpec, parallelCoordsSpec, probabilityPlotSpec, heatmapDendroSpec,
  waferHeatmapSpec, defectStackSpec, spatialParetoSpec, trendWaferMapsSpec,
} from "./mock-data";

export type ChartGroup = "Primitive" | "EDA" | "SPC" | "Diagnostic" | "Wafer";

export interface ChartExample {
  /** Short label shown in the detail-page dropdown. */
  label: string;
  /** Factory returning a fresh ChartSpec. Idempotent (deterministic mock data). */
  spec: () => ChartSpec;
}

export interface ChartCatalogEntry {
  /** Detail-page URL: /help/charts/{id} */
  id: string;
  /** Match name in pb_blocks. */
  blockId: string;
  /** ChartType union member used by SvgChartRenderer dispatcher. */
  chartType: ChartType;
  group: ChartGroup;
  title: string;
  hint: string;
  examples: ChartExample[];
  llmPrompts: string[];
}

export const CHART_CATALOG: ChartCatalogEntry[] = [
  // ── Primitives ─────────────────────────────────────────────────────
  {
    id: "line", blockId: "block_line_chart", chartType: "line",
    group: "Primitive",
    title: "Line Chart",
    hint: "純時序趨勢、多線疊圖、雙 Y 軸 — 最常用的時間序列圖",
    examples: [
      { label: "SPC trend with UCL/LCL", spec: lineSpec },
    ],
    llmPrompts: [
      "畫 EQP-05 thickness 過去 24 小時趨勢，標 UCL/LCL/Center 三條線",
      "把 SPC value 跟 APC rf_power_bias 雙軸疊圖",
    ],
  },
  {
    id: "bar", blockId: "block_bar_chart", chartType: "bar",
    group: "Primitive",
    title: "Bar Chart",
    hint: "類別比較、count、ranking — 一張圖看出哪個類別最多",
    examples: [
      { label: "OOC count by tool", spec: barSpec },
    ],
    llmPrompts: [
      "全廠各機台 24h OOC count bar chart，超過 30% 標紅",
      "每個 step 的 alarm 數量比較",
    ],
  },
  {
    id: "scatter", blockId: "block_scatter_chart", chartType: "scatter",
    group: "Primitive",
    title: "Scatter Plot",
    hint: "看兩個變數相關性、x-vs-y 散布",
    examples: [
      { label: "RF power vs thickness", spec: scatterSpec },
    ],
    llmPrompts: [
      "RF Power 跟 thickness 的散布圖看相關性",
      "stage_time vs OOC% 散布",
    ],
  },

  // ── EDA ────────────────────────────────────────────────────────────
  {
    id: "box_plot", blockId: "block_box_plot", chartType: "box_plot",
    group: "EDA",
    title: "Box Plot",
    hint: "比較不同組之間的數值分布、看離群點 — IQR + whisker + outlier",
    examples: [
      { label: "Tool × Chamber thickness", spec: boxPlotSpec },
    ],
    llmPrompts: [
      "比較 4 台機台的 thickness 分布",
      "每個 lot 的 CD 變異 box plot，巢狀分組顯示 wafer 階層",
    ],
  },
  {
    id: "splom", blockId: "block_splom", chartType: "splom",
    group: "EDA",
    title: "Scatter Plot Matrix (SPLOM)",
    hint: "5+ 個變數兩兩散布 + 對角 density + |r| 熱力 — FDC 多參數探索",
    examples: [
      { label: "FDC 5-param exploration", spec: splomSpec },
    ],
    llmPrompts: [
      "5 個 FDC sensor 兩兩散布矩陣，異常點標紅",
      "Recipe 主要參數的 pairwise correlation",
    ],
  },
  {
    id: "histogram", blockId: "block_histogram_chart", chartType: "histogram",
    group: "EDA",
    title: "Histogram",
    hint: "分布直方圖 + USL/LSL spec window + 自動算 Cpk + ppm",
    examples: [
      { label: "CD distribution with spec", spec: histogramSpec },
    ],
    llmPrompts: [
      "STEP_007 thickness 直方圖，給 USL=15.5 LSL=14.5 算 Cpk",
      "EQP-03 的 RF power 分布看常態性",
    ],
  },

  // ── SPC ────────────────────────────────────────────────────────────
  {
    id: "xbar_r", blockId: "block_xbar_r", chartType: "xbar_r",
    group: "SPC",
    title: "X̄/R Control Chart",
    hint: "標準 SPC X̄/R 管制圖 + WECO R1-R8 自動偵測 — subgroup-size 監控",
    examples: [
      { label: "Subgroup size 5 with WECO", spec: xbarRSpec },
    ],
    llmPrompts: [
      "STEP_007 thickness 的 X̄/R 管制圖，subgroup_size=5，所有 WECO 規則開",
      "幫我建一個 lot-level X̄/R chart 監控 spc_xbar_chart_value",
    ],
  },
  {
    id: "imr", blockId: "block_imr", chartType: "imr",
    group: "SPC",
    title: "Individual + Moving Range (I-MR)",
    hint: "n=1 SPC 監控 — destructive test / single-shot endpoint 用這個",
    examples: [
      { label: "Endpoint thickness n=1", spec: imrSpec },
    ],
    llmPrompts: [
      "EQP-04 endpoint thickness 的 IMR chart，WECO R1+R2",
      "destructive test 的 individual chart",
    ],
  },
  {
    id: "ewma_cusum", blockId: "block_ewma_cusum", chartType: "ewma_cusum",
    group: "SPC",
    title: "EWMA / CUSUM",
    hint: "微小偏移早期警示 — 比 X̄/R 更敏感、抓 0.5σ 級緩慢漂移",
    examples: [
      { label: "EWMA λ=0.2", spec: () => ewmaCusumSpec("ewma") },
      { label: "CUSUM k=0.5 h=4", spec: () => ewmaCusumSpec("cusum") },
    ],
    llmPrompts: [
      "EQP-02 的 EWMA chart，λ=0.2 抓緩慢漂移",
      "CUSUM 偵測 STEP_005 RF power 的 1σ shift",
    ],
  },

  // ── Diagnostic ─────────────────────────────────────────────────────
  {
    id: "pareto", blockId: "block_pareto", chartType: "pareto",
    group: "Diagnostic",
    title: "Pareto Chart",
    hint: "排序 bars + 累計 % 線 + 80% 參考線 — 「找最大貢獻者」必備",
    examples: [
      { label: "Defect type top-N", spec: paretoSpec },
    ],
    llmPrompts: [
      "全廠最常見的 defect type pareto",
      "哪幾台機台貢獻 80% OOC 事件",
    ],
  },
  {
    id: "variability_gauge", blockId: "block_variability_gauge", chartType: "variability_gauge",
    group: "Diagnostic",
    title: "Variability Gauge",
    hint: "多階分組變異分解 — 看 lot/wafer/tool 各層 shift 來源",
    examples: [
      { label: "Lot × Wafer × Tool", spec: variabilityGaugeSpec },
    ],
    llmPrompts: [
      "Thickness 變異分解成 lot / wafer / tool 三層",
      "比較 lot-to-lot 跟 wafer-to-wafer 的變異哪個大",
    ],
  },
  {
    id: "parallel_coords", blockId: "block_parallel_coords", chartType: "parallel_coords",
    group: "Diagnostic",
    title: "Parallel Coordinates",
    hint: "N 軸並列、每筆 row 一條折線 — Recipe 5+ params 探索 yield",
    examples: [
      { label: "Recipe params vs yield", spec: parallelCoordsSpec },
    ],
    llmPrompts: [
      "Recipe 6 個關鍵參數 vs Yield 的平行座標，yield<92 標紅",
      "FDC 多參數同時看哪幾組數值跑掉",
    ],
  },
  {
    id: "probability_plot", blockId: "block_probability_plot", chartType: "probability_plot",
    group: "Diagnostic",
    title: "Q-Q Probability Plot",
    hint: "常態檢定 + Anderson-Darling p-value — Cpk 算前確認常態性",
    examples: [
      { label: "AD test on thickness", spec: probabilityPlotSpec },
    ],
    llmPrompts: [
      "EQP-03 thickness 是否常態分布，給 AD test p-value",
      "Cpk 算之前先看 QQ plot",
    ],
  },
  {
    id: "heatmap_dendro", blockId: "block_heatmap_dendro", chartType: "heatmap_dendro",
    group: "Diagnostic",
    title: "Clustered Heatmap (with Dendrogram)",
    hint: "相關矩陣 + 階層分群 — 自動把同步異常的參數放一起",
    examples: [
      { label: "FDC param correlation", spec: heatmapDendroSpec },
    ],
    llmPrompts: [
      "FDC 全部 sensor 兩兩相關矩陣，cluster 排序",
      "哪幾個 step 的 OOC 同步發生",
    ],
  },

  // ── Wafer ──────────────────────────────────────────────────────────
  {
    id: "wafer_heatmap", blockId: "block_wafer_heatmap", chartType: "wafer_heatmap",
    group: "Wafer",
    title: "Wafer Heatmap (IDW)",
    hint: "49-site 量測 + IDW 內插 + uniformity 統計 — 看空間分布",
    examples: [
      { label: "49-site thickness", spec: waferHeatmapSpec },
    ],
    llmPrompts: [
      "WAFER-001 的 49-site thickness wafer heatmap",
      "edge ring drift 比較，notch 朝下",
    ],
  },
  {
    id: "defect_stack", blockId: "block_defect_stack", chartType: "defect_stack",
    group: "Wafer",
    title: "Defect Stack Map",
    hint: "晶圓缺陷空間分布 — particle / scratch / pattern 著色",
    examples: [
      { label: "Multi-code defect map", spec: defectStackSpec },
    ],
    llmPrompts: [
      "最近 50 wafer 的 defect 空間分布，按缺陷類型著色",
      "Particle 是否聚集在 edge ring",
    ],
  },
  {
    id: "spatial_pareto", blockId: "block_spatial_pareto", chartType: "spatial_pareto",
    group: "Wafer",
    title: "Spatial Pareto",
    hint: "Yield 切格 + diverging palette + 最差 cell 黑框 — 看哪一區最差",
    examples: [
      { label: "Yield by grid cell", spec: spatialParetoSpec },
    ],
    llmPrompts: [
      "WAFER-001 的 yield 空間 pareto，找最差區域",
      "Edge yield drop 嚴重程度",
    ],
  },
  {
    id: "trend_wafer_maps", blockId: "block_trend_wafer_maps", chartType: "trend_wafer_maps",
    group: "Wafer",
    title: "Trend Wafer Maps",
    hint: "Small multiples — 多片 wafer 隨時間排列、PM 日紅框",
    examples: [
      { label: "7-day pre/post PM", spec: trendWaferMapsSpec },
    ],
    llmPrompts: [
      "EQP-04 過去 7 天每天 wafer 空間分布 small multiples，PM 日標紅",
      "Lot-to-lot 重複性比較",
    ],
  },
];

export function getChartById(id: string): ChartCatalogEntry | undefined {
  return CHART_CATALOG.find((c) => c.id === id);
}

export const CHART_GROUPS: ChartGroup[] = [
  "Primitive", "EDA", "SPC", "Diagnostic", "Wafer",
];
