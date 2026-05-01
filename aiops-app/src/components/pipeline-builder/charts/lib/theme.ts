/**
 * Theme reader — pulls chart-styling tokens from CSS custom properties so a
 * single CSS variable change re-themes every chart on the page.
 *
 * The variables live in `aiops-app/src/styles/chart-tokens.css` (loaded once
 * by BuilderLayout). Each chart calls `readTheme(svg)` at the top of its
 * render — the values are scoped to the SVG element's computed style, so
 * Builder pages can locally override (e.g. wrap one chart in a div with
 * different `--chart-data` for highlight) without affecting the rest.
 */

export interface ChartTheme {
  /** Primary data series color (line / bar / scatter). */
  data: string;
  /** Secondary / dual-axis color. */
  secondary: string;
  /** Alarm / OOC / outlier color. */
  alert: string;
  /** Light grid line color. */
  grid: string;
  /** Strong grid color (axis line). */
  gridStrong: string;
  /** Surface background. */
  bg: string;
  /** Default ink color (axis labels, titles). */
  ink: string;
  /** Stroke width for primary series. */
  stroke: number;
  /** Fill opacity for filled shapes (boxplot, area, density). */
  fillOp: number;
  /** Default scatter point radius. */
  pointR: number;
}

const DEFAULTS: ChartTheme = {
  data: '#2563EB',
  secondary: '#64748B',
  alert: '#DC2626',
  grid: '#e8e7e3',
  gridStrong: '#c8c6c0',
  bg: '#ffffff',
  ink: '#1a1a17',
  stroke: 1.4,
  fillOp: 0.18,
  pointR: 2.6,
};

function pick(cs: CSSStyleDeclaration, name: string, fallback: string): string {
  const v = cs.getPropertyValue(name).trim();
  return v || fallback;
}

function pickNum(cs: CSSStyleDeclaration, name: string, fallback: number): number {
  const raw = cs.getPropertyValue(name).trim();
  const n = parseFloat(raw);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * Read the chart theme from an SVG element's computed CSS variables. Falls
 * back silently when the element is detached or the stylesheet hasn't loaded.
 */
export function readTheme(svg: SVGElement | null): ChartTheme {
  if (!svg) return { ...DEFAULTS };
  const cs = getComputedStyle(svg);
  return {
    data: pick(cs, '--chart-data', DEFAULTS.data),
    secondary: pick(cs, '--chart-secondary', DEFAULTS.secondary),
    alert: pick(cs, '--chart-alert', DEFAULTS.alert),
    grid: pick(cs, '--chart-grid', DEFAULTS.grid),
    gridStrong: pick(cs, '--chart-grid-strong', DEFAULTS.gridStrong),
    bg: pick(cs, '--chart-bg', DEFAULTS.bg),
    ink: pick(cs, '--chart-ink', DEFAULTS.ink),
    stroke: pickNum(cs, '--chart-stroke', DEFAULTS.stroke),
    fillOp: pickNum(cs, '--chart-fill-op', DEFAULTS.fillOp),
    pointR: pickNum(cs, '--chart-point-r', DEFAULTS.pointR),
  };
}
