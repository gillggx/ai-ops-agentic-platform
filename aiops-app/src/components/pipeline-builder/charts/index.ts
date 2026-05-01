/**
 * Chart engine public API.
 *
 * Each chart component accepts `{ spec: ChartSpec, height? }` and renders
 * SVG inside a `.pb-chart-card` wrapper. The SvgChartRenderer (added in a
 * later PR) routes ChartSpec.type to the right component.
 */

// Lib (re-export for engineers building one-off charts outside the dispatcher).
export * from './lib';
export * from './types';

// Primitives (PR-B).
export { default as LineChart, renderLineChart } from './LineChart';
export { default as BarChart, renderBarChart } from './BarChart';
export { default as ScatterChart, renderScatterChart } from './ScatterChart';
