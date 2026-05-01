/**
 * Chart engine barrel export.
 *
 * Charts in `charts/<Name>.tsx` import primitives + svg helpers + the
 * useSvgChart hook from here so the API surface stays one path.
 */

export {
  scale,
  ticks,
  mean,
  std,
  quantile,
  quartiles,
  pearson,
  normPdf,
  normInv,
  viridis,
  diverging,
  mix,
  DEFECT_COLORS,
  type LinearScale,
  type BoxStats,
} from './primitives';

export { el, clear, size, SVG_NS, type SVGAttrs } from './svg-utils';

export { tooltip, destroyTooltip } from './tooltip';

export { readTheme, type ChartTheme } from './theme';

export { useSvgChart, type SvgRenderer } from './useSvgChart';
