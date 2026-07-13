/**
 * headless.ts (result-vision, 2026-07-13) — React-free chart dispatch。
 *
 * 成品目檢用：sidecar 在 build 完成前把最終 chart_spec 用「跟使用者看到
 * 一模一樣」的渲染器畫成 SVG → 截圖 → 給 vision judge。這裡只彙整 18 個
 * chart 的純 render 函式（與 SvgChartRenderer 的 TYPE_MAP 同一組 type 名），
 * 不 import React；由 tools/result_render/entry.ts 打包成 headless bundle。
 * 新 chart 類型：SvgChartRenderer TYPE_MAP 加了這裡也要加（回歸包會抓漏）。
 */
import type { ChartSpec } from './types';
import { renderLineChart } from './LineChart';
import { renderBarChart } from './BarChart';
import { renderScatterChart } from './ScatterChart';
import { renderBoxPlot } from './BoxPlot';
import { renderSplom } from './Splom';
import { renderHistogram } from './Histogram';
import { renderIMR } from './IMR';
import { renderXbarR } from './XbarR';
import { renderEwmaCusum } from './EwmaCusum';
import { renderPareto } from './Pareto';
import { renderVariabilityGauge } from './VariabilityGauge';
import { renderParallelCoords } from './ParallelCoords';
import { renderProbabilityPlot } from './ProbabilityPlot';
import { renderHeatmapDendro } from './HeatmapDendro';
import { renderWaferHeatmap } from './WaferHeatmap';
import { renderDefectStack } from './DefectStack';
import { renderSpatialPareto } from './SpatialPareto';
import { renderTrendWaferMaps } from './TrendWaferMaps';

// 部分 render fn 收第三個 opts 參數（有預設值）— 統一簽名容忍之。
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type RenderFn = (svg: SVGSVGElement, spec: ChartSpec, ...rest: any[]) => void;

const RENDER_MAP: Record<string, RenderFn> = {
  line: renderLineChart,
  bar: renderBarChart,
  scatter: renderScatterChart,
  box_plot: renderBoxPlot,
  boxplot: renderBoxPlot,
  splom: renderSplom,
  histogram: renderHistogram,
  distribution: renderHistogram,
  xbar_r: renderXbarR,
  imr: renderIMR,
  ewma_cusum: renderEwmaCusum,
  pareto: renderPareto,
  variability_gauge: renderVariabilityGauge,
  parallel_coords: renderParallelCoords,
  probability_plot: renderProbabilityPlot,
  heatmap_dendro: renderHeatmapDendro,
  heatmap: renderHeatmapDendro,
  wafer_heatmap: renderWaferHeatmap,
  defect_stack: renderDefectStack,
  spatial_pareto: renderSpatialPareto,
  trend_wafer_maps: renderTrendWaferMaps,
};

/** 渲染一份 chart_spec 進 svg；未知 type 回 false（caller 決定 fallback）。 */
export function renderChartHeadless(svg: SVGSVGElement, spec: ChartSpec): boolean {
  const fn = RENDER_MAP[String((spec as { type?: string }).type ?? "")];
  if (!fn) return false;
  // 有些 render fn 收第三個 opts（BoxPlot expanded/showOutliers 等）——
  // headless 給空物件（屬性讀到 undefined = 預設關）。
  fn(svg, spec, {});
  return true;
}

export const HEADLESS_CHART_TYPES = Object.keys(RENDER_MAP);
