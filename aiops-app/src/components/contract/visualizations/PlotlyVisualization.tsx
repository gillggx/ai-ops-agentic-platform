import { McpChartRenderer } from "@/components/McpChartRenderer";

export function PlotlyVisualization({ spec }: { spec: Record<string, unknown> }) {
  const chartData = spec.chart_data as string | undefined;
  if (!chartData) return null;
  return (
    <McpChartRenderer
      uiRender={{ chart_data: chartData, charts: [], type: "trend_chart" }}
      dataset={[]}
    />
  );
}
