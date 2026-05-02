/**
 * Histogram — distribution chart with optional USL/LSL/target spec lines and
 * normal-fit overlay. Returns Cpk / Cp / ppm stats inline as a top-right
 * annotation when spec lines are provided.
 *
 * Two input shapes:
 *   1. **Raw values**: data rows, spec.value_column / spec.y[0] = column name
 *      → bins computed on the fly (default 28 bins).
 *   2. **Pre-binned**: data rows have `bin_center` + `count` columns
 *      → bars drawn directly from those.
 *
 * Spec extras:
 *   spec.usl?, spec.lsl?, spec.target?    — spec / target lines
 *   spec.bins?                            — bin count for raw mode (28)
 *   spec.show_normal?                     — overlay normal PDF (true)
 *   spec.unit?                            — appended to axis title (nm, Å, etc.)
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, normPdf, readTheme, size, std, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 18, r: 14, b: 42, l: 50 };

interface Binned {
  binW: number;
  counts: number[];
  centers: number[];
  rangeMin: number;
  rangeMax: number;
  values?: number[]; // pass-through when raw was given (for normal fit)
}

function binValues(values: number[], bins: number, dMin: number, dMax: number): Binned {
  const binW = (dMax - dMin) / bins;
  const counts = new Array<number>(bins).fill(0);
  const centers: number[] = [];
  for (let i = 0; i < bins; i++) centers.push(dMin + (i + 0.5) * binW);
  for (const v of values) {
    if (!Number.isFinite(v)) continue;
    const i = Math.min(bins - 1, Math.max(0, Math.floor((v - dMin) / binW)));
    counts[i] += 1;
  }
  return { binW, counts, centers, rangeMin: dMin, rangeMax: dMax, values };
}

function preBinned(rows: Array<Record<string, unknown>>): Binned | null {
  if (rows.length === 0) return null;
  const has = (k: string) => rows[0][k] !== undefined;
  if (!has('bin_center') || !has('count')) return null;
  const centers = rows.map((r) => Number(r.bin_center)).filter((v) => Number.isFinite(v));
  const counts = rows.map((r) => Number(r.count)).filter((v) => Number.isFinite(v));
  if (centers.length !== rows.length || counts.length !== rows.length) return null;
  // Approximate bin width as gap between sorted centers.
  const sorted = [...centers].sort((a, b) => a - b);
  let binW = 0;
  for (let i = 1; i < sorted.length; i++) {
    const d = sorted[i] - sorted[i - 1];
    if (d > 0 && (binW === 0 || d < binW)) binW = d;
  }
  if (binW === 0) binW = 1;
  const dMin = Math.min(...centers) - binW / 2;
  const dMax = Math.max(...centers) + binW / 2;
  return { binW, counts, centers, rangeMin: dMin, rangeMax: dMax };
}

interface CpkStats {
  mu: number;
  sigma: number;
  n: number;
  cp?: number;
  cpk?: number;
  ppm?: number;
}

function computeCpk(values: number[] | undefined, usl: number | null, lsl: number | null): CpkStats {
  if (!values || values.length === 0) return { mu: NaN, sigma: NaN, n: 0 };
  const mu = mean(values);
  const sigma = std(values);
  const r: CpkStats = { mu, sigma, n: values.length };
  if (sigma > 0 && usl !== null && lsl !== null) {
    r.cp = (usl - lsl) / (6 * sigma);
    r.cpk = Math.min((usl - mu) / (3 * sigma), (mu - lsl) / (3 * sigma));
    r.ppm = (values.filter((v) => v < lsl || v > usl).length / values.length) * 1e6;
  }
  return r;
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const data = Array.isArray(spec.data) ? spec.data : [];
  if (data.length === 0) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
    return;
  }

  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  const usl = typeof spec.usl === 'number' ? (spec.usl as number) : null;
  const lsl = typeof spec.lsl === 'number' ? (spec.lsl as number) : null;
  const target = typeof spec.target === 'number' ? (spec.target as number) : null;
  const showNormal = spec.show_normal !== false;
  const unit = typeof spec.unit === 'string' ? spec.unit : '';

  // Try pre-binned first; else raw values.
  let binned: Binned | null = preBinned(data);
  let rawValues: number[] | undefined;
  if (!binned) {
    if (!valueCol) {
      el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: 'spec.value_column 缺' }, svg);
      return;
    }
    rawValues = data
      .map((r) => Number(r[valueCol]))
      .filter((v) => Number.isFinite(v));
    if (rawValues.length === 0) {
      el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '（無資料）' }, svg);
      return;
    }
    const bins = (typeof spec.bins === 'number' && spec.bins > 0) ? Math.floor(spec.bins) : 28;
    const vMin = Math.min(...rawValues);
    const vMax = Math.max(...rawValues);
    let dMin = vMin - (vMax - vMin) * 0.04;
    let dMax = vMax + (vMax - vMin) * 0.04;
    if (lsl !== null) dMin = Math.min(dMin, lsl - 0.5);
    if (usl !== null) dMax = Math.max(dMax, usl + 0.5);
    if (dMin === dMax) {
      dMin -= 0.5;
      dMax += 0.5;
    }
    binned = binValues(rawValues, bins, dMin, dMax);
  }

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  const x = scale(binned.rangeMin, binned.rangeMax, innerLeft, innerRight);
  const yMax = Math.max(...binned.counts) * 1.15 || 1;
  const y = scale(0, yMax, innerBottom, innerTop);

  // Y grid + labels
  ticks(0, yMax, 4).forEach((v) => {
    const yy = y(v);
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 6, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: `${Math.round(v)}` }, svg);
  });

  // Bars
  binned.counts.forEach((c, i) => {
    if (c === 0) return;
    const center = binned.centers[i];
    const x0 = x(center - binned.binW / 2);
    const x1 = x(center + binned.binW / 2);
    const oos = (lsl !== null && center < lsl) || (usl !== null && center > usl);
    el('rect', {
      x: x0 + 1,
      y: y(c),
      width: Math.max(1, x1 - x0 - 1),
      height: Math.max(1, y(0) - y(c)),
      fill: oos ? T.alert : T.data,
      'fill-opacity': oos ? '0.75' : `${Math.max(0.4, T.fillOp + 0.4)}`,
    }, svg);
  });

  // Normal curve
  if (showNormal && rawValues && rawValues.length > 1) {
    const mu = mean(rawValues);
    const sigma = std(rawValues);
    if (sigma > 0) {
      const yScaleFactor = rawValues.length * binned.binW;
      const pts: Array<[number, number]> = [];
      for (let k = 0; k <= 120; k++) {
        const v = binned.rangeMin + ((binned.rangeMax - binned.rangeMin) * k) / 120;
        pts.push([x(v), y(normPdf(v, mu, sigma) * yScaleFactor)]);
      }
      const path = pts
        .map((p, k) => `${k === 0 ? 'M' : 'L'}${p[0].toFixed(2)},${p[1].toFixed(2)}`)
        .join('');
      el('path', {
        d: path,
        fill: 'none',
        stroke: T.secondary,
        'stroke-width': T.stroke,
        'stroke-dasharray': '4 2',
      }, svg);
    }
  }

  // X axis line + ticks
  el('line', { x1: innerLeft, x2: innerRight, y1: innerBottom, y2: innerBottom, class: 'axis-line' }, svg);
  ticks(binned.rangeMin, binned.rangeMax, 7).forEach((v) => {
    el('line', { x1: x(v), x2: x(v), y1: innerBottom, y2: innerBottom + 4, stroke: T.gridStrong, 'stroke-width': 1 }, svg);
    el('text', { x: x(v), y: innerBottom + 16, 'text-anchor': 'middle', class: 'axis-label', text: v.toFixed(1) }, svg);
  });

  // X axis title
  if (valueCol) {
    el('text', {
      x: innerLeft + (innerRight - innerLeft) / 2,
      y: H - 6,
      'text-anchor': 'middle',
      class: 'axis-title',
      text: unit ? `${valueCol} (${unit})` : valueCol,
    }, svg);
  }

  // Title
  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }

  // Spec lines
  if (lsl !== null) {
    el('line', { x1: x(lsl), x2: x(lsl), y1: innerTop, y2: innerBottom, stroke: T.alert, 'stroke-width': 1, 'stroke-dasharray': '4 3' }, svg);
    el('text', { x: x(lsl), y: innerTop + 10, 'text-anchor': 'middle', 'font-size': '10', fill: T.alert, 'font-family': 'var(--chart-font-mono)', text: 'LSL' }, svg);
  }
  if (usl !== null) {
    el('line', { x1: x(usl), x2: x(usl), y1: innerTop, y2: innerBottom, stroke: T.alert, 'stroke-width': 1, 'stroke-dasharray': '4 3' }, svg);
    el('text', { x: x(usl), y: innerTop + 10, 'text-anchor': 'middle', 'font-size': '10', fill: T.alert, 'font-family': 'var(--chart-font-mono)', text: 'USL' }, svg);
  }
  if (target !== null) {
    el('line', { x1: x(target), x2: x(target), y1: innerTop, y2: innerBottom, stroke: '#059669', 'stroke-width': 1, 'stroke-dasharray': '2 3' }, svg);
  }

  // Stats annotation (top-right)
  const stats = computeCpk(rawValues, usl, lsl);
  if (Number.isFinite(stats.mu)) {
    const lines: string[] = [
      `n=${stats.n}`,
      `μ=${stats.mu.toFixed(3)}`,
      `σ=${stats.sigma.toFixed(3)}`,
    ];
    if (stats.cp !== undefined) lines.push(`Cp=${stats.cp.toFixed(2)}`);
    if (stats.cpk !== undefined) lines.push(`Cpk=${stats.cpk.toFixed(2)}`);
    if (stats.ppm !== undefined) lines.push(`ppm=${stats.ppm.toFixed(0)}`);
    const text = lines.join('   ');
    el('text', {
      x: innerRight - 4,
      y: 12,
      'text-anchor': 'end',
      class: 'axis-label',
      'font-family': 'var(--chart-font-mono)',
      text,
    }, svg);
  }
}

export default function Histogram({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 280 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Histogram'} />
    </div>
  );
}

export { render as renderHistogram };
