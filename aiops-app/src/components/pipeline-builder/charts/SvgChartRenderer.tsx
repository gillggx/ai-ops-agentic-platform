/**
 * SvgChartRenderer — Stage 4 dispatcher.
 *
 * Single lookup table that routes a ChartSpec (or wrapper produced by
 * pipeline_executor `result_summary.charts[i]`) to the matching SVG chart
 * component from the 18-block engine. No per-type if/else logic.
 *
 * Usage:
 *   <SvgChartRenderer spec={chartDsl} height={280} />
 *
 * Wrapper unwrap: pipeline executor emits each chart as
 *   { title, node_id, sequence, chart_spec: { type, x, y, ... } }
 * for `result_summary.charts`. Pipeline Builder's ResultsBody peels
 * chart_spec out itself, but the alarm detail / RenderMiddleware path
 * passes the wrapper straight through. We unwrap defensively here so the
 * dispatcher stays the same in both paths.
 *
 * Legacy aliases (so existing block_chart output keeps rendering until
 * Stage 5 migration renames the producers):
 *   boxplot      → BoxPlot
 *   heatmap      → HeatmapDendro (cluster=false unless caller asks)
 *   distribution → Histogram
 */

'use client';

import * as React from 'react';
import {
  LineChart, BarChart, ScatterChart,
  BoxPlot, Splom, Histogram,
  XbarR, IMR, EwmaCusum,
  Pareto, VariabilityGauge, ParallelCoords, ProbabilityPlot, HeatmapDendro,
  WaferHeatmap, DefectStack, SpatialPareto, TrendWaferMaps,
  StyleAdjuster, themeStyle, DEFAULT_THEME,
  type ChartCardTheme,
  type ChartSpec,
} from '.';
import { useUserChartTheme } from '@/lib/charts/useUserChartTheme';

interface Props {
  spec: ChartSpec | Record<string, unknown> | null | undefined;
  height?: number;
  /** Disable the per-card StyleAdjuster ✦ button (e.g. for thumbnails / SSR previews). */
  noStyleAdjuster?: boolean;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ChartFC = React.FC<{ spec: ChartSpec; height?: number }>;

const TYPE_MAP: Record<string, ChartFC> = {
  // PR-B primitives
  line: LineChart,
  bar: BarChart,
  scatter: ScatterChart,
  // PR-C EDA + legacy aliases
  box_plot: BoxPlot,
  boxplot: BoxPlot,
  splom: Splom,
  histogram: Histogram,
  distribution: Histogram,
  // PR-D SPC
  xbar_r: XbarR,
  imr: IMR,
  ewma_cusum: EwmaCusum,
  // PR-E Diagnostic + legacy heatmap alias
  pareto: Pareto,
  variability_gauge: VariabilityGauge,
  parallel_coords: ParallelCoords,
  probability_plot: ProbabilityPlot,
  heatmap_dendro: HeatmapDendro,
  heatmap: HeatmapDendro,
  // PR-F Wafer
  wafer_heatmap: WaferHeatmap,
  defect_stack: DefectStack,
  spatial_pareto: SpatialPareto,
  trend_wafer_maps: TrendWaferMaps,
};

// Defensive unwrap of pipeline_executor's chart wrapper.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function unwrapSpec(input: any): ChartSpec | null {
  if (!input || typeof input !== 'object') return null;
  // wrapper {title, node_id, sequence, chart_spec}
  if (input.chart_spec && typeof input.chart_spec === 'object') {
    return {
      ...input.chart_spec,
      title: input.chart_spec.title ?? input.title,
    } as ChartSpec;
  }
  return input as ChartSpec;
}

function PlaceholderEmpty({ title, message }: { title?: string; message?: string }) {
  return (
    <div data-testid="svg-chart-empty" className="pb-chart-empty">
      <div className="pb-chart-ph-title">{title || 'No data'}</div>
      <div>{message || '上游無資料 — 圖無法繪製'}</div>
    </div>
  );
}

function PlaceholderUnknown({ type }: { type: string }) {
  return (
    <div data-testid="svg-chart-unknown" className="pb-chart-unknown">
      <div className="pb-chart-ph-title">
        ⚠ Unknown chart type: <code>{type}</code>
      </div>
      <div>新 chart 類型未在 dispatcher 註冊；請在 SvgChartRenderer.tsx TYPE_MAP 補上。</div>
    </div>
  );
}

export default function SvgChartRenderer({ spec, height, noStyleAdjuster }: Props) {
  // Per-card theme state — initial value comes from the user's saved
  // preference (cached, fetched once per session). CSS vars cascade from
  // this host div into the chart's own `.pb-chart-card`, so we don't
  // need to thread a `theme` prop through every chart component.
  // After mount, the hook may resolve and update the cached theme;
  // we apply it to local state via effect (one-shot — don't clobber
  // user's per-card ✦ tweaks).
  const { theme: userTheme, saveAsDefault } = useUserChartTheme();
  const [theme, setTheme] = React.useState<ChartCardTheme>(userTheme);
  const initFromUserRef = React.useRef(false);
  React.useEffect(() => {
    if (initFromUserRef.current) return;
    setTheme(userTheme);
    initFromUserRef.current = true;
  }, [userTheme]);

  const inner = unwrapSpec(spec);
  if (!inner || typeof inner.type !== 'string') {
    return <PlaceholderEmpty title="(no spec)" message="ChartSpec missing or has no type" />;
  }
  // Backend executors emit `type: 'empty'` for placeholder cards; not in
  // the canonical ChartType union but flows through the same path.
  if ((inner.type as string) === 'empty') {
    return (
      <PlaceholderEmpty
        title={(inner as { title?: string }).title}
        message={(inner as { message?: string }).message}
      />
    );
  }
  const Component = TYPE_MAP[inner.type as string];
  if (!Component) return <PlaceholderUnknown type={inner.type} />;

  // Wrap with theme host — CSS vars cascade into the chart's own
  // `.pb-chart-card`, StyleAdjuster ✦ overlays in the top-right.
  // `position: relative` is required by .pb-style-btn's absolute positioning.
  return (
    <div
      className="pb-chart-card-host"
      style={{ position: 'relative', width: '100%', ...themeStyle(theme) }}
    >
      {!noStyleAdjuster && (
        <StyleAdjuster
          theme={theme}
          setTheme={setTheme}
          chartType={inner.type}
          onSaveAsDefault={() => saveAsDefault(theme)}
        />
      )}
      <Component spec={inner} height={height} />
    </div>
  );
}
