/**
 * ProbabilityPlot — normal Q-Q plot with Anderson-Darling p-value.
 *
 * Plots sample-vs-theoretical-quantile to test how well the data fits a
 * normal distribution. Reference line is y = (x − μ)/σ; deviations from
 * the line indicate non-normality. AD statistic + p-value annotated
 * top-right (Stephens 1986 approximation).
 *
 * Spec shape:
 *   spec.data: rows
 *   spec.value_column / spec.y[0]
 *   spec.values?: number[]      pre-aggregated alternative
 */

'use client';

import * as React from 'react';
import {
  clear, el, mean, normInv, readTheme, size, std, useSvgChart,
} from './lib';
import { scale, ticks } from './lib/primitives';
import type { ChartSpec } from './types';

interface Props {
  spec: ChartSpec;
  height?: number;
}

const M = { t: 18, r: 18, b: 42, l: 56 };

function hexToRgba(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

// Abramowitz/Stegun erf approx (used by AD p-value)
function erf(x: number): number {
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const p = 0.3275911;
  const sign = x < 0 ? -1 : 1;
  const ax = Math.abs(x);
  const t = 1 / (1 + p * ax);
  const y = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-ax * ax);
  return sign * y;
}

function readValues(spec: ChartSpec): number[] {
  if (Array.isArray(spec.values)) {
    return (spec.values as unknown[])
      .map((v) => Number(v))
      .filter((v): v is number => Number.isFinite(v));
  }
  const data = Array.isArray(spec.data) ? spec.data : [];
  const valueCol = (spec.value_column as string | undefined)
    ?? (Array.isArray(spec.y) && spec.y[0] ? spec.y[0] : null);
  if (!valueCol) return [];
  return data
    .map((r) => Number(r[valueCol]))
    .filter((v): v is number => Number.isFinite(v));
}

function adPValue(values: number[], mu: number, sigma: number): { A2: number; pVal: number } {
  const n = values.length;
  if (n < 5 || sigma <= 0) return { A2: NaN, pVal: NaN };
  const sorted = [...values].sort((a, b) => a - b);
  let A2 = 0;
  for (let i = 0; i < n; i += 1) {
    const z = (sorted[i] - mu) / sigma;
    const p = 0.5 * (1 + erf(z / Math.SQRT2));
    const zEnd = (sorted[n - 1 - i] - mu) / sigma;
    const pp = 1 - 0.5 * (1 + erf(zEnd / Math.SQRT2));
    A2 += ((2 * i + 1) / n) * (Math.log(Math.max(1e-9, p)) + Math.log(Math.max(1e-9, pp)));
  }
  A2 = -n - A2;
  A2 *= 1 + 0.75 / n + 2.25 / (n * n);
  let pVal: number;
  if (A2 < 0.2) pVal = 1 - Math.exp(-13.436 + 101.14 * A2 - 223.73 * A2 * A2);
  else if (A2 < 0.34) pVal = 1 - Math.exp(-8.318 + 42.796 * A2 - 59.938 * A2 * A2);
  else if (A2 < 0.6) pVal = Math.exp(0.9177 - 4.279 * A2 - 1.38 * A2 * A2);
  else pVal = Math.exp(1.2937 - 5.709 * A2 + 0.0186 * A2 * A2);
  pVal = Math.max(0, Math.min(1, pVal));
  return { A2, pVal };
}

