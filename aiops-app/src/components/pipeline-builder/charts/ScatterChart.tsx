/**
 * ScatterChart — primitive scatter plot.
 *
 * One marker per row at (x, y). Multiple `y` columns produce multiple
 * series; alternatively `series_field` groups rows into colored series
 * (same convention as LineChart).
 *
 * Rules + highlight are supported the same way as LineChart. Use this for
 * correlation / dispersion / general "x vs y" cases.
 */

'use client';

import * as React from 'react';
import {
  clear, el, readTheme, size, tooltip, useSvgChart,
} from './lib';
import type { ChartTheme } from './lib';
import { buildAxis, projectX, type Axis } from './lib/axis';
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

interface Trace {
  name: string;
  color: string;
  points: Array<[number, number, Record<string, unknown>]>;
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  const yKeys = Array.isArray(spec.y) ? spec.y : [];
  const seriesField = typeof spec.series_field === 'string' ? spec.series_field : null;

  if (data.length === 0 || yKeys.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const xValues = data.map((r) => r[spec.x]);
  const x = buildAxis(xValues, { rangeStart: innerLeft, rangeEnd: innerRight, tickCount: 6, pad: 0.04 });

  // Build traces — series_field grouping (only when single y) or one trace per y key.
  const traces: Trace[] = [];
  if (seriesField && yKeys.length === 1) {
    const yk = yKeys[0];
    const groups = new Map<string, Record<string, unknown>[]>();
    for (const r of data) {
      const key = String(r[seriesField] ?? 'default');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(r);
    }
    let idx = 0;
    groups.forEach((rows, name) => {
      const color = SERIES_COLORS[idx % SERIES_COLORS.length];
      traces.push({
        name,
        color,
        points: rows.map((r) => {
          const px = projectX(x, r[spec.x]);
          return [px ?? NaN, Number(r[yk]), r];
        }),
      });
      idx += 1;
    });
  } else {
    yKeys.forEach((yk, idx) => {
      const color = SERIES_COLORS[idx % SERIES_COLORS.length];
      traces.push({
        name: yk,
        color,
        points: data.map((r) => {
          const px = projectX(x, r[spec.x]);
          return [px ?? NaN, Number(r[yk]), r];
        }),
      });
    });
  }

  // Y domain
  const yVals = traces.flatMap((t) => t.points.map((p) => p[1])).filter((v) => Number.isFinite(v));
  for (const rule of spec.rules ?? []) {
    if (Number.isFinite(rule.value)) yVals.push(rule.value);
  }
  const yMin = yVals.length ? Math.min(...yVals) : 0;
  const yMax = yVals.length ? Math.max(...yVals) : 1;
  const yPad = (yMax - yMin) * 0.06 || 0.5;
  const y = scale(yMin - yPad, yMax + yPad, innerBottom, innerTop);
  const yTicks = ticks(yMin - yPad, yMax + yPad, 6);
  const yFmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3));

  drawAxes(svg, T, x, y, yTicks, yFmt, {
    x0: innerLeft, y0: innerTop, x1: innerRight, y1: innerBottom,
  });

  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

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

  // Markers
  for (const tr of traces) {
    for (const [px, py, row] of tr.points) {
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      const yy = y(py);
      const dot = el('circle', {
        cx: px,
        cy: yy,
        r: T.pointR + 0.5,
        fill: tr.color,
        'fill-opacity': '0.75',
        stroke: tr.color,
        'stroke-width': 1,
      }, svg);
      (dot as SVGElement).style.cursor = 'pointer';
      const xLabel = String(row[spec.x] ?? '');
      const tt = tooltip();
      dot.addEventListener('mouseenter', (e) => {
        const me = e as MouseEvent;
        tt.show(
          `<div><b>${tr.name}</b></div><div style="color:#75736d">${spec.x}: ${xLabel}</div><div>value: ${py.toFixed(3)}</div>`,
          me.clientX,
          me.clientY,
        );
      });
      dot.addEventListener('mouseleave', () => tt.hide());
    }
  }

  // Highlight overlay
  if (spec.highlight && yKeys.length > 0) {
    const { field, eq } = spec.highlight;
    const yk = yKeys[0];
    const matched = data.filter((r) => r[field] === eq);
    for (const r of matched) {
      const px = projectX(x, r[spec.x]);
      const py = Number(r[yk]);
      if (px == null || !Number.isFinite(py)) continue;
      el('circle', {
        cx: px,
        cy: y(py),
        r: T.pointR + 5,
        fill: 'none',
        stroke: T.alert,
        'stroke-width': 2,
      }, svg);
    }
  }

  // Legend
  if (traces.length > 1 || seriesField !== null) {
    let lx = innerLeft;
    const ly = innerBottom + 32;
    for (const tr of traces) {
      el('circle', { cx: lx + 5, cy: ly - 3, r: 4, fill: tr.color }, svg);
      el('text', { x: lx + 14, y: ly + 1, class: 'axis-label', text: tr.name }, svg);
      lx += Math.max(50, tr.name.length * 6 + 24);
      if (lx > innerRight - 60) break;
    }
  }
}

export default function ScatterChart({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 280 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Scatter chart'} />
    </div>
  );
}

export { render as renderScatterChart };
