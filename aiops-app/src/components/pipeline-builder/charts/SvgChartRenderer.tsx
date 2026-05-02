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
  type ChartSpec,
} from '.';

interface Props {
  spec: ChartSpec | Record<string, unknown> | null | undefined;
  height?: number;
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
    <div
      data-testid="svg-chart-empty"
      style={{
        padding: 16,
        textAlign: 'center',
        border: '1px dashed #cbd5e0',
        borderRadius: 6,
        background: '#f8fafc',
        color: '#64748b',
        fontSize: 12,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: '#475569', marginBottom: 4 }}>
        {title || 'No data'}
      </div>
      <div>{message || '上游無資料 — 圖無法繪製'}</div>
    </div>
  );
}

function PlaceholderUnknown({ type }: { type: string }) {
  return (
    <div
      data-testid="svg-chart-unknown"
      style={{
        padding: 16,
        textAlign: 'center',
        border: '1px dashed #fcd34d',
        borderRadius: 6,
        background: '#fffbeb',
        color: '#92400e',
        fontSize: 12,
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
        ⚠ Unknown chart type: <code>{type}</code>
      </div>
      <div>新 chart 類型未在 dispatcher 註冊；請在 SvgChartRenderer.tsx TYPE_MAP 補上。</div>
    </div>
  );
}

export default function SvgChartRenderer({ spec, height }: Props) {
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
  return <Component spec={inner} height={height} />;
}
