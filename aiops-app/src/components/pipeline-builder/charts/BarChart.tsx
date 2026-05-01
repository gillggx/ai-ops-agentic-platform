/**
 * BarChart — primitive bar / grouped-bar chart.
 *
 * For multiple `y` columns, bars are drawn side-by-side per category. Most
 * pipelines use a single y; multi-y is for compare-side-by-side cases.
 *
 * Rules (horizontal target / threshold lines) and highlight (mark one
 * category red) are supported. `series_field` is *not* honoured for bars —
 * use multiple `y` columns instead.
 */

'use client';

import * as React from 'react';
import {
  clear, el, readTheme, size, tooltip, useSvgChart,
} from './lib';
import type { ChartTheme } from './lib';
import { buildAxis, type Axis } from './lib/axis';
import { scale, ticks } from './lib/primitives';
import {
  RULE_COLOR,
  SERIES_COLORS,
  type ChartSpec,
} from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 16, r: 16, b: 48, l: 56 };

function drawAxes(
  svg: SVGSVGElement,
  T: ChartTheme,
  x: Axis,
  yScale: (v: number) => number,
  yTicks: number[],
  yFmt: (v: number) => string,
  area: { x0: number; y0: number; x1: number; y1: number },
) {
  const { x0, y0, x1, y1 } = area;
  yTicks.forEach((v) => {
    const yy = yScale(v);
    el('line', { x1: x0, x2: x1, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: x0 - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: yFmt(v) }, svg);
  });
  el('line', { x1: x0, x2: x0, y1: y0, y2: y1, class: 'axis-line' }, svg);
  el('line', { x1: x0, x2: x1, y1: y1, y2: y1, class: 'axis-line' }, svg);
  if (x.kind === 'category') {
    x.domain.forEach((label) => {
      const xx = x.positionOf(label);
      el('text', { x: xx, y: y1 + 16, 'text-anchor': 'middle', class: 'axis-label', text: label }, svg);
    });
  } else {
    x.ticks.forEach((v) => {
      const xx = x.scale(v);
      if (xx < x0 - 0.5 || xx > x1 + 0.5) return;
      el('line', { x1: xx, x2: xx, y1: y1, y2: y1 + 4, stroke: T.gridStrong, 'stroke-width': 1 }, svg);
      el('text', { x: xx, y: y1 + 16, 'text-anchor': 'middle', class: 'axis-label', text: x.format(v) }, svg);
    });
  }
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  const yKeys = Array.isArray(spec.y) ? spec.y : [];
  if (data.length === 0 || yKeys.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  // Force categorical x for bars (data point per row)
  const xValues = data.map((r) => r[spec.x]);
  const x = buildAxis(xValues, {
    rangeStart: innerLeft,
    rangeEnd: innerRight,
    kind: 'category',
  }) as Extract<Axis, { kind: 'category' }>;

  // Y domain
  const yVals: number[] = [];
  for (const r of data) for (const k of yKeys) {
    const v = Number(r[k]);
    if (Number.isFinite(v)) yVals.push(v);
  }
  for (const rule of spec.rules ?? []) {
    if (Number.isFinite(rule.value)) yVals.push(rule.value);
  }
  // Bars usually start from 0 unless data goes negative
  const yMin = Math.min(0, ...yVals);
  const yMax = Math.max(0, ...yVals);
  const yPad = (yMax - yMin) * 0.06 || 0.5;
  const y = scale(yMin, yMax + yPad, innerBottom, innerTop);
  const yTicks = ticks(yMin, yMax + yPad, 6);
  const yFmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3));
  const baseline = y(0);

  drawAxes(svg, T, x, y, yTicks, yFmt, {
    x0: innerLeft, y0: innerTop, x1: innerRight, y1: innerBottom,
  });

  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Bar geometry — within each category band, bars sit side by side.
  const groupCount = yKeys.length;
  const bandPad = 0.18;
  const usableWidth = x.bandWidth * (1 - bandPad);
  const barWidth = usableWidth / groupCount;

  data.forEach((row, rowIdx) => {
    const cx = x.positionOf(String(row[spec.x] ?? rowIdx));
    yKeys.forEach((yk, gi) => {
      const v = Number(row[yk]);
      if (!Number.isFinite(v)) return;
      const color = SERIES_COLORS[gi % SERIES_COLORS.length];
      const yy = y(v);
      const x0 = cx - usableWidth / 2 + gi * barWidth;
      const top = Math.min(baseline, yy);
      const h = Math.abs(baseline - yy);
      const bar = el('rect', {
        x: x0 + 1,
        y: top,
        width: Math.max(1, barWidth - 2),
        height: Math.max(1, h),
        fill: color,
        'fill-opacity': '0.85',
        stroke: color,
        'stroke-width': 1,
      }, svg);
      (bar as SVGElement).style.cursor = 'pointer';
      const tt = tooltip();
      bar.addEventListener('mouseenter', (e) => {
        const me = e as MouseEvent;
        tt.show(
          `<div><b>${yk}</b></div><div style="color:#75736d">${spec.x}: ${row[spec.x] ?? ''}</div><div>value: ${v.toFixed(3)}</div>`,
          me.clientX,
          me.clientY,
        );
      });
      bar.addEventListener('mouseleave', () => tt.hide());
    });
  });

  // Rules
  for (const rule of spec.rules ?? []) {
    if (!Number.isFinite(rule.value)) continue;
    const yy = y(rule.value);
    if (yy < innerTop - 1 || yy > innerBottom + 1) continue;
    const color = rule.color ?? RULE_COLOR[rule.style ?? 'center'];
    el('line', {
      x1: innerLeft,
      x2: innerRight,
      y1: yy,
      y2: yy,
      stroke: color,
      'stroke-width': 1.5,
      'stroke-dasharray': rule.style === 'center' ? '2 4' : '6 4',
    }, svg);
    el('text', {
      x: innerRight - 4,
      y: yy - 3,
      'text-anchor': 'end',
      class: 'axis-label',
      fill: color,
      text: `${rule.label} ${rule.value.toFixed(2)}`,
    }, svg);
  }

  // Highlight: red border on bars where row[field] === eq
  if (spec.highlight) {
    const { field, eq } = spec.highlight;
    data.forEach((row, rowIdx) => {
      if (row[field] !== eq) return;
      const cx = x.positionOf(String(row[spec.x] ?? rowIdx));
      const x0 = cx - usableWidth / 2;
      el('rect', {
        x: x0,
        y: innerTop,
        width: usableWidth,
        height: innerBottom - innerTop,
        fill: 'none',
        stroke: T.alert,
        'stroke-width': 2,
        'stroke-dasharray': '3 3',
      }, svg);
    });
  }

  // Legend
  if (yKeys.length > 1) {
    let lx = innerLeft;
    const ly = innerBottom + 32;
    yKeys.forEach((yk, gi) => {
      const color = SERIES_COLORS[gi % SERIES_COLORS.length];
      el('rect', { x: lx, y: ly - 8, width: 10, height: 10, fill: color }, svg);
      el('text', { x: lx + 14, y: ly + 1, class: 'axis-label', text: yk }, svg);
      lx += Math.max(50, yk.length * 6 + 24);
      if (lx > innerRight - 60) return;
    });
  }
}

export default function BarChart({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 280 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Bar chart'} />
    </div>
  );
}

export { render as renderBarChart };
