/**
 * Pareto — descending bars + cumulative percent line + 80% reference.
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.category_column / spec.x   : the category column (defect type, tool, …)
 *   spec.value_column / spec.y[0]   : the count / value column
 *   spec.cumulative_threshold?      : reference line %, default 80
 */

'use client';

import * as React from 'react';
import {
  clear, el, readTheme, size, tooltip, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 18, r: 56, b: 70, l: 56 };

interface Item {
  code: string;
  count: number;
}

function readItems(spec: ChartSpec): Item[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length === 0) return [];
  const catCol = (spec.category_column as string | undefined) ?? spec.x;
  const valCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!catCol || !valCol) return [];

  // Aggregate (in case data has multiple rows per category).
  const map = new Map<string, number>();
  for (const r of data) {
    const k = String(r[catCol] ?? '');
    const v = Number(r[valCol]);
    if (!Number.isFinite(v)) continue;
    map.set(k, (map.get(k) ?? 0) + v);
  }
  return Array.from(map.entries()).map(([code, count]) => ({ code, count }));
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const items = readItems(spec).sort((a, b) => b.count - a.count);
  if (items.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const threshold = typeof spec.cumulative_threshold === 'number'
    ? Math.max(0, Math.min(100, spec.cumulative_threshold as number))
    : 80;

  const total = items.reduce((s, d) => s + d.count, 0);
  let cum = 0;
  const cumPct = items.map((d) => {
    cum += d.count;
    return (cum / total) * 100;
  });

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const yMax = Math.max(...items.map((d) => d.count)) * 1.05;
  const bw = (innerRight - innerLeft) / items.length;
  const yL = scale(0, yMax, innerBottom, innerTop);
  const yR = scale(0, 100, innerBottom, innerTop);

  // Y-left grid + labels (counts)
  ticks(0, yMax, 5).forEach((v) => {
    el('line', { x1: innerLeft, x2: innerRight, y1: yL(v), y2: yL(v), class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 5, y: yL(v) + 3, 'text-anchor': 'end', class: 'axis-label', text: `${Math.round(v)}` }, svg);
  });
  // Y-right ticks (percent)
  [0, 25, 50, 75, 100].forEach((v) => {
    el('text', { x: innerRight + 5, y: yR(v) + 3, 'text-anchor': 'start', class: 'axis-label', text: `${v}%` }, svg);
  });

  // Threshold reference line
  el('line', {
    x1: innerLeft, x2: innerRight,
    y1: yR(threshold), y2: yR(threshold),
    stroke: '#d97706', 'stroke-width': 1, 'stroke-dasharray': '2 2',
  }, svg);
  el('text', {
    x: innerLeft + 4, y: yR(threshold) - 3,
    'font-family': 'var(--chart-font-mono)', 'font-size': 9.5,
    fill: T.alert, text: `${threshold}%`,
  }, svg);

  // Title
  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Bars + x labels
  const tt = tooltip();
  items.forEach((d, i) => {
    const x0 = innerLeft + i * bw;
    const fill = cumPct[i] <= threshold ? T.data : T.secondary;
    const bar = el('rect', {
      x: x0 + 2,
      y: yL(d.count),
      width: Math.max(1, bw - 4),
      height: Math.max(1, yL(0) - yL(d.count)),
      fill,
    }, svg);
    (bar as SVGElement).style.cursor = 'pointer';
    bar.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      tt.show(
        `<b>${d.code}</b><br/>count: ${d.count}<br/>cumulative: ${cumPct[i].toFixed(1)}%`,
        me.clientX, me.clientY,
      );
    });
    bar.addEventListener('mouseleave', () => tt.hide());
    // Rotated x label
    el('text', {
      x: x0 + bw / 2,
      y: innerBottom + 12,
      'text-anchor': 'end',
      class: 'axis-label',
      transform: `rotate(-30 ${x0 + bw / 2} ${innerBottom + 12})`,
      text: d.code,
    }, svg);
    // Count label on top of bar
    el('text', {
      x: x0 + bw / 2,
      y: yL(d.count) - 4,
      'text-anchor': 'middle',
      'font-family': 'var(--chart-font-mono)', 'font-size': 9.5,
      fill: T.ink,
      text: `${d.count}`,
    }, svg);
  });

  // Cumulative line
  const linePts = cumPct.map((v, i) => [innerLeft + (i + 0.5) * bw, yR(v)] as [number, number]);
  const path = linePts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join('');
  el('path', { d: path, fill: 'none', stroke: T.alert, 'stroke-width': T.stroke + 0.4 }, svg);
  linePts.forEach((p, i) => {
    const c = el('circle', {
      cx: p[0], cy: p[1], r: 3.2,
      fill: T.alert, stroke: T.bg, 'stroke-width': 1.5,
    }, svg);
    (c as SVGElement).style.cursor = 'pointer';
    c.addEventListener('mouseenter', (e) => {
      const me = e as MouseEvent;
      const topN = items.slice(0, i + 1).map((s) => s.code).join(', ');
      tt.show(
        `<b>Top ${i + 1}: ${topN}</b><br/>cumulative: ${cumPct[i].toFixed(1)}%`,
        me.clientX, me.clientY,
      );
    });
    c.addEventListener('mouseleave', () => tt.hide());
  });

  // Axis lines + titles
  el('line', { x1: innerLeft, x2: innerLeft, y1: innerTop, y2: innerBottom, class: 'axis-line' }, svg);
  el('line', { x1: innerRight, x2: innerRight, y1: innerTop, y2: innerBottom, class: 'axis-line' }, svg);
  el('text', {
    x: 14, y: innerTop + (innerBottom - innerTop) / 2,
    'text-anchor': 'middle', class: 'axis-title',
    transform: `rotate(-90 14 ${innerTop + (innerBottom - innerTop) / 2})`,
    text: 'Frequency',
  }, svg);
  el('text', {
    x: W - 14, y: innerTop + (innerBottom - innerTop) / 2,
    'text-anchor': 'middle', class: 'axis-title',
    transform: `rotate(90 ${W - 14} ${innerTop + (innerBottom - innerTop) / 2})`,
    text: 'Cumulative %',
  }, svg);
}

export default function Pareto({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 320 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Pareto chart'} />
    </div>
  );
}

export { render as renderPareto };
