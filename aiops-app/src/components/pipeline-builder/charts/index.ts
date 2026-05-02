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

// EDA (PR-C).
export { default as BoxPlot, renderBoxPlot } from './BoxPlot';
export { default as Splom, renderSplom } from './Splom';
export { default as Histogram, renderHistogram } from './Histogram';

// SPC (PR-D).
export { default as XbarR, computeXbarR } from './XbarR';
export { default as IMR, computeIMR } from './IMR';
export { default as EwmaCusum, renderEwmaCusum } from './EwmaCusum';
export {
  wecoCheck,
  wecoCheckAll,
  ALL_WECO_RULES,
  type WecoRuleId,
  type WecoViolation,
} from './lib/weco';
export {
  spcConstants,
  rangeSigma,
  IMR_D2,
  IMR_D4,
  type SpcConstants,
} from './lib/spc';
