/**
 * ChartDSL type — the JSON shape `block_chart` (legacy) and the new
 * dedicated chart blocks emit. The frontend dispatcher routes by `type`
 * to the corresponding chart component in `charts/<Name>.tsx`.
 *
 * This mirrors the legacy `ChartDSL` in `operations/SkillOutputRenderer.tsx`;
 * once Stage 6 cleanup lands and the legacy renderer is removed, this file
 * becomes the single source of truth for the engine.
 */

export type ChartType =
  // Primitives (PR-B)
  | 'line'
  | 'bar'
  | 'scatter'
  // EDA (PR-C)
  | 'box_plot'
  | 'splom'
  | 'histogram'
  | 'distribution' // legacy alias of histogram
  // SPC (PR-D)
  | 'xbar_r'
  | 'imr'
  | 'ewma_cusum'
  // Diagnostic (PR-E)
  | 'pareto'
  | 'variability_gauge'
  | 'parallel_coords'
  | 'probability_plot'
  | 'heatmap_dendro'
  | 'heatmap' // legacy alias of heatmap_dendro
  // Wafer (PR-F)
  | 'wafer_heatmap'
  | 'defect_stack'
  | 'spatial_pareto'
  | 'trend_wafer_maps'
  // Legacy
  | 'boxplot'; // legacy alias of box_plot

export interface ChartRule {
  value: number;
  label: string;
  style?: 'danger' | 'warning' | 'center' | 'sigma';
  color?: string;
}

export interface ChartHighlight {
  field: string;
  eq: unknown;
}

/** Common chart spec for line / bar / scatter primitives. */
export interface ChartSpec {
  type: ChartType;
  title?: string;
  data: Array<Record<string, unknown>>;
  /** X-axis field name. */
  x: string;
  /** Y-axis field names (one per primary-axis series). */
  y: string[];
  /** Secondary-axis series (dual Y). */
  y_secondary?: string[];
  /** Horizontal reference lines (UCL / LCL / Center / sigma bands). */
  rules?: ChartRule[];
  /** Mark rows where `row[field] === eq` with red rings. */
  highlight?: ChartHighlight | null;
  /** When set: group rows by this field, one colored trace per group. */
  series_field?: string;
  // Type-specific extras (kept loose for primitives — chart components own their schema)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [extra: string]: any;
}

/** Default 7-color series palette (auto-cycle for series_field grouping). */
export const SERIES_COLORS: readonly string[] = [
  '#48bb78', // green
  '#ed8936', // orange
  '#4299e1', // blue
  '#9f7aea', // purple
  '#38b2ac', // teal
  '#f56565', // red
  '#ecc94b', // yellow
];

export const RULE_COLOR: Record<NonNullable<ChartRule['style']>, string> = {
  danger: '#e53e3e',
  warning: '#dd6b20',
  center: '#4a5568',
  sigma: '#a0aec0',
};
