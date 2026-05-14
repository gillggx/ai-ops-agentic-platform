/**
 * LineChart — primitive line/multi-line chart for the new SVG engine.
 *
 * Replaces Plotly's `renderLineBarScatter` for type="line". Supports the full
 * legacy ChartDSL feature set:
 *   - rules:        UCL / LCL / Center / sigma horizontal reference lines
 *   - highlight:    {field, eq} → red rings on matching x-values
 *   - series_field: group rows by this column, one colored trace per group
 *   - y_secondary:  dual-axis series rendered with a dotted style
 *
 * X-axis kind is auto-detected (numeric / ISO time / categorical). Y-axis is
 * always linear.
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, readTheme, size, tooltip, useSvgChart,
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

function drawAxes(svg: SVGSVGElement, T: ChartTheme, x: Axis, yScale: (v: number) => number, yTicks: number[], yFmt: (v: number) => string, area: { x0: number; y0: number; x1: number; y1: number }) {
  const { x0, y0, x1, y1 } = area;
  // Y grid + labels
  yTicks.forEach((v) => {
    const yy = yScale(v);
    el('line', { x1: x0, x2: x1, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: x0 - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: yFmt(v) }, svg);
  });
  // Y axis line
  el('line', { x1: x0, x2: x0, y1: y0, y2: y1, class: 'axis-line' }, svg);
  // X axis line
  el('line', { x1: x0, x2: x1, y1: y1, y2: y1, class: 'axis-line' }, svg);
  // X axis ticks + labels
  if (x.kind === 'numeric' || x.kind === 'time') {
    x.ticks.forEach((v) => {
      const xx = x.scale(v);
      if (xx < x0 - 0.5 || xx > x1 + 0.5) return;
      el('line', { x1: xx, x2: xx, y1: y1, y2: y1 + 4, stroke: T.gridStrong, 'stroke-width': 1 }, svg);
      el('text', { x: xx, y: y1 + 16, 'text-anchor': 'middle', class: 'axis-label', text: x.format(v) }, svg);
    });
  } else {
    x.domain.forEach((label) => {
      const xx = x.positionOf(label);
      el('text', { x: xx, y: y1 + 16, 'text-anchor': 'middle', class: 'axis-label', text: label }, svg);
    });
  }
}

function buildPath(points: Array<[number, number]>): string {
  if (points.length === 0) return '';
  const parts: string[] = [];
  let inSeg = false;
  for (let i = 0; i < points.length; i++) {
    const [x, y] = points[i];
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      inSeg = false;
      continue;
    }
    parts.push(`${inSeg ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`);
    inSeg = true;
  }
  return parts.join(' ');
}

interface Trace {
  name: string;
  color: string;
  points: Array<[number, number, Record<string, unknown>]>; // px,py,row
  axis: 'primary' | 'secondary';
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  const primaryY = Array.isArray(spec.y) ? spec.y : [];
  const secondaryY = Array.isArray(spec.y_secondary) ? spec.y_secondary : [];
  const seriesField = typeof spec.series_field === 'string' ? spec.series_field : null;

  if (data.length === 0 || primaryY.length === 0) {
    el('text', {
      x: W / 2,
      y: H / 2,
      'text-anchor': 'middle',
      class: 'axis-label',
      text: '（無資料）',
    }, svg);
    return;
  }

  const innerLeft = M.l;
  const innerRight = W - M.r - (secondaryY.length > 0 ? 36 : 0);
  const innerTop = M.t;
  const innerBottom = H - M.b;

  // X axis
  const xValues = data.map((r) => r[spec.x]);
  const x = buildAxis(xValues, { rangeStart: innerLeft, rangeEnd: innerRight, tickCount: 6, pad: 0.02 });

  // Build traces
  const traces: Trace[] = [];

  if (seriesField && primaryY.length === 1) {
    // Group by series_field
    const yk = primaryY[0];
    const groups = new Map<string, Record<string, unknown>[]>();
    for (const row of data) {
      const key = String(row[seriesField] ?? 'default');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(row);
    }
    let idx = 0;
    const specColors = (spec as { colors?: string[] }).colors;
    groups.forEach((rows, name) => {
      const color = specColors?.[idx] ?? SERIES_COLORS[idx % SERIES_COLORS.length];
      traces.push({
        name,
        color,
        axis: 'primary',
        points: rows.map((r) => {
          const px = projectX(x, r[spec.x]);
          const py = Number(r[yk]);
          return [px ?? NaN, py, r];
        }),
      });
      idx += 1;
    });
  } else {
    const specColors = (spec as { colors?: string[] }).colors;
    primaryY.forEach((yk, idx) => {
      const color = specColors?.[idx] ?? SERIES_COLORS[idx % SERIES_COLORS.length];
      traces.push({
        name: yk,
        color,
        axis: 'primary',
        points: data.map((r) => {
          const px = projectX(x, r[spec.x]);
          return [px ?? NaN, Number(r[yk]), r];
        }),
      });
    });
  }
  secondaryY.forEach((yk, idx) => {
    const color = SERIES_COLORS[(primaryY.length + idx) % SERIES_COLORS.length];
    traces.push({
      name: yk,
      color,
      axis: 'secondary',
      points: data.map((r) => {
        const px = projectX(x, r[spec.x]);
        return [px ?? NaN, Number(r[yk]), r];
      }),
    });
  });

  // Y domains (per axis)
  const primaryYs = traces.filter((t) => t.axis === 'primary').flatMap((t) => t.points.map((p) => p[1])).filter((v) => Number.isFinite(v));
  const secondaryYs = traces.filter((t) => t.axis === 'secondary').flatMap((t) => t.points.map((p) => p[1])).filter((v) => Number.isFinite(v));
  // Include rule values in domain (so rules don't get clipped)
  if (spec.rules) {
    for (const rule of spec.rules) {
      if (Number.isFinite(rule.value)) primaryYs.push(rule.value);
    }
  }
  const yMin = primaryYs.length ? Math.min(...primaryYs) : 0;
  const yMax = primaryYs.length ? Math.max(...primaryYs) : 1;
  const yPad = (yMax - yMin) * 0.06 || 0.5;
  const y = scale(yMin - yPad, yMax + yPad, innerBottom, innerTop);
  const yTicks = ticks(yMin - yPad, yMax + yPad, 6);
  const yFmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(3));

  let y2: ((v: number) => number) | null = null;
  let y2Ticks: number[] = [];
  if (secondaryYs.length > 0) {
    const y2Min = Math.min(...secondaryYs);
    const y2Max = Math.max(...secondaryYs);
    const y2Pad = (y2Max - y2Min) * 0.06 || 0.5;
    y2 = scale(y2Min - y2Pad, y2Max + y2Pad, innerBottom, innerTop);
    y2Ticks = ticks(y2Min - y2Pad, y2Max + y2Pad, 6);
  }

  // Background grid + axes
  drawAxes(svg, T, x, y, yTicks, yFmt, {
    x0: innerLeft, y0: innerTop, x1: innerRight, y1: innerBottom,
  });

  // Secondary axis (right)
  if (y2) {
    el('line', { x1: innerRight, x2: innerRight, y1: innerTop, y2: innerBottom, class: 'axis-line' }, svg);
    y2Ticks.forEach((v) => {
      const yy = y2!(v);
      el('text', { x: innerRight + 6, y: yy + 3, 'text-anchor': 'start', class: 'axis-label', text: yFmt(v) }, svg);
    });
  }

  // Title
  if (spec.title) {
    el('text', {
      x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title,
    }, svg);
  }

  // Rules (horizontal lines)
  for (const rule of spec.rules ?? []) {
    if (!Number.isFinite(rule.value)) continue;
    const yy = y(rule.value);
    if (yy < innerTop - 1 || yy > innerBottom + 1) continue;
    const color = rule.color ?? RULE_COLOR[rule.style ?? 'center'];
    const isSigma = rule.style === 'sigma';
    const isCenter = rule.style === 'center';
    el('line', {
      x1: innerLeft,
      x2: innerRight,
      y1: yy,
      y2: yy,
      stroke: color,
      'stroke-width': isSigma ? 1 : 1.5,
      'stroke-dasharray': isCenter ? '2 4' : isSigma ? '4 2 1 2' : '6 4',
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

  // Series traces
  // Project secondary using y2
  for (const tr of traces) {
    const yProj = tr.axis === 'secondary' && y2 ? y2 : y;
    const projectedPts = tr.points.map(([px, py, row]) => [px, Number.isFinite(py) ? yProj(py) : NaN, row] as [number, number, Record<string, unknown>]);
    const path = buildPath(projectedPts.map(([px, py]) => [px, py]));
    el('path', {
      d: path,
      fill: 'none',
      stroke: tr.color,
      'stroke-width': T.stroke,
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'stroke-dasharray': tr.axis === 'secondary' ? '4 3' : '',
    }, svg);
    // Points
    for (const [px, py, row] of projectedPts) {
      if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
      const dot = el('circle', {
        cx: px,
        cy: py,
        r: T.pointR,
        fill: tr.color,
        stroke: T.bg,
        'stroke-width': 0.5,
      }, svg);
      (dot as SVGElement).style.cursor = 'pointer';
      const xLabel = String(row[spec.x] ?? '');
      const tt = tooltip();
      dot.addEventListener('mouseenter', (e) => {
        const me = e as MouseEvent;
        tt.show(
          `<div><b>${tr.name}</b></div><div style="color:#75736d">${spec.x}: ${xLabel}</div><div>value: ${(row[tr.name] ?? py).toString()}</div>`,
          me.clientX,
          me.clientY,
        );
      });
      dot.addEventListener('mouseleave', () => tt.hide());
    }
  }

  // Highlight overlay (red rings on matching rows)
  if (spec.highlight && primaryY.length > 0) {
    const { field, eq } = spec.highlight;
    const yk = primaryY[0];
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

  // Legend (when multi-series or seriesField)
  const showLegend = traces.length > 1 || seriesField !== null;
  if (showLegend) {
    let lx = innerLeft;
    const ly = innerBottom + 32;
    for (const tr of traces) {
      const labelW = Math.max(40, tr.name.length * 6 + 16);
      el('line', {
        x1: lx, x2: lx + 12, y1: ly, y2: ly,
        stroke: tr.color, 'stroke-width': T.stroke,
        'stroke-dasharray': tr.axis === 'secondary' ? '4 3' : '',
      }, svg);
      el('text', {
        x: lx + 16, y: ly + 3, class: 'axis-label', text: tr.name,
      }, svg);
      lx += labelW + 8;
      if (lx > innerRight - 60) break; // truncate if no room
    }
  }
}

export default function LineChart({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 280 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Line chart'} />
    </div>
  );
}

// Re-export for engineers wiring custom layouts.
export { render as renderLineChart };
