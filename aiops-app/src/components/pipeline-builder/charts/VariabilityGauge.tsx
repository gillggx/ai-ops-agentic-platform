/**
 * VariabilityGauge — multi-level decomposition of a metric.
 *
 * Plots every measurement as a jittered point grouped under a hierarchical
 * X axis (e.g. lot > wafer > tool). A bold horizontal mean line per innermost
 * group + a dashed step line connecting group means makes shifts between
 * lots / wafers / tools immediately visible.
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.value_column / spec.y[0]
 *   spec.levels: string[]   — outer-most → inner-most grouping columns
 *                              e.g. ['lot', 'wafer', 'tool']
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, readTheme, size, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

interface Col {
  /** Innermost-group label values, ordered outer→inner. */
  levelValues: string[];
  values: number[];
  mu: number;
}

const M = { t: 18, r: 14, b: 70, l: 56 };

function buildCols(spec: ChartSpec, levels: string[], valueCol: string): Col[] {
  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length === 0 || levels.length === 0) return [];

  // Group rows by full level path; preserve first-seen order for chronological feel.
  const map = new Map<string, { lvl: string[]; values: number[] }>();
  for (const row of data) {
    const lvl = levels.map((k) => String(row[k] ?? ''));
    const key = lvl.join('|');
    let bucket = map.get(key);
    if (!bucket) {
      bucket = { lvl, values: [] };
      map.set(key, bucket);
    }
    const v = Number(row[valueCol]);
    if (Number.isFinite(v)) bucket.values.push(v);
  }
  return Array.from(map.values())
    .filter((b) => b.values.length > 0)
    .map((b) => ({ levelValues: b.lvl, values: b.values, mu: mean(b.values) }));
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  const levels = Array.isArray(spec.levels) ? (spec.levels as string[]) : [];
  if (!valueCol || levels.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: 'spec.levels / value_column 缺' }, svg);
    return;
  }

  const cols = buildCols(spec, levels, valueCol);
  if (cols.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  // Reserve more space for hierarchical X labels (one row per level).
  const xLabelRows = levels.length;
  const innerBottom = H - M.b - (xLabelRows - 1) * 18;

  const allV: number[] = [];
  for (const c of cols) for (const v of c.values) allV.push(v);
  const yMin = Math.min(...allV);
  const yMax = Math.max(...allV);
  const pad = (yMax - yMin) * 0.1 || 0.5;
  const y = scale(yMin - pad, yMax + pad, innerBottom, innerTop);

  const bw = (innerRight - innerLeft) / cols.length;
  const xC = (i: number) => innerLeft + (i + 0.5) * bw;

  // Y grid + labels
  ticks(yMin - pad, yMax + pad, 5).forEach((v) => {
    el('line', { x1: innerLeft, x2: innerRight, y1: y(v), y2: y(v), class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 5, y: y(v) + 3, 'text-anchor': 'end', class: 'axis-label', text: v.toFixed(1) }, svg);
  });

  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Jittered points + per-column mean line
  cols.forEach((c, i) => {
    c.values.forEach((v, k) => {
      const jx = xC(i) + (k / Math.max(1, c.values.length) - 0.5) * bw * 0.5;
      el('circle', {
        cx: jx, cy: y(v), r: 1.8,
        fill: T.data, opacity: '0.7',
      }, svg);
    });
    el('line', {
      x1: xC(i) - bw * 0.3,
      x2: xC(i) + bw * 0.3,
      y1: y(c.mu), y2: y(c.mu),
      stroke: T.ink, 'stroke-width': 2,
    }, svg);
  });

  // Step line connecting consecutive means
  const step: string[] = [];
  cols.forEach((c, i) => {
    const x0 = xC(i) - bw * 0.3;
    const x1 = xC(i) + bw * 0.3;
    step.push(`${i === 0 ? 'M' : 'L'}${x0.toFixed(2)},${y(c.mu).toFixed(2)}`);
    step.push(`L${x1.toFixed(2)},${y(c.mu).toFixed(2)}`);
    if (i < cols.length - 1) {
      const nx = xC(i + 1) - bw * 0.3;
      step.push(`L${nx.toFixed(2)},${y(cols[i + 1].mu).toFixed(2)}`);
    }
  });
  el('path', {
    d: step.join(' '),
    fill: 'none',
    stroke: T.alert,
    'stroke-width': T.stroke,
    'stroke-dasharray': '3 2',
    opacity: '0.7',
  }, svg);

  // Hierarchical X axis. Innermost level (last in levels[]) is per-column;
  // outer levels become brackets.
  const innermost = levels.length - 1;
  cols.forEach((c, i) => {
    el('text', {
      x: xC(i),
      y: innerBottom + 12,
      'text-anchor': 'middle',
      class: 'axis-label',
      text: c.levelValues[innermost] ?? '',
    }, svg);
  });

  // Outer brackets (levels 0..innermost-1, drawn from innermost outward)
  function drawBracket(start: number, end: number, label: string, yOff: number) {
    const x0 = xC(start) - bw * 0.4;
    const x1 = xC(end) + bw * 0.4;
    const yy = innerBottom + yOff;
    el('line', { x1: x0, x2: x1, y1: yy, y2: yy, stroke: T.ink, 'stroke-width': 1 }, svg);
    el('line', { x1: x0, x2: x0, y1: yy, y2: yy + 3, stroke: T.ink }, svg);
    el('line', { x1: x1, x2: x1, y1: yy, y2: yy + 3, stroke: T.ink }, svg);
    el('text', {
      x: (x0 + x1) / 2,
      y: yy + 13,
      'text-anchor': 'middle',
      class: 'axis-title',
      text: label,
    }, svg);
  }

  for (let lvlIdx = innermost - 1; lvlIdx >= 0; lvlIdx -= 1) {
    const yOff = 24 + (innermost - 1 - lvlIdx) * 20;
    let runStart = 0;
    let currKey = cols[0].levelValues.slice(0, lvlIdx + 1).join('|');
    for (let i = 1; i <= cols.length; i += 1) {
      const k = i < cols.length ? cols[i].levelValues.slice(0, lvlIdx + 1).join('|') : null;
      if (k !== currKey) {
        drawBracket(runStart, i - 1, cols[runStart].levelValues[lvlIdx] ?? '', yOff);
        runStart = i;
        currKey = k ?? '';
      }
    }
  }
}

export default function VariabilityGauge({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ height: height ?? 340 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Variability gauge'} />
    </div>
  );
}

export { render as renderVariabilityGauge };