function render(svg: SVGSVGElement, spec: ChartSpec) {
  clear(svg);
  const T = readTheme(svg);
  const [W, H] = size(svg);
  if (W <= 0 || H <= 0) return;

  const raw = readValues(spec);
  if (raw.length < 5) {
    el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', class: 'axis-label', text: '需要 ≥ 5 個樣本' }, svg);
    return;
  }
  const sorted = [...raw].sort((a, b) => a - b);
  const n = sorted.length;
  const mu = mean(sorted);
  const sigma = std(sorted);

  const innerLeft = M.l;
  const innerRight = W - M.r;
  const innerTop = M.t;
  const innerBottom = H - M.b;

  // Plotting positions
  const probs = sorted.map((_, i) => (i + 0.5) / n);
  const quantiles = probs.map((p) => normInv(p));

  const xMin = sorted[0] - 1;
  const xMax = sorted[n - 1] + 1;
  const x = scale(xMin, xMax, innerLeft, innerRight);
  const yPad = 0.4;
  const y = scale(quantiles[0] - yPad, quantiles[n - 1] + yPad, innerBottom, innerTop);

  // Y nonlinear ticks (probability labels at standard quantiles)
  [0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99].forEach((p) => {
    const yy = y(normInv(p));
    el('line', { x1: innerLeft, x2: innerRight, y1: yy, y2: yy, class: 'grid-line' }, svg);
    el('text', { x: innerLeft - 5, y: yy + 3, 'text-anchor': 'end', class: 'axis-label', text: `${(p * 100).toFixed(0)}%` }, svg);
  });
  // X grid + labels
  ticks(sorted[0], sorted[n - 1], 6).forEach((v) => {
    el('line', { x1: x(v), x2: x(v), y1: innerTop, y2: innerBottom, class: 'grid-line' }, svg);
    el('text', { x: x(v), y: innerBottom + 13, 'text-anchor': 'middle', class: 'axis-label', text: v.toFixed(1) }, svg);
  });

  // Reference line: y = (x − μ)/σ
  const refX0 = xMin;
  const refX1 = xMax;
  el('line', {
    x1: x(refX0), y1: y((refX0 - mu) / sigma),
    x2: x(refX1), y2: y((refX1 - mu) / sigma),
    stroke: T.alert, 'stroke-width': T.stroke, 'stroke-dasharray': '4 2',
  }, svg);

  // Lilliefors-ish confidence band (visual aid)
  const offset = 1.36 / Math.sqrt(n);
  const bandUp: Array<[number, number]> = [];
  const bandDn: Array<[number, number]> = [];
  for (let i = 0; i < n; i += 1) {
    bandUp.push([x(sorted[i]), y(normInv(Math.max(0.001, Math.min(0.999, probs[i] + offset))))]);
  }
  for (let i = n - 1; i >= 0; i -= 1) {
    bandDn.push([x(sorted[i]), y(normInv(Math.max(0.001, Math.min(0.999, probs[i] - offset))))]);
  }
  const bandPath = [...bandUp, ...bandDn]
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(2)},${p[1].toFixed(2)}`)
    .join('') + 'Z';
  el('path', { d: bandPath, fill: hexToRgba(T.alert, 0.07), stroke: 'none' }, svg);

  // Points
  sorted.forEach((v, i) => {
    el('circle', {
      cx: x(v), cy: y(quantiles[i]),
      r: T.pointR * 0.9,
      fill: T.data, opacity: '0.75',
    }, svg);
  });

  // Anderson-Darling annotation
  const { A2, pVal } = adPValue(sorted, mu, sigma);
  if (Number.isFinite(A2)) {
    const verdict = pVal >= 0.05 ? 'normal ✓' : 'non-normal ⚠';
    const text = `n=${n}   A²=${A2.toFixed(2)}   p=${pVal.toFixed(3)}   ${verdict}`;
    el('text', {
      x: innerRight - 4, y: 12,
      'text-anchor': 'end', class: 'axis-label',
      'font-family': 'var(--chart-font-mono)',
      fill: pVal >= 0.05 ? T.ink : T.alert,
      text,
    }, svg);
  }

  // Axis titles
  el('text', { x: innerLeft + (innerRight - innerLeft) / 2, y: H - 4, 'text-anchor': 'middle', class: 'axis-title', text: 'Sample value' }, svg);
  el('text', {
    x: 14, y: innerTop + (innerBottom - innerTop) / 2,
    'text-anchor': 'middle', class: 'axis-title',
    transform: `rotate(-90 14 ${innerTop + (innerBottom - innerTop) / 2})`,
    text: 'Cumulative probability',
  }, svg);

  if (spec.title) {
    el('text', { x: innerLeft, y: 12, 'text-anchor': 'start', class: 'axis-title', text: spec.title }, svg);
  }
}

export default function ProbabilityPlot({ spec, height }: Props) {
  const ref = useSvgChart((svg) => render(svg, spec), [spec]);
  return (
    <div className="pb-chart-card" style={{ width: '100%', height: height ?? 320 }}>
      <svg ref={ref} role="img" aria-label={spec.title ?? 'Probability plot'} />
    </div>
  );
}

export { render as renderProbabilityPlot };
