/**
 * specStyle — agent-adjustable chart style helpers (chart-style wave 1).
 *
 * Chart blocks pass `style` / `tooltip_fields` / `weco_annotate` through
 * chart_spec (see sidecar blocks/_chart_style.py — the two files must agree
 * on key names). These helpers keep the per-chart components thin.
 */

import { el } from './svg-utils';

export interface SpecStyle {
  spc_zones?: boolean;
  line_style?: 'solid' | 'dash' | 'step';
  show_markers?: boolean;
  marker_size?: 'small' | 'medium' | 'large';
  show_values?: boolean;
  x_label?: string;
  y_label?: string;
  legend?: 'none' | 'top' | 'right';
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function specStyle(spec: any): SpecStyle {
  return (spec && typeof spec.style === 'object' && spec.style) || {};
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function tooltipFields(spec: any): string[] {
  return Array.isArray(spec?.tooltip_fields)
    ? spec.tooltip_fields.filter((f: unknown) => typeof f === 'string').slice(0, 5)
    : [];
}

/** Marker radius by style keyword (falls back to the theme's pointR). */
export function markerRadius(style: SpecStyle, themeR: number): number {
  if (style.show_markers === false) return 0;
  switch (style.marker_size) {
    case 'small': return Math.max(1.5, themeR - 1);
    case 'large': return themeR + 1.5;
    default: return themeR;
  }
}

/** σ Zone A/B/C shading between control limits. Draw BEFORE grid/axes so the
 *  bands sit underneath everything. Zone colors follow the visual spec doc
 *  (docs/CHART_STYLE_SPEC_VISUAL.html): C greenish, B sand, A reddish. */
export function drawSpcZones(
  svg: SVGSVGElement,
  area: { x0: number; x1: number },
  yScale: (v: number) => number,
  limits: { ucl: number; lcl: number; center?: number | null },
): void {
  const center = limits.center ?? (limits.ucl + limits.lcl) / 2;
  const sigma = (limits.ucl - center) / 3;
  if (!Number.isFinite(sigma) || sigma <= 0) return;
  const bands: Array<[number, number, string]> = [
    [2, 3, '#f4dedb'], // Zone A
    [1, 2, '#efe9df'], // Zone B
    [0, 1, '#e9efe6'], // Zone C
  ];
  const w = area.x1 - area.x0;
  for (const [s0, s1, fill] of bands) {
    for (const sign of [1, -1]) {
      const yTop = yScale(center + sign * s1 * sigma);
      const yBot = yScale(center + sign * s0 * sigma);
      const yy = Math.min(yTop, yBot);
      const hh = Math.abs(yBot - yTop);
      if (hh <= 0) continue;
      el('rect', { x: area.x0, y: yy, width: w, height: hh, fill, opacity: 0.7 }, svg);
    }
  }
  // Zone letters at the right edge (upper half only — convention).
  const letters: Array<[number, string]> = [[2.5, 'A'], [1.5, 'B'], [0.5, 'C']];
  for (const [mult, letter] of letters) {
    el('text', {
      x: area.x1 - 4, y: yScale(center + mult * sigma) + 3,
      'text-anchor': 'end', 'font-size': 8, fill: '#a89a90', text: letter,
    }, svg);
  }
}

/** Extra tooltip lines from tooltip_fields — appended after the chart's own
 *  base lines. Values are HTML-escaped. */
export function tooltipFieldLines(
  row: Record<string, unknown>, fields: string[],
): string {
  if (!fields.length) return '';
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  return fields
    .map((f) => `<div style="color:#9fb0a3">${esc(f)}: ${esc(String(row[f] ?? '—'))}</div>`)
    .join('');
}

/** Axis titles from style.x_label / y_label. Call after axes are drawn. */
export function drawAxisLabels(
  svg: SVGSVGElement,
  style: SpecStyle,
  area: { x0: number; y0: number; x1: number; y1: number },
): void {
  if (style.y_label) {
    const cy = (area.y0 + area.y1) / 2;
    const t = el('text', {
      x: 12, y: cy, 'font-size': 10, fill: '#5d675e', 'font-weight': '700',
      'text-anchor': 'middle', text: style.y_label,
    }, svg);
    t.setAttribute('transform', `rotate(-90 12 ${cy})`);
  }
  if (style.x_label) {
    el('text', {
      x: (area.x0 + area.x1) / 2, y: area.y1 + 30,
      'text-anchor': 'middle', 'font-size': 10, fill: '#5d675e',
      'font-weight': '700', text: style.x_label,
    }, svg);
  }
}

/** WECO R1 annotation for simple limit-breach points (line_chart path —
 *  proper multi-rule engines live in XbarR/IMR which own their WECO calc). */
export function wecoBreachText(v: number, ucl: number, lcl: number): string | null {
  if (v > ucl) return `違反 R1：單點超出 UCL（${ucl.toFixed(2)}）`;
  if (v < lcl) return `違反 R1：單點低於 LCL（${lcl.toFixed(2)}）`;
  return null;
}
